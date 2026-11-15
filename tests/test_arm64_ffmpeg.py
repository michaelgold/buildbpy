"""Prevent optional host libdrm leaking into Blender's static FFmpeg."""
from pathlib import Path
import subprocess

import pytest

from buildbpy import arm64_deps


def test_upstream_ffmpeg_configure_disables_drm_but_keeps_cuda(tmp_path):
    fixture = Path(__file__).parent / "fixtures/blender-v5.3.0/ffmpeg.cmake"
    assert arm64_deps.sha256_file(fixture) == "5a0d3048848fda9c2911093375137fef886ca5c6380e7a180abca92937650b85"
    target = tmp_path / "ffmpeg.cmake"
    target.write_text(fixture.read_text())
    arm64_deps.disable_arm64_ffmpeg_libdrm(target)
    script = tmp_path / "check.cmake"
    script.write_text(
        "cmake_minimum_required(VERSION 3.16)\n"
        "set(UNIX TRUE)\nset(APPLE FALSE)\nset(WIN32 FALSE)\n"
        "macro(ExternalProject_Add)\n"
        '  set(args ${ARGV})\n'
        '  foreach(flag --disable-libdrm --disable-vaapi --enable-nvdec --enable-nvenc --enable-vulkan)\n'
        '    if(NOT flag IN_LIST args)\n'
        '      message(FATAL_ERROR "Missing flag: ${flag}")\n'
        '    endif()\n'
        '  endforeach()\n'
        "endmacro()\n"
        "macro(add_dependencies)\nendmacro()\n"
        "macro(harvest)\nendmacro()\n"
        f'include("{target.as_posix()}")\n'
    )
    subprocess.run(["cmake", "-P", str(script)], check=True, capture_output=True, text=True)


def test_disable_ffmpeg_libdrm_is_minimal_and_idempotent(tmp_path):
    target = tmp_path / "ffmpeg.cmake"
    original = "ExternalProject_Add(external_ffmpeg\n  CONFIGURE_COMMAND configure\n      --disable-vaapi\n      --enable-gpl\n)\n"
    target.write_text(original)
    assert arm64_deps.disable_arm64_ffmpeg_libdrm(target) is True
    expected = original.replace("      --disable-vaapi\n", "      --disable-vaapi\n      --disable-libdrm\n")
    assert target.read_text() == expected
    assert arm64_deps.disable_arm64_ffmpeg_libdrm(target) is False
    assert target.read_text() == expected


@pytest.mark.parametrize("text", ["", "# --disable-vaapi\n", "      --disable-vaapi\n" * 2])
def test_reject_unknown_ffmpeg_layout_without_write(tmp_path, text):
    target = tmp_path / "ffmpeg.cmake"
    target.write_text(text)
    with pytest.raises(ValueError, match="Unrecognized Blender FFmpeg"):
        arm64_deps.disable_arm64_ffmpeg_libdrm(target)
    assert target.read_text() == text
