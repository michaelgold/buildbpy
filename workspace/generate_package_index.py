from pathlib import Path
import typer
from github import Github

def create_project_index_page(releases, project_name, docs_path):
    project_links = []
    for release in releases:
        for asset in release.get_assets():
            if asset.name.endswith('.whl'):
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
    root_html_content = f"<html><body>\n<a href='/{project_name}/'>{project_name}</a>\n</body></html>"

    # Write the root index.html content
    root_index_path = docs_path / 'index.html'
    with root_index_path.open('w') as file:
        file.write(root_html_content)

    print("Package index generated successfully.")

if __name__ == "__main__":
    typer.run(main)
