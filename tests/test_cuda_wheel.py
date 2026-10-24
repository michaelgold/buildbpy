import zipfile
from pathlib import Path

import pytest
import zstandard

from buildbpy import cuda_wheel
from buildbpy.main import BlenderBuilder, LinuxOSStrategy


def make_wheel(path, missing=None, compressed=True, version="5.2"):
    addons = "addons_core" if version == "5.2" else "addons"
    with zipfile.ZipFile(path, "w") as wheel:
        for arch in cuda_wheel.CUDA_ARCHITECTURES:
            if arch == missing:
                continue
            ext = "ptx" if arch.startswith("compute_") else "cubin"
            suffix = ".zst" if compressed else ""
            wheel.writestr(
                f"bpy/{version}/scripts/{addons}/cycles/lib/kernel_{arch}.{ext}{suffix}",
                zstandard.ZstdCompressor().compress(b"kernel fixture")
                if compressed
                else b"kernel fixture",
            )


@pytest.mark.parametrize(
    "payload", [b"not zstd", zstandard.ZstdCompressor().compress(b"")]
)
def test_wheel_validation_rejects_invalid_or_empty_compressed_kernel(tmp_path, payload):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, missing="sm_120")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "bpy/5.2/scripts/addons_core/cycles/lib/kernel_sm_120.cubin.zst", payload
        )
    with pytest.raises(ValueError, match="sm_120"):
        cuda_wheel.validate_cuda_wheel(wheel)


@pytest.mark.parametrize(
    "payload",
    [
        zstandard.ZstdCompressor().compress(b"kernel") + b"garbage",
        zstandard.ZstdCompressor(write_content_size=False).compress(b"kernel"),
    ],
)
def test_wheel_validation_rejects_frames_blender_cannot_load(tmp_path, payload):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, missing="sm_120")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "bpy/5.2/scripts/addons_core/cycles/lib/kernel_sm_120.cubin.zst", payload
        )
    with pytest.raises(ValueError, match="sm_120"):
        cuda_wheel.validate_cuda_wheel(wheel)


def test_modern_blender_rejects_uncompressed_only_wheel(tmp_path):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, compressed=False)
    with pytest.raises(ValueError, match="CUDA kernels"):
        cuda_wheel.validate_cuda_wheel(wheel)


def test_wheel_validation_rejects_unknown_resource_version(tmp_path):
    with pytest.raises(ValueError, match="resource version"):
        cuda_wheel.validate_cuda_wheel(tmp_path / "unknown.whl")


def test_wheel_validation_rejects_stale_version_kernels(tmp_path):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, missing="sm_120")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(
            "bpy/5.1/scripts/addons_core/cycles/lib/kernel_sm_120.cubin.zst",
            zstandard.ZstdCompressor().compress(b"kernel"),
        )
    with pytest.raises(ValueError, match="sm_120"):
        cuda_wheel.validate_cuda_wheel(wheel)


def test_wheel_validation_rejects_missing_blackwell(tmp_path):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, missing="sm_120")
    validator = getattr(cuda_wheel, "validate_cuda_wheel", None)
    assert callable(validator), "CUDA wheel validator is missing"
    with pytest.raises(ValueError, match="sm_120"):
        validator(wheel)


@pytest.mark.parametrize("is_arm64", [False, True])
@pytest.mark.parametrize("output", ["missing", "empty", "valid"])
def test_validate_before_install_or_publish(tmp_path, monkeypatch, is_arm64, output):
    builder = BlenderBuilder.__new__(BlenderBuilder)
    strategy = LinuxOSStrategy.__new__(LinuxOSStrategy)
    strategy.is_arm64 = is_arm64
    builder.os_strategy = strategy
    builder.blender_repo_dir = tmp_path
    calls = []

    def run(command, **kwargs):
        calls.append("build" if len(command) == 3 else "install")
        if len(command) == 3 and output != "missing":
            if output == "valid":
                make_wheel(tmp_path / "bpy-5.2.1-test.whl")
            else:
                with zipfile.ZipFile(tmp_path / "bpy-5.2.1-test.whl", "w"):
                    pass

    monkeypatch.setattr("buildbpy.main.subprocess.run", run)
    monkeypatch.setattr(
        builder, "publish_github", lambda *args: calls.append("publish")
    )
    if output == "valid":
        builder.build_and_manage_wheel(tmp_path, True, True, "unused", "v5.2.1")
        assert calls == ["build", "install", "publish"]
    else:
        with pytest.raises(ValueError, match="wheel|CUDA"):
            builder.build_and_manage_wheel(tmp_path, True, True, "unused", "v5.2.1")
        assert calls == ["build"]


@pytest.mark.parametrize("compressed", [False, True])
def test_wheel_validation_accepts_all_packaged_kernels(tmp_path, compressed):
    version = "5.2" if compressed else "4.1"
    wheel = tmp_path / f"bpy-{version}.1-test.whl"
    make_wheel(wheel, compressed=compressed, version=version)
    assert len(cuda_wheel.validate_cuda_wheel(wheel)) == len(
        cuda_wheel.CUDA_ARCHITECTURES
    )


@pytest.mark.parametrize(
    "bad_path,data",
    [
        ("bpy/5.2/scripts/addons_core/cycles/lib/kernel_sm_120.cubin.zst", b""),
        ("other/cycles/lib/kernel_sm_120.cubin.zst", b"kernel"),
        ("bpy/5.2/source/kernel_sm_120.cubin.zst", b"kernel"),
        ("bpy/5.2/scripts/addons_core/cycles/lib/kernel_sm_120.ptx.zst", b"kernel"),
    ],
)
def test_wheel_validation_rejects_empty_misplaced_or_wrong_format(
    tmp_path, bad_path, data
):
    wheel = tmp_path / "bpy-5.2.1-test.whl"
    make_wheel(wheel, missing="sm_120")
    with zipfile.ZipFile(wheel, "a") as archive:
        archive.writestr(bad_path, data)
    with pytest.raises(ValueError, match="sm_120"):
        cuda_wheel.validate_cuda_wheel(wheel)


@pytest.mark.parametrize(
    "workflow,repository_arch",
    [
        ("build_linux.yml", "x86_64"),
        ("build_linux_arm64.yml", "sbsa"),
    ],
)
def test_linux_workflows_install_cuda13_before_build(workflow, repository_arch):
    text = (
        Path(__file__).resolve().parents[1] / ".github/workflows" / workflow
    ).read_text()
    assert f"ubuntu2404/{repository_arch}/cuda-keyring_" in text
    assert "cuda-toolkit-13-0" in text
    assert "cuda-toolkit-12-8" not in text
    assert "/usr/local/cuda-13.0/bin" in text
    assert text.index("cuda-toolkit-13-0") < text.index("      - name: Build ")
    assert "--install --publish" not in text
    assert text.index("import bpy") < text.index(
        "      - name: Publish verified bpy wheel"
    )


@pytest.mark.parametrize("is_arm64", [False, True])
def test_linux_builds_cuda13_kernels(tmp_path, is_arm64):
    strategy = LinuxOSStrategy.__new__(LinuxOSStrategy)
    strategy.is_arm64 = is_arm64
    strategy.blender_repo_dir = tmp_path
    config = tmp_path / "build_files/cmake/config/bpy_module.cmake"
    config.parent.mkdir(parents=True)
    config.touch()
    strategy.set_cmake_directives()
    text = config.read_text()
    assert 'set(WITH_CYCLES_CUDA_BINARIES ON CACHE BOOL "" FORCE)' in text
    assert 'set(WITH_CYCLES_DEVICE_CUDA ON CACHE BOOL "" FORCE)' in text
    assert (
        'set(CYCLES_CUDA_BINARIES_ARCH "sm_75;sm_80;sm_86;sm_89;sm_90;sm_100;sm_120;compute_120" CACHE STRING "" FORCE)'
        in text
    )
