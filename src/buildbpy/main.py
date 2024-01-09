import typer
from pathlib import Path
import httpx
import json
import subprocess
import dotenv
import os
import glob
import ssl
import platform
import tarfile
import zipfile
import shutil
from .utils import dmgextractor
from .utils import make_utils
from github import Github

app = typer.Typer()
# Load the environment variables
dotenv.load_dotenv()
script_dir = Path(__file__).parent



def get_valid_commits(commit_hash: str):
    """ """
    g = Github()
    repo = g.get_repo("blender/blender")


    commit = repo.get_commit(commit_hash)
    if commit_hash in commit.sha:
        return commit.sha
    else:
        return None

def get_valid_branch(branch: str):
    """ """
    g = Github()
    repo = g.get_repo("blender/blender")
    branches = repo.get_branches()
    for b in branches:
        if branch == b.name:
            print(f"Found branch: {b}")
            return b.commit.sha
    else:
        return None

def get_version(blender_source_dir: Path = None):
    """ Gets the major and minor version from the tag. """
    version_cycle = "release"
    # if tag:
    #     tag = tag.lstrip('v');
    #     parts = tag.split('.')
    #     major_version = '.'.join(parts[:2])
    #     minor_version = '.'.join(parts[:3])
    # else:
    version = make_utils.parse_blender_version(blender_source_dir)
    major_version = f"{version.version // 100}.{version.version % 100}"
    minor_version = f"{version.version // 100}.{version.version % 100}.{version.patch}"
    version_cycle = version.cycle
    return major_version, minor_version, version_cycle

def download_blender(major_version: str, minor_version: str, release_cycle: str,  commit_hash: str, blender_source_dir: Path):
    """ Downloads Blender Binary based on Tag."""
    commit_hash_short = ""
    if commit_hash:
        commit_hash_short = commit_hash[:12]
    print(f"commit_hash_short: {commit_hash_short}")

    url_root = f"https://mirrors.ocf.berkeley.edu/blender/release/Blender{major_version}" if release_cycle == "release" else "https://builder.blender.org/download/daily"
    release_abbreviation = ""
    release_suffix = "" 
    file_suffix = "" if release_cycle == "release" else f"-release"
    if release_cycle == "alpha" or release_cycle == "beta":
        release_suffix = f"-{release_cycle}+main.{commit_hash_short}"
    elif release_cycle == "rc":
        major_version_short = major_version.replace(".", "")
        release_suffix = f"-candidatie+{major_version_short}.{commit_hash_short}"


    

    # Determine the OS type (Linux, Windows, MacOS)
    os_type = platform.system()
    arch = platform.machine()
    filename = ""

    # Construct the download URL based on the OS type and Blender version
    if os_type == "Linux":
        system_type = "linux-" if release_cycle == "release" else "linux."
        arch = "x64" if release_cycle == "release" else "x86_64"
        file_ext = "tar.xz"
    elif os_type == "Windows":
        system_type = "windows-" if release_cycle == "release" else "windows."
        arch = "x64" if release_cycle == "release" else "amd64"
        file_ext = "zip"
    elif os_type == "Darwin":  # MacOS
        arch = "arm64" if arch == "arm64" else "x64"
        system_type = "macos-" if release_cycle == "release" else "darwin."
        file_ext = "dmg"
    else:
        raise Exception("Unsupported operating system")
    
    filename = f"blender-{minor_version}{release_suffix}-{system_type}{arch}{file_suffix}.{file_ext}"
    url = f"{url_root}/{filename}"
    
    download_dir = script_dir / "../downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading Blender from {url}")
    # Download the file
    with httpx.Client() as client:
        response = client.get(url)
        if response.status_code == 200:
            with open(download_dir / filename, 'wb') as file:
                file.write(response.content)
        else:
            raise Exception(f"Failed to download Blender. Status code: {response.status_code}")

    print(f"Downloaded Blender to {download_dir / filename}")

    bin_dir = script_dir / "../blender-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # empty the bin directory
    for file in bin_dir.glob("*"):
        if file.is_file():
            file.unlink()
        else:
            shutil.rmtree(file)
    # Extract the file
    if file_ext == "tar.xz":
        with tarfile.open(download_dir / filename, "r:xz") as tar:
            tar.extractall(bin_dir)
    elif file_ext == "zip":
        with zipfile.ZipFile(download_dir / filename, 'r') as zip_ref:
            zip_ref.extractall(bin_dir)
    elif file_ext == "dmg":
        with dmgextractor.DMGExtractor(download_dir / filename) as extractor:
            extractor.extractall(bin_dir)
    print(f"Extracted Blender to {bin_dir}")



def publish_github(tag: str, wheel_dir: Path, repo: str = "michaelgold/buildbpy"):
    """ Publishes the wheel file to GitHub Releases. """
    github_token = os.getenv("GITHUB_TOKEN")
    if not github_token:
        raise ValueError("GitHub token not found in environment variables.")
    headers = {
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github.v3+json"
    }
    ssl_context = ssl.create_default_context()


    client = httpx.Client(headers=headers, verify=ssl_context)
    whl_files = list(wheel_dir.glob("*.whl"))
    if not whl_files:
        raise FileNotFoundError("No .whl file found in the specified directory.")
    whl_file_path = whl_files[0]
           
    print(f"Wheel file found: {whl_file_path}")
    selected_tag = tag  
    # https://docs.github.com/en/rest/reference/repos#create-a-release

    # check if the release already exists
    release_url = f"https://api.github.com/repos/{repo}/releases/tags/{selected_tag}"
    # response = requests.get(release_url, headers=headers)

    try:
        # response = requests.get(release_url, headers=headers)
        response = client.get(release_url)
        print(f"GET request to {release_url} completed with status code: {response.status_code}")
        print(f"Response JSON: {response.json()}")
    except httpx.RequestError as e:
        raise Exception(f"Error during GET request to {release_url}: {e}")

    print(f"response code: {response.status_code}")
    print(f"response json: {response.json()}")

    if response.status_code == 200 or response.status_code == 201:
        print("Release already exists. Skipping creation.")
    
        response_json = response.json()
        release_id = response_json.get("id", None)
        print(f"Release ID: {release_id}")

        release_assets = response_json.get("assets", [])
        existing_asset = None
        for asset in release_assets:
            if asset["name"] == f"{whl_file_path.stem}.whl":
                existing_asset = asset
                break
        
        if existing_asset:
            # Delete the existing asset
            print("Deleting existing asset.")
            asset_id = existing_asset["id"]
            delete_url = f"https://api.github.com/repos/{repo}/releases/assets/{asset_id}"
            response = client.delete(delete_url)
            print(f"Asset deleted response code: {response.status_code}")
        
    else:
        print("Creating release.")
        # Step 1: Create the release

        release_name = f"bpy-{selected_tag}"
        release_body = f"Blender Python API for Blender {selected_tag}"
        release_url = f"https://api.github.com/repos/{repo}/releases"
        release_data = {
            "tag_name": selected_tag,
            "target_commitish": "main",
            "name": release_name,
            "body": release_body,
            "draft": False,
            "prerelease": False
        }
        response = client.post(release_url, json=release_data)


        if response.status_code != 200 and response.status_code != 201:
            raise Exception(f"Failed to get release info: {response.text}")

        release_id = response.json()['id']

    # Step 2: Upload the .whl file
    upload_url = f"https://uploads.github.com/repos/{repo}/releases/{release_id}/assets?name={whl_file_path.stem}.whl"
    headers['Content-Type'] = 'application/octet-stream'

    print(f"Uploading file to {upload_url}...")

    # with open(whl_file_path, 'rb') as file:
    #     upload_response = requests.post(upload_url, headers=headers, data=file)
    print(f"Attempting to upload file to {upload_url}")
    try:
        with open(whl_file_path, 'rb') as file:
            upload_response = client.post(upload_url, content=file, headers=headers)
            print(f"POST request to {upload_url} completed with status code: {upload_response.status_code}")
            if upload_response.status_code not in [200, 201]:
                print(f"Failed to upload asset: {upload_response.text}")
            else:
                print("File uploaded successfully.")
    except httpx.RequestError as e:
        raise Exception(f"Error during POST request to {upload_url}: {e}")


    # if upload_response.status_code not in [200, 201]:
    #     raise Exception(f"Failed to upload asset: {upload_response.text}")

    # print("File uploaded successfully.")

def generate_stubs(blender_repo_dir: Path, major_version: str, minor_version: str, release_cycle, commit_hash, build_dir: Path):
    """ Generates stub files for the bpy module. """
    download_blender(major_version, minor_version, release_cycle, commit_hash, blender_repo_dir)
    # Determine the OS type (Linux, Windows, MacOS)
    os_type = platform.system()

    if os_type == "Linux":
        blender_bin_dir = script_dir / "../blender-bin/"
        print(f"contents of blender-bin: {list(blender_bin_dir.glob('*'))}")
        blender_dir = list(blender_bin_dir.glob("blender-*"))[0]
        blender_binary = blender_dir / "blender"
    elif os_type == "Windows":
        blender_bin_dir = script_dir / "../blender-bin/"
        print(f"contents of blender-bin: {list(blender_bin_dir.glob('*'))}")
        blender_dir = list(blender_bin_dir.glob("blender-*"))[0]
        print(f"contents of blender_dir: {list(blender_dir.glob('*'))}")
        blender_binary = blender_dir / "blender.exe"
    elif os_type == "Darwin":  # MacOS
        blender_binary = script_dir / "../blender-bin/Blender.app/Contents/MacOS/Blender"
    else:
        raise Exception("Unsupported operating system")
        
    python_api_dir =  script_dir / "../python_api"
    
    # build the python api docs
    subprocess.run([blender_binary, "--background", "--factory-startup", "-noaudio", "--python", blender_repo_dir / "doc/python_api/sphinx_doc_gen.py", "--", f"--output={python_api_dir}"])
    

    # build the python api stubs in the build directory (for the wheel)
    subprocess.run(["python", "-m", "bpystubgen", python_api_dir / "sphinx-in", build_dir / "bin"])

def get_valid_tag(tag: str = None):
    """ Validates tag is in the Blender repository. """
    client = httpx.Client()
    repo_url = "https://api.github.com/repos/blender/blender"
    data_file_path: Path = script_dir / "data.json"
    # Get the tags from the GitHub API
    response = client.get(f"{repo_url}/tags")
    tags = response.json()

    # Determine which tag to use
    if tag and any(t['name'] == tag for t in tags):
        selected_tag = tag
    elif not tag:
        selected_tag = tags[0]['name']
    else:
        print(f"Tag '{tag}' not found.")
        selected_tag = None

    # Load the current tag from the data file
    if data_file_path.exists():
        with open(data_file_path, 'r') as file:
            tag_data = json.load(file)
            current_tag = tag_data.get("latest_tag", "")
    else:
        current_tag = ""
        tag_data = {}
    
    if (selected_tag == current_tag) and (tag is None):
        # If the tag is the same as the current tag, and no specific tag was provided, do nothing
        print(f"Tag '{selected_tag}' has already been built. Specify a tag if you want to build it again.")
        selected_tag = None
    
    return selected_tag, tag_data, data_file_path

 
@app.command()
def main(tag: str = typer.Option(None, help="Specific tag to build"), commit: str = typer.Option(None, help="Specific commit to build"), branch: str = typer.Option(None, help="Specific branch to build"), clear_lib: bool = typer.Option(False, help = "Clear the library dependencies"), clear_cache: bool = typer.Option(False, help = "Clear the cmake build cache"), publish: bool = typer.Option(False, help="Upload the wheel to GitHub Releases"), install: bool = typer.Option(False, help="Install the wheel using pip"), publish_repo: str = typer.Option("michaelgold/buildbpy", help="GitHub repository to publish the wheel to"), blender_source_dir: str = typer.Option(None, help="Path to the Blender source directory")):
    """
    This script checks for new tags in the Blender repository on GitHub.
    If a new tag is found, or a specific tag is provided, it updates the local repository and a data file.
    """
    os.chdir(Path(__file__).parent)
    selected_tag = None
    commit_hash = None
    is_valid_branch = False
    is_valid_commit = False
    print (f"branch: {branch}")

    if tag:
        selected_tag, tag_data, data_file_path = get_valid_tag(tag)

    if branch:
        is_valid_branch = get_valid_branch(branch)
        print(f"is_valid_branch: {is_valid_branch}")
        commit_hash = is_valid_branch
        if not is_valid_branch:
            print(f"Branch '{branch}' not found.")

    if commit:
        is_valid_commit = get_valid_commits(commit)
        commit_hash = is_valid_commit
        if not is_valid_commit:
            print(f"Commit '{commit}' not found.")

    if not selected_tag and not is_valid_branch and not is_valid_commit:
        return False

    # If the tag is different from the current tag, or a specific tag was provided, update the local repository and build blender
    # print(f"Tag found: {selected_tag}. Updating and checking out the repo.")

    # Clone the repository and checkout the selected tag
    # 
    if blender_source_dir:
        blender_repo_dir = Path(blender_source_dir)
    else:
        blender_repo_dir = script_dir / "../blender"
    if not blender_repo_dir.exists():
        subprocess.run(["git", "clone", "--recursive", "https://github.com/blender/blender.git"], cwd=script_dir / "..")
    subprocess.run(["git", "fetch", "--all"], cwd=blender_repo_dir)
    if selected_tag:
        subprocess.run(["git", "checkout", f"tags/{selected_tag}"], cwd=blender_repo_dir)
    elif branch:
        subprocess.run(["git", "checkout", branch], cwd=blender_repo_dir)
    elif commit:
        subprocess.run(["git", "checkout", commit], cwd=blender_repo_dir)

    if clear_cache:
        if build_dir.exists():
            shutil.rmtree(build_dir)

    lib_dir = script_dir / "../lib"
    if clear_lib:
        if lib_dir.exists():
            shutil.rmtree(lib_dir)

    os_type = platform.system()
    major_version, minor_version, release_cycle = get_version( blender_repo_dir)
    make_command = blender_repo_dir / "make.bat" if os_type == "Windows" else "make"


    if os_type == "Linux":
        build_dir = script_dir / "../../build_linux_bpy"
        # checkout libraries
        if not lib_dir.exists():
            print(f"Installing libraries to: {lib_dir}")
            lib_dir.mkdir()
            svnpath = f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{major_version}-release/lib/linux_x86_64_glibc_228/"
            print(f"Checking out libraries from {svnpath}")
            subprocess.run(["svn", "checkout", svnpath], cwd=lib_dir)
    elif os_type == "Windows":
        build_dir = script_dir / "../../build_windows_Bpy_x64_vc17_Release/bin/"
        if not lib_dir.exists():
            print(f"Installing libraries to: {lib_dir}")
            lib_dir.mkdir()
            svnpath = f"https://svn.blender.org/svnroot/bf-blender/tags/blender-{major_version}-release/lib/win64_vc15"
            print(f"Checking out libraries from {svnpath}")
            subprocess.run(["svn", "checkout", svnpath], cwd=lib_dir)
    elif os_type == "Darwin":  # MacOS
        build_dir = script_dir / "../../build_darwin_bpy"
    else:
        raise Exception("Unsupported operating system")
    

  
    generate_stubs(blender_repo_dir, major_version, minor_version, release_cycle, commit_hash, build_dir)

    # Build blender
    print("Updating Blender Dependencies")
    subprocess.run([make_command, "update"], cwd=blender_repo_dir, )
    print("Building Blender")
    subprocess.run([make_command, "bpy"], cwd=blender_repo_dir)

    # tag_parts = selected_tag.split('.')
    # major_version = '.'.join(tag_parts[:2])
    # minor_version = '.'.join(tag_parts[:3])

    #./blender --background --factory-startup -noaudio --python ../blender-git/doc/python_api/sphinx_doc_gen.py -- --output=../python_api
    
  
    # Make the wheel

    # remove existing wheel files
    bin_path = build_dir / "bin"
    whl_files = list(bin_path.glob("*.whl"))
    for file in whl_files:
        file.unlink()
    
    print("Making the bpy wheel")
    # build the wheel
    subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])
    make_script = script_dir / "../blender/build_files/utils/make_bpy_wheel.py"

    # Copy the make_bpy_wheel.py script to the build directory
    shutil.copy2(script_dir / "make_bpy_wheel.py", make_script )
    subprocess.run(["python", make_script, build_dir / "bin/"])


    if install:
        print("Installing the wheel")
        wheel_file = list(bin_path.glob("*.whl"))[0]
        subprocess.run(["pip", "install", "--force-reinstall", "--no-deps",
         wheel_file])
    
    if publish:
        print("Publishing to GitHub Releases")
        publish_github(selected_tag, bin_path, publish_repo)
    
    
    # Update the data file
    # TODO reimplement data file updating
    # tag_data["latest_tag"] = selected_tag
    # with open(data_file_path, 'w') as file:
    #     json.dump(tag_data, file)
    
    return True



if __name__ == "__main__":
    app()
