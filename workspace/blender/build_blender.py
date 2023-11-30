import subprocess
import os

def build_blender():
    # Run Blender's build commands
    os.chdir('blender')
    subprocess.check_call(['make', 'update'])
    subprocess.check_call(['make', 'bpy'])

    # Create wheel
    os.chdir('build_files/utils')
    subprocess.check_call(['python3', 'make_bpy_wheel.py', '/build/build_darwin_bpy/bin/', '/wheel-output'])

if __name__ == "__main__":
    build_blender()
