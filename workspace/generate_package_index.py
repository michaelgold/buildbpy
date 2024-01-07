from pathlib import Path
import typer
from github import Github

def create_package_links(release):
    links = []
    for asset in release.get_assets():
        if asset.name.endswith('.whl'):
            link = f'<a href="{asset.browser_download_url}">{asset.name}</a><br>\n'
            links.append(link)
    return links

def main(token: str, repository: str):
    # Initialize GitHub API
    g = Github(token)
    repo = g.get_repo(repository)

    # Gather all package links
    package_links = []
    for release in repo.get_releases():
        package_links.extend(create_package_links(release))

    # Generate HTML content
    html_content = "<html><body>\n<h1>Links for bpygold</h1>\n" + "".join(package_links) + "</body></html>"

    # Ensure the docs directory exists
    docs_path = Path('docs')
    docs_path.mkdir(parents=True, exist_ok=True)

    # Write the HTML content to a file
    index_path = docs_path / 'index.html'
    with index_path.open('w') as file:
        file.write(html_content)

    print("Package index generated successfully.")

if __name__ == "__main__":
    typer.run(main)
