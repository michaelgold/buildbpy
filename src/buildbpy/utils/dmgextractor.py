import subprocess
from pathlib import Path
import os
import shutil

class DMGExtractor:
    def __init__(self, dmg_path, mount_point=Path.home() / 'dmgmountpoint'):
        self.dmg_path = Path(dmg_path)
        self.mount_point = mount_point

    def __enter__(self):
        self.mount_dmg()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.unmount_dmg()

    def mount_dmg(self):
        self.dmg_path = self.dmg_path.resolve()  # Ensure the path is absolute
        print(f"Mounting DMG at: {self.dmg_path}")  # Debugging: print the path

        self.mount_point.mkdir(parents=True, exist_ok=True)
        mount_cmd = f"hdiutil attach -mountpoint {self.mount_point} {self.dmg_path}"
        # result = subprocess.run(mount_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # if result.returncode != 0:
        #     raise Exception(f"Failed to mount dmg: {result.stderr.decode()}")
    
        mount_cmd = f"hdiutil attach -mountpoint {self.mount_point} {self.dmg_path}"
        result = subprocess.run(mount_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Print debugging information
        # print(f"Mount Command Output: {result.stdout.decode()}")
        # print(f"Mount Command Error: {result.stderr.decode()}")

        if result.returncode != 0:
            raise Exception(f"Failed to mount dmg: {result.stderr.decode()}")

    def unmount_dmg(self):
        unmount_cmd = f"hdiutil detach {self.mount_point}"
        result = subprocess.run(unmount_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode != 0:
            raise Exception(f"Failed to unmount dmg: {result.stderr.decode()}")

    def extractall(self, extraction_path: str):
        """ Copy all files from the mounted dmg to the extraction path """
        extraction_path = Path(extraction_path)

        # exclude = ''  # Name of the shortcut to exclude

        if not extraction_path.exists():
            extraction_path.mkdir(parents=True)

        for item in os.listdir(self.mount_point):
            s = self.mount_point / item
            d = extraction_path / item
            if not s.is_symlink():
                if s.is_dir():
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

        print(f"Copied files to {extraction_path}")
