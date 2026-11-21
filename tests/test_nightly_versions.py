"""Nightly detection/commit boundary: advance only the completed selection."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("check_latest", ROOT / "workspace/check_latest.py")
assert spec is not None and spec.loader is not None
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_detection_is_read_only_and_records_selected_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    check.write_version_info("version_info.json", "v5.2.0", "a" * 40)
    original = Path("version_info.json").read_bytes()
    monkeypatch.setattr(check, "get_latest_tag", lambda: "v5.3.0")
    monkeypatch.setattr(check, "get_latest_commit", lambda: "b" * 40)
    check.main([])
    assert Path("version_info.json").read_bytes() == original
    assert "new_tag=true" in output.read_text()
    assert "latest_commit=" + "b" * 40 in output.read_text()
    # Upstream can move during the builds. Record exactly the successful selection.
    monkeypatch.setattr(check, "get_latest_tag", lambda: pytest.fail("must not re-query upstream"))
    monkeypatch.setattr(check, "get_latest_commit", lambda: pytest.fail("must not re-query upstream"))
    check.main(["--record-tag", "v5.3.0", "--record-commit", "b" * 40])
    assert json.loads(Path("version_info.json").read_text()) == {
        "previous_tag": "v5.3.0", "previous_commit": "b" * 40}
    monkeypatch.setattr(check, "get_latest_tag", lambda: "v5.3.0")
    monkeypatch.setattr(check, "get_latest_commit", lambda: "c" * 40)
    output.write_text("")
    check.main([])
    assert "new_tag=false" in output.read_text()  # next nightly does not rebuild


@pytest.mark.parametrize("args", [
    ["--record-tag", "v5.3.0"],
    ["--record-commit", "a" * 40],
    ["--record-tag", "main", "--record-commit", "a" * 40],
    ["--record-tag", "v5.3.0", "--record-commit", "bad"],
])
def test_incomplete_or_invalid_selection_does_not_write(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        check.main(args)
    assert not Path("version_info.json").exists()


def test_metadata_requires_every_platform_and_uses_original_selection():
    jobs = yaml.safe_load((ROOT / ".github/workflows/build_all.yml").read_text())["jobs"]
    update = jobs["update-versions"]
    assert set(update["needs"]) == {"check-version", "build-for-windows", "build-for-linux",
                                    "build-for-linux-arm64", "build-for-macos"}
    assert update["if"] == "${{ needs.check-version.outputs.new_tag == 'true' }}"
    # The implicit success() gate must not be bypassed by always()/failure().
    for platform in update["needs"][1:]:
        assert "continue-on-error" not in jobs[platform]
    run = next(s["run"] for s in update["steps"] if s.get("name") == "Update versions")
    assert '--record-tag "$SELECTED_TAG"' in run
    assert '--record-commit "$SELECTED_COMMIT"' in run
    env = next(s["env"] for s in update["steps"] if s.get("name") == "Update versions")
    assert env["SELECTED_TAG"] == "${{ needs.check-version.outputs.tag_input }}"
    assert env["SELECTED_COMMIT"] == "${{ needs.check-version.outputs.latest_commit }}"
    assert jobs["check-version"]["outputs"]["latest_commit"] == "${{ steps.check.outputs.latest_commit }}"
    assert jobs["update-repository-index"]["needs"] == ["update-versions"]
