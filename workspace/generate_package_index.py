from pathlib import Path
import typer
from github import Github
import hashlib
import requests
from tempfile import NamedTemporaryFile

def compute_sha256(url):
    """Download a file and compute its SHA256 hash."""
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    sha256_hash = hashlib.sha256()
    with NamedTemporaryFile() as temp_file:
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
            sha256_hash.update(chunk)
        return sha256_hash.hexdigest()

def create_project_index_page(releases, project_name, docs_path):
    project_links = []
    for release in releases:
        for asset in release.get_assets():
            if asset.name.endswith('.whl'):
                try:
                    print(f"Computing SHA256 for {asset.name}...")
                    sha256_hash = compute_sha256(asset.browser_download_url)
                    link = f'<a href="{asset.browser_download_url}#sha256={sha256_hash}">{asset.name}</a><br>\n'
                    project_links.append(link)
                except Exception as e:
                    print(f"Error processing {asset.name}: {e}")
                    # Add the link without the hash if there's an error
                    link = f'<a href="{asset.browser_download_url}">{asset.name}</a><br>\n'
                    project_links.append(link)

    project_page_content = "<html><body>\n" + "".join(project_links) + "</body></html>"

    project_path = docs_path / project_name
    project_path.mkdir(parents=True, exist_ok=True)
    project_index_path = project_path / 'index.html'
    with project_index_path.open('w') as file:
        file.write(project_page_content)

def main(token: str, repository: str, project_name: str):
    # Initialize GitHub API
    g = Github(token)
    repo = g.get_repo(repository)

    # Gather all releases
    releases = repo.get_releases()

    # Ensure the docs directory exists
    docs_path = Path('docs')
    docs_path.mkdir(parents=True, exist_ok=True)

    # Create project index page (e.g., bpygold/index.html)
    create_project_index_page(releases, project_name, docs_path)

    # Generate root index.html content
    repo_name = repository.split('/')[-1]  # Extract repo name from the full repository string
    root_html_content = f"<html><body>\n<a href='/{repo_name}/{project_name}/'>{project_name}</a>\n</body></html>"

    # Write the root index.html content
    root_index_path = docs_path / 'index.html'
    with root_index_path.open('w') as file:
        file.write(root_html_content)

    print("Package index generated successfully.")

if __name__ == "__main__":
    typer.run(main)
