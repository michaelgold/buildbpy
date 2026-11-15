"""Measure make task scheduling through the real upstream wrapper.

Each task also compiles a C object, but the timed task intervals include a sleep:
this regression measures scheduling overlap, not simultaneous cc process life.
"""
import json
import shlex
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from buildbpy.main import LinuxOSStrategy, ReleaseVersionCycleStrategy

FIXTURES = Path(__file__).parent / "fixtures/blender-v5.3.0"


@pytest.mark.parametrize("version", ["5.2.0", "5.3.0"])
@pytest.mark.parametrize("makeflags", [None, "-j2"], ids=["local", "hosted"])
def test_native_dependency_subprojects_schedule_requested_parallelism(tmp_path, monkeypatch, makeflags, version):
    blender = tmp_path / "blender"
    source = blender / "build_files/build_environment"
    (source / "cmake").mkdir(parents=True)
    (source / "linux").mkdir()
    shutil.copyfile(FIXTURES.parent / f"blender-v{version}/GNUmakefile", blender / "GNUmakefile")
    wrapper = source / "linux/make_deps_wrapper.sh"
    shutil.copyfile(FIXTURES / "make_deps_wrapper.sh", wrapper)
    wrapper.chmod(0o755)
    (source / "cmake/osl.cmake").write_text(
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))\n"
        "  list(APPEND OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\nendif()\n"
    )
    (source / "cmake/ffmpeg.cmake").write_text("      --disable-vaapi\n")
    (source / "cmake/wayland.cmake").write_text(
        "${MESON} setup\n  --prefix ${LIBDIR}/wayland\n  ${MESON_BUILD_TYPE}\n"
    )
    child = source / "child"
    child.mkdir()
    record = tmp_path / "events.jsonl"
    (child / "unit.c").write_text("int example(void) { return 42; }\n")
    (child / "compile.py").write_text(
        "import json, os, subprocess, sys, time\n"
        "def record(kind):\n"
        "    with open(sys.argv[1], 'a') as f:\n"
        "        f.write(json.dumps([time.monotonic_ns(), kind, os.getpid()])+'\\n')\n"
        "record('start')\n"
        "time.sleep(0.3)\n"
        "subprocess.run(['cc', '-c', sys.argv[2], '-o', sys.argv[3]], check=True)\n"
        "record('end')\n"
    )
    (child / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(child C)\n"
        + "\n".join(
            f"add_custom_target(unit{i} ALL COMMAND python3 {child}/compile.py "
            f"{record} {child}/unit.c ${{CMAKE_BINARY_DIR}}/unit{i}.o)"
            for i in range(4)
        )
        + "\ninstall(FILES unit.c DESTINATION share)\n"
    )
    (source / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.16)\nproject(parent NONE)\n"
        "include(ExternalProject)\n"
        f'ExternalProject_Add(child SOURCE_DIR {child} CMAKE_GENERATOR "Unix Makefiles" '
        'CMAKE_ARGS -DCMAKE_INSTALL_PREFIX=${CMAKE_BINARY_DIR}/install INSTALL_COMMAND "")\n'
        'install(FILES CMakeLists.txt DESTINATION ${CMAKE_BINARY_DIR}/installed)\n'
    )
    monkeypatch.setenv("NPROCS", "2")
    monkeypatch.setenv("CMAKE_BUILD_PARALLEL_LEVEL", "2")
    monkeypatch.setenv("BUILDBPY_ARM64_DEPS_USE_RELEASE", "0")
    monkeypatch.delenv("BUILDBPY_ARM64_DEPS_ARCHIVE", raising=False)
    monkeypatch.delenv("MAKEFLAGS", raising=False)
    if makeflags:
        monkeypatch.setenv("MAKEFLAGS", makeflags)
    with patch("platform.machine", return_value="aarch64"), httpx.Client() as client:
        strategy = LinuxOSStrategy(
            ReleaseVersionCycleStrategy(".".join(version.split(".")[:2]), version, "release", "abc123"),
            tmp_path, blender, client,
        )
        def run(command, cwd):
            if "make_update.py" not in command:
                result = subprocess.run(shlex.split(command), cwd=cwd, text=True,
                                        capture_output=True, timeout=60)
                assert result.returncode == 0, result.stdout + result.stderr
        monkeypatch.setattr(strategy, "run_command", run)
        strategy.setup_build_environment()
    active = peak = 0
    events = sorted(json.loads(line) for line in record.read_text().splitlines())
    assert len(events) == 8
    for _, kind, _ in events:
        active += 1 if kind == "start" else -1
        peak = max(peak, active)
    assert active == 0
    assert peak == 2, f"expected two concurrent build tasks, observed {peak}"
    assert len(list((tmp_path / "build_linux/deps_arm64").rglob("unit*.o"))) == 4
