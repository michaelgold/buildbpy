"""Linux CUDA 13 kernel policy and wheel content validation."""

import re
import zipfile
from pathlib import Path, PurePosixPath

import zstandard

# CUDA 13 removed offline compilation below compute capability 7.5.
# Keep a PTX fallback as well as native kernels, including Blackwell sm_120.
CUDA_ARCHITECTURES = (
    "sm_75",
    "sm_80",
    "sm_86",
    "sm_89",
    "sm_90",
    "sm_100",
    "sm_120",
    "compute_120",
)


def validate_cuda_wheel(wheel_path: Path) -> list[str]:
    """Require every configured kernel in the installed Cycles resource tree.

    Accept upstream's compressed kernels and older uncompressed packaging.
    This is a content gate, not a replacement for a target-GPU render test.
    """
    version = re.match(r"bpy-(\d+\.\d+)\.", wheel_path.name)
    if not version:
        raise ValueError(
            f"Cannot determine Blender resource version from wheel {wheel_path}"
        )
    compressed = tuple(map(int, version[1].split("."))) >= (4, 2)
    addons = "addons_core" if compressed else "addons"
    resource_dir = PurePosixPath(f"bpy/{version[1]}/scripts/{addons}/cycles/lib")
    with zipfile.ZipFile(wheel_path) as wheel:
        kernels = {}
        for info in wheel.infolist():
            path = PurePosixPath(info.filename)
            if path.parent == resource_dir and info.file_size > 0:
                kernels[path.name] = info.filename
        found = []
        missing = []
        for arch in CUDA_ARCHITECTURES:
            ext = "ptx" if arch.startswith("compute_") else "cubin"
            name = f"kernel_{arch}.{ext}"
            match = kernels.get(name + ".zst" if compressed else name)
            if match:
                try:
                    payload = wheel.read(match)  # Also validates the ZIP CRC.
                    if match.endswith(".zst"):
                        size = zstandard.frame_content_size(payload)
                        if size < 0 or size > 512 * 1024 * 1024:
                            raise ValueError(
                                "missing or excessive declared kernel size"
                            )
                        payload = zstandard.ZstdDecompressor().decompress(
                            payload, allow_extra_data=False
                        )
                    if not payload:
                        raise ValueError("empty kernel payload")
                except (zstandard.ZstdError, zipfile.BadZipFile, ValueError) as exc:
                    raise ValueError(
                        f"{wheel_path}: invalid CUDA kernel {match}: {exc}"
                    ) from exc
                found.append(match)
            else:
                missing.append(arch)
        if missing:
            raise ValueError(
                f"{wheel_path}: missing nonempty Cycles CUDA kernels: {', '.join(missing)}"
            )
        return sorted(found)
