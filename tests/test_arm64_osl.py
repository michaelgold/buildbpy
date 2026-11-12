from pathlib import Path
import shutil
import subprocess

import pytest

from buildbpy.arm64_deps import disable_arm64_osl_optix, sha256_file


FIXTURE = Path(__file__).parent / "fixtures/blender-v5.3.0/osl.cmake"
LEGACY = "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM))"
CURRENT = "if(NOT APPLE)"


def test_upstream_5_3_osl_patch(tmp_path: Path):
    assert sha256_file(FIXTURE) == (
        "534ccae78a3160fb24ace3163e82982c29891d1015e3e6b8a624490b6ddd6b6e"
    )
    original = FIXTURE.read_text()
    target = tmp_path / "osl.cmake"
    target.write_text(original)

    assert disable_arm64_osl_optix(target) is True
    expected = original.replace(CURRENT, "if(NOT (APPLE OR BLENDER_PLATFORM_ARM))", 1)
    assert target.read_text() == expected
    assert disable_arm64_osl_optix(target) is False
    assert target.read_text() == expected


@pytest.mark.parametrize("condition", [LEGACY, CURRENT])
def test_osl_patch_preserves_other_guards(tmp_path: Path, condition: str):
    original = (
        "if(NOT APPLE)\n  set(UNRELATED ON)\nendif()\n"
        f"{condition}\n  list(APPEND OSL_EXTRA_ARGS\n"
        "    -DOSL_USE_OPTIX=ON\n  )\nendif()\n"
    )
    target = tmp_path / "osl.cmake"
    target.write_text(original)
    replacement = (
        "if(NOT (APPLE OR BLENDER_PLATFORM_WINDOWS_ARM OR BLENDER_PLATFORM_ARM))"
        if condition == LEGACY else "if(NOT (APPLE OR BLENDER_PLATFORM_ARM))"
    )
    assert disable_arm64_osl_optix(target) is True
    expected = original.replace(condition + "\n  list", replacement + "\n  list")
    assert target.read_text() == expected
    assert disable_arm64_osl_optix(target) is False
    assert target.read_text() == expected


@pytest.mark.parametrize("text", [
    "set(OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\n",
    "if(NOT APPLE)\n  set(UNRELATED ON)\nendif()\n",
    "if(NOT UNKNOWN_PLATFORM)\n  list(APPEND OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\nendif()\n",
    ("if(NOT APPLE)\n  list(APPEND OSL_EXTRA_ARGS -DOSL_USE_OPTIX=ON)\nendif()\n") * 2,
], ids=["missing-guard", "unrelated-guard", "unknown-guard", "ambiguous-guards"])
def test_osl_patch_rejects_unknown_layout_without_writing(tmp_path: Path, text: str):
    target = tmp_path / "osl.cmake"
    target.write_text(text)
    with pytest.raises(ValueError, match="Unrecognized Blender OSL"):
        disable_arm64_osl_optix(target)
    assert target.read_text() == text


@pytest.mark.skipif(not shutil.which("cmake"), reason="requires CMake")
@pytest.mark.parametrize("guard", [LEGACY, CURRENT])
@pytest.mark.parametrize("apple,arm,windows_arm,optix", [
    (False, True, False, False),
    (False, False, False, True),
    (True, True, False, False),
    (False, True, True, False),
], ids=["linux-arm64", "linux-x86_64", "apple-arm64", "windows-arm64"])
def test_patched_osl_arguments_in_cmake(
    tmp_path: Path, guard: str, apple: bool, arm: bool,
    windows_arm: bool, optix: bool,
):
    # Evaluate the full upstream file; only dependency-build/harvest commands
    # are stubbed, so no downloads or compilation occur in this unit test.
    target = tmp_path / "osl.cmake"
    target.write_text(FIXTURE.read_text().replace(CURRENT, guard, 1))
    disable_arm64_osl_optix(target)
    script = tmp_path / "check.cmake"
    stubs = "".join(
        f"macro({name})\nendmacro()\n" for name in (
            "ExternalProject_Add", "ExternalProject_Add_Step", "add_dependencies",
            "harvest", "harvest_rpath_bin", "harvest_rpath_lib", "harvest_rpath_python",
        )
    )
    script.write_text(
        "cmake_minimum_required(VERSION 3.16)\n" + stubs
        + f"set(APPLE {int(apple)})\nset(BLENDER_PLATFORM_ARM {int(arm)})\n"
        + f"set(BLENDER_PLATFORM_WINDOWS_ARM {int(windows_arm)})\n"
        + f'include("{target.as_posix()}")\n'
        + f"set(EXPECT_OPTIX {int(optix)})\n"
        + 'if(NOT "-DUSE_LLVM_BITCODE=ON" IN_LIST OSL_EXTRA_ARGS)\n'
        + '  message(FATAL_ERROR "CPU LLVM bitcode disabled")\nendif()\n'
        + 'foreach(flag "-DOSL_USE_OPTIX=ON" "-DCUDA_TARGET_ARCH=sm_50" '
        + '"-DCUDA_TOOLKIT_ROOT_DIR=")\n'
        + '  if(EXPECT_OPTIX AND NOT flag IN_LIST OSL_EXTRA_ARGS)\n'
        + '    message(FATAL_ERROR "Missing GPU flag: ${flag}")\n'
        + '  elseif(NOT EXPECT_OPTIX AND flag IN_LIST OSL_EXTRA_ARGS)\n'
        + '    message(FATAL_ERROR "Unexpected GPU flag: ${flag}")\n'
        + '  endif()\nendforeach()\n'
    )
    subprocess.run(
        ["cmake", "-P", str(script)],
        check=True, capture_output=True, text=True,
    )
