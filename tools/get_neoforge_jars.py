# Download NeoForge server installer JARs from NeoForge Maven
"""
This tool fetches and downloads NeoForge Minecraft server installer JARs.
NeoForge is a fork of Forge that started after Minecraft 1.20.1, providing
continued modding support with improved features.

API: https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge

Modes:
  --list              List all available NeoForge versions (default)
  --download          Download server JARs to serverexecutables/neoforge/
  --download-latest=N Download only the latest N versions

Options:
  --stable-only       Only include stable versions (exclude beta)
  --include-beta      Include beta versions (default excludes beta)
  --version=X         Download a specific version

Output format: neoforge:<VERSION>=URL
Downloaded files: serverexecutables/neoforge/neoforge-<VERSION>-installer.jar

Note: NeoForge provides installer JARs. You need to run the installer to create the server.
      java -jar neoforge-X.X.X-installer.jar --installServer

NeoForge Version Mapping (approximate):
  20.2.x -> MC 1.20.2
  20.3.x -> MC 1.20.3
  20.4.x -> MC 1.20.4
  20.5.x -> MC 1.20.5
  20.6.x -> MC 1.20.6
  21.0.x -> MC 1.21.0
  21.1.x -> MC 1.21.1
  21.2.x -> MC 1.21.2
  21.3.x -> MC 1.21.3
  21.4.x -> MC 1.21.4
  21.5.x -> MC 1.21.5
  ...and so on
"""

import requests
import json
import sys
import os
import time
import re
from pathlib import Path

NEOFORGE_API_URL = "https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge"
NEOFORGE_MAVEN_BASE = "https://maven.neoforged.net/releases/net/neoforged/neoforge"

# Get the base directory (parent of tools folder)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables' / 'neoforge'


def fetch_neoforge_versions():
    """Fetch all available NeoForge versions from the API"""
    print("📥 Fetching NeoForge versions...")
    try:
        response = requests.get(NEOFORGE_API_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
        versions = data.get('versions', [])
        return versions
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to fetch NeoForge versions: {e}")
        return None


def parse_version(version_str):
    """
    Parse a NeoForge version string
    
    Args:
        version_str: Version like "21.4.156" or "21.4.120-beta"
    
    Returns:
        Dict with parsed info or None if invalid
    """
    # Skip snapshot/alpha versions
    if 'snapshot' in version_str.lower() or 'alpha' in version_str.lower():
        return None
    
    # Skip special versions like "0.25w14craftmine.3-beta"
    if version_str.startswith('0.') or 'craftmine' in version_str.lower():
        return None
    
    is_beta = '-beta' in version_str
    clean_version = version_str.replace('-beta', '')
    
    # Parse major.minor.patch format
    parts = clean_version.split('.')
    if len(parts) < 2:
        return None
    
    try:
        major = int(parts[0])
        minor = int(parts[1])
        patch = int(parts[2]) if len(parts) > 2 else 0
        
        # Determine MC version from NeoForge version
        # NeoForge 20.x.x -> MC 1.20.x
        # NeoForge 21.x.x -> MC 1.21.x
        mc_major = f"1.{major}"
        mc_minor = minor
        mc_version = f"{mc_major}.{mc_minor}" if mc_minor > 0 else mc_major
        
        return {
            'version': version_str,
            'clean_version': clean_version,
            'is_beta': is_beta,
            'major': major,
            'minor': minor,
            'patch': patch,
            'mc_version': mc_version,
            'sort_key': (major, minor, patch, 0 if is_beta else 1)
        }
    except ValueError:
        return None


def filter_versions(versions, stable_only=True, include_beta=False):
    """
    Filter and sort versions
    
    Args:
        versions: List of version strings
        stable_only: Only include stable releases
        include_beta: Include beta versions
    
    Returns:
        List of parsed version dicts, sorted newest first
    """
    parsed = []
    
    for v in versions:
        info = parse_version(v)
        if info is None:
            continue
        
        if stable_only and info['is_beta'] and not include_beta:
            continue
        
        parsed.append(info)
    
    # Sort by version (newest first)
    parsed.sort(key=lambda x: x['sort_key'], reverse=True)
    return parsed


def get_latest_per_mc_version(versions):
    """
    Get the latest stable version for each MC version
    
    Args:
        versions: List of parsed version dicts
    
    Returns:
        List of latest versions per MC version
    """
    latest = {}
    
    for v in versions:
        mc = v['mc_version']
        if mc not in latest:
            latest[mc] = v
        elif not v['is_beta'] and latest[mc]['is_beta']:
            # Prefer stable over beta
            latest[mc] = v
    
    result = list(latest.values())
    result.sort(key=lambda x: x['sort_key'], reverse=True)
    return result


def get_download_url(version):
    """Get the download URL for a specific NeoForge version"""
    filename = f"neoforge-{version}-installer.jar"
    url = f"{NEOFORGE_MAVEN_BASE}/{version}/{filename}"
    return url, filename


def verify_url(url):
    """Verify that a URL exists and get its size"""
    try:
        response = requests.head(url, timeout=10, allow_redirects=True)
        if response.status_code == 200:
            size = int(response.headers.get('content-length', 0))
            return True, size
        return False, 0
    except requests.exceptions.RequestException:
        return False, 0


def get_server_info(versions, limit=None, quiet=False, verify=False):
    """
    Get server download info for all versions
    
    Args:
        versions: List of parsed version dicts
        limit: Maximum number of versions to process (None for all)
        quiet: Suppress progress output
        verify: Verify URLs exist (slower)
    
    Returns:
        List of dicts with download info
    """
    server_info = []
    
    if limit:
        versions = versions[:limit]
    
    total = len(versions)
    
    if not quiet:
        print(f"\n🔍 Processing {total} versions...")
        print("-" * 60)
    
    for i, version in enumerate(versions):
        v = version['version']
        mc = version['mc_version']
        is_beta = version['is_beta']
        
        if not quiet:
            type_badge = "🔧" if is_beta else "⭐"
            print(f"  [{i + 1}/{total}] {type_badge} NeoForge {v} (MC {mc})...", end=" ", flush=True)
        
        url, filename = get_download_url(v)
        
        if verify:
            exists, size = verify_url(url)
            if not exists:
                if not quiet:
                    print("❌ Not found")
                continue
            if not quiet:
                print(f"✅ ({format_bytes(size)})")
        else:
            if not quiet:
                print("✅")
        
        server_info.append({
            'version': v,
            'mc_version': mc,
            'is_beta': is_beta,
            'url': url,
            'filename': filename
        })
        
        # Small delay to be nice to the server
        if verify:
            time.sleep(0.1)
    
    if not quiet:
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   ✅ Found NeoForge installers: {len(server_info)}")
    
    return server_info


def format_output(server_info):
    """Format the server info in the required format"""
    output_lines = []
    for item in server_info:
        beta_marker = " [beta]" if item['is_beta'] else ""
        output_lines.append(f"neoforge:{item['version']}={item['url']}{beta_marker}")
    return output_lines


def download_jar(version, url, filename, skip_existing=True):
    """
    Download a single JAR file
    
    Args:
        version: NeoForge version string
        url: Download URL
        filename: Original filename
        skip_existing: Skip if file already exists
    
    Returns:
        Tuple: (success: bool, message: str, size: int)
    """
    # Ensure directory exists
    SERVER_EXECUTABLES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use a consistent naming format
    local_filename = f"neoforge-{version}-installer.jar"
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


def bulk_download(server_info, skip_existing=True):
    """
    Download multiple JAR files
    
    Args:
        server_info: List of dicts with version, url keys
        skip_existing: Skip files that already exist
    """
    total = len(server_info)
    downloaded = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    
    print(f"\n📥 Downloading {total} NeoForge installer JARs to:")
    print(f"   {SERVER_EXECUTABLES_DIR}")
    print("-" * 60)
    
    for i, item in enumerate(server_info):
        version = item['version']
        url = item['url']
        filename = item['filename']
        
        print(f"  [{i + 1}/{total}] neoforge-{version}-installer.jar...", end=" ", flush=True)
        
        success, message, size = download_jar(version, url, filename, skip_existing)
        
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
    print(f"\n💡 To install a server, run:")
    print(f"   java -jar neoforge-<VERSION>-installer.jar --installServer")


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
    
    files = list(SERVER_EXECUTABLES_DIR.glob("neoforge-*-installer.jar"))
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


def download_single_version(version, force=False):
    """Download a specific NeoForge version"""
    print(f"\n🔍 Preparing to download NeoForge {version}...")
    
    url, filename = get_download_url(version)
    
    # Verify URL exists
    exists, size = verify_url(url)
    if not exists:
        print(f"❌ Version {version} not found or installer doesn't exist")
        return False
    
    print(f"✅ Found: {filename} ({format_bytes(size)})")
    print(f"\n📥 Downloading...")
    
    success, message, downloaded_size = download_jar(
        version, url, filename,
        skip_existing=not force
    )
    
    if success:
        if message == "Already exists":
            print(f"⏭️ {message} ({format_bytes(downloaded_size)})")
        else:
            print(f"✅ {message} ({format_bytes(downloaded_size)})")
        print(f"\n📁 File saved to: {SERVER_EXECUTABLES_DIR / filename}")
        print(f"\n💡 To install the server, run:")
        print(f"   java -jar {filename} --installServer")
        return True
    else:
        print(f"❌ {message}")
        return False


def print_usage():
    """Print usage information"""
    print("""
Usage: python get_neoforge_jars.py [mode] [options]

Modes:
  --list              List all available NeoForge versions (default)
  --download          Download ALL NeoForge installer JARs
  --download-latest=N Download only the latest N versions
  --version=X         Download a specific version (e.g., --version=21.4.156)
  --list-downloaded   Show already downloaded files

Options:
  --stable-only       Only include stable versions (default, excludes beta)
  --include-beta      Include beta versions in listing/download
  --latest-per-mc     Show only the latest stable version per MC version
  --verify            Verify URLs exist before listing (slower)
  --force             Re-download even if file exists
  --quiet, -q         Suppress progress output during processing

Examples:
  python get_neoforge_jars.py --list
  python get_neoforge_jars.py --list --include-beta
  python get_neoforge_jars.py --list --latest-per-mc
  python get_neoforge_jars.py --download-latest=10
  python get_neoforge_jars.py --version=21.4.156
  python get_neoforge_jars.py --download --include-beta --force
  python get_neoforge_jars.py --list-downloaded

NeoForge Version Mapping:
  20.x.y -> Minecraft 1.20.x
  21.x.y -> Minecraft 1.21.x
  etc.

Note: NeoForge provides installer JARs. After downloading, run:
      java -jar neoforge-<VERSION>-installer.jar --installServer
""")


def main():
    print("=" * 60)
    print("🔶 NeoForge Server JAR Fetcher & Downloader")
    print("=" * 60)
    
    # Parse arguments
    args = sys.argv[1:]
    
    mode = 'list'  # default
    limit = None
    specific_version = None
    force_download = '--force' in args
    quiet = '--quiet' in args or '-q' in args
    include_beta = '--include-beta' in args
    stable_only = '--stable-only' in args or not include_beta
    latest_per_mc = '--latest-per-mc' in args
    verify = '--verify' in args
    
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
        list_downloaded()
        return
    
    if mode == 'single':
        if not specific_version:
            print("❌ No version specified. Use --version=X.X.X")
            return
        download_single_version(specific_version, force=force_download)
        return
    
    # Fetch versions for list or download modes
    raw_versions = fetch_neoforge_versions()
    if not raw_versions:
        print("\n❌ Could not fetch NeoForge versions. Exiting.")
        return
    
    # Filter and parse versions
    versions = filter_versions(raw_versions, stable_only=stable_only, include_beta=include_beta)
    
    if not versions:
        print("\n❌ No valid NeoForge versions found.")
        return
    
    print(f"✅ Found {len(versions)} NeoForge versions")
    
    # Get latest per MC version if requested
    if latest_per_mc:
        versions = get_latest_per_mc_version(versions)
        print(f"   (Filtered to {len(versions)} - latest per MC version)")
    
    if versions:
        print(f"   Latest: {versions[0]['version']} (MC {versions[0]['mc_version']})")
        print(f"   Oldest: {versions[-1]['version']} (MC {versions[-1]['mc_version']})")
    
    # Get server info
    server_info = get_server_info(
        versions, 
        limit=limit,
        quiet=quiet,
        verify=verify
    )
    
    if not server_info:
        print("\n❌ No NeoForge installer JARs found.")
        return
    
    if mode == 'list':
        # Format and display output
        print("\n" + "=" * 60)
        print("📋 NEOFORGE INSTALLER JARS (neoforge:<version>=URL)")
        print("=" * 60 + "\n")
        
        output_lines = format_output(server_info)
        for line in output_lines:
            print(line)
        
        # Save to file
        output_file = BASE_DIR / "neoforge_server_urls.txt"
        with open(output_file, 'w') as f:
            f.write("# NeoForge Server Installer JAR Download URLs\n")
            f.write(f"# Generated from {NEOFORGE_API_URL}\n")
            f.write(f"# Total: {len(output_lines)} versions\n")
            f.write("# Format: neoforge:<version>=URL\n\n")
            for line in output_lines:
                f.write(line + "\n")
        
        print(f"\n💾 Saved to: {output_file}")
        
    elif mode == 'download':
        # Bulk download
        bulk_download(server_info, skip_existing=not force_download)
    
    print("\n✅ Done!")


if __name__ == "__main__":
    print_usage()
    main()
