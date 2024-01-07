#!/usr/bin/env python3

"""
Make Python wheel package (`*.whl`) file from Blender built with 'WITH_PYTHON_MODULE' enabled.
"""

import argparse
import os
import sys
import platform
import setuptools
from pathlib import Path

# ------------------------------------------------------------------------------
# Argument Parser

def argparse_create() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "install_dir",
        metavar='INSTALL_DIR',
        type=str,
        help="The installation directory containing the \"bpy\" package.",
    )
    parser.add_argument(
        "--output-dir",
        metavar='OUTPUT_DIR',
        default=None,
        help="The destination directory for the '*.whl' file (use INSTALL_DIR when omitted).",
        required=False,
    )

    return parser

# ------------------------------------------------------------------------------
long_description = """# Blender
[Blender](https://www.blender.org) is the free and open source 3D creation suite. It supports the entirety of the 3D pipeline—modeling, rigging, animation, simulation, rendering, compositing and motion tracking, even video editing.

This package provides Blender as a Python module for use in studio pipelines, web services, scientific research, and more.

## Documentation

* [Blender Python API](https://docs.blender.org/api/current/)
* [Blender as a Python Module](https://docs.blender.org/api/current/info_advanced_blender_as_bpy.html)

## Requirements

[System requirements](https://www.blender.org/download/requirements/) are the same as Blender.

Each Blender release supports one Python version, and the package is only compatible with that version.

## Source Code

* [Releases](https://download.blender.org/source/)
* Repository: [projects.blender.org/blender/blender.git](https://projects.blender.org/blender/blender)

## Credits

Created by the [Blender developer community](https://www.blender.org/about/credits/).

Thanks to Tyler Alden Gubala for maintaining the original version of this package."""



# Main Function



def main() -> None:

    # Parse arguments.
    args = argparse_create().parse_args()

    install_dir = os.path.abspath(args.install_dir)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else install_dir

    # Set platform tag following conventions.
    if sys.platform == "darwin":
        platform_tag = "macosx_10_15_x86_64"  # Example tag, adjust as needed
    elif sys.platform == "win32":
        platform_tag = "win_amd64"  # Example tag, adjust as needed
    elif sys.platform == "linux":
        platform_tag = "manylinux1_x86_64"  # Example tag, adjust as needed
    else:
        sys.stderr.write("Unsupported platform: %s, abort!\n" % (sys.platform))
        sys.exit(1)

    os.chdir(install_dir)

    # Build wheel.
    sys.argv = [sys.argv[0], "bdist_wheel"]

    setuptools.setup(
        name="bpygold",
        version="4.0.1",  # Example version, adjust as needed
        packages=["bpy"],
        distclass=setuptools.dist.Distribution,
        options={"bdist_wheel": {"plat_name": platform_tag}},

        description="Blender as a Python module",

        long_description_content_type='text/markdown',
        license="GPL-3.0",
        author="Michael Gold",  # Adjust as needed
        author_email="goldmichael@gmail.com",  # Adjust as needed
        url="https://mike.gold"  # Adjust as needed
    )

    # Ensure output directory exists and move wheel file there.
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    dist_dir = os.path.join(install_dir, "dist")
    for f in os.listdir(dist_dir):
        if f.endswith(".pyi"):
            os.rename(os.path.join(dist_dir, f), os.path.join(output_dir, f))


if __name__ == "__main__":
    main()
