"""Verified reuse or explicit backed-up replacement of Linux wheel assets.

The workflow must retain the prepare directory with upload-artifact before publish.
No delete API is used; only the exact validated wheel is uploaded with --clobber.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def gh(*args: str) -> str:
    return subprocess.check_output(["gh", *args], text=True)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return "sha256:" + checksum.hexdigest()


def validate(wheel: Path, tag: str) -> None:
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)", tag)
    if not match or not re.fullmatch(
        rf"bpy-{re.escape(match[1])}-cp\d+-cp\d+-manylinux_\d+_\d+_(?:x86_64|aarch64)\.whl",
        wheel.name,
    ):
        raise ValueError("Only exact-version Linux bpy wheel releases are permitted")
    if not wheel.is_file():
        raise ValueError("Wheel does not exist")


def asset(repo: str, tag: str, name: str):
    assets = json.loads(gh("release", "view", tag, "--repo", repo, "--json", "assets"))["assets"]
    matches = [a for a in assets if a["name"] == name]
    if len(matches) > 1:
        raise ValueError("Duplicate release asset")
    return matches[0] if matches else None


def identity(value):
    if value is None:
        return None
    return {key: value[key] for key in ("id", "name", "size", "digest")}


def verify_backup(path: Path, old: dict) -> None:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", old.get("digest") or ""):
        raise ValueError("Existing asset has no valid SHA-256 digest")
    if digest(path) != old["digest"] or path.stat().st_size != old["size"]:
        raise ValueError("Backup size/digest differs from release asset")


def verify_runtime(wheel: Path, tag: str) -> None:
    """Smoke the downloaded asset, not the freshly built/importable bpy tree."""
    with tempfile.TemporaryDirectory(prefix="bpy-release-smoke-") as directory:
        python = Path(directory) / "venv/bin/python"
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        subprocess.run([sys.executable, "-m", "venv", str(python.parent.parent)],
                       check=True, env=env)
        subprocess.run([str(python), "-I", "-m", "pip", "install", str(wheel.resolve())],
                       check=True, cwd=directory, env=env)
        subprocess.run([str(python), "-I", "-c",
                        "import bpy, numpy; import sys; "
                        "expected = tuple(map(int, sys.argv[1][1:].split('.'))); "
                        "assert bpy.app.version == expected, (bpy.app.version, expected); "
                        "print('Verified existing bpy:', bpy.app.version)", tag],
                       check=True, cwd=directory, env=env)


def prepare(wheel: Path, tag: str, repo: str, backup: Path, replace_existing: bool,
            reuse_existing: bool = False) -> None:
    validate(wheel, tag)
    if replace_existing and reuse_existing:
        raise ValueError("Replacement and reuse are mutually exclusive")
    old = asset(repo, tag, wheel.name)
    if old and not (replace_existing or reuse_existing):
        raise ValueError("Asset exists: explicit --replace-existing is required")
    backup.mkdir(parents=True, exist_ok=False)
    if old:
        gh("release", "download", tag, "--repo", repo, "--pattern", wheel.name,
           "--dir", str(backup))
        verify_backup(backup / wheel.name, old)
        if reuse_existing:
            verify_runtime(backup / wheel.name, tag)
            verify_backup(backup / wheel.name, old)
    receipt = {"repo": repo, "tag": tag, "name": wheel.name,
               "new_digest": digest(wheel), "old": identity(old),
               "reuse_existing": bool(old and reuse_existing)}
    (backup / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def publish(wheel: Path, tag: str, repo: str, backup: Path) -> None:
    validate(wheel, tag)
    receipt = json.loads((backup / "receipt.json").read_text())
    for key, value in {"repo": repo, "tag": tag, "name": wheel.name,
                       "new_digest": digest(wheel)}.items():
        if receipt[key] != value:
            raise ValueError(f"Prepared publication changed: {key}")
    old = receipt["old"]
    if old:
        verify_backup(backup / wheel.name, old)
    if identity(asset(repo, tag, wheel.name)) != old:
        raise ValueError("Release asset changed since backup; refusing replacement")
    if receipt.get("reuse_existing"):
        if not old:
            raise ValueError("Reuse requires a verified existing asset")
        print(json.dumps({"reused": old}, indent=2))
        return
    args = ["release", "upload", tag, "--repo", repo, str(wheel)]
    if old:
        args.append("--clobber")
    gh(*args)
    current = asset(repo, tag, wheel.name)
    if not current or current["digest"] != receipt["new_digest"] or current["size"] != wheel.stat().st_size:
        raise ValueError("Published wheel failed size/digest readback")
    print(json.dumps({"published": identity(current), "previous": old}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "publish"))
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--backup", type=Path, required=True)
    collision = parser.add_mutually_exclusive_group()
    collision.add_argument("--replace-existing", action="store_true")
    collision.add_argument("--reuse-existing", action="store_true",
                           help="Verify and import the existing wheel; never overwrite it")
    args = parser.parse_args()
    wheels = list(args.wheel_dir.glob("bpy-*.whl"))
    if len(wheels) != 1:
        parser.error(f"Expected exactly one wheel, found {len(wheels)}")
    if args.action == "prepare":
        prepare(wheels[0], args.tag, args.repo, args.backup, args.replace_existing,
                args.reuse_existing)
    else:
        publish(wheels[0], args.tag, args.repo, args.backup)


if __name__ == "__main__":
    main()
