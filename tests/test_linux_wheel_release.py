"""Collision-safe publication contracts (no live GitHub writes)."""
import hashlib
import json
from pathlib import Path

import pytest
import yaml

from buildbpy import linux_wheel_release as release

NAME = "bpy-5.2.3-cp313-cp313-manylinux_2_39_aarch64.whl"


def setup_release(tmp_path, monkeypatch, *, digest=None):
    wheel = tmp_path / NAME
    wheel.write_bytes(b"new wheel")
    old = {"name": NAME, "id": 123, "size": 9,
           "digest": digest or "sha256:" + hashlib.sha256(b"old wheel").hexdigest()}
    calls = []
    def gh(*args):
        calls.append(args)
        if args[:2] == ("release", "view"):
            return json.dumps({"assets": [old]})
        if args[:2] == ("release", "download"):
            Path(args[args.index("--dir") + 1], NAME).write_bytes(b"old wheel")
        return ""
    monkeypatch.setattr(release, "gh", gh)
    return wheel, old, calls


def test_collision_requires_explicit_opt_in(tmp_path, monkeypatch):
    wheel, _, calls = setup_release(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="replace-existing"):
        release.prepare(wheel, "v5.2.3", "owner/repo", tmp_path / "backup", False)
    assert not any(c[1] in {"download", "upload"} for c in calls)


def test_verified_backup_and_readback_before_replacement(tmp_path, monkeypatch):
    wheel, old, calls = setup_release(tmp_path, monkeypatch)
    backup = tmp_path / "backup"
    release.prepare(wheel, "v5.2.3", "owner/repo", backup, True)
    assert (backup / NAME).read_bytes() == b"old wheel"
    # Return the replacement metadata on the post-upload readback.
    original = release.gh
    def gh(*args):
        result = original(*args)
        if args[:2] == ("release", "upload"):
            old.update(id=456, size=wheel.stat().st_size,
                       digest="sha256:" + hashlib.sha256(wheel.read_bytes()).hexdigest())
        return result
    monkeypatch.setattr(release, "gh", gh)
    release.publish(wheel, "v5.2.3", "owner/repo", backup)
    uploads = [c for c in calls if c[:2] == ("release", "upload")]
    assert len(uploads) == 1 and "--clobber" in uploads[0]
    assert str(wheel) in uploads[0]


def test_new_asset_never_clobbers(tmp_path, monkeypatch):
    wheel, new, calls = setup_release(tmp_path, monkeypatch)
    original = release.gh
    uploaded = False
    def gh(*args):
        nonlocal uploaded
        result = original(*args)
        if args[:2] == ("release", "upload"):
            uploaded = True
        if args[:2] == ("release", "view"):
            new.update(size=wheel.stat().st_size, digest=release.digest(wheel))
            return json.dumps({"assets": [new] if uploaded else []})
        return result
    monkeypatch.setattr(release, "gh", gh)
    backup = tmp_path / "backup"
    release.prepare(wheel, "v5.2.3", "owner/repo", backup, False)
    release.publish(wheel, "v5.2.3", "owner/repo", backup)
    assert not any("--clobber" in c for c in calls)
    assert not any(c[:2] == ("release", "download") for c in calls)


def test_post_upload_readback_is_required(tmp_path, monkeypatch):
    wheel, _, _ = setup_release(tmp_path, monkeypatch)
    backup = tmp_path / "backup"
    release.prepare(wheel, "v5.2.3", "owner/repo", backup, True)
    with pytest.raises(ValueError, match="readback"):
        release.publish(wheel, "v5.2.3", "owner/repo", backup)


@pytest.mark.parametrize("digest", [None, "", "md5:abcd", "sha256:short"])
def test_missing_or_invalid_digest_cannot_authorize_replacement(tmp_path, monkeypatch, digest):
    wheel, old, calls = setup_release(tmp_path, monkeypatch)
    old["digest"] = digest
    with pytest.raises(ValueError, match="digest"):
        release.prepare(wheel, "v5.2.3", "owner/repo", tmp_path / "backup", True)
    assert not any(c[:2] == ("release", "upload") for c in calls)


@pytest.mark.parametrize("mutation", ["digest", "backup", "asset", "wheel"])
def test_fail_closed_on_corruption_or_race(tmp_path, monkeypatch, mutation):
    wheel, old, calls = setup_release(tmp_path, monkeypatch)
    backup = tmp_path / "backup"
    if mutation == "digest":
        old["digest"] = "sha256:" + "0" * 64
        with pytest.raises(ValueError, match="digest"):
            release.prepare(wheel, "v5.2.3", "owner/repo", backup, True)
    else:
        release.prepare(wheel, "v5.2.3", "owner/repo", backup, True)
        if mutation == "backup":
            (backup / NAME).write_bytes(b"corrupted")
        elif mutation == "asset":
            old["id"] = 999
        else:
            wheel.write_bytes(b"changed")
        with pytest.raises(ValueError):
            release.publish(wheel, "v5.2.3", "owner/repo", backup)
    assert not any(c[:2] == ("release", "upload") for c in calls)


@pytest.mark.parametrize("name,tag", [(NAME, "deps-blender-5.2.0-linux-arm64-v1"),
    (NAME.replace("aarch64", "win_amd64"), "v5.2.3"), (NAME, "v5.2.2")])
def test_rejects_out_of_scope_assets(tmp_path, name, tag):
    wheel = tmp_path / name
    wheel.write_bytes(b"test")
    with pytest.raises(ValueError):
        release.prepare(wheel, tag, "owner/repo", tmp_path / "backup", True)


@pytest.mark.parametrize("filename", ["build_linux.yml", "build_linux_arm64.yml"])
def test_workflow_requires_durable_backup_before_publish(filename):
    workflow = yaml.safe_load((Path(__file__).parents[1] / ".github/workflows" / filename).read_text())
    triggers = workflow.get("on", workflow.get(True))
    for trigger in ("workflow_call", "workflow_dispatch"):
        assert triggers[trigger]["inputs"]["replace_existing"]["default"] is False
    steps = workflow["jobs"]["build"]["steps"]
    names = [s.get("name") for s in steps]
    prepare = names.index("Prepare verified bpy wheel publication")
    backup = names.index("Preserve previous Linux wheel")
    publish = names.index("Publish verified bpy wheel")
    assert prepare < backup < publish
    assert steps[backup]["uses"] == "actions/upload-artifact@v4"
    assert steps[backup]["with"]["if-no-files-found"] == "error"
    assert "if" not in steps[backup] and "continue-on-error" not in steps[backup]
    assert "linux_wheel_release publish" in steps[publish]["run"]
    assert "--clobber" not in steps[publish]["run"]
