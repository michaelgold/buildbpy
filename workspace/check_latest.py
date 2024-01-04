import requests
import json
import os

def get_latest_tag():
    response = requests.get('https://api.github.com/repos/blender/blender/tags')
    tags = response.json()
    return tags[0]['name'] if tags else None

def get_latest_commit():
    response = requests.get('https://api.github.com/repos/blender/blender/commits/main')
    commit = response.json()
    return commit['sha'] if commit else None

def read_version_info(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as file:
            return json.load(file)
    return {"previous_tag": "", "previous_commit": ""}

def write_version_info(file_path, tag, commit):
    with open(file_path, 'w') as file:
        json.dump({"previous_tag": tag, "previous_commit": commit}, file)

def main():
    file_path = 'version_info.json'
    version_info = read_version_info(file_path)

    latest_tag = get_latest_tag()
    latest_commit = get_latest_commit()

    new_tag = latest_tag != version_info.get('previous_tag')
    new_commit = latest_commit != version_info.get('previous_commit')

    # Update the JSON file only if there's a new tag or commit
    if new_tag or new_commit:
        write_version_info(file_path, latest_tag, latest_commit)

    print(f"::set-output name=new_tag::{str(new_tag).lower()}")
    print(f"::set-output name=new_commit::{str(new_commit).lower()}")
    print(f"::set-output name=latest_tag::{latest_tag or ''}")  # Latest tag or empty string

if __name__ == "__main__":
    main()
