import typer
from pathlib import Path
import requests
import json
import subprocess
import dotenv
import os
import glob

app = typer.Typer()
# Load the environment variables
dotenv.load_dotenv()
github_token = os.getenv("GITHUB_TOKEN")



# get script directory

@app.command()
def publish_github(tag: str, wheel_dir: Path):
    """ Publishes the wheel file to GitHub Releases. """
    whl_file_path = list(wheel_dir.glob("*.whl"))[0]
           
    print(f"Wheel file found: {whl_file_path}")
    selected_tag = tag  
    # https://docs.github.com/en/rest/reference/repos#create-a-release
    headers = {
    "Authorization": f"Bearer {github_token}",
    "Accept": "application/vnd.github.v3+json"
    }

    # check if the release already exists
    release_url = f"https://api.github.com/repos/michaelgold/bpy/releases/tags/{selected_tag}"
    response = requests.get(release_url, headers=headers)
    print(f"response code: {response.status_code}")
    print(f"response json: {response.json()}")

    if response.status_code == 200 or response.status_code == 201:
        print("Release already exists. Skipping creation.")
        response = requests.get(release_url, headers=headers)
        response_json = response.json()
        release_id = response_json.get("id", None)

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
            delete_url = f"https://api.github.com/repos/michaelgold/bpy/releases/assets/{asset_id}"
            response = requests.delete(delete_url, headers=headers)
            print(f"Asset deleted response code: {response.status_code}")
        
    else:
        print("Creating release.")
        # Step 1: Create the release

        release_name = f"gold-bpy-{selected_tag}"
        release_body = f"Blender Python API for Blender {selected_tag}"
        release_tag = f"gold-bpy-{selected_tag}"
        release_url = f"https://api.github.com/repos/michaelgold/bpy/releases"
        release_data = {
            "tag_name": selected_tag,
            "target_commitish": "main",
            "name": release_name,
            "body": release_body,
            "draft": False,
            "prerelease": False
        }
        response = requests.post(release_url, headers=headers, json=release_data)


        if response.status_code != 200 and response.status_code != 201:
            raise Exception(f"Failed to get release info: {response.text}")

        release_id = response.json()['id']

    # Step 2: Upload the .whl file
    upload_url = f"https://uploads.github.com/repos/michaelgold/bpy/releases/{release_id}/assets?name={whl_file_path.stem}.whl"
    headers['Content-Type'] = 'application/octet-stream'

    with open(whl_file_path, 'rb') as file:
        data = file.read()
        upload_response = requests.post(upload_url, headers=headers, data=data)

    if upload_response.status_code not in [200, 201]:
        raise Exception(f"Failed to upload asset: {upload_response.text}")

    print("File uploaded successfully.")

def check_new_tag(tag: str = None):
    repo_url = "https://api.github.com/repos/blender/blender"
    data_file_path: Path = Path.cwd() / "data.json"
    # Get the tags from the GitHub API
    response = requests.get(f"{repo_url}/tags")
    tags = response.json()

    # Determine which tag to use
    if tag and any(t['name'] == tag for t in tags):
        selected_tag = tag
    elif not tag:
        selected_tag = tags[0]['name']
    else:
        print(f"Tag '{tag}' not found.")
        return False

    # Load the current tag from the data file
    if data_file_path.exists():
        with open(data_file_path, 'r') as file:
            tag_data = json.load(file)
            current_tag = tag_data.get("latest_tag", "")
    else:
        current_tag = ""
        tag_data = {}
    
    if (selected_tag == current_tag) and (tag is not None):
        # If the tag is the same as the current tag, and no specific tag was provided, do nothing
        print(f"Tag '{selected_tag}' is already checked out.")
        return False

    else:
        # If the tag is different from the current tag, or a specific tag was provided, update the local repository and build blender
        print(f"Tag found: {selected_tag}. Updating and checking out the repo.")

        # Clone the repository and checkout the selected tag
        # subprocess.run(["git", "clone", "https://github.com/blender/blender.git"])
        blender_repo_dir = Path.cwd() / "../blender"
        subprocess.run(["git", "fetch", "--all"], cwd=blender_repo_dir)
        subprocess.run(["git", "checkout", f"tags/{selected_tag}"], cwd=blender_repo_dir)

        # Build blender
        subprocess.run(["make", "update"], cwd=blender_repo_dir)
        # subprocess.run(["make", "bpy"], cwd=blender_repo_dir)

        # tag_parts = selected_tag.split('.')
        # major_version = '.'.join(tag_parts[:2])
        # minor_version = '.'.join(tag_parts[:3])

        #./blender --background --factory-startup -noaudio --python ../blender-git/doc/python_api/sphinx_doc_gen.py -- --output=../python_api
        python_api_dir = Path.cwd() / "../python_api"

        blender_binary = "/Applications/Blender.app/Contents/MacOS/Blender"
        # build the python api docs
        subprocess.run([blender_binary, "--background", "--factory-startup", "-noaudio", "--python", blender_repo_dir / "doc/python_api/sphinx_doc_gen.py", "--", f"--output={python_api_dir}"])
        build_dir = Path.cwd() / "../build_darwin_bpy"

        # build the python api stubs in the build directory (for the wheel)
        subprocess.run(["python", "-m", "bpystubgen", python_api_dir / "sphinx-in", build_dir / "bin"])



        # Make the wheel

       

        subprocess.run(["pip", "install", "-U", "pip", "setuptools", "wheel"])
        subprocess.run(["python", blender_repo_dir / "build_files/utils/make_bpy_wheel.py", build_dir / "bin/"])

        # Get the wheel file
        bin_path = build_dir / "bin"



        publish_github(selected_tag, bin_path)
        




        # Update the data file
        tag_data["latest_tag"] = selected_tag
        with open(data_file_path, 'w') as file:
            json.dump(tag_data, file)
        
        return True
   
@app.command()
def build(tag: str = typer.Option(None, help="Specific tag to check out")):
    """
    This script checks for new tags in the Blender repository on GitHub.
    If a new tag is found, or a specific tag is provided, it updates the local repository and a data file.
    """
    os.chdir(Path(__file__).parent)
    check_new_tag(tag)

if __name__ == "__main__":
    app()
