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
import requests

dotenv.load_dotenv()


from abc import ABC, abstractmethod


def del_readonly(action, name, exc):
    os.chmod(name, stat.S_IWRITE)
    os.remove(name)


def fetch_latest_build_info(http_client: httpx.Client, preferred_version=None):
    url = "https://builder.blender.org/download/daily/?format=json&v=1"
    try:
        response = http_client.get(url)
        response.raise_for_status()
        builds = response.json()

        arch = platform.machine().lower()
        system = platform.system().lower()

        if system == "windows":
            file_extension = "zip"
        elif system == "darwin":
            file_extension = "dmg"
        elif system == "linux":
            file_extension = "xz"

        # print(f"builds \n{builds}")

        print(f"filtering for arch = {arch} and system = {system}")

        # Filter builds based on platform and architecture
        filtered_builds = [
            build
            for build in builds
            if build["platform"] == system
            and build["architecture"] == arch
            and build["file_extension"] == file_extension
        ]

        # Sort builds by version, descending
        sorted_builds = sorted(
            filtered_builds, key=lambda x: x["version"], reverse=True
        )

        # Select the build for the preferred version or the latest one
        if preferred_version:
            for build in sorted_builds:
                if build["version"].startswith(preferred_version):
                    print(f"found version build: \n{build}")
                    return build

        print(f"found build: \n{sorted_builds[0]}")

        return sorted_builds[0] if sorted_builds else None

    except httpx.HTTPError as e:
        # Handle HTTP errors
        raise BlenderDownloadError("Failed to fetch Blender build information") from e


class BlenderDownloadError(Exception):
    """Exception raised for errors in the download process.

    Attributes:
        message -- explanation of the error
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


# Abstract Factory for creating strategies
class StrategyFactory(ABC):
    @abstractmethod
    def create_os_strategy(
        self, os_type, version_strategy, root_dir, blender_repo_dir, http_client
    ):
        """
        Create and return an OS-specific strategy.

        :param os_type: Type of the operating system.
        :param version_strategy: The version cycle strategy to be used.
        :param http_client: The HTTP client for downloading tasks.
        :return: An instance of a subclass of OSStrategy.
        """
        pass

    @abstractmethod
    def create_version_strategy(
        self, major_version, minor_version, release_cycle, commit_hash
    ):
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
    def create_os_strategy(
        self, os_type, version_strategy, root_dir, blender_repo_dir, http_client
    ):
        """
        Create and return an OS-specific strategy based on the provided OS type.

        :param os_type: Type of the operating system.
        :param version_strategy: The version cycle strategy to be used.
        :param http_client: The HTTP client for downloading tasks.
        :return: An instance of a subclass of OSStrategy specific to the given OS type.
        """
        if os_type == "Windows":
            return WindowsOSStrategy(
                version_strategy, root_dir, blender_repo_dir, http_client
            )
        elif os_type == "Linux":
            return LinuxOSStrategy(
                version_strategy, root_dir, blender_repo_dir, http_client
            )
        elif os_type == "Darwin":
            return MacOSStrategy(
                version_strategy, root_dir, blender_repo_dir, http_client
            )
        else:
            raise ValueError(f"Unsupported OS type: {os_type}")

    def create_version_strategy(
        self, major_version, minor_version, release_cycle, commit_hash
    ):
        """
        Create and return a version cycle strategy based on the provided version details.

        :param major_version: Major version of Blender.
        :param minor_version: Minor version of Blender.
        :param release_cycle: Release cycle (e.g., alpha, beta, release).
        :return: An instance of a subclass of VersionCycleStrategy specific to the given version details.
        """
        if release_cycle == "release":
            return ReleaseVersionCycleStrategy(
                major_version, minor_version, release_cycle, commit_hash
            )
        elif release_cycle == "rc":
            return CandidateVersionCycleStrategy(
                major_version, minor_version, release_cycle, commit_hash
            )
        elif release_cycle == "alpha":
            return AlphaBetaVersionCycleStrategy(
                major_version, minor_version, release_cycle, commit_hash
            )
        elif release_cycle == "beta":
            return AlphaBetaVersionCycleStrategy(
                major_version, minor_version, release_cycle, commit_hash
            )
        else:
            raise ValueError(f"Unsupported release cycle: {release_cycle}")


# Strategy Interface for Download
class VersionCycleStrategy(ABC):
    def __init__(
        self,
        major_version: str,
        minor_version: str,
        release_cycle: str,
        commit_hash: str,
    ):
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
        return (
            f"-candidate+{self.major_version.replace('.', '')}.{self.commit_hash_short}"
        )

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
    def __init__(
        self,
        version_strategy: VersionCycleStrategy,
        root_dir: Path,
        blender_repo_dir: Path,
        http_client: httpx.Client,
        preferred_version: str = None,
    ):
        self.blender_repo_dir = blender_repo_dir
        self.build_dir: Path = None
        self.lib_path: Path = None
        self.root_dir = root_dir
        self.bin_dir = self.root_dir / "blender-bin"
        self.download_dir = self.root_dir / "downloads"
        self.lib_dir = self.root_dir / "lib"
        self.version_strategy = version_strategy
        self.http_client = http_client
        self.download_url = None
        if self.version_strategy.release_cycle == "release":
            self.download_filename = f"blender-{self.version_strategy.minor_version}{self.version_strategy.get_download_url_suffix()}-{self.get_system_type()}{self.get_arch()}{self.version_strategy.get_file_suffix()}.{self.get_file_ext()}"
            self.download_url = f"{self.version_strategy.get_download_url_root()}/{self.download_filename}"
        else:
            build_info = fetch_latest_build_info(http_client, preferred_version)
            self.download_url = build_info["url"]
            self.download_filename = build_info["file_name"]

    def setup_build_environment(self):
        # Checkout libraries if not present
        if not self.lib_dir.exists():
            self.lib_dir.mkdir(parents=True, exist_ok=True)
            self.run_svn_checkout()
        else:
            print(f"Libraries already installed in {self.lib_dir}")

    def run_svn_checkout(self):
        print(f"Installing libraries to: {self.lib_dir}")
        subprocess.run(["svn", "checkout", self.lib_path], cwd=self.lib_dir)

    def run_command(self, command: str, cwd: Path):
        """
        Run a shell command with default behavior.
        :param command: The command to run.
        :param cwd: The working directory for the command.
        """
        subprocess.run(command, cwd=cwd, shell=True)

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

    @abstractmethod
    def set_cmake_directives(self):
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

    def download_file(self) -> Path:
        url = self.download_url
        download_dir = self.download_dir
        download_dir.mkdir(parents=True, exist_ok=True)

        print(f"Downloading Blender from {url}")
        response = self.http_client.get(url)
        if response.status_code == 200:
            download_path = download_dir / self.download_filename
            with open(download_path, "wb") as file:
                file.write(response.content)
        else:
            raise Exception(f"Failed to download Blender from {url}")

        return download_path


class WindowsOSStrategy(OSStrategy):
    def __init__(
        self,
        version_strategy: VersionCycleStrategy,
        root_dir: Path,
        blender_repo_dir: Path,
        http_client: httpx.Client,
    ):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}win64_vc15"
        self.build_dir = self.root_dir / "build_windows_Bpy_x64_vc16_Release"
        self.make_command = blender_repo_dir / "make.bat"
        self.make_command = "make.bat"
        self.build_wheel_dir = self.build_dir / "bin/Release"

    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender.exe"

    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with zipfile.ZipFile(downloaded_file, "r") as zip_ref:
            zip_ref.extractall(self.bin_dir)

    def get_system_type(self):
        system_type = (
            "windows-"
            if self.version_strategy.release_cycle == "release"
            else "windows."
        )
        return system_type

    def get_arch(self):
        arch = "x64" if self.version_strategy.release_cycle == "release" else "amd64"
        return arch

    def get_file_ext(self):
        return "zip"

    def set_cmake_directives(self):
        cmake_file_path = (
            self.blender_repo_dir / "build_files/cmake/config/bpy_module.cmake"
        )
        print(f"Setting CMake directives in {cmake_file_path}")
        directives = [
            'set(WITH_CYCLES_CUDA_BINARIES ON CACHE BOOL "" FORCE)',
            'set(WITH_AUDASPACE ON CACHE BOOL "" FORCE)'
        ]
        
        with open(cmake_file_path, 'a') as file:
            for directive in directives:
                file.write(f"{directive}\n")

    def run_command(self, command: str, cwd: Path):
        """
        Run a shell command on Windows with special handling for piped input.
        :param command: The command to run.
        :param cwd: The working directory for the command.
        """
        if "update" in command:
                subprocess.run(command, cwd=cwd, shell=True, input="y\n", text=True)
        else:
            subprocess.run(command, cwd=cwd, shell=True)


class MacOSStrategy(OSStrategy):
    def __init__(
        self,
        version_strategy: VersionCycleStrategy,
        root_dir: Path,
        blender_repo_dir: Path,
        http_client: httpx.Client,
    ):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}macos"
        self.build_dir = self.root_dir / "build_darwin_bpy"
        self.build_wheel_dir = self.build_dir / "bin"
        self.make_command = "make"

    def get_blender_binary(self):
        return self.bin_dir / f"Blender.app/Contents/MacOS/Blender"

    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with dmgextractor.DMGExtractor(downloaded_file) as extractor:
            extractor.extractall(self.bin_dir)

    def get_system_type(self):
        system_type = (
            "macos-" if self.version_strategy.release_cycle == "release" else "darwin."
        )
        return system_type

    def get_arch(self):
        arch = "arm64" if platform.machine() == "arm64" else "x64"
        return arch

    def get_file_ext(self):
        return "dmg"

    def set_cmake_directives(self):
        cmake_file_path = (
            self.blender_repo_dir / "build_files/cmake/config/bpy_module.cmake"
        )
        print(f"Setting CMake directives in {cmake_file_path}")
        directives = [
            'set(WITH_AUDASPACE ON CACHE BOOL "" FORCE)',
            'set(WITH_CODEC_FFMPEG ON CACHE BOOL "" FORCE)',
            'set(WITH_CODEC_SNDFILE ON CACHE BOOL "" FORCE)',
            'set(WITH_COREAUDIO ON CACHE BOOL "" FORCE)',
            'set(WITH_JACK ON CACHE BOOL "" FORCE)',
            'set(WITH_OPENAL ON CACHE BOOL "" FORCE)',
            'set(WITH_PULSEAUDIO ON CACHE BOOL "" FORCE)',
            'set(WITH_SDL ON CACHE BOOL "" FORCE)',
            'set(WITH_WASAPI ON CACHE BOOL "" FORCE)'
        ]
        
        with open(cmake_file_path, 'a') as file:
            for directive in directives:
                file.write(f"{directive}\n")

    def run_svn_checkout(self):
        """Override the svn checkout command for MacOS"""
        pass


class LinuxOSStrategy(OSStrategy):
    def __init__(
        self,
        version_strategy: VersionCycleStrategy,
        root_dir: Path,
        blender_repo_dir: Path,
        http_client: httpx.Client,
    ):
        super().__init__(version_strategy, root_dir, blender_repo_dir, http_client)
        self.lib_path = f"{self.version_strategy.get_svn_root()}linux_x86_64_glibc_228"
        self.build_dir = self.root_dir / "build_linux_bpy"
        self.build_wheel_dir = self.build_dir / "bin"
        self.make_command = "make"

    def setup_build_environment(self):
        """Override to use make_update.py instead of SVN for Linux"""
        if not self.lib_dir.exists():
            self.lib_dir.mkdir(parents=True, exist_ok=True)
            print(f"Installing libraries using make_update.py")
            self.run_command(
                f"python ./build_files/utils/make_update.py --use-linux-libraries",
                self.blender_repo_dir
            )
        else:
            print(f"Libraries already installed in {self.lib_dir}")

    def get_blender_binary(self):
        blender_dir = list(self.bin_dir.glob("blender*"))[0]
        return blender_dir / f"blender"

    def extract(self, downloaded_file: Path):
        self._prepare_bin_dir()
        with tarfile.open(downloaded_file, "r:xz") as tar:
            tar.extractall(self.bin_dir)

    def run_svn_checkout(self):
        """Override the svn checkout command for Linux"""
        print(f"Running svn checkout for Linux")
        self.run_command(f"python ./build_files/utils/make_update.py --use-linux-libraries", self.blender_repo_dir)

    def get_system_type(self):
        system_type = (
            "linux-" if self.version_strategy.release_cycle == "release" else "linux."
        )
        return system_type

    def get_arch(self):
        arch = "x64" if self.version_strategy.release_cycle == "release" else "x86_64"
        return arch

    def get_file_ext(self):
        return "tar.xz"

    def set_cmake_directives(self):
        cmake_file_path = (
            self.blender_repo_dir / "build_files/cmake/config/bpy_module.cmake"
        )
        print(f"Setting CMake directives in {cmake_file_path}")
        directives = [
            'set(WITH_CYCLES_CUDA_BINARIES ON CACHE BOOL "" FORCE)',
            'set(WITH_AUDASPACE ON CACHE BOOL "" FORCE)'
        ]
        
        with open(cmake_file_path, 'a') as file:
            for directive in directives:
                file.write(f"{directive}\n")


class CheckoutStrategy(ABC):
    def __init__(self, blender_repo_dir: Path, http_client: httpx.Client = None):
        self.blender_repo_dir = blender_repo_dir
        self.http_client = http_client
        if not blender_repo_dir.exists():
            root_dir = blender_repo_dir.parent
            # make the root_dir if it doesn't exist
            root_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--recursive",
                    "https://github.com/blender/blender.git",
                ],
                cwd=root_dir,
            )
        subprocess.run(["git", "fetch", "--all"], cwd=blender_repo_dir)

    @abstractmethod
    def checkout(self, id: str):
        pass

    @abstractmethod
    def set_version(self, commit_hash: str = None, tag: str = None):
        pass


        print(f"Setting Version: {self.major_version}.{self.minor_version}.{self.release_cycle}")


class TagCheckoutStrategy(CheckoutStrategy):
    def checkout(self, id):
        # reset the repo to the tag
        subprocess.run(["git", "reset", "--hard", f"tags/{id}"], cwd=self.blender_repo_dir)

    def set_version(self, commit_hash: str = None, tag: str = None):
        # parse a tag in the format of "v4.3.2" in to major_version 4.3 and minor_version 4.3.2 first remove the v and then split by .
        tag_version = tag.replace("v", "")
        version_components = tag_version.split(".")
        self.major_version = f"{version_components[0]}.{version_components[1]}"
        self.minor_version = tag_version
        self.release_cycle = "release"


class CommitCheckoutStrategy(CheckoutStrategy):
    def checkout(self, id):
        subprocess.run(["git", "checkout", id], cwd=self.blender_repo_dir)

    def set_version(self, commit_hash: str = None, tag: str = None):
        blender_source_dir = self.blender_repo_dir
        version = make_utils.parse_blender_version(blender_source_dir)
        self.major_version = f"{version.version // 100}.{version.version % 100}"
        self.minor_version = (
            f"{version.version // 100}.{version.version % 100}.{version.patch}"
        )
        self.release_cycle = version.cycle


class DailyCheckoutStrategy(CheckoutStrategy):
    def __init__(
        self,
        blender_repo_dir: Path,
        http_client: httpx.Client = None,
        preferred_version: str = None,
    ):
        super().__init__(blender_repo_dir, http_client)
        self.build_info = fetch_latest_build_info(self.http_client, preferred_version)

    def set_version(self, commit_hash: str = None, tag: str = None):
        """Override to use fetch_latest_build_info"""

        version_components = self.build_info["version"].split(".")
        if len(version_components) >= 2:
            self.major_version = f"{version_components[0]}.{version_components[1]}"
        else:
            raise BlenderDownloadError("Invalid version format in build info")

        self.minor_version = self.build_info["version"]
        self.release_cycle = self.build_info["release_cycle"]

    def checkout(self, id=None):
        """Here we override the id and use the hash from self.build_info"""
        commit = self.build_info["hash"]

        subprocess.run(["git", "checkout", commit], cwd=self.blender_repo_dir)


class BlenderBuilder:
    """Main class for building the Blender Python Module"""

    def __init__(
        self,
        blender_repo_dir: Path,
        http_client: httpx.Client,
        factory: StrategyFactory,
        github_client: Github,
    ):
        self.http_client = http_client
        self.factory = factory
        self.root_dir = Path.home() / ".buildbpy"
        self.blender_repo_dir = (
            blender_repo_dir
            if blender_repo_dir is not None
            else self.root_dir / "blender"
        )
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

    def setup_strategies(
        self,
        os_type,
        major_version,
        minor_version,
        release_cycle,
        commit_hash,
        root_dir,
        blender_repo_dir,
    ):
        """
        Set up the version and OS strategies for the build process.

        Args:
            os_type (str): The type of operating system.
            major_version (int): The major version of Blender.
            minor_version (int): The minor version of Blender.
            release_cycle (str): The release cycle of Blender.
            commit_hash (str): The commit hash of the Blender repository.
            root_dir (str): The root directory of the build process.
            blender_repo_dir (str): The directory of the Blender repository.

        Returns:
            None
        """
        self.version_strategy = self.factory.create_version_strategy(
            major_version, minor_version, release_cycle, commit_hash
        )
        self.os_strategy = self.factory.create_os_strategy(
            os_type, self.version_strategy, root_dir, blender_repo_dir, self.http_client
        )

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
        """
        Generate stubs for the Blender Python API.

        Args:
            commit_hash (str): The commit hash of the Blender version to generate stubs for.

        Returns:
            None
        """
        downloaded_file = self.os_strategy.download_file()
        self.os_strategy.extract(downloaded_file)
        blender_binary = self.os_strategy.get_blender_binary()
        output_dir = self.os_strategy.build_wheel_dir

        subprocess.run(
            [
                blender_binary,
                "--background",
                "--factory-startup",
                "-noaudio",
                "--python",
                self.blender_repo_dir / "doc/python_api/sphinx_doc_gen.py",
                "--",
                f"--output={self.python_api_dir}",
            ]
        )
        subprocess.run(
            [
                "python",
                "-m",
                "bpystubgen",
                self.python_api_dir / "sphinx-in",
                output_dir,
            ]
        )

    def get_valid_tag(self, tag: str = None):
        """
        Retrieves a valid tag from the Blender repository.

        Args:
            tag (str, optional): The specific tag to retrieve. If not provided, the first available tag will be returned.

        Returns:
            str: The selected tag, or None if no valid tag is found.
        """
        tags = self.blender_repo.get_tags()
        selected_tag = (
            next((t.name for t in tags if t.name == tag), None)
            if tag
            else next((t.name for t in tags), None) if tags else None
        )
        return selected_tag

    def build_and_manage_wheel(
        self,
        bin_path: Path,
        install: bool,
        publish: bool,
        publish_repo: str,
        selected_tag: str,
    ):
        """
        Build and manage the bpy wheel.

        Args:
            bin_path (Path): The path to the directory where the wheel will be built.
            install (bool): Flag indicating whether to install the wheel after building.
            publish (bool): Flag indicating whether to publish the wheel to GitHub Releases.
            publish_repo (str): The repository to publish the wheel to.
            selected_tag (str): The tag to associate with the published wheel.
        """
        # Remove existing wheel files
        for file in bin_path.glob("*.whl"):
            file.unlink()

        print("Making the bpy wheel")
        # Build the wheel
        # subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])

        make_script = self.blender_repo_dir / "build_files/utils/make_bpy_wheel.py"
        print(f"Running python {make_script} {bin_path}")
        subprocess.run(["python", make_script, bin_path])

        if install:
            wheel_file = next(bin_path.glob("*.whl"), None)
            if wheel_file:
                print("Installing the wheel")
                subprocess.run(
                    ["pip", "install", "--force-reinstall", "--no-deps", wheel_file]
                )

        if publish:
            print("Publishing to GitHub Releases")
            self.publish_github(selected_tag, bin_path, publish_repo)

    def main(
        self,
        tag: str,
        commit: str,
        clear_lib: bool,
        clear_cache: bool,
        publish: bool,
        install: bool,
        publish_repo: str,
        daily_version: str,
        daily: bool,
    ):
        selected_tag = None
        commit_hash = None
        is_valid_commit = False

        if tag:
            selected_tag = self.get_valid_tag(tag)

        # if branch:
        #     is_valid_branch = self.get_valid_branch(branch)
        #     commit_hash = is_valid_branch if is_valid_branch else None

        if commit:
            is_valid_commit = self.get_valid_commits(commit)
            commit_hash = is_valid_commit if is_valid_commit else None

        if (
            not selected_tag
            and not is_valid_commit
            and not daily
            and daily_version == ""
        ):
            print("No valid tag, commit or daily version found")
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

        elif daily_version or daily:
            self.checkout_strategy = DailyCheckoutStrategy(
                blender_repo_dir, http_client, daily_version
            )
            print(f"Checking out daily version {daily_version}")
            self.checkout_strategy.checkout()

        # Get Blender version and setup build
        self.checkout_strategy.set_version(commit_hash, tag)

        # print the version
        
        self.major_version = self.checkout_strategy.major_version
        self.minor_version = self.checkout_strategy.minor_version
        self.release_cycle = self.checkout_strategy.release_cycle
        print(f"Getting Version: {self.major_version}.{self.minor_version}.{self.release_cycle}")

        self.setup_strategies(
            self.os_type,
            self.major_version,
            self.minor_version,
            self.release_cycle,
            commit_hash,
            self.root_dir,
            blender_repo_dir,
        )
        self.build_dir = self.os_strategy.build_dir

        # Clear cache and library if requested
        if clear_cache and self.build_dir.exists():
            print(f"Clearing build directory {self.build_dir}")
            shutil.rmtree(self.build_dir)
        if clear_lib and self.lib_dir.exists():
            print(f"Clearing lib directory {self.lib_dir}")
            shutil.rmtree(self.lib_dir)

        make_command = self.os_strategy.make_command
        self.os_strategy.setup_build_environment()

        # Generate stubs and build Blender
        self.generate_stubs(commit_hash)
        self.os_strategy.set_cmake_directives()
        os.chdir(blender_repo_dir)
        # subprocess.run(f"{make_command} update", cwd=blender_repo_dir, shell=True)
        # subprocess.run(f"{make_command} bpy", cwd=blender_repo_dir, shell=True)
                # Use the OS strategy to run the commands
        self.os_strategy.run_command(f"{make_command} update", blender_repo_dir)
        self.os_strategy.run_command(f"{make_command} bpy", blender_repo_dir)


        # Build and install or publish the wheel
        wheel_path = self.os_strategy.build_wheel_dir
        self.build_and_manage_wheel(
            wheel_path, install, publish, publish_repo, selected_tag
        )

        # # Update the data file if needed
        # if tag and data_file_path:
        #     tag_data["latest_tag"] = selected_tag
        #     with open(data_file_path, 'w') as file:
        #         json.dump(tag_data, file)

        return True

    def publish_github(self, tag: str, wheel_dir: Path, repo_name: str):
        
        if not tag:
            tag = f"v{self.major_version}.{self.version_strategy.release_cycle}"
        repo = self.github_client.get_repo(repo_name)
        release = next((r for r in repo.get_releases() if r.tag_name == tag), None)

        if not release:
            release = repo.create_git_release(
                tag=tag,
                name=f"bpy-{tag}",
                message=f"Blender Python Module for Blender {tag}",
                draft=False,
                prerelease=False,
            )

        # Upload wheel files to the release
        for wheel_file in wheel_dir.glob("*.whl"):
            for asset in release.get_assets():
                if asset.name == wheel_file.name:
                    print(f"Deleting existing asset {asset.name}")
                    asset.delete_asset()
            
            print(f"Uploading asset {wheel_file}")
            
            # Set up the session with retries
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(
                max_retries=requests.urllib3.Retry(
                    total=5,
                    backoff_factor=1,
                    status_forcelist=[500, 502, 503, 504]
                )
            )
            session.mount('https://', adapter)
            
            # Verify token is being set correctly
            headers = {
                'Authorization': f'Bearer {github_token}',  # Changed from 'token' to 'Bearer'
                'Content-Type': 'application/octet-stream',
                'Accept': 'application/vnd.github.v3+json'
            }
            
            print("Authorization header set:", bool(headers['Authorization'] != 'Bearer None'))
            
            # Get upload URL
            upload_url = release.upload_url.split('{')[0]
            params = {'name': wheel_file.name}
            
            # Upload with progress
            try:
                file_size = os.path.getsize(wheel_file)
                with open(wheel_file, 'rb') as f:
                    print(f"Starting upload of {file_size/1024/1024:.1f}MB file")
                    
                    response = session.post(
                        upload_url,
                        headers=headers,
                        params=params,
                        data=f,
                        stream=True
                    )
                    
                    # Check if the upload was successful
                    if response.status_code == 201:
                        print(f"Successfully uploaded {wheel_file.name}")
                    else:
                        print(f"Upload failed with status code {response.status_code}")
                        print(f"Response: {response.text}")
                        response.raise_for_status()
                    
            except Exception as e:
                print(f"Error uploading file: {e}")
                raise
            finally:
                session.close()


app = typer.Typer()
http_client = httpx.Client()
strategy_factory = ConcreteStrategyFactory()
github_token = os.getenv("GITHUB_TOKEN")
github_client = Github(github_token)


@app.command()
def main(
    tag: str = typer.Option(None, help="Blender repo tag to build"),
    commit: str = typer.Option(None, help="Blender repo commit to build"),
    daily_version: str = typer.Option(None),
    latest_daily: bool = typer.Option(False),
    clear_lib: bool = typer.Option(False),
    clear_cache: bool = typer.Option(False),
    publish: bool = typer.Option(False),
    install: bool = typer.Option(False),
    publish_repo: str = typer.Option("michaelgold/buildbpy"),
    blender_source_dir: str = typer.Option(None),
):
    builder = BlenderBuilder(
        blender_source_dir, http_client, strategy_factory, github_client
    )
    return builder.main(
        tag,
        commit,
        clear_lib,
        clear_cache,
        publish,
        install,
        publish_repo,
        daily_version,
        latest_daily,
    )


if __name__ == "__main__":
    app()
