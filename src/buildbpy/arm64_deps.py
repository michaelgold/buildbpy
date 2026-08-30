from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import tarfile
import tempfile
from typing import Any

import httpx


RELEASE_TIMEOUT = httpx.Timeout(300.0, connect=30.0, write=30.0, pool=30.0)


@dataclass(frozen=True)
class BundleSpec:
    blender_version: str
    revision: int = 1
    os_name: str = "ubuntu24.04"
    compiler: str = "gcc13"
    architecture: str = "arm64"

    @classmethod
    def for_blender_version(cls, blender_version: str) -> "BundleSpec":
        """Select the immutable dependency bundle for a Blender release."""
        if re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", blender_version) is None:
            raise ValueError(
                f"Blender dependency bundle requires a semantic version: {blender_version!r}"
            )
        parts = blender_version.split(".")
        dependency_version = (
            "5.2.0" if len(parts) == 3 and parts[:2] == ["5", "2"] else blender_version
        )
        return cls(dependency_version)

    @property
    def release_tag(self) -> str:
        return (
            f"deps-blender-{self.blender_version}-linux-"
            f"{self.architecture}-v{self.revision}"
        )

    @property
    def archive_name(self) -> str:
        return (
            f"blender-{self.blender_version}-linux-{self.architecture}-"
            f"{self.os_name}-{self.compiler}-v{self.revision}.tar.zst"
        )

    @property
    def manifest_name(self) -> str:
        return f"{self.archive_name}.manifest.json"

    @property
    def checksum_name(self) -> str:
        return f"{self.archive_name}.sha256"

    def identity(self) -> dict[str, Any]:
        return {
            "blender_version": self.blender_version,
            "bundle_revision": self.revision,
            "os": self.os_name,
            "compiler": self.compiler,
            "architecture": self.architecture,
        }


@dataclass(frozen=True)
class BundleArtifacts:
    archive: Path
    manifest: Path
    checksum: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def disable_arm64_osl_optix(osl_cmake: Path) -> bool:
    """Prevent OSL's unsupported CUDA/OptiX bitcode build on Linux ARM64."""
    original = "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))"
    replacement = (
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM OR BLENDER_PLATFORM_ARM))"
    )
    text = osl_cmake.read_text()
    if replacement in text:
        return False
    if original not in text:
        raise ValueError(f"Unrecognized Blender OSL dependency configuration: {osl_cmake}")
    osl_cmake.write_text(text.replace(original, replacement, 1))
    return True


def configure_arm64_wayland_lib64(wayland_cmake: Path) -> bool:
    """Match Wayland's Meson install directory to Blender's harvest rules."""
    text = wayland_cmake.read_text()
    if "--libdir lib64" in text:
        return False
    prefix = "--prefix ${LIBDIR}/wayland\n"
    if prefix not in text:
        raise ValueError(
            f"Unrecognized Blender Wayland dependency configuration: {wayland_cmake}"
        )
    prefix_start = text.rfind("\n", 0, text.index(prefix)) + 1
    indentation = text[prefix_start : text.index(prefix)]
    replacement = f"{prefix}{indentation}--libdir lib64\n"
    wayland_cmake.write_text(text.replace(prefix, replacement, 1))
    return True


def download_release_bundle(
    client: httpx.Client,
    repository: str,
    token: str,
    spec: BundleSpec,
    output_dir: Path,
) -> BundleArtifacts | None:
    api_headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        api_headers["Authorization"] = f"Bearer {token}"
    response = client.get(
        f"https://api.github.com/repos/{repository}/releases/tags/{spec.release_tag}",
        headers=api_headers,
        timeout=RELEASE_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("GitHub release response must be a JSON object")
    raw_assets = payload.get("assets")
    if not isinstance(raw_assets, list):
        raise ValueError("GitHub release response assets must be a list")
    assets = {}
    for asset in raw_assets:
        if not isinstance(asset, dict):
            raise ValueError("GitHub release asset must be a JSON object")
        name = asset.get("name")
        url = asset.get("url")
        if not isinstance(name, str) or not isinstance(url, str):
            raise ValueError("GitHub release asset name and URL must be strings")
        assets[name] = url
    required = [spec.archive_name, spec.manifest_name, spec.checksum_name]
    if any(name not in assets for name in required):
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []
    asset_headers = {**api_headers, "Accept": "application/octet-stream"}
    for name in required:
        path = output_dir / name
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=output_dir,
                prefix=f".{name}.",
                suffix=".tmp",
                delete=False,
            ) as file:
                temporary_path = Path(file.name)
                with client.stream(
                    "GET",
                    assets[name],
                    headers=asset_headers,
                    timeout=RELEASE_TIMEOUT,
                ) as asset_response:
                    asset_response.raise_for_status()
                    for chunk in asset_response.iter_bytes():
                        file.write(chunk)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        downloaded.append(path)
    return BundleArtifacts(*downloaded)


def create_bundle(
    source: Path,
    output_dir: Path,
    spec: BundleSpec,
    *,
    blender_commit: str = "",
    python_version: str = "",
) -> BundleArtifacts:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Dependency source directory does not exist: {source}")
    if source.name != "linux_arm64":
        raise ValueError("Dependency source directory must be named linux_arm64")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / spec.archive_name
    manifest_path = output_dir / spec.manifest_name
    checksum_path = output_dir / spec.checksum_name

    subprocess.run(
        [
            "tar",
            "--zstd",
            "--sort=name",
            "--mtime=@0",
            "--owner=0",
            "--group=0",
            "--numeric-owner",
            "-cf",
            str(archive),
            "-C",
            str(source.parent),
            source.name,
        ],
        check=True,
    )
    archive_sha256 = sha256_file(archive)
    manifest = {
        **spec.identity(),
        "release_tag": spec.release_tag,
        "archive": spec.archive_name,
        "archive_sha256": archive_sha256,
        "blender_commit": blender_commit,
        "python_version": python_version,
        "builder_machine": platform.machine().lower(),
        "format": 1,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    checksum_path.write_text(f"{archive_sha256}  {spec.archive_name}\n")
    return BundleArtifacts(archive, manifest_path, checksum_path)


@contextmanager
def _open_zstd_tar(archive: Path):
    stderr_file = tempfile.TemporaryFile()
    try:
        try:
            process = subprocess.Popen(
                ["zstd", "-dc", "--", str(archive)],
                stdout=subprocess.PIPE,
                stderr=stderr_file,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "zstd executable is required to verify ARM64 dependency bundles"
            ) from exc

        assert process.stdout is not None
        try:
            with tarfile.open(fileobj=process.stdout, mode="r|") as tar:
                yield tar
        except BaseException:
            process.kill()
            process.wait()
            raise
        else:
            process.stdout.close()
            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                stderr = stderr_file.read()
                raise subprocess.CalledProcessError(
                    return_code, process.args, stderr=stderr
                )
        finally:
            process.stdout.close()
    finally:
        stderr_file.close()


def _validate_archive_members(archive: Path, destination: Path) -> None:
    with _open_zstd_tar(archive) as tar:
        for info in tar:
            member = PurePosixPath(info.name)
            if member.is_absolute() or ".." in member.parts:
                raise ValueError(f"Unsafe bundle member: {info.name}")
            if not member.parts or member.parts[0] != "linux_arm64":
                raise ValueError(
                    f"Bundle member is outside linux_arm64: {info.name}"
                )
            if info.issym() or info.islnk():
                link_name = PurePosixPath(info.linkname)
                if link_name.is_absolute():
                    raise ValueError(
                        f"Unsafe bundle link: {info.name} -> {info.linkname}"
                    )
                target = member.parent / link_name if info.issym() else link_name
                normalized_parts: list[str] = []
                for part in target.parts:
                    if part in {"", "."}:
                        continue
                    if part == "..":
                        if not normalized_parts:
                            raise ValueError(
                                f"Unsafe bundle link: {info.name} -> {info.linkname}"
                            )
                        normalized_parts.pop()
                    else:
                        normalized_parts.append(part)
                if not normalized_parts or normalized_parts[0] != "linux_arm64":
                    raise ValueError(
                        f"Unsafe bundle link: {info.name} -> {info.linkname}"
                    )
            try:
                tarfile.data_filter(info, str(destination))
            except tarfile.FilterError as exc:
                raise ValueError(f"Unsafe bundle member: {info.name}: {exc}") from exc


def verify_and_extract_bundle(
    archive: Path,
    manifest_path: Path,
    checksum_path: Path,
    destination: Path,
    spec: BundleSpec,
    *,
    expected_blender_commit: str = "",
    expected_python_series: str = "",
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict):
        raise ValueError("Dependency bundle manifest must be a JSON object")
    expected_identity = spec.identity()
    actual_identity = {key: manifest.get(key) for key in expected_identity}
    if actual_identity != expected_identity:
        raise ValueError(
            f"Dependency bundle identity mismatch: {actual_identity} != {expected_identity}"
        )
    if manifest.get("archive") != archive.name:
        raise ValueError("Dependency bundle archive name does not match manifest")
    if manifest.get("release_tag") != spec.release_tag:
        raise ValueError("Dependency bundle release tag does not match specification")
    if manifest.get("format") != 1:
        raise ValueError("Unsupported dependency bundle manifest format")
    if expected_blender_commit and manifest.get("blender_commit") != expected_blender_commit:
        raise ValueError("Dependency bundle Blender commit does not match checkout")
    python_version = manifest.get("python_version")
    if expected_python_series and (
        not isinstance(python_version, str)
        or not python_version.startswith(f"{expected_python_series}.")
    ):
        raise ValueError("Dependency bundle Python version is incompatible")
    actual_sha256 = sha256_file(archive)
    checksum_parts = checksum_path.read_text().split()
    if (
        len(checksum_parts) != 2
        or checksum_parts[0] != actual_sha256
        or checksum_parts[1] != archive.name
    ):
        raise ValueError("Dependency bundle checksum asset SHA-256 does not match archive")
    if actual_sha256 != manifest.get("archive_sha256"):
        raise ValueError("Dependency bundle SHA-256 does not match manifest")

    data_filter = getattr(tarfile, "data_filter", None)
    if not callable(data_filter):
        raise RuntimeError(
            "Python tarfile extraction filters are required to install ARM64 "
            "dependency bundles"
        )
    _validate_archive_members(archive, destination)
    destination.mkdir(parents=True, exist_ok=True)
    with _open_zstd_tar(archive) as tar:
        tar.extractall(destination, filter="data")
    return manifest
