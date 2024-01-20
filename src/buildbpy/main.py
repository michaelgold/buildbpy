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
import stat

dotenv.load_dotenv()

from abc import ABC, abstractmethod

def del_readonly(action, name, exc):
    os.chmod(name, stat.S_IWRITE)
    os.remove(name)

# Abstract Factory for creating strategies
class StrategyFactory(ABC):
    @abstractmethod
    def create_os_strategy(self, os_type, version_strategy, root_dir, blender_repo_dir, http_client):
        """
        Create and return an OS-specific strategy.

        :param os_type: Type of the operating system.
        :param version_strategy: The version cycle strategy to be used.
        :param http_client: The HTTP client for downloading tasks.
        :return: An instance of a subclass of OSStrategy.
        """
        pass

    @abstractmethod
    def create_version_strategy(self, major_version, minor_version, release_cycle, commit_hash):
        """
        Create and return a version cycle strategy.

        :param major_version: Major version of Blender.
        :param minor_version: Minor version of Blender.
        :param release_cycle: Release cycle (e.g., alpha, beta, release).
        :return: An instance of a subclass of VersionCycleStrategy.
        """
        pass

# Concrete implementation of the strategy factory
class ConcreteStrategyFactory(StrategyFactory):
    def create_os_strategy(self, os_type, version_strategy, root_dir, blender_repo_dir, http_client):
        """
        Create and return an OS-specific strategy based on the provided OS type.

        :param os_type: Type of the operating system.
        :param version_strategy: The version cycle strategy to be used.
        :param http_client: The HTTP client for downloading tasks.
        :return: An instance of a subclass of OSStrategy specific to the given OS type.
        """
        if os_type == "Windows":
            return WindowsOSStrategy(version_strategy, root_dir, blender_repo_dir, http_client)
        elif os_type == "Linux":
            return LinuxOSStrategy(version_strategy, root_dir, blender_repo_dir, http_client)
        elif os_type == "Darwin":
            return MacOSStrategy(version_strategy, root_dir, blender_repo_dir, http_client)
        else:
            raise ValueError(f"Unsupported OS type: {os_type}")

    def create_version_strategy(self, major_version, minor_version, release_cycle, commit_hash):
        """
        Create and return a version cycle strategy based on the provided version details.

        :param major_version: Major version of Blender.
        :param minor_version: Minor version of Blender.
        :param release_cycle: Release cycle (e.g., alpha, beta, release).
        :return: An instance of a subclass of VersionCycleStrategy specific to the given version details.
        """
        if release_cycle == "release":
            return ReleaseVersionCycleStrategy(major_version, minor_version, release_cycle, commit_hash)
        elif release_cycle == "rc":
            return CandidateVersionCycleStrategy(major_version, minor_version, release_cycle, commit_hash)
        elif release_cycle == "alpha":
            return AlphaBetaVersionCycleStrategy(major_version, minor_version, release_cycle, commit_hash)
        elif release_cycle == "beta":
            return AlphaBetaVersionCycleStrategy(major_version,minor_version, release_cycle, commit_hash)
        else:
            raise ValueError(f"Unsupported release cycle: {release_cycle}")



# Strategy Interface for Download
class VersionCycleStrategy(ABC):
    def __init__(self, major_version: str, minor_version: str, release_cycle: str, commit_hash: str):
        self.major_version = major_version
        self.minor_version = minor_version
        self.release_cycle = release_cycle
        self.commit_hash = commit_hash
        self.commit_hash_short = commit_hash[:12] if commit_hash else ""

    @abstractmethod
    def get_svn_root(self) -> Path:
        pass

    @abstractmethod 
    def get_download_url_root(self) -> str:
        pass    
    
    @abstractmethod 
    def get_download_url_suffix(self) -> str:
        pass
    
    @abstractmethod 
    def get_file_suffix(self) -> str:
        pass


class ReleaseVersionCycleStrategy(VersionCycleStrategy):
    def get_svn_root(self):
        return f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{self.major_version}-release/lib/" 
    
    def get_download_url_root(self):
        return f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{self.major_version}"
    
    def get_download_url_suffix(self):
        return ""
    
    def get_file_suffix(self):
        return ""


class CandidateVersionCycleStrategy(VersionCycleStrategy):
    def get_svn_root(self):
        return f"https://svn.blender.org/svnroot/bf-blender/trunk/lib/"
    
    def get_download_url_root(self):
        return "https://builder.blender.org/download/daily"
    
    def get_download_url_suffix(self):
        return f"-candidate+{self.major_version.replace('.', '')}.{self.commit_hash_short}"
    
    def get_file_suffix(self):
        return "-release"


class AlphaBetaVersionCycleStrategy(VersionCycleStrategy):
    def get_svn_root(self):
        return f"https://svn.blender.org/svnroot/bf-blender/trunk/lib/"
    
    def get_download_url_root(self):
        return "https://builder.blender.org/download/daily"
    
    def get_download_url_suffix(self):
        return f"-{self.release_cycle}+main.{self.commit_hash_short}"
    
    def get_file_suffix(self):
        return "-release" 


class OSStrategy(ABC):
    def __init__(self, version_strategy: VersionCycleStrategy,  root_dir: Path, blender_repo_dir: Path, http_client: httpx.Client):
        self.build_dir: Path = None
        self.lib_path: Path = None
        self.root_dir = root_dir
        self.bin_dir = self.root_dir / "blender-bin"
        self.download_dir = self.root_dir / "downloads"
        self.version_strategy = version_strategy
        self.http_client = http_client
        self.download_filename = f"blender-{self.version_strategy.minor_version}{self.version_strategy.get_download_url_suffix()}-{self.get_system_type()}{self.get_arch()}{self.version_strategy.get_file_suffix()}.{self.get_file_ext()}"
    
    @abstractmethod
    def get_blender_binary(self) -> Path:
        pass

    @abstractmethod
    def extract(self, downloaded_file: Path):
        pass

    @abstractmethod
    def get_system_type(self):
        pass

    @abstractmethod
    def get_arch(self):
        pass

    @abstractmethod
    def get_file_ext(self):
        pass
        
    def _prepare_bin_dir(self):
        bin_dir = self.bin_dir
        bin_dir.mkdir(parents=True, exist_ok=True)

        # Empty and extract the bin directory
        for file in bin_dir.glob("*"):
            if file.is_file():
                file.unlink()
            else:
                shutil.rmtree(file)
        
    def get_download_url(self):
        url = f"{self.version_strategy.get_download_url_root()}/{self.download_filename}"
        return url
    
    def download_file(self) -> Path:
        url = self.get_download_url()
        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        print(f"Downloading Blender from {url}")
        response = self.http_client.get(url)
        if response.status_code == 200:
            download_path = download_dir / self.download_filename
            with open(download_path, 'wb') as file:
                file.write(response.content)
        else:
            raise Exception(f"Failed to download Blender from {url}")
        
        return download_path


class WindowsOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path, http_client: httpx.Client):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}win64_vc15"
        self.build_dir = self.root_dir / "build_windows_Bpy_x64_vc17_Release/bin/"
        self.make_command = blender_repo_dir / "make.bat"
    
    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender.exe"
    
    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with zipfile.ZipFile(downloaded_file, 'r') as zip_ref:
                zip_ref.extractall(self.bin_dir)

    def get_system_type(self):
        system_type = "windows-" if self.version_strategy.release_cycle == "release" else "windows."
        return system_type

    def get_arch(self):
        arch = "x64" if self.version_strategy.release_cycle == "release" else "amd64"
        return arch

    def get_file_ext(self):
        return "zip"


class MacOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path, http_client: httpx.Client):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}macos"
        self.build_dir = self.root_dir / "build_darwin_bpy"
        self.make_command = "make"

    def get_blender_binary(self):
        return self.bin_dir / f"Blender.app/Contents/MacOS/Blender"
    
    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with dmgextractor.DMGExtractor(downloaded_file) as extractor:
            extractor.extractall(self.bin_dir)

    def get_system_type(self):
        system_type = "macos-" if self.version_strategy.release_cycle == "release" else "darwin."
        return system_type

    def get_arch(self):
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        return arch

    def get_file_ext(self):
        return "dmg"

class LinuxOSStrategy(OSStrategy):
    def __init__(self, version_strategy: VersionCycleStrategy, root_dir: Path, blender_repo_dir: Path, http_client: httpx.Client):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}build_linux_bpy"
        self.build_dir = self.root_dir / "linux_x86_64_glibc_228"
        self.make_command = "make"
    
    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender"
    
    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with tarfile.open(downloaded_file, "r:xz") as tar:
                tar.extractall(self.bin_dir)

    def get_system_type(self):
        system_type = "linux-" if self.version_strategy.release_cycle == "release" else "linux."
        return system_type

    def get_arch(self):
        arch = "x64" if self.version_strategy.release_cycle == "release" else "x86_64"
        return arch

    def get_file_ext(self):
        return "tar.xz"


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
    def __init__(self, blender_repo_dir: Path, http_client: httpx.Client, factory: StrategyFactory, github_client: Github):
        self.http_client = http_client
        self.factory = factory
        self.root_dir = Path.home() / ".buildbpy"
        self.blender_repo_dir = blender_repo_dir if blender_repo_dir is not None else self.root_dir / "blender"
        self.lib_dir = self.root_dir / "lib"
        self.bin_dir = self.root_dir / "blender-bin"
        self.download_dir = self.root_dir / "downloads"
        self.python_api_dir = self.root_dir / "python_api"
        self.os_type = platform.system()
        self.version_strategy: VersionCycleStrategy = None
        self.os_strategy: OSStrategy = None
        self.checkout_strategy: CheckoutStrategy = None
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.github_client = github_client
        self.blender_repo = github_client.get_repo("blender/blender")
        self.build_dir = None

    def setup_strategies(self, os_type, major_version, minor_version, release_cycle, commit_hash, root_dir, blender_repo_dir):
        self.version_strategy = self.factory.create_version_strategy(major_version, minor_version, release_cycle, commit_hash)
        self.os_strategy = self.factory.create_os_strategy(os_type, self.version_strategy, root_dir, blender_repo_dir, self.http_client)

    def set_version(self, commit_hash: str, blender_source_dir: Path = None):
        version = make_utils.parse_blender_version(blender_source_dir)
        self.major_version = f"{version.version // 100}.{version.version % 100}"
        self.minor_version = f"{version.version // 100}.{version.version % 100}.{version.patch}"
        self.release_cycle = version.cycle

    def get_valid_commits(self, commit_hash: str):
        commit = self.blender_repo.get_commit(commit_hash)
        return commit.sha if commit_hash in commit.sha else None

    def get_valid_branch(self, branch: str):
        branches = self.blender_repo.get_branches()
        for b in branches:
            if branch == b.name:
                print(f"Found branch: {b}")
                return b.commit.sha
        return None

    def generate_stubs(self, commit_hash):
        downloaded_file = self.os_strategy.download_file()
        self.os_strategy.extract(downloaded_file)
        blender_binary = self.os_strategy.get_blender_binary()

        subprocess.run([blender_binary, "--background", "--factory-startup", "-noaudio", "--python", self.blender_repo_dir / "doc/python_api/sphinx_doc_gen.py", "--", f"--output={self.python_api_dir}"])
        subprocess.run(["python", "-m", "bpystubgen", self.python_api_dir / "sphinx-in", self.build_dir / "bin"])

    def get_valid_tag(self, tag: str = None):
        tags = self.blender_repo.get_tags()
        selected_tag = next((t.name for t in tags if t.name == tag), None) if tag else next((t.name for t in tags), None) if tags else None
        return selected_tag

    
    def build_and_manage_wheel(self, bin_path: Path, install: bool, publish: bool, publish_repo: str, selected_tag: str):
        # Remove existing wheel files
        for file in bin_path.glob("*.whl"):
            file.unlink()

        print("Making the bpy wheel")
        # Build the wheel
        # subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])
        
        make_script = self.blender_repo_dir / "build_files/utils/make_bpy_wheel.py"
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
            

        # Get Blender version and setup build
        self.set_version(commit_hash, blender_repo_dir)
        self.setup_strategies(self.os_type, self.major_version, self.minor_version, self.release_cycle, commit_hash, self.root_dir, blender_repo_dir)
        self.build_dir = self.os_strategy.build_dir.parent
        
        # Clear cache and library if requested
        if clear_cache and self.build_dir.exists():
            print(f"Clearing build directory {self.build_dir}")
            shutil.rmtree(self.build_dir, onerror=del_readonly)
        if clear_lib and self.lib_dir.exists():
            print(f"Clearing lib directory {self.lib_dir}")
            shutil.rmtree(self.lib_dir, onerror=del_readonly)
        
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
    
    def publish_github(self, tag: str, wheel_dir: Path, repo_name: str):
        # Use GitHub client to access the repository
        repo = self.github_client.get_repo(repo_name)
        release = next((r for r in repo.get_releases() if r.tag_name == tag), None)

        if not release:
            release = repo.create_git_release(tag=tag, name=f"Release {tag}", message=f"Release for Blender {tag}", draft=False, prerelease=False)

        # Upload wheel files to the release
        for wheel_file in wheel_dir.glob("*.whl"):
            with open(wheel_file, 'rb') as file:
                release.upload_asset(path=wheel_file, label=wheel_file.name, content_type='application/octet-stream')


app = typer.Typer()
http_client = httpx.Client()
strategy_factory = ConcreteStrategyFactory()
github_token = os.getenv("GITHUB_TOKEN")
github_client = Github(github_token)
        

@app.command()
def main(tag: str = typer.Option(None), commit: str = typer.Option(None), branch: str = typer.Option(None), clear_lib: bool = typer.Option(False), clear_cache: bool = typer.Option(False), publish: bool = typer.Option(False), install: bool = typer.Option(False), publish_repo: str = typer.Option("michaelgold/buildbpy"), blender_source_dir: str = typer.Option(None)):
    builder = BlenderBuilder(blender_source_dir, http_client, strategy_factory, github_client)
    return builder.main(tag, commit, branch, clear_lib, clear_cache, publish, install, publish_repo)

if __name__ == "__main__":
    app()

  