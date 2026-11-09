"""Exercise source checkout with real Git/LFS and unavailable test-data objects."""
import os
import subprocess

import pytest

from buildbpy.main import CommitCheckoutStrategy, DailyCheckoutStrategy, TagCheckoutStrategy

SOURCE_URL = "https://projects.blender.org/blender/blender.git"


def git(*args, cwd=None, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True,
        timeout=30,
    )


@pytest.fixture
def source(tmp_path, monkeypatch):
    # Isolate all configuration and LFS storage; never contact Blender's server.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.delenv("GIT_LFS_SKIP_SMUDGE", raising=False)
    git("lfs", "version")  # Required, not a silently skipped regression.
    git("lfs", "install", "--skip-repo")
    remote = tmp_path / "upstream"
    git("init", "--initial-branch=main", str(remote))
    git("config", "user.email", "test@example.invalid", cwd=remote)
    git("config", "user.name", "Test", cwd=remote)
    (remote / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
    for char, version in [("a", "release"), ("b", "main")]:
        (remote / "test-data.bin").write_text(
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{char * 64}\nsize 123\n"
        )
        (remote / "source.txt").write_text(version)
        git("add", ".", cwd=remote)
        git("commit", "-m", version, cwd=remote)
        if version == "release":
            git("tag", "v5.2.3", cwd=remote)
    git("config", "--global", f"url.{remote}.insteadOf", SOURCE_URL)
    return remote, tmp_path / "build" / "blender"


@pytest.mark.parametrize("recover", [False, True], ids=["fresh", "failed-clone"])
@pytest.mark.parametrize("kind", ["tag", "commit", "daily"])
def test_source_checkout_without_lfs_objects(source, monkeypatch, recover, kind):
    remote, target = source
    target.parent.mkdir()
    if recover:
        result = git("clone", SOURCE_URL, str(target), check=False)
        assert result.returncode == 128
        assert "smudge" in result.stderr.lower()
        assert "Clone succeeded, but checkout failed" in result.stderr
        assert (target / ".git").is_dir()
    before = dict(os.environ)
    if kind == "tag":
        strategy = TagCheckoutStrategy(target)
        strategy.checkout("v5.2.3")
    elif kind == "commit":
        strategy = CommitCheckoutStrategy(target)
        strategy.checkout(git("rev-parse", "v5.2.3", cwd=remote).stdout.strip())
    else:
        monkeypatch.setattr(
            "buildbpy.main.fetch_latest_build_info",
            lambda *_: {"hash": git("rev-parse", "v5.2.3", cwd=remote).stdout.strip()},
        )
        strategy = DailyCheckoutStrategy(target)
        strategy.checkout()
    assert (target / "source.txt").read_text() == "release"
    assert "oid sha256:" + "a" * 64 in (target / "test-data.bin").read_text()
    assert git("rev-parse", "HEAD", cwd=target).stdout == git("rev-parse", "v5.2.3", cwd=remote).stdout
    assert git("status", "--porcelain", cwd=target).stdout == ""
    assert dict(os.environ) == before
    # A later dependency hydration must still attempt LFS and fail if unavailable.
    hydration = git("lfs", "pull", cwd=target, check=False)
    assert hydration.returncode != 0
    assert not git("config", "--local", "--get", "lfs.skipSmudge", cwd=target, check=False).stdout


def test_source_environment_is_copied_and_existing_setting_restored(source, monkeypatch):
    _, target = source
    monkeypatch.setenv("GIT_LFS_SKIP_SMUDGE", "0")
    monkeypatch.setenv("BUILDBPY_TEST_SENTINEL", "preserved")
    before = dict(os.environ)
    strategy = TagCheckoutStrategy(target)
    strategy.checkout("v5.2.3")
    assert dict(os.environ) == before


@pytest.mark.parametrize("kind", ["commit", "daily"])
def test_invalid_commit_fails_closed(source, monkeypatch, kind):
    _, target = source
    monkeypatch.setenv("GIT_LFS_SKIP_SMUDGE", "1")
    if kind == "commit":
        strategy = CommitCheckoutStrategy(target)
    else:
        monkeypatch.setattr("buildbpy.main.fetch_latest_build_info", lambda *_: {"hash": "missing-commit"})
        strategy = DailyCheckoutStrategy(target)
    before = dict(os.environ)
    with pytest.raises(subprocess.CalledProcessError):
        strategy.checkout("missing-commit")
    assert dict(os.environ) == before


def test_existing_index_and_local_edits_are_preserved(source):
    _, target = source
    CommitCheckoutStrategy(target)
    (target / "source.txt").write_text("local edits")
    strategy = CommitCheckoutStrategy(target)
    with pytest.raises(subprocess.CalledProcessError):
        strategy.checkout("v5.2.3")
    assert (target / "source.txt").read_text() == "local edits"


def test_clone_uses_requested_directory(source):
    _, target = source
    target = target.with_name("custom-source")
    strategy = TagCheckoutStrategy(target)
    strategy.checkout("v5.2.3")
    assert (target / "source.txt").read_text() == "release"
