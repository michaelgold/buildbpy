import typer
from pathlib import Path
import httpx
import json
import subprocess
import dotenv
import os
import ssl
import platform
import tarfile
import zipfile
import shutil
from github import Github
from .utils import dmgextractor, make_utils
from abc import ABC, abstractmethod

dotenv.load_dotenv()

# Strategy Interface for Download
class VersionCycleStrategy(ABC):
    def __init__(self, major_version: str, minor_version: str, release_cycle: str):
        self.major_version = major_version
        self.minor_version = minor_version
        self.release_cycle = release_cycle

    @abstractmethod
    def get_svn_root(self) -> Path:
        pass

    @abstractmethod
    def download(self, major_version, minor_version, release_cycle):
        pass

class ReleaseVersionCycleStrategy(VersionCycleStrategy):
    def get_svn_root(self):
        return f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{self.major_version}-release/lib/" 
    
    def download(self, major_version, minor_version, release_cycle):
        # Implement download logic for release version
        pass


class CandidateVersionCycleStrategy(VersionCycleStrategy):
    def download(self, major_version, minor_version, release_cycle):
        # Implement download logic for candidate version
        pass


class OSStrategy(ABC):
    def __init__(self, version_strategy: VersionCycleStrategy,  root_dir: Path, blender_repo_dir: Path):
        self.build_dir: Path = None
        self.lib_path: Path = None
        self.root_dir = root_dir
        self.bin_dir = self.root_dir / "blender-bin"
        self.version_strategy = version_strategy
    
    @abstractmethod
    def get_blender_binary(self) -> Path:
        pass

class WindowsOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path):
        super().__init__(version_strategy, root_dir, blender_repo_dir)
        self.lib_path = f"{self.version_strategy.get_svn_root()}win64_vc15"
        self.build_dir = self.root_dir / "build_windows_Bpy_x64_vc17_Release/bin/"
        self.make_command = blender_repo_dir / "make.bat"
    
    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender.exe"

class MacOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path):
        super().__init__(version_strategy, root_dir, blender_repo_dir)
        self.lib_path = f"{self.version_strategy.get_svn_root()}macos"
        self.build_dir = self.root_dir / "build_darwin_bpy"
        self.make_command = "make"

    def get_blender_binary(self):
        return self.bin_dir / f"Blender.app/Contents/MacOS/Blender"
    
class LinuxOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path):
        super().__init__(version_strategy, root_dir, blender_repo_dir)
        self.lib_path = f"{self.version_strategy.get_svn_root()}build_linux_bpy"
        self.build_dir = self.root_dir / "linux_x86_64_glibc_228"
        self.make_command = "make"
    
    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender"


class CheckoutStrategy(ABC):
    def __init__(self, blender_repo_dir: Path):
        self.blender_repo_dir = blender_repo_dir
        if not blender_repo_dir.exists():
            subprocess.run(["git", "clone", "--recursive", "https://github.com/blender/blender.git"], cwd=self.root_dir)
        subprocess.run(["git", "fetch", "--all"], cwd=blender_repo_dir)
    
    @abstractmethod
    def checkout(self, id: str):
        pass

class TagCheckoutStrategy(CheckoutStrategy):
    def checkout(self, id):
        subprocess.run(["git", "checkout", f"tags/{id}"], cwd=self.blender_repo_dir)

class CommitCheckoutStrategy(CheckoutStrategy):
    def checkout(self, id):
        subprocess.run(["git", "checkout", id], cwd=self.blender_repo_dir)




class BlenderBuilder:
    def __init__(self, blender_repo_dir: Path):
        self.root_dir = Path.home() / ".buildbpy"

        self.blender_repo_dir = blender_repo_dir if blender_repo_dir is not None else self.root_dir / "blender"
        self.lib_dir = self.root_dir / "lib"
        self.bin_dir = self.root_dir / "blender-bin"
        self.download_dir = self.root_dir / "downloads"
        self.python_api_dir = self.root_dir / "python_api"
        self.os_type = platform.system()
        self.github = Github()
        self.github_repo = self.github.get_repo("blender/blender")
        self.root_dir.mkdir(parents=True, exist_ok=True)
        # self.build_dir = None
        self.version_strategy: VersionCycleStrategy = None
        self.major_version = None
        self.minor_version = None 
        self.release_cycle = None
        self.checkout_strategy: CheckoutStrategy = None
        self.os_strategy: OSStrategy = None
    
    def set_version_strategy(self):
        if self.release_cycle == "release":
            self.version_strategy = ReleaseVersionCycleStrategy(self.major_version, self.minor_version, self.release_cycle)
        elif self.release_cycle == "candidate":
            self.version_strategy = CandidateVersionCycleStrategy(self.major_version, self.minor_version, self.release_cycle)
        # Add conditions for other release cycles (alpha, beta)
        else:
            raise ValueError(f"Unsupported release cycle: {self.release_cycle}")
    
  


    def get_valid_commits(self, commit_hash: str):
        commit = self.github_repo.get_commit(commit_hash)
        return commit.sha if commit_hash in commit.sha else None

    def get_valid_branch(self, branch: str):
        branches = self.github_repo.get_branches()
        for b in branches:
            if branch == b.name:
                print(f"Found branch: {b}")
                return b.commit.sha
        return None

    def set_version(self, blender_source_dir: Path = None):
        version = make_utils.parse_blender_version(blender_source_dir)
        self.major_version = f"{version.version // 100}.{version.version % 100}"
        self.minor_version = f"{version.version // 100}.{version.version % 100}.{version.patch}"
        self.release_cycle = version.cycle
        self.set_version_strategy()

    def download_blender(self, commit_hash: str):
        commit_hash_short = commit_hash[:12] if commit_hash else ""
        url_root = f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{self.major_version}" if self.release_cycle == "release" else "https://builder.blender.org/download/daily"
        release_suffix = f"-{self.release_cycle}+main.{commit_hash_short}" if self.release_cycle in ["alpha", "beta"] else f"-candidate+{self.major_version.replace('.', '')}.{commit_hash_short}" if self.release_cycle == "rc" else ""
        file_suffix = "" if self.release_cycle == "release" else "-release"
        
        system_type = "linux-" if self.os_type == "Linux" else "windows-" if self.os_type == "Windows" else "macos-" if self.os_type == "Darwin" else ""
        arch = "x64" if self.release_cycle == "release" else "x86_64" if self.os_type == "Linux" else "amd64" if self.os_type == "Windows" else "arm64" if platform.machine() == "arm64" else "x64"
        file_ext = "tar.xz" if self.os_type == "Linux" else "zip" if self.os_type == "Windows" else "dmg"

        filename = f"blender-{self.minor_version}{release_suffix}-{system_type}{arch}{file_suffix}.{file_ext}"
        url = f"{url_root}/{filename}"
        
        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)
        
        with httpx.Client() as client:
            response = client.get(url)
            if response.status_code == 200:
                with open(download_dir / filename, 'wb') as file:
                    file.write(response.content)
            else:
                raise Exception(f"Failed to download Blender. Status code: {response.status_code}")

        bin_dir = self.bin_dir
        bin_dir.mkdir(parents=True, exist_ok=True)

        # Empty and extract the bin directory
        for file in bin_dir.glob("*"):
            if file.is_file():
                file.unlink()
            else:
                shutil.rmtree(file)

        if file_ext == "tar.xz":
            with tarfile.open(download_dir / filename, "r:xz") as tar:
                tar.extractall(bin_dir)
        elif file_ext == "zip":
            with zipfile.ZipFile(download_dir / filename, 'r') as zip_ref:
                zip_ref.extractall(bin_dir)
        elif file_ext == "dmg":
            with dmgextractor.DMGExtractor(download_dir / filename) as extractor:
                extractor.extractall(bin_dir)

    def generate_stubs(self, commit_hash):
        # self.download_blender(commit_hash)
        # if self.os_type == "Linux":
        #     blender_dir = list(self.bin_dir.glob("blender*"))[0]
        #     blender_binary = blender_dir / f"blender"
        # elif self.os_type == "Windows":
        #     blender_dir = list(self.bin_dir.glob("blender*"))[0]
        #     blender_binary = blender_dir / f"blender.exe"
        # elif self.os_type == "Darwin":
        #     blender_binary = self.bin_dir / f"Blender.app/Contents/MacOS/Blender"
        # else:
        #     raise Exception("Unsupported operating system")
        blender_binary = self.os_strategy.get_blender_binary()

        subprocess.run([blender_binary, "--background", "--factory-startup", "-noaudio", "--python", self.blender_repo_dir / "doc/python_api/sphinx_doc_gen.py", "--", f"--output={self.python_api_dir}"])
        subprocess.run(["python", "-m", "bpystubgen", self.python_api_dir / "sphinx-in", self.build_dir / "bin"])

    def get_valid_tag(self, tag: str = None):
        response = httpx.get(f"https://api.github.com/repos/blender/blender/tags")
        tags = response.json()
        selected_tag = tag if tag and any(t['name'] == tag for t in tags) else tags[0]['name'] if tags else None

        # data_file_path = self.root_dir / "data.json"

        # if data_file_path.exists():
        #     with open(data_file_path, 'r') as file:
        #         tag_data = json.load(file)
        #         current_tag = tag_data.get("latest_tag", "")
        # else:
        #     current_tag = ""
        #     tag_data = {}

        # if selected_tag == current_tag and not tag:
        #     print(f"Tag '{selected_tag}' has already been built. Specify a tag if you want to build it again.")
        #     return None, tag_data, data_file_path

        return selected_tag
    
    def build_and_manage_wheel(self, bin_path: Path, install: bool, publish: bool, publish_repo: str, selected_tag: str):
        # Remove existing wheel files
        for file in bin_path.glob("*.whl"):
            file.unlink()

        print("Making the bpy wheel")
        # Build the wheel
        # subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])
        make_script = self.root_dir / "blender/build_files/utils/make_bpy_wheel.py"
        subprocess.run(["python", make_script, bin_path])

        if install:
            wheel_file = next(bin_path.glob("*.whl"), None)
            if wheel_file:
                print("Installing the wheel")
                subprocess.run(["pip", "install", "--force-reinstall", "--no-deps", wheel_file])
        
        if publish:
            print("Publishing to GitHub Releases")
            self.publish_github(selected_tag, bin_path, publish_repo)
    
    def setup_build_environment(self):
        # Determine the appropriate build directory and library path based on the OS
        # if self.os_type == "Linux":
        #     self.build_dir = self.root_dir / "build_linux_bpy"
        #     lib_path = f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{self.major_version}-release/lib/linux_x86_64_glibc_228/"
        # elif self.os_type == "Windows":
        #     self.build_dir = self.root_dir / "build_windows_Bpy_x64_vc17_Release/bin/"
        #     lib_path = f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{self.major_version}-release/lib/win64_vc15/"
        # elif self.os_type == "Darwin":  # MacOS
        #     self.build_dir = self.root_dir / "build_darwin_bpy"
        #     lib_path = f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{self.major_version}-release/lib/macos/"
        # else:
        #     raise Exception("Unsupported operating system for library setup")

        self.build_dir = self.os_strategy.build_dir
        lib_path = self.os_strategy.lib_path
        
        # Checkout libraries if not present
        if not self.lib_dir.exists():
            print(f"Installing libraries to: {self.lib_dir}")
            self.lib_dir.mkdir(parents=True, exist_ok=True)
            if self.os_type != "Darwin":
                subprocess.run(["svn", "checkout", lib_path], cwd=self.lib_dir)
        else:
            print(f"Libraries already installed in {self.lib_dir}")


        
    def main(self, tag: str, commit: str, branch: str, clear_lib: bool, clear_cache: bool, publish: bool, install: bool, publish_repo: str):
        selected_tag = None
        commit_hash = None
        is_valid_branch = False
        is_valid_commit = False

        if tag:
            selected_tag = self.get_valid_tag(tag)

        # if branch:
        #     is_valid_branch = self.get_valid_branch(branch)
        #     commit_hash = is_valid_branch if is_valid_branch else None

        if commit:
            is_valid_commit = self.get_valid_commits(commit)
            commit_hash = is_valid_commit if is_valid_commit else None

        if not selected_tag and not is_valid_commit:
            return False

       
        blender_repo_dir = self.blender_repo_dir

        # Checkout the correct state in the repo
        if selected_tag:
            self.checkout_strategy = TagCheckoutStrategy(blender_repo_dir)
            self.checkout_strategy.checkout(selected_tag)

        # elif branch:
        #     subprocess.run(["git", "checkout", branch], cwd=blender_repo_dir)

        elif commit:
            self.checkout_strategy = CommitCheckoutStrategy(blender_repo_dir)
            self.checkout_strategy.checkout(commit)
            

        # Clear cache and library if requested
        if clear_cache and self.build_dir.exists():
            shutil.rmtree(self.build_dir)
        if clear_lib and self.lib_dir.exists():
            shutil.rmtree(self.lib_dir)

        # Get Blender version and setup build
        self.set_version(blender_repo_dir)
        if self.os_type == "Linux":
            self.os_strategy = LinuxOSStrategy(self.version_strategy, self.root_dir, self.blender_repo_dir)
        elif self.os_type == "Windows":
            self.os_strategy = WindowsOSStrategy(self.version_strategy, self.root_dir, self.blender_repo_dir)
        elif self.os_type == "Darwin":
            self.os_strategy = MacOSStrategy(self.version_strategy, self.root_dir, self.blender_repo_dir)
        else:
            raise Exception("Unsupported operating system")
        
        make_command = self.os_strategy.make_command
        self.setup_build_environment()

        # Generate stubs and build Blender
        self.generate_stubs( commit_hash)
        subprocess.run([make_command, "update"], cwd=blender_repo_dir)
        subprocess.run([make_command, "bpy"], cwd=blender_repo_dir)

        # Build and install or publish the wheel
        bin_path = self.build_dir / "bin"
        self.build_and_manage_wheel(bin_path, install, publish, publish_repo, selected_tag)

        # # Update the data file if needed
        # if tag and data_file_path:
        #     tag_data["latest_tag"] = selected_tag
        #     with open(data_file_path, 'w') as file:
        #         json.dump(tag_data, file)
        
        return True
    
    def publish_github(self, tag: str, wheel_dir: Path, repo: str):
        github_token = self._get_github_token()
        headers = self._get_github_headers(github_token)
        ssl_context = self._get_ssl_context()

        with httpx.Client(headers=headers, verify=ssl_context) as client:
            release_id = self._get_or_create_release(client, tag, repo)
            self._upload_assets_to_release(client, tag, wheel_dir, release_id, repo)

    def _get_github_token(self):
        github_token = os.getenv("GITHUB_TOKEN")
        if not github_token:
            raise ValueError("GitHub token not found in environment variables.")
        return github_token

    def _get_github_headers(self, github_token):
        return {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }

    def _get_ssl_context(self):
        return ssl.create_default_context()

    def _get_or_create_release(self, client, tag, repo):
        release_url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
        response = client.get(release_url)
        if response.status_code in [200, 201]:
            return response.json()['id']
        
        # Create a new release if not exists
        return self._create_new_release(client, tag, repo)

    def _create_new_release(self, client, tag, repo):
        release_data = {
            "tag_name": tag,
            "target_commitish": "main",
            "name": f"Release {tag}",
            "body": f"Release for Blender {tag}",
            "draft": False,
            "prerelease": False
        }
        response = client.post(f"https://api.github.com/repos/{repo}/releases", json=release_data)
        response.raise_for_status()  # Will raise an exception for HTTP error responses
        return response.json()['id']

    def _upload_assets_to_release(self, client, tag, wheel_dir, release_id, repo):
        for wheel_file in wheel_dir.glob("*.whl"):
            upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={wheel_file.name}"
            with open(wheel_file, 'rb') as file:
                response = client.post(upload_url, content=file.read(), headers={"Content-Type": "application/octet-stream"})
                response.raise_for_status()  # Will raise an exception for HTTP error responses


app = typer.Typer()


@app.command()
def main(tag: str = typer.Option(None), commit: str = typer.Option(None), branch: str = typer.Option(None), clear_lib: bool = typer.Option(False), clear_cache: bool = typer.Option(False), publish: bool = typer.Option(False), install: bool = typer.Option(False), publish_repo: str = typer.Option("michaelgold/buildbpy"), blender_source_dir: str = typer.Option(None)):
    builder = BlenderBuilder(blender_source_dir)
    return builder.main(tag, commit, branch, clear_lib, clear_cache, publish, install, publish_repo)

if __name__ == "__main__":
    app()

  