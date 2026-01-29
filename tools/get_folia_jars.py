# Download Folia server JARs from the PaperMC API
"""
This tool fetches and downloads Folia Minecraft server JARs from the PaperMC API.
Folia is a fork of Paper that adds regionized multithreading for improved performance
on servers with many spread-out players.

API Documentation: https://api.papermc.io/docs/swagger-ui/index.html

Modes:
  --list              List all available Folia versions (default)
  --download          Download server JARs to serverexecutables/folia/
  --download-latest=N Download only the latest N versions

Output format: folia:<VERSION>=API (latest build fetched automatically)
Downloaded files: serverexecutables/folia/folia-<VERSION>-<BUILD>.jar
"""

import requests
import json
import sys
import os
import time
from pathlib import Path

FOLIA_API_BASE = "https://api.papermc.io/v2/projects/folia"

# Get the base directory (parent of tools folder)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables' / 'folia'


def fetch_folia_versions(quiet=False):
    """Fetch all available Folia versions from the API"""
    if not quiet:
        print("📥 Fetching Folia versions...")
    try:
        response = requests.get(FOLIA_API_BASE, timeout=30)
        response.raise_for_status()
        data = response.json()
        versions = data.get('versions', [])
        # Reverse to get newest first
        versions = list(reversed(versions))
        return versions
    except requests.exceptions.RequestException as e:
        if not quiet:
            print(f"❌ Failed to fetch Folia versions: {e}")
        return None


def fetch_version_builds(version):
    """Fetch all builds for a specific version"""
    try:
        url = f"{FOLIA_API_BASE}/versions/{version}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get('builds', [])
    except requests.exceptions.RequestException:
        return []


def get_latest_build(version):
    """Get the latest build number for a version"""
    builds = fetch_version_builds(version)
    if builds:
        return max(builds)
    return None


def get_download_info(version, build):
    """Get download information for a specific version and build"""
    try:
        url = f"{FOLIA_API_BASE}/versions/{version}/builds/{build}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        downloads = data.get('downloads', {})
        application = downloads.get('application', {})
        filename = application.get('name')
        sha256 = application.get('sha256')
        
        if filename:
            download_url = f"{FOLIA_API_BASE}/versions/{version}/builds/{build}/downloads/{filename}"
            return {
                'filename': filename,
                'url': download_url,
                'sha256': sha256,
                'build': build
            }
        return None
    except requests.exceptions.RequestException:
        return None


def get_server_info(versions, limit=None, quiet=False):
    """
    Get server download info for all versions
    
    Args:
        versions: List of version strings
        limit: Maximum number of versions to process (None for all)
        quiet: Suppress progress output
    
    Returns:
        List of dicts: {'version': str, 'build': int, 'url': str, 'filename': str}
    """
    server_info = []
    
    if limit:
        versions = versions[:limit]
    
    total = len(versions)
    
    if not quiet:
        print(f"\n🔍 Processing {total} versions...")
        print("-" * 60)
    
    for i, version in enumerate(versions):
        if not quiet:
            print(f"  [{i + 1}/{total}] Fetching {version}...", end=" ", flush=True)
        
        # Get latest build for this version
        build = get_latest_build(version)
        
        if not build:
            if not quiet:
                print("⚠️ No builds available")
            continue
        
        # Get download info
        info = get_download_info(version, build)
        
        if info:
            server_info.append({
                'version': version,
                'build': info['build'],
                'url': info['url'],
                'filename': info['filename'],
                'sha256': info['sha256']
            })
            if not quiet:
                print(f"✅ Build {build}")
        else:
            if not quiet:
                print("❌ Failed to get download info")
        
        # Small delay to be nice to the API
        time.sleep(0.1)
    
    if not quiet:
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   ✅ Found Folia JARs: {len(server_info)}")
    
    return server_info


def format_output(server_info):
    """Format the server info in the required format"""
    output_lines = []
    for item in server_info:
        # Format: folia:version=API (will fetch latest build automatically)
        output_lines.append(f"folia:{item['version']}=API (build {item['build']})")
    return output_lines


def download_jar(version, build, url, filename, skip_existing=True):
    """
    Download a single JAR file
    
    Args:
        version: Version string (e.g., "1.21.4")
        build: Build number
        url: Download URL
        filename: Original filename from API
        skip_existing: Skip if file already exists
    
    Returns:
        Tuple: (success: bool, message: str, size: int)
    """
    # Ensure directory exists
    SERVER_EXECUTABLES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use a consistent naming format
    local_filename = f"folia-{version}-{build}.jar"
    filepath = SERVER_EXECUTABLES_DIR / local_filename
    
    # Check if already exists
    if skip_existing and filepath.exists():
        return True, "Already exists", filepath.stat().st_size
    
    try:
        response = requests.get(url, stream=True, timeout=120)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0
        
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
        
        return True, "Downloaded", downloaded
        
    except requests.exceptions.RequestException as e:
        # Clean up partial download
        if filepath.exists():
            filepath.unlink()
        return False, str(e), 0
    except Exception as e:
        if filepath.exists():
            filepath.unlink()
        return False, str(e), 0


def bulk_download(server_info, skip_existing=True, json_output=False):
    """
    Download multiple JAR files

    Args:
        server_info: List of dicts with version, build, url, filename keys
        skip_existing: Skip files that already exist
        json_output: Return results as dict for JSON output

    Returns:
        Dict with download results if json_output=True
    """
    total = len(server_info)
    downloaded = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    results_list = []

    if not json_output:
        print(f"\n📥 Downloading {total} Folia server JARs to:")
        print(f"   {SERVER_EXECUTABLES_DIR}")
        print("-" * 60)

    for i, item in enumerate(server_info):
        version = item['version']
        build = item['build']
        url = item['url']
        filename = item['filename']

        if not json_output:
            print(f"  [{i + 1}/{total}] folia-{version}-{build}.jar...", end=" ", flush=True)

        success, message, size = download_jar(version, build, url, filename, skip_existing)

        if success:
            if message == "Already exists":
                skipped += 1
                if not json_output:
                    print(f"⏭️ {message} ({format_bytes(size)})")
            else:
                downloaded += 1
                total_bytes += size
                if not json_output:
                    print(f"✅ {message} ({format_bytes(size)})")
        else:
            failed += 1
            if not json_output:
                print(f"❌ {message}")

        results_list.append({
            "version": version,
            "build": build,
            "success": success,
            "message": message,
            "size": size
        })

        # Small delay between downloads
        if success and message != "Already exists":
            time.sleep(0.2)

    if not json_output:
        print("-" * 60)
        print(f"\n📊 Download Summary:")
        print(f"   ✅ Downloaded: {downloaded} ({format_bytes(total_bytes)})")
        print(f"   ⏭️ Skipped (existing): {skipped}")
        print(f"   ❌ Failed: {failed}")
        print(f"\n📁 Files saved to: {SERVER_EXECUTABLES_DIR}")

    if json_output:
        return {
            "success": True,
            "mode": "download",
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "total_bytes": total_bytes,
            "results": results_list
        }


def format_bytes(bytes_size):
    """Format bytes to human-readable string"""
    if bytes_size == 0:
        return "0 B"
    sizes = ['B', 'KB', 'MB', 'GB']
    i = 0
    while bytes_size >= 1024 and i < len(sizes) - 1:
        bytes_size /= 1024
        i += 1
    return f"{bytes_size:.2f} {sizes[i]}"


def list_downloaded_silent():
    """List already downloaded JAR files (returns data only, no printing)"""
    if not SERVER_EXECUTABLES_DIR.exists():
        return []

    files = list(SERVER_EXECUTABLES_DIR.glob("folia-*.jar"))
    files.sort(reverse=True)

    result = []
    for f in files:
        result.append({
            "name": f.name,
            "size": f.stat().st_size,
            "path": str(f)
        })
    return result


def list_downloaded():
    """List already downloaded JAR files"""
    if not SERVER_EXECUTABLES_DIR.exists():
        print("\n📁 No downloaded files yet.")
        return []

    files = list(SERVER_EXECUTABLES_DIR.glob("folia-*.jar"))
    files.sort(reverse=True)

    if not files:
        print("\n📁 No downloaded files yet.")
        return []

    print(f"\n📁 Downloaded files in {SERVER_EXECUTABLES_DIR}:")
    print("-" * 60)

    total_size = 0
    for f in files:
        size = f.stat().st_size
        total_size += size
        print(f"  {f.name} ({format_bytes(size)})")

    print("-" * 60)
    print(f"   Total: {len(files)} files ({format_bytes(total_size)})")

    return files


def download_single_version(version, force=False, json_output=False):
    """Download a specific Folia version (latest build)"""
    if not json_output:
        print(f"\n🔍 Fetching latest build for Folia {version}...")

    build = get_latest_build(version)
    if not build:
        if not json_output:
            print(f"❌ No builds found for version {version}")
        if json_output:
            return {"success": False, "error": f"No builds found for version {version}"}
        return False

    info = get_download_info(version, build)
    if not info:
        if not json_output:
            print(f"❌ Could not get download info for {version} build {build}")
        if json_output:
            return {"success": False, "error": f"Could not get download info for {version} build {build}"}
        return False

    if not json_output:
        print(f"✅ Found build {build}")
        print(f"\n📥 Downloading folia-{version}-{build}.jar...")

    success, message, size = download_jar(
        version, build, info['url'], info['filename'],
        skip_existing=not force
    )

    if success:
        if not json_output:
            if message == "Already exists":
                print(f"⏭️ {message} ({format_bytes(size)})")
            else:
                print(f"✅ {message} ({format_bytes(size)})")
            print(f"\n📁 File saved to: {SERVER_EXECUTABLES_DIR / f'folia-{version}-{build}.jar'}")
        if json_output:
            return {
                "success": True,
                "mode": "single",
                "version": version,
                "build": build,
                "message": message,
                "size": size,
                "path": str(SERVER_EXECUTABLES_DIR / f'folia-{version}-{build}.jar')
            }
        return True
    else:
        if not json_output:
            print(f"❌ {message}")
        if json_output:
            return {"success": False, "error": message}
        return False


def print_usage():
    """Print usage information"""
    print("""
Usage: python get_folia_jars.py [mode] [options]

Modes:
  --list              List all available Folia versions (default)
  --download          Download ALL Folia server JARs (latest build for each version)
  --download-latest=N Download only the latest N versions
  --version=X         Download a specific version (e.g., --version=1.21.4)
  --list-downloaded   Show already downloaded files

Options:
  --force             Re-download even if file exists
  --quiet, -q         Suppress progress output during URL fetching
  --json              Output results as JSON (for programmatic use)

Examples:
  python get_folia_jars.py --list
  python get_folia_jars.py --download-latest=10
  python get_folia_jars.py --version=1.21.4
  python get_folia_jars.py --download --force
  python get_folia_jars.py --list-downloaded
  python get_folia_jars.py --list --json

Note: Folia downloads always use the latest build for each version.
Format: folia:<version>=API (build fetched automatically)

About Folia:
  Folia is a fork of Paper that adds regionized multithreading.
  It's designed for servers with many spread-out players across the world.
""")


def main():
    # Parse arguments
    args = sys.argv[1:]

    # Check for JSON output mode first
    json_output = '--json' in args

    if not json_output:
        print("=" * 60)
        print("🌿 Folia Server JAR Fetcher & Downloader")
        print("=" * 60)

    mode = 'list'  # default
    limit = None
    specific_version = None
    force_download = '--force' in args
    quiet = '--quiet' in args or '-q' in args or json_output
    
    # Determine mode
    if '--download' in args:
        mode = 'download'
    elif '--list-downloaded' in args:
        mode = 'list-downloaded'
    elif '--list' in args:
        mode = 'list'
    
    # Check for download-latest=N
    for arg in args:
        if arg.startswith('--download-latest='):
            mode = 'download'
            try:
                limit = int(arg.split('=')[1])
            except ValueError:
                print("❌ Invalid --download-latest value. Use --download-latest=N where N is a number.")
                return
        elif arg.startswith('--limit='):
            try:
                limit = int(arg.split('=')[1])
            except ValueError:
                pass
        elif arg.startswith('--version='):
            mode = 'single'
            specific_version = arg.split('=')[1]
    
    # Execute based on mode
    if mode == 'list-downloaded':
        files = list_downloaded_silent() if json_output else None
        if json_output:
            result = {"success": True, "mode": "list-downloaded", "files": files or []}
            print(json.dumps(result))
        else:
            list_downloaded()
        return

    if mode == 'single':
        if not specific_version:
            if json_output:
                print(json.dumps({"success": False, "error": "No version specified"}))
            else:
                print("❌ No version specified. Use --version=X.X.X")
            return
        result = download_single_version(specific_version, force=force_download, json_output=json_output)
        if json_output:
            print(json.dumps(result))
        return

    # Fetch versions for list or download modes
    versions = fetch_folia_versions(quiet=json_output)
    if not versions:
        if json_output:
            print(json.dumps({"success": False, "error": "Could not fetch Folia versions"}))
        else:
            print("\n❌ Could not fetch Folia versions. Exiting.")
        return

    if not json_output:
        print(f"✅ Found {len(versions)} Folia versions")
        print(f"   Latest: {versions[0]}")
        print(f"   Oldest: {versions[-1]}")

    # Get server info
    server_info = get_server_info(
        versions,
        limit=limit,
        quiet=quiet
    )

    if not server_info:
        if json_output:
            print(json.dumps({"success": False, "error": "No Folia server JARs found"}))
        else:
            print("\n❌ No Folia server JARs found.")
        return

    if mode == 'list':
        if json_output:
            # JSON output format
            result = {
                "success": True,
                "mode": "list",
                "count": len(server_info),
                "versions": [{"version": item['version'], "build": item['build'], "url": item['url']} for item in server_info]
            }
            print(json.dumps(result))
        else:
            # Format and display output
            print("\n" + "=" * 60)
            print("📋 FOLIA SERVER JARS (folia:<version>=API)")
            print("=" * 60 + "\n")

            output_lines = format_output(server_info)
            for line in output_lines:
                print(line)

            # Save to file
            output_file = BASE_DIR / "folia_server_urls.txt"
            with open(output_file, 'w') as f:
                f.write("# Folia Server JAR Download Info\n")
                f.write(f"# Generated from {FOLIA_API_BASE}\n")
                f.write(f"# Total: {len(output_lines)} versions\n")
                f.write("# Format: folia:<version>=API (latest build fetched automatically)\n\n")
                for item in server_info:
                    f.write(f"folia:{item['version']}=API (build {item['build']}, url: {item['url']})\n")

            print(f"\n💾 Saved to: {output_file}")

    elif mode == 'download':
        # Bulk download
        results = bulk_download(server_info, skip_existing=not force_download, json_output=json_output)
        if json_output:
            print(json.dumps(results))

    if not json_output:
        print("\n✅ Done!")


if __name__ == "__main__":
    if '--json' not in sys.argv:
        print_usage()
    main()
