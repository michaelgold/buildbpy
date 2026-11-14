"""The native ARM64 fallback must configure Blender's own mirror option."""
import shlex
import subprocess
from pathlib import Path
import hashlib
import shutil
from unittest.mock import patch

import httpx
import pytest

from buildbpy.main import LinuxOSStrategy, ReleaseVersionCycleStrategy


@pytest.mark.parametrize("checkout", ["blender", "custom-checkout"])
@pytest.mark.parametrize("version", ["5.2.0", "5.3.0", "5.3.1"])
def test_native_dependencies_configure_mirror_before_make(tmp_path, monkeypatch, version, checkout):
    root = tmp_path / "build with spaces"
    blender = root / checkout
    cmake_dir = blender / "build_files/build_environment/cmake"
    cmake_dir.mkdir(parents=True)
    (cmake_dir / "osl.cmake").write_text(
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\n"
        "  list(APPEND OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\nendif()\n"
    )
    (cmake_dir / "wayland.cmake").write_text(
        "${MESON} setup\n  --prefix ${LIBDIR}/wayland\n  ${MESON_BUILD_TYPE}\n"
    )
    # A real, tiny CMake project checks cache propagation, including an existing
    # upstream-enabled cache. It deliberately doesn't emulate Blender downloads.
    (cmake_dir.parent / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.16)\nproject(mirror NONE)\n'
        'option(PACKAGE_USE_UPSTREAM_SOURCES "upstream" ON)\n'
    )
    build = root / "build_linux/deps_arm64"
    subprocess.run(["cmake", "-S", str(cmake_dir.parent), "-B", str(build),
                    "-DPACKAGE_USE_UPSTREAM_SOURCES:BOOL=ON"], check=True, capture_output=True)
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_ARCHIVE", raising=False)
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", "0")
    with patch("platform.machine", return_value="aarch64"), httpx.Client() as client:
        strategy = LinuxOSStrategy(
            ReleaseVersionCycleStrategy(".".join(version.split(".")[:2]), version, "release", "abc123"),
            root, blender, client,
        )
        commands = []
        def run(command, cwd):
            args = shlex.split(command)
            commands.append(args)
            if args[0] == "cmake":
                subprocess.run(args, cwd=cwd, check=True, capture_output=True)
        monkeypatch.setattr(strategy, "run_command", run)
        strategy.setup_build_environment()
    assert len(commands) == 3
    assert commands[1] == [
        "cmake", "-S", str(cmake_dir.parent), "-B", str(build),
        "-DPACKAGE_USE_UPSTREAM_SOURCES:BOOL=OFF",
        f"-DHARVEST_TARGET={blender / 'lib/linux_arm64'}",
    ]
    assert commands[2] == ["make", "deps", f"DEPS_BUILD_DIR={build}",
                           f"DEPS_INSTALL_DIR={blender / 'lib/linux_arm64'}"]
    assert "PACKAGE_USE_UPSTREAM_SOURCES:BOOL=OFF" in (build / "CMakeCache.txt").read_text()


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("version", ["5.2.0", "5.3.0"])
def test_upstream_make_deps_preserves_preconfigured_mirror(tmp_path, version):
    shutil.copyfile(FIXTURES / f"blender-v{version}" / "GNUmakefile", tmp_path / "GNUmakefile")
    source = tmp_path / "build_files/build_environment"
    source.mkdir(parents=True)
    (source / "CMakeLists.txt").write_text(
        'cmake_minimum_required(VERSION 3.16)\nproject(mirror NONE)\n'
        'option(PACKAGE_USE_UPSTREAM_SOURCES "upstream" ON)\n'
        'if(PACKAGE_USE_UPSTREAM_SOURCES)\nmessage(FATAL_ERROR "upstream enabled")\nendif()\n'
    )
    build = tmp_path / "deps"
    subprocess.run(["cmake", "-S", str(source), "-B", str(build),
                    "-DPACKAGE_USE_UPSTREAM_SOURCES:BOOL=OFF"], check=True, capture_output=True)
    # Exercise the unchanged upstream recipe, replacing only dependency compilation.
    subprocess.run(["make", "deps", f"DEPS_BUILD_DIR={build}",
                    f"DEPS_INSTALL_DIR={tmp_path / 'harvest'}", "DEPS_BUILD_COMMAND=true",
                    "BUILD_CMAKE_ARGS=-DPACKAGE_USE_UPSTREAM_SOURCES:BOOL=ON"],
                   cwd=tmp_path, check=True, capture_output=True)
    assert "PACKAGE_USE_UPSTREAM_SOURCES:BOOL=OFF" in (build / "CMakeCache.txt").read_text()


@pytest.mark.parametrize("version", ["5.2.0", "5.3.0"])
@pytest.mark.parametrize("valid", [True, False], ids=["valid-cache", "corrupt-cache"])
def test_upstream_mirror_checks_cached_archive_hash(tmp_path, version, valid):
    source = (FIXTURES / f"blender-v{version}" / "download.cmake").read_text()
    # Isolate the unchanged upstream function from the full dependency call list.
    function = source.split("endfunction(download_source)", 1)[0] + "endfunction(download_source)\n"
    archive = tmp_path / "package.tar.xz"
    archive.write_bytes(b"good archive" if valid else b"corrupt archive")
    expected = hashlib.sha256(b"good archive").hexdigest()
    script = tmp_path / "check.cmake"
    script.write_text(
        'cmake_minimum_required(VERSION 3.16)\n' + function +
        f'set(PACKAGE_DIR "{tmp_path}")\n'
        'set(PACKAGE_USE_UPSTREAM_SOURCES OFF)\n'
        'set(TEST_FILE package.tar.xz)\nset(TEST_HASH_TYPE SHA256)\n'
        f'set(TEST_HASH {expected})\ndownload_source(TEST)\n'
    )
    result = subprocess.run(["cmake", "-P", str(script)], capture_output=True, text=True)
    if valid:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "SHA256 mismatch" in result.stderr
