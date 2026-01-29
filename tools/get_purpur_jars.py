# Download Purpur server JARs from the PurpurMC API
"""
This tool fetches and downloads Purpur Minecraft server JARs from the PurpurMC API.
Purpur is a fork of Paper/Pufferfish with additional gameplay and configuration options.

API Documentation: https://api.purpurmc.org/

Modes:
  --list              List all available Purpur versions (default)
  --download          Download server JARs to serverexecutables/purpur/
  --download-latest=N Download only the latest N versions

Output format: purpur:<VERSION>=API (latest build fetched automatically)
Downloaded files: serverexecutables/purpur/purpur-<VERSION>-<BUILD>.jar
"""

import requests
import json
import sys
import os
import time
from pathlib import Path

PURPUR_API_BASE = "https://api.purpurmc.org/v2/purpur"

# Get the base directory (parent of tools folder)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables' / 'purpur'


def fetch_purpur_versions(quiet=False):
    """Fetch all available Purpur versions from the API"""
    if not quiet:
        print("📥 Fetching Purpur versions...")
    try:
        response = requests.get(PURPUR_API_BASE, timeout=30)
        response.raise_for_status()
        data = response.json()
        versions = data.get('versions', [])
        # Reverse to get newest first
        versions = list(reversed(versions))
        return versions
    except requests.exceptions.RequestException as e:
        if not quiet:
            print(f"❌ Failed to fetch Purpur versions: {e}")
        return None


def fetch_version_info(version):
    """Fetch build info for a specific version"""
    try:
        url = f"{PURPUR_API_BASE}/{version}"
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get('builds', {})
    except requests.exceptions.RequestException:
        return {}


def get_latest_build(version):
    """Get the latest build number for a version"""
    builds = fetch_version_info(version)
    if builds:
        return builds.get('latest')
    return None


def get_download_url(version, build):
    """Get the download URL for a specific version and build"""
    return f"{PURPUR_API_BASE}/{version}/{build}/download"


def get_server_info(versions, limit=None, quiet=False):
    """
    Get server download info for all versions
    
    Args:
        versions: List of version strings
        limit: Maximum number of versions to process (None for all)
        quiet: Suppress progress output
    
    Returns:
        List of dicts: {'version': str, 'build': str, 'url': str}
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
        
        # Get download URL
        url = get_download_url(version, build)
        
        server_info.append({
            'version': version,
            'build': build,
            'url': url
        })
        
        if not quiet:
            print(f"✅ Build {build}")
        
        # Small delay to be nice to the API
        time.sleep(0.1)
    
    if not quiet:
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   ✅ Found Purpur JARs: {len(server_info)}")
    
    return server_info


def format_output(server_info):
    """Format the server info in the required format"""
    output_lines = []
    for item in server_info:
        # Format: purpur:version=API (will fetch latest build automatically)
        output_lines.append(f"purpur:{item['version']}=API (build {item['build']})")
    return output_lines


def download_jar(version, build, url, skip_existing=True):
    """
    Download a single JAR file
    
    Args:
        version: Version string (e.g., "1.21.4")
        build: Build number
        url: Download URL
        skip_existing: Skip if file already exists
    
    Returns:
        Tuple: (success: bool, message: str, size: int)
    """
    # Ensure directory exists
    SERVER_EXECUTABLES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use a consistent naming format
    local_filename = f"purpur-{version}-{build}.jar"
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
        server_info: List of dicts with version, build, url keys
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
        print(f"\n📥 Downloading {total} Purpur server JARs to:")
        print(f"   {SERVER_EXECUTABLES_DIR}")
        print("-" * 60)

    for i, item in enumerate(server_info):
        version = item['version']
        build = item['build']
        url = item['url']

        if not json_output:
            print(f"  [{i + 1}/{total}] purpur-{version}-{build}.jar...", end=" ", flush=True)

        success, message, size = download_jar(version, build, url, skip_existing)

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

    files = list(SERVER_EXECUTABLES_DIR.glob("purpur-*.jar"))
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

    files = list(SERVER_EXECUTABLES_DIR.glob("purpur-*.jar"))
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
    """Download a specific Purpur version (latest build)"""
    if not json_output:
        print(f"\n🔍 Fetching latest build for Purpur {version}...")

    build = get_latest_build(version)
    if not build:
        if not json_output:
            print(f"❌ No builds found for version {version}")
        if json_output:
            return {"success": False, "error": f"No builds found for version {version}"}
        return False

    url = get_download_url(version, build)

    if not json_output:
        print(f"✅ Found build {build}")
        print(f"\n📥 Downloading purpur-{version}-{build}.jar...")

    success, message, size = download_jar(
        version, build, url,
        skip_existing=not force
    )

    if success:
        if not json_output:
            if message == "Already exists":
                print(f"⏭️ {message} ({format_bytes(size)})")
            else:
                print(f"✅ {message} ({format_bytes(size)})")
            print(f"\n📁 File saved to: {SERVER_EXECUTABLES_DIR / f'purpur-{version}-{build}.jar'}")
        if json_output:
            return {
                "success": True,
                "mode": "single",
                "version": version,
                "build": build,
                "message": message,
                "size": size,
                "path": str(SERVER_EXECUTABLES_DIR / f'purpur-{version}-{build}.jar')
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
Usage: python get_purpur_jars.py [mode] [options]

Modes:
  --list              List all available Purpur versions (default)
  --download          Download ALL Purpur server JARs (latest build for each version)
  --download-latest=N Download only the latest N versions
  --version=X         Download a specific version (e.g., --version=1.21.4)
  --list-downloaded   Show already downloaded files

Options:
  --force             Re-download even if file exists
  --quiet, -q         Suppress progress output during URL fetching
  --json              Output results as JSON (for programmatic use)

Examples:
  python get_purpur_jars.py --list
  python get_purpur_jars.py --download-latest=10
  python get_purpur_jars.py --version=1.21.4
  python get_purpur_jars.py --download --force
  python get_purpur_jars.py --list-downloaded
  python get_purpur_jars.py --list --json

Note: Purpur downloads always use the latest build for each version.
Format: purpur:<version>=API (build fetched automatically)

About Purpur:
  Purpur is a fork of Paper/Pufferfish with additional gameplay features
  and extensive configuration options for server customization.
""")


def main():
    # Parse arguments
    args = sys.argv[1:]

    # Check for JSON output mode first
    json_output = '--json' in args

    if not json_output:
        print("=" * 60)
        print("🟣 Purpur Server JAR Fetcher & Downloader")
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
    versions = fetch_purpur_versions(quiet=json_output)
    if not versions:
        if json_output:
            print(json.dumps({"success": False, "error": "Could not fetch Purpur versions"}))
        else:
            print("\n❌ Could not fetch Purpur versions. Exiting.")
        return

    if not json_output:
        print(f"✅ Found {len(versions)} Purpur versions")
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
            print(json.dumps({"success": False, "error": "No Purpur server JARs found"}))
        else:
            print("\n❌ No Purpur server JARs found.")
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
            print("📋 PURPUR SERVER JARS (purpur:<version>=API)")
            print("=" * 60 + "\n")

            output_lines = format_output(server_info)
            for line in output_lines:
                print(line)

            # Save to file
            output_file = BASE_DIR / "purpur_server_urls.txt"
            with open(output_file, 'w') as f:
                f.write("# Purpur Server JAR Download Info\n")
                f.write(f"# Generated from {PURPUR_API_BASE}\n")
                f.write(f"# Total: {len(output_lines)} versions\n")
                f.write("# Format: purpur:<version>=API (latest build fetched automatically)\n\n")
                for item in server_info:
                    f.write(f"purpur:{item['version']}=API (build {item['build']}, url: {item['url']})\n")

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
