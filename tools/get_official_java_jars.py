# Fetch and download official Minecraft Java Edition server JARs from Mojang
"""
This tool fetches official Minecraft Java Edition server JAR download URLs
from Mojang's version manifest and can bulk download them.

Modes:
  --list              List all available server JAR URLs (default)
  --download          Download server JARs to serverexecutables/vanilla/
  --download-latest=N Download only the latest N versions

Output format: vanilla-<VERSION>:<URL>
Downloaded files: serverexecutables/vanilla/vanilla-<VERSION>.jar
"""

import requests
import json
import sys
import os
import time
from pathlib import Path

VERSION_MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

# Get the base directory (parent of tools folder)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables' / 'vanilla'


def fetch_manifest():
    """Fetch the main version manifest from Mojang"""
    print("📥 Fetching version manifest...")
    try:
        response = requests.get(VERSION_MANIFEST_URL, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to fetch manifest: {e}")
        return None


def fetch_version_json(version_url):
    """Fetch a specific version's JSON file"""
    try:
        response = requests.get(version_url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        return None


def get_server_urls(manifest, include_snapshots=False, limit=None, quiet=False):
    """
    Extract server download URLs from all versions in the manifest
    
    Args:
        manifest: The version manifest JSON
        include_snapshots: Whether to include snapshot versions
        limit: Maximum number of versions to process (None for all)
        quiet: Suppress progress output
    
    Returns:
        List of dicts: {'version': str, 'url': str}
    """
    versions = manifest.get('versions', [])
    server_urls = []
    processed = 0
    skipped_no_server = 0
    skipped_type = 0
    
    # Filter to only releases first if not including snapshots
    if not include_snapshots:
        versions = [v for v in versions if v.get('type') == 'release']
    
    total = len(versions) if limit is None else min(limit, len(versions))
    
    if not quiet:
        print(f"\n🔍 Processing {total} versions...")
        print("-" * 60)
    
    for i, version_info in enumerate(versions):
        if limit and processed >= limit:
            break
            
        version_id = version_info.get('id')
        version_url = version_info.get('url')
        
        # Progress indicator
        if not quiet:
            print(f"  [{processed + 1}/{total}] Fetching {version_id}...", end=" ", flush=True)
        
        # Fetch the version JSON
        version_data = fetch_version_json(version_url)
        
        if not version_data:
            if not quiet:
                print("❌ Failed")
            continue
        
        # Extract server download URL
        downloads = version_data.get('downloads', {})
        server_info = downloads.get('server', {})
        server_url = server_info.get('url')
        
        if server_url:
            server_urls.append({
                'version': version_id,
                'url': server_url
            })
            if not quiet:
                print(f"✅ Found")
        else:
            skipped_no_server += 1
            if not quiet:
                print("⚠️ No server JAR")
        
        processed += 1
        
        # Small delay to be nice to the API
        time.sleep(0.05)
    
    if not quiet:
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   ✅ Found server JARs: {len(server_urls)}")
        print(f"   ⚠️ No server JAR available: {skipped_no_server}")
    
    return server_urls


def format_output(server_urls):
    """Format the server URLs in the required format"""
    output_lines = []
    for item in server_urls:
        output_lines.append(f"vanilla-{item['version']}:{item['url']}")
    return output_lines


def download_jar(version, url, skip_existing=True):
    """
    Download a single JAR file
    
    Args:
        version: Version string (e.g., "1.21.11")
        url: Download URL
        skip_existing: Skip if file already exists
    
    Returns:
        Tuple: (success: bool, message: str, size: int)
    """
    # Ensure directory exists
    SERVER_EXECUTABLES_DIR.mkdir(parents=True, exist_ok=True)
    
    filename = f"vanilla-{version}.jar"
    filepath = SERVER_EXECUTABLES_DIR / filename
    
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


def bulk_download(server_urls, skip_existing=True):
    """
    Download multiple JAR files
    
    Args:
        server_urls: List of dicts with 'version' and 'url' keys
        skip_existing: Skip files that already exist
    """
    total = len(server_urls)
    downloaded = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    
    print(f"\n📥 Downloading {total} server JARs to:")
    print(f"   {SERVER_EXECUTABLES_DIR}")
    print("-" * 60)
    
    for i, item in enumerate(server_urls):
        version = item['version']
        url = item['url']
        
        print(f"  [{i + 1}/{total}] vanilla-{version}.jar...", end=" ", flush=True)
        
        success, message, size = download_jar(version, url, skip_existing)
        
        if success:
            if message == "Already exists":
                skipped += 1
                print(f"⏭️ {message} ({format_bytes(size)})")
            else:
                downloaded += 1
                total_bytes += size
                print(f"✅ {message} ({format_bytes(size)})")
        else:
            failed += 1
            print(f"❌ {message}")
        
        # Small delay between downloads
        if success and message != "Already exists":
            time.sleep(0.2)
    
    print("-" * 60)
    print(f"\n📊 Download Summary:")
    print(f"   ✅ Downloaded: {downloaded} ({format_bytes(total_bytes)})")
    print(f"   ⏭️ Skipped (existing): {skipped}")
    print(f"   ❌ Failed: {failed}")
    print(f"\n📁 Files saved to: {SERVER_EXECUTABLES_DIR}")


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


def list_downloaded():
    """List already downloaded JAR files"""
    if not SERVER_EXECUTABLES_DIR.exists():
        print("\n📁 No downloaded files yet.")
        return []
    
    files = list(SERVER_EXECUTABLES_DIR.glob("vanilla-*.jar"))
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


def print_usage():
    """Print usage information"""
    print("""
Usage: python get_official_java_jars.py [mode] [options]

Modes:
  --list              List all available server JAR URLs (default)
  --download          Download ALL server JARs (~92 versions, ~4GB)
  --download-latest=N Download only the latest N release versions
  --list-downloaded   Show already downloaded files

Options:
  --snapshots, -s     Include snapshot versions (with --list or --download)
  --force             Re-download even if file exists
  --quiet, -q         Suppress progress output during URL fetching

Examples:
  python get_official_java_jars.py --list
  python get_official_java_jars.py --download-latest=10
  python get_official_java_jars.py --download --force
  python get_official_java_jars.py --list-downloaded
""")


def main():
    print("=" * 60)
    print("🎮 Minecraft Java Server JAR Fetcher & Downloader")
    print("=" * 60)
    
    # Parse arguments
    args = sys.argv[1:]
    
    mode = 'list'  # default
    limit = None
    include_snapshots = '--snapshots' in args or '-s' in args
    force_download = '--force' in args
    quiet = '--quiet' in args or '-q' in args
    
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
    
    # Execute based on mode
    if mode == 'list-downloaded':
        list_downloaded()
        return
    
    # Fetch manifest for list or download modes
    manifest = fetch_manifest()
    if not manifest:
        print("\n❌ Could not fetch version manifest. Exiting.")
        return
    
    total_versions = len(manifest.get('versions', []))
    release_count = len([v for v in manifest.get('versions', []) if v.get('type') == 'release'])
    print(f"✅ Manifest loaded: {total_versions} total versions ({release_count} releases)")
    
    # Get server URLs
    server_urls = get_server_urls(
        manifest, 
        include_snapshots=include_snapshots, 
        limit=limit,
        quiet=quiet
    )
    
    if not server_urls:
        print("\n❌ No server URLs found.")
        return
    
    if mode == 'list':
        # Format and display output
        print("\n" + "=" * 60)
        print("📋 SERVER JAR URLs (vanilla-<version>:<url>)")
        print("=" * 60 + "\n")
        
        output_lines = format_output(server_urls)
        for line in output_lines:
            print(line)
        
        # Save to file
        output_file = BASE_DIR / "vanilla_server_urls.txt"
        with open(output_file, 'w') as f:
            f.write("# Official Minecraft Java Server JAR URLs\n")
            f.write(f"# Generated from {VERSION_MANIFEST_URL}\n")
            f.write(f"# Total: {len(output_lines)} versions\n")
            f.write("# Format: vanilla-<version>:<url>\n\n")
            for line in output_lines:
                f.write(line + "\n")
        
        print(f"\n💾 Saved to: {output_file}")
        
    elif mode == 'download':
        # Bulk download
        bulk_download(server_urls, skip_existing=not force_download)
    
    print("\n✅ Done!")


if __name__ == "__main__":
    print_usage()
    main()

