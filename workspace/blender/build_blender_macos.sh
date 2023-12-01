#!/bin/bash

source ~/.bashrc 
python -m pip install -U pip setuptools wheel
python --version
env
# build
cd blender
make update
make bpy

# Create wheel
cd build_files/utils
python make_bpy_wheel.py /build/build_darwin_bpy/bin/ /wheel-output

