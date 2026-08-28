from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tarfile
from unittest.mock import patch
from types import SimpleNamespace

import httpx
import pytest

from buildbpy.arm64_deps import (
    BundleSpec,
    configure_arm64_wayland_lib64,
    create_bundle,
    disable_arm64_osl_optix,
    download_release_bundle,
    sha256_file,
    verify_and_extract_bundle,
)
from buildbpy.main import BlenderBuilder, LinuxOSStrategy, ReleaseVersionCycleStrategy


def test_bundle_spec_has_stable_release_names():
    spec = BundleSpec(blender_version="5.2.0", revision=1)

    assert spec.release_tag == "deps-blender-5.2.0-linux-arm64-v1"
    assert spec.archive_name == "blender-5.2.0-linux-arm64-ubuntu24.04-gcc13-v1.tar.zst"
    assert spec.manifest_name == f"{spec.archive_name}.manifest.json"
    assert spec.checksum_name == f"{spec.archive_name}.sha256"


def test_arm64_osl_patch_disables_cuda_optix_only_on_arm(tmp_path: Path):
    osl_cmake = tmp_path / "osl.cmake"
    osl_cmake.write_text(
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\n"
        "  list(APPEND OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\n"
        "endif()\n"
    )

    changed = disable_arm64_osl_optix(osl_cmake)

    assert changed is True
    assert "BLENDER_PLATFORM_ARM" in osl_cmake.read_text()
    assert disable_arm64_osl_optix(osl_cmake) is False


def test_arm64_wayland_patch_uses_harvested_lib64_directory(tmp_path: Path):
    wayland_cmake = tmp_path / "wayland.cmake"
    wayland_cmake.write_text(
        "${MESON} setup\n"
        "  --prefix ${LIBDIR}/wayland\n"
        "  ${MESON_BUILD_TYPE}\n"
    )

    changed = configure_arm64_wayland_lib64(wayland_cmake)

    assert changed is True
    assert "--libdir lib64" in wayland_cmake.read_text()
    assert configure_arm64_wayland_lib64(wayland_cmake) is False


def test_bundle_round_trip_verifies_and_extracts(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    (source / "lib").mkdir(parents=True)
    (source / "lib" / "libexample.a").write_bytes(b"arm64-library")
    output = tmp_path / "dist"
    spec = BundleSpec(blender_version="5.2.0", revision=1)

    artifacts = create_bundle(
        source,
        output,
        spec,
        blender_commit="abc123",
        python_version="3.13.12",
    )
    destination = tmp_path / "installed"
    manifest = verify_and_extract_bundle(
        artifacts.archive,
        artifacts.manifest,
        artifacts.checksum,
        destination,
        spec,
    )

    assert (destination / "linux_arm64/lib/libexample.a").read_bytes() == b"arm64-library"
    assert manifest["blender_commit"] == "abc123"
    assert manifest["python_version"] == "3.13.12"
    assert artifacts.checksum.read_text().split()[1] == spec.archive_name


def test_bundle_rejects_modified_archive(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    (source / "value").write_text("original")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    artifacts.archive.write_bytes(artifacts.archive.read_bytes() + b"tampered")

    with pytest.raises(ValueError, match="SHA-256"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            spec,
        )


def test_bundle_rejects_modified_checksum_asset(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    (source / "value").write_text("original")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    artifacts.checksum.write_text(f"{'0' * 64}  {spec.archive_name}\n")

    with pytest.raises(ValueError, match="checksum asset"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            spec,
        )


def test_bundle_rejects_manifest_for_another_version(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    (source / "value").write_text("original")
    source_spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", source_spec)

    with pytest.raises(ValueError, match="bundle identity"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            BundleSpec(blender_version="5.3.0", revision=1),
        )


def test_bundle_rejects_symlink_target_outside_prefix(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    (source / "value").write_text("original")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    raw_tar = tmp_path / "malicious.tar"
    with tarfile.open(raw_tar, "w") as archive:
        root = tarfile.TarInfo("linux_arm64")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        link = tarfile.TarInfo("linux_arm64/outside")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    subprocess.run(
        ["zstd", "-f", str(raw_tar), "-o", str(artifacts.archive)], check=True
    )
    digest = sha256_file(artifacts.archive)
    manifest = json.loads(artifacts.manifest.read_text())
    manifest["archive_sha256"] = digest
    artifacts.manifest.write_text(json.dumps(manifest))
    artifacts.checksum.write_text(f"{digest}  {spec.archive_name}\n")

    with pytest.raises(ValueError, match="Unsafe bundle (member|link)"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            spec,
        )


def test_linux_arm64_uses_verified_local_bundle_instead_of_make_deps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source" / "linux_arm64"
    (source / "lib").mkdir(parents=True)
    (source / "lib" / "libexample.a").write_bytes(b"compiled")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(
        source,
        tmp_path / "dist",
        spec,
        blender_commit="abc123",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.0",
    )
    blender_repo = tmp_path / "blender"
    blender_repo.mkdir()
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    commands = []
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_ARCHIVE", str(artifacts.archive))
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_MANIFEST", str(artifacts.manifest))
    monkeypatch.setattr(strategy, "run_command", lambda command, cwd: commands.append(command))

    strategy.setup_build_environment()

    assert commands == ["./build_files/utils/make_update.py --no-libraries"]
    assert (blender_repo / "lib/linux_arm64/lib/libexample.a").read_bytes() == b"compiled"


def test_linux_arm64_builds_bpy_with_gcc14(tmp_path: Path):
    blender_repo = tmp_path / "blender"
    blender_repo.mkdir()
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    stale_cache = strategy.build_dir / "CMakeCache.txt"
    stale_cache.parent.mkdir(parents=True)
    stale_cache.write_text(
        "CMAKE_C_COMPILER:FILEPATH=/usr/bin/cc\n"
        "CMAKE_CXX_COMPILER:FILEPATH=/usr/bin/c++\n"
    )

    strategy.prepare_bpy_build()

    assert strategy.get_bpy_build_command() == "CC=gcc-14 CXX=g++-14 make bpy"
    assert not strategy.build_dir.exists()


def test_linux_arm64_falls_back_to_native_dependencies_without_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    blender_repo = tmp_path / "blender"
    blender_repo.mkdir()
    osl_cmake = blender_repo / "build_files/build_environment/cmake/osl.cmake"
    osl_cmake.parent.mkdir(parents=True)
    osl_cmake.write_text("if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\nendif()\n")
    wayland_cmake = osl_cmake.with_name("wayland.cmake")
    wayland_cmake.write_text(
        "${MESON} setup\n"
        "  --prefix ${LIBDIR}/wayland\n"
        "  ${MESON_BUILD_TYPE}\n"
    )
    stale_wayland_build = tmp_path / "build_linux/deps_arm64/build/wayland"
    stale_wayland_build.mkdir(parents=True)
    (stale_wayland_build / "configured-with-lib").write_text("stale")
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    commands = []
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_ARCHIVE", raising=False)
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", "0")
    monkeypatch.setattr(strategy, "run_command", lambda command, cwd: commands.append(command))

    strategy.setup_build_environment()

    assert commands == [
        "./build_files/utils/make_update.py --no-libraries",
        "make deps",
    ]
    assert "--libdir lib64" in wayland_cmake.read_text()
    assert not stale_wayland_build.exists()


def test_linux_arm64_keeps_wayland_cache_after_lib64_was_harvested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    blender_repo = tmp_path / "blender"
    cmake_dir = blender_repo / "build_files/build_environment/cmake"
    cmake_dir.mkdir(parents=True)
    (cmake_dir / "osl.cmake").write_text(
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\nendif()\n"
    )
    (cmake_dir / "wayland.cmake").write_text(
        "  --prefix ${LIBDIR}/wayland\n  ${MESON_BUILD_TYPE}\n"
    )
    wayland_build = tmp_path / "build_linux/deps_arm64/build/wayland"
    wayland_build.mkdir(parents=True)
    harvested_lib64 = blender_repo / "lib/linux_arm64/wayland/lib64"
    harvested_lib64.mkdir(parents=True)
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", "0")
    monkeypatch.setattr(strategy, "run_command", lambda command, cwd: None)

    strategy.setup_build_environment()

    assert wayland_build.exists()


def test_wheel_build_and_install_use_running_python_and_check_failures(tmp_path: Path):
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    builder = type("Builder", (), {"blender_repo_dir": tmp_path / "blender"})()

    def create_wheel(*args, **kwargs):
        if not list(bin_path.glob("*.whl")):
            (bin_path / "bpy-5.2.0-cp313-cp313-manylinux_2_39_aarch64.whl").touch()

    with patch("buildbpy.main.subprocess.run", side_effect=create_wheel) as run:
        BlenderBuilder.build_and_manage_wheel(
            builder, bin_path, True, False, "", "v5.2.0"
        )

    assert run.call_args_list[0].args[0][0] == sys.executable
    assert run.call_args_list[0].kwargs["check"] is True
    assert run.call_args_list[1].args[0][:3] == [sys.executable, "-m", "pip"]
    assert run.call_args_list[1].kwargs["check"] is True


def test_download_release_bundle_streams_named_assets(tmp_path: Path):
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    payloads = {
        spec.archive_name: b"archive-bytes",
        spec.manifest_name: b'{"archive": "test"}',
        spec.checksum_name: b"checksum  archive\n",
    }

    request_timeouts = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_timeouts.append(request.extensions["timeout"])
        if request.url.path.endswith(f"/releases/tags/{spec.release_tag}"):
            assets = [
                {
                    "name": name,
                    "url": f"https://api.github.test/assets/{index}",
                }
                for index, name in enumerate(payloads)
            ]
            return httpx.Response(200, json={"assets": assets})
        index = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, content=list(payloads.values())[index])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        artifacts = download_release_bundle(
            client,
            "michaelgold/buildbpy",
            "token",
            spec,
            tmp_path,
        )

    assert artifacts is not None
    assert artifacts.archive.read_bytes() == payloads[spec.archive_name]
    assert artifacts.manifest.read_bytes() == payloads[spec.manifest_name]
    assert artifacts.checksum.read_bytes() == payloads[spec.checksum_name]
    assert all(
        all(value is not None for value in timeout.values())
        for timeout in request_timeouts
    )


def test_interrupted_release_download_preserves_existing_asset(tmp_path: Path):
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    existing = tmp_path / spec.archive_name
    existing.write_bytes(b"previous-valid-archive")

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial"
            raise httpx.ReadError("interrupted")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/releases/tags/{spec.release_tag}"):
            return httpx.Response(
                200,
                json={
                    "assets": [
                        {"name": spec.archive_name, "url": "https://api.github.test/a"},
                        {"name": spec.manifest_name, "url": "https://api.github.test/m"},
                        {"name": spec.checksum_name, "url": "https://api.github.test/s"},
                    ]
                },
            )
        return httpx.Response(200, stream=BrokenStream())

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ReadError, match="interrupted"):
            download_release_bundle(
                client, "michaelgold/buildbpy", "token", spec, tmp_path
            )

    assert existing.read_bytes() == b"previous-valid-archive"
    assert list(tmp_path.glob("*.tmp")) == []


def test_linux_arm64_uses_github_release_bundle_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source" / "linux_arm64"
    (source / "lib").mkdir(parents=True)
    (source / "lib" / "libexample.a").write_bytes(b"release")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(
        source,
        tmp_path / "release",
        spec,
        blender_commit="abc123",
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.0",
    )
    blender_repo = tmp_path / "blender"
    blender_repo.mkdir()
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    commands = []
    calls = []
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_ARCHIVE", raising=False)
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "michaelgold/buildbpy")
    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setattr(strategy, "run_command", lambda command, cwd: commands.append(command))

    def fake_download(client, repository, token, bundle_spec, output_dir):
        calls.append((repository, token, bundle_spec, output_dir))
        return artifacts

    monkeypatch.setattr("buildbpy.main.download_release_bundle", fake_download)

    strategy.setup_build_environment()

    assert commands == ["./build_files/utils/make_update.py --no-libraries"]
    assert calls[0][0:2] == ("michaelgold/buildbpy", "token")
    assert (blender_repo / "lib/linux_arm64/lib/libexample.a").read_bytes() == b"release"


def test_linux_arm64_falls_back_when_release_bundle_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "source" / "linux_arm64"
    source.mkdir(parents=True)
    (source / "value").write_text("release")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "release", spec)
    artifacts.checksum.write_text(f"{'0' * 64}  {spec.archive_name}\n")
    blender_repo = tmp_path / "blender"
    cmake_dir = blender_repo / "build_files/build_environment/cmake"
    cmake_dir.mkdir(parents=True)
    (cmake_dir / "osl.cmake").write_text(
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\nendif()\n"
    )
    (cmake_dir / "wayland.cmake").write_text(
        "${MESON} setup\n  --prefix ${LIBDIR}/wayland\n  ${MESON_BUILD_TYPE}\n"
    )
    version = ReleaseVersionCycleStrategy("5.2", "5.2.0", "release", "abc123")
    with patch("platform.machine", return_value="aarch64"):
        strategy = LinuxOSStrategy(version, tmp_path, blender_repo, httpx.Client())
    commands = []
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_ARCHIVE", raising=False)
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", raising=False)
    monkeypatch.setattr(strategy, "run_command", lambda command, cwd: commands.append(command))
    monkeypatch.setattr(
        "buildbpy.main.download_release_bundle", lambda *args, **kwargs: artifacts
    )

    strategy.setup_build_environment()

    assert commands == [
        "./build_files/utils/make_update.py --no-libraries",
        "make deps",
    ]


def test_arm64_workflow_validates_exact_tag_and_publishes_immutable_release():
    workflow = Path(".github/workflows/build_linux_arm64.yml").read_text()

    assert (
        'expected_version = tuple(map(int, os.environ["TAG"].removeprefix("v").split(".")))'
        in workflow
    )
    assert "assert bpy.app.version == expected_version" in workflow
    assert "gh release create" in workflow and "--draft" in workflow
    assert "gh release edit" in workflow and "--draft=false" in workflow
    assert "--clobber" not in workflow
    verify_offset = workflow.index("- name: Verify wheel architecture and import")
    assert "--publish" not in workflow[:verify_offset]
    assert workflow.index("- name: Publish verified bpy wheel") > verify_offset
    assert "- name: Check existing ARM64 dependency release" in workflow
    assert "id: deps_release" in workflow
    assert workflow.count("steps.deps_release.outputs.exists != 'true'") == 2
    assert "already exists and is immutable" not in workflow


def test_build_all_includes_linux_arm64_in_aggregate_success_barrier():
    workflow = Path(".github/workflows/build_all.yml").read_text()

    assert "build-for-linux-arm64:" in workflow
    assert "uses: ./.github/workflows/build_linux_arm64.yml" in workflow
    assert "tag: ${{ needs.check-version.outputs.tag_input }}" in workflow
    assert "python_version: ${{ needs.check-version.outputs.python_version }}" in workflow
    update_section = workflow.split("  update-versions:", 1)[1]
    update_needs = update_section.split("\n    if:", 1)[0]
    assert "build-for-linux-arm64" in update_needs


def test_download_release_bundle_rejects_non_object_api_payload(tmp_path: Path):
    spec = BundleSpec(blender_version="5.2.0", revision=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="release response must be a JSON object"):
            download_release_bundle(
                client, "michaelgold/buildbpy", "token", spec, tmp_path
            )


def test_bundle_rejects_link_outside_linux_arm64_subtree(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    raw_tar = tmp_path / "malicious.tar"
    with tarfile.open(raw_tar, "w") as archive:
        root = tarfile.TarInfo("linux_arm64")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        link = tarfile.TarInfo("linux_arm64/escape")
        link.type = tarfile.SYMTYPE
        link.linkname = "../sibling"
        archive.addfile(link)
    subprocess.run(
        ["zstd", "-f", str(raw_tar), "-o", str(artifacts.archive)], check=True
    )
    digest = sha256_file(artifacts.archive)
    manifest = json.loads(artifacts.manifest.read_text())
    manifest["archive_sha256"] = digest
    artifacts.manifest.write_text(json.dumps(manifest))
    artifacts.checksum.write_text(f"{digest}  {spec.archive_name}\n")

    with pytest.raises(ValueError, match="Unsafe bundle link"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            spec,
        )


def test_bundle_rejects_non_object_manifest(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    artifacts.manifest.write_text("[]")

    with pytest.raises(ValueError, match="manifest must be a JSON object"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "installed",
            spec,
        )


def test_bundle_validates_manifest_provenance(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(
        source,
        tmp_path / "dist",
        spec,
        blender_commit="expected-commit",
        python_version="3.13.12",
    )

    manifest = verify_and_extract_bundle(
        artifacts.archive,
        artifacts.manifest,
        artifacts.checksum,
        tmp_path / "installed",
        spec,
        expected_blender_commit="expected-commit",
        expected_python_series="3.13",
    )
    assert manifest["format"] == 1
    assert manifest["release_tag"] == spec.release_tag

    changed = json.loads(artifacts.manifest.read_text())
    changed["format"] = 2
    artifacts.manifest.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="format"):
        verify_and_extract_bundle(
            artifacts.archive,
            artifacts.manifest,
            artifacts.checksum,
            tmp_path / "again",
            spec,
            expected_blender_commit="expected-commit",
            expected_python_series="3.13",
        )


def test_zstd_decoder_large_stderr_does_not_deadlock(tmp_path: Path):
    source = tmp_path / "linux_arm64"
    source.mkdir()
    (source / "value").write_text("original")
    spec = BundleSpec(blender_version="5.2.0", revision=1)
    artifacts = create_bundle(source, tmp_path / "dist", spec)
    real_zstd = shutil.which("zstd")
    assert real_zstd is not None
    wrapper_dir = tmp_path / "bin"
    wrapper_dir.mkdir()
    wrapper = wrapper_dir / "zstd"
    wrapper.write_text(
        "#!/bin/sh\n"
        "dd if=/dev/zero bs=1048576 count=1 1>&2 2>/dev/null\n"
        f'exec "{real_zstd}" "$@"\n'
    )
    wrapper.chmod(0o755)
    code = (
        "from pathlib import Path; "
        "from buildbpy.arm64_deps import BundleSpec, verify_and_extract_bundle; "
        f"verify_and_extract_bundle(Path({str(artifacts.archive)!r}), "
        f"Path({str(artifacts.manifest)!r}), Path({str(artifacts.checksum)!r}), "
        f"Path({str(tmp_path / 'installed')!r}), BundleSpec('5.2.0'))"
    )
    environment = {**os.environ, "PATH": f"{wrapper_dir}:{os.environ['PATH']}"}

    subprocess.run([sys.executable, "-c", code], env=environment, check=True, timeout=10)


def test_tag_build_resolves_checked_out_head_for_dependency_provenance(tmp_path: Path):
    builder = BlenderBuilder.__new__(BlenderBuilder)
    builder.blender_repo_dir = tmp_path / "blender"
    builder.blender_repo_dir.mkdir()
    builder.root_dir = tmp_path
    builder.os_type = "Linux"
    builder.lib_dir = tmp_path / "lib"
    checkout = SimpleNamespace(
        checkout=lambda tag: None,
        set_version=lambda commit, tag: None,
        major_version="5.2",
        minor_version="5.2.0",
        release_cycle="release",
    )
    captured = {}

    def setup_strategies(
        os_type, major_version, minor_version, release_cycle, commit_hash, root, repo
    ):
        captured["commit_hash"] = commit_hash
        builder.os_strategy = SimpleNamespace(
            build_dir=tmp_path / "build",
            make_command="make",
            setup_build_environment=lambda: None,
            set_cmake_directives=lambda: None,
            prepare_bpy_build=lambda: None,
            get_bpy_build_command=lambda: "make bpy",
            run_command=lambda command, cwd: None,
            build_wheel_dir=tmp_path / "wheel",
        )

    builder.setup_strategies = setup_strategies
    builder.generate_stubs = lambda commit: None
    builder.build_and_manage_wheel = lambda *args: None

    with (
        patch("buildbpy.main.TagCheckoutStrategy", return_value=checkout),
        patch(
            "buildbpy.main.subprocess.check_output",
            return_value="resolved-head-commit\n",
        ),
    ):
        assert builder.main(
            "v5.2.0", "", False, False, False, False, "", "", False
        )

    assert captured["commit_hash"] == "resolved-head-commit"
