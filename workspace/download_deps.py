import re
import httpx
import typer
import asyncio
from hashlib import md5, sha256
from pathlib import Path
import aioftp
import urllib
import shutil

app = typer.Typer()

def get_hash_func(hash_type: str):
    return md5 if hash_type.lower() == 'md5' else sha256


def parse_cmake_file(file_path):
    with open(file_path, 'r') as file:
        content = file.read()

    # Extract all set commands
    set_commands = re.findall(r'set\((.*?)\)', content, re.DOTALL)

    # Create a dictionary to store the libraries
    libraries = {}
    current_lib = None

    def is_new_library(command):
        # typer.echo(f"checking command: {command}")
        # return ("VERSION" in command) and  ("${" not in command) and ("." in command) and ("NODOTS" not in command) and ("SHORT" not in command)
        parts = command.split()
        return (("VERSION" in parts[0]) or ("YEAR" in parts[0] )) and ("NODOTS" not in command) and ("SHORT" not in command)


    for command in set_commands:
        # Split the command into variable name and value
        parts = command.split()
        if len(parts) < 2:
            continue
        lib_name = None
        variable_name = parts[0]
        # variable_value = ' '.join(parts[1:]).strip('"')
        variable_value = parts[1]
        if is_new_library(command):
            

            version = parts[1]

            # Extract the library name from the variable name
            lib_name = '_'.join(variable_name.split('_')[:-1])
            typer.echo(f"new library: {lib_name}, version: {version}")

        # If a new library is encountered, update current_lib
        if lib_name and lib_name != current_lib:
            current_lib = lib_name
            libraries[current_lib] = {}

        # If there is a current library, add the property to it
        if current_lib:
            libraries[current_lib][variable_name.replace(f'{current_lib}_', '')] = variable_value
        # Replace placeholders in the URI or FILE for each library
    for lib_name, properties in libraries.items():
        for prop_name, prop_value in properties.items():
            # typer.echo(f"prop_name: {prop_name}\nprop_value: {prop_value}\nlib_name: {lib_name}\n\n")
            if 'URI' in prop_name or 'FILE' or 'YEAR' in prop_name:
                
                # Find all placeholders in the URI or FILE
                placeholders = re.findall(r'\${(.*?)}', prop_value)
                # typer.echo(f"placeholders: {placeholders}")
                for i in range(0, 2):
                    for placeholder in placeholders:
                        # Check if the placeholder exists in the library's properties
                        placeholder_without_library = placeholder.replace(f'{lib_name}_', '')
                        placeholder_without_version = placeholder.replace(f'_VERSION', '')
                        # typer.echo(f"placeholder_without_library: {placeholder_without_library}")
                        if placeholder_without_library in libraries[lib_name]:




                            # Replace the placeholder with the value from the same library
                            old_prop_value = prop_value
                            prop_value = prop_value.replace(f'${{{placeholder}}}', libraries[lib_name][placeholder_without_library])
                            # typer.echo(f"old value: {old_prop_value} new prop_value: {prop_value}")
                        elif placeholder_without_version in libraries:
                            # Replace the placeholder with the value from the same library
                            old_prop_value = prop_value
                            prop_value = prop_value.replace(f'${{{placeholder}}}', libraries[placeholder_without_version]['VERSION'])
                            typer.echo(f"old value: {old_prop_value} new prop_value: {prop_value}")
                        else:
                            print(f"Warning: Placeholder {placeholder} not found in properties of {lib_name}.")
                    
                properties[prop_name] = prop_value
    
    for lib_name, properties in libraries.items():
        version = properties.get('VERSION')
        if version and version.startswith('${') and version.endswith('}'):
            # typer.echo(f"found version: {version}")
            parent_lib_name = version[2:-1].replace("_VERSION", "")  # Extract parent library name
            parent_lib = libraries.get(parent_lib_name)
            # typer.echo(f"parent_lib: {parent_lib_name}")
            if parent_lib:
                parent_version = parent_lib.get('VERSION')
                if parent_version:
                    # Replace placeholders in URI and FILE
                    properties['URI'] = properties['URI'].replace(version, parent_version)
                    properties['FILE'] = properties['FILE'].replace(version, parent_version)
                    typer.echo(f"Replacing {version} with {parent_version} in {lib_name}")

    # handle special cases
    libraries['GMP']['URI'] = "https://ftp.gnu.org/gnu/gmp/gmp-6.2.1.tar.xz"
    # libraries['TBB']['URI'] = "https://github.com/oneapi-src/oneTBB/archive/2020.tar.gz"
    # libraries['TBB']['FILE'] = "oneTBB-2020_U3.tar.gz"

    typer.echo(f"TBB: {libraries['TBB']}")


    return libraries

async def download_file(client: httpx.AsyncClient, uri, destination: Path):
    if uri.startswith('http'):
        # uri.replace('http://', 'https://')
        try: 
            response = await client.get(uri)
        except httpx.RequestError as e:
            
            typer.echo(f"Request Error downloading {uri}: {e}")
            return False
        except httpx.HTTPStatusError as e:
            typer.echo(f"HTTP Status Error downloading {uri}: {e.response}")
            return False
        # if response.status_code in [301, 302]:
        #     uri = response.headers['Location']
        #     response = await client.get(uri)

        # content_disposition = response.headers.get('Content-Disposition')
        # if content_disposition:
        #     filename = re.findall('filename=(.+)', content_disposition)[0]
        # else:
        #     filename = Path(uri).name


        with open(destination, "wb") as file:
            file.write(response.content)
            
    elif uri.startswith('ftp'):
        url = urllib.parse.urlparse(uri)
        path = url.path
        downloaded_file_name = Path(url.path).name
        destination_dir = destination.parent
       
        async with aioftp.Client.context(url.hostname, url.port or 21) as client:
            await client.download(path, destination_dir)
            shutil.move(destination_dir / downloaded_file_name, destination)        
    else:
        raise ValueError(f"Unsupported protocol in URI: {uri}")

    return True

def verify_file(file_path: Path, expected_hash: str, hash_type: str):
    hash_func = get_hash_func(hash_type)
    try:
        with open(file_path, 'rb') as f:
            file_hash = hash_func(f.read()).hexdigest()
            
        return { file_hash == expected_hash, file_hash }
    except Exception as e:
        typer.echo(f"Error verifying {file_path}: {e}")
        return { False, None }

@app.command()
def download_deps(cmakelists_path: str, download_path: str):
    libraries = parse_cmake_file(cmakelists_path)
    asyncio.run(download_deps_async(libraries, download_path))

async def download_deps_async(libraries: dict, download_path: str):
    download_dir = Path(download_path)
    download_dir.mkdir(parents=True, exist_ok=True)
    

    # typer.echo(f"libraries: {libraries}")
    timeout = httpx.Timeout(60.0, connect=60.0)

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        for lib_name, properties in libraries.items():
            uri = properties.get('URI')
            hash_value = properties.get('HASH')
            hash_type = properties.get('HASH_TYPE', 'md5').lower()
            filename = properties.get('FILE')

            if uri and filename:
                destination = download_dir / filename
                typer.echo(f"Downloading {lib_name} from {uri} to {destination}")
                if await download_file(client, uri, destination):
                    is_hash_verified, hash = verify_file(destination, hash_value, hash_type)
                    if is_hash_verified:
                        pass
                        # typer.echo(f"Verified {filename} successfully.")
                    else:
                        typer.echo(f"Verification failed for {filename}. expecting {hash_value} got {hash}")
                else:
                    typer.echo(f"Failed to download {lib_name}.")

if __name__ == "__main__":
    app()
