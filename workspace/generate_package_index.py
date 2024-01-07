from pathlib import Path
import typer
from github import Github

def generate_html_for_release(release):
    html_content = f"<h2>{release.tag_name}</h2>\n<ul>\n"
    for asset in release.get_assets():
        if asset.name.endswith('.whl'):
            html_content += f'<li><a href="{asset.browser_download_url}">{asset.name}</a></li>\n'
    html_content += "</ul>\n"
    return html_content

def main(token: str, repository: str):
    # Initialize GitHub API
    g = Github(token)
    repo = g.get_repo(repository)

    html_index = "<html><body>\n"

    # Loop through each release and add to the HTML index
    for release in repo.get_releases():
        html_index += generate_html_for_release(release)

    html_index += "</body></html>"

    # Ensure the docs directory exists
    docs_path = Path('docs')
    docs_path.mkdir(parents=True, exist_ok=True)

    # Write the HTML index to a file
    index_path = docs_path / 'index.html'
    with index_path.open('w') as file:
        file.write(html_index)

    print("Package index generated successfully.")

if __name__ == "__main__":
    typer.run(main)
