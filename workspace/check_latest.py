import json
import os

import requests


def github_headers():
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_json(url):
    response = requests.get(url, headers=github_headers(), timeout=30)
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"GitHub API returned non-JSON response from {url}: HTTP {response.status_code}") from exc
    if response.status_code >= 400:
        message = payload.get("message") if isinstance(payload, dict) else payload
        raise RuntimeError(f"GitHub API request failed for {url}: HTTP {response.status_code}: {message}")
    return payload


def get_latest_tag():
    tags = get_json("https://api.github.com/repos/blender/blender/tags")
    if not isinstance(tags, list):
        raise RuntimeError(f"Expected tag list from GitHub API, got {type(tags).__name__}: {tags}")
    return tags[0]["name"] if tags else None


def get_latest_commit():
    commit = get_json("https://api.github.com/repos/blender/blender/commits/main")
    if not isinstance(commit, dict):
        raise RuntimeError(f"Expected commit object from GitHub API, got {type(commit).__name__}: {commit}")
    return commit["sha"] if commit else None


def read_version_info(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            return json.load(file)
    return {"previous_tag": "", "previous_commit": ""}


def write_version_info(file_path, tag, commit):
    with open(file_path, "w") as file:
        json.dump({"previous_tag": tag, "previous_commit": commit}, file)


def main():
    file_path = "version_info.json"
    version_info = read_version_info(file_path)

    latest_tag = get_latest_tag()
    latest_commit = get_latest_commit()

    new_tag = latest_tag != version_info.get("previous_tag")
    new_commit = latest_commit != version_info.get("previous_commit")

    if new_tag or new_commit:
        write_version_info(file_path, latest_tag, latest_commit)

    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as output_file:
            output_file.write(f"new_tag={str(new_tag).lower()}\n")
            output_file.write(f"new_commit={str(new_commit).lower()}\n")
            output_file.write(f"latest_tag={latest_tag or ''}\n")


if __name__ == "__main__":
    main()
