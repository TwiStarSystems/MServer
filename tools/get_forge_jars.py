# Download Forge server installer JARs from Minecraft Forge Maven
"""
This tool fetches and downloads Forge Minecraft server installer JARs.
Forge is a popular modding platform for Minecraft Java Edition.

Modes:
  --list              List all available Forge versions (default)
  --download          Download server JARs to serverexecutables/forge/
  --download-latest=N Download only the latest N versions

Output format: forge:<MC_VERSION>-<FORGE_VERSION>=URL
Downloaded files: serverexecutables/forge/forge-<MC_VERSION>-<FORGE_VERSION>-installer.jar

Note: Forge provides installer JARs. You need to run the installer to create the server.
      java -jar forge-X.X.X-X.X.X-installer.jar --installServer
"""

import requests
import json
import sys
import os
import time
import re
from pathlib import Path

FORGE_PROMOTIONS_URL = "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json"
FORGE_MAVEN_BASE = "https://maven.minecraftforge.net/net/minecraftforge/forge"

# Get the base directory (parent of tools folder)
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
SERVER_EXECUTABLES_DIR = BASE_DIR / 'serverexecutables' / 'forge'


def fetch_forge_versions(quiet=False):
    """Fetch all available Forge versions from the promotions API"""
    if not quiet:
        print("📥 Fetching Forge versions...")
    try:
        response = requests.get(FORGE_PROMOTIONS_URL, timeout=30)
        response.raise_for_status()
        data = response.json()
        promos = data.get('promos', {})
        return promos
    except requests.exceptions.RequestException as e:
        if not quiet:
            print(f"❌ Failed to fetch Forge versions: {e}")
        return None


def parse_versions(promos, recommended_only=False):
    """
    Parse the promotions data into a structured format
    
    Args:
        promos: Dict of "mcversion-type": "forgeversion"
        recommended_only: Only include recommended versions
    
    Returns:
        List of dicts: {'mc_version': str, 'forge_version': str, 'type': str}
    """
    versions = []
    seen = set()
    
    for key, forge_version in promos.items():
        # Parse key like "1.21.4-latest" or "1.21.4-recommended"
        match = re.match(r'^(.+)-(latest|recommended)$', key)
        if not match:
            continue
        
        mc_version = match.group(1)
        version_type = match.group(2)
        
        if recommended_only and version_type != 'recommended':
            continue
        
        # Create unique key for mc_version + forge_version combo
        unique_key = f"{mc_version}-{forge_version}"
        if unique_key in seen:
            continue
        seen.add(unique_key)
        
        versions.append({
            'mc_version': mc_version,
            'forge_version': forge_version,
            'type': version_type,
            'full_version': f"{mc_version}-{forge_version}"
        })
    
    # Sort by MC version (newest first)
    def version_key(v):
        # Parse version string to tuple for proper sorting
        parts = v['mc_version'].split('.')
        try:
            return tuple(int(p) for p in parts)
        except ValueError:
            return (0,)
    
    versions.sort(key=version_key, reverse=True)
    return versions


def get_download_url(mc_version, forge_version):
    """Get the download URL for a specific Forge version"""
    full_version = f"{mc_version}-{forge_version}"
    filename = f"forge-{full_version}-installer.jar"
    url = f"{FORGE_MAVEN_BASE}/{full_version}/{filename}"
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
        versions: List of version dicts
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
        mc_version = version['mc_version']
        forge_version = version['forge_version']
        version_type = version['type']
        
        if not quiet:
            type_badge = "⭐" if version_type == 'recommended' else "🔄"
            print(f"  [{i + 1}/{total}] {type_badge} Forge {mc_version}-{forge_version}...", end=" ", flush=True)
        
        url, filename = get_download_url(mc_version, forge_version)
        
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
            'mc_version': mc_version,
            'forge_version': forge_version,
            'full_version': version['full_version'],
            'type': version_type,
            'url': url,
            'filename': filename
        })
        
        # Small delay to be nice to the server
        if verify:
            time.sleep(0.1)
    
    if not quiet:
        print("-" * 60)
        print(f"\n📊 Summary:")
        print(f"   ✅ Found Forge installers: {len(server_info)}")
    
    return server_info


def format_output(server_info):
    """Format the server info in the required format"""
    output_lines = []
    for item in server_info:
        type_marker = " [recommended]" if item['type'] == 'recommended' else ""
        output_lines.append(f"forge:{item['full_version']}={item['url']}{type_marker}")
    return output_lines


def download_jar(mc_version, forge_version, url, filename, skip_existing=True):
    """
    Download a single JAR file
    
    Args:
        mc_version: Minecraft version string
        forge_version: Forge version string
        url: Download URL
        filename: Original filename
        skip_existing: Skip if file already exists
    
    Returns:
        Tuple: (success: bool, message: str, size: int)
    """
    # Ensure directory exists
    SERVER_EXECUTABLES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use a consistent naming format
    local_filename = f"forge-{mc_version}-{forge_version}-installer.jar"
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
        server_info: List of dicts with version info
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
        print(f"\n📥 Downloading {total} Forge installer JARs to:")
        print(f"   {SERVER_EXECUTABLES_DIR}")
        print("-" * 60)

    for i, item in enumerate(server_info):
        mc_version = item['mc_version']
        forge_version = item['forge_version']
        url = item['url']
        filename = item['filename']

        if not json_output:
            type_badge = "⭐" if item['type'] == 'recommended' else "🔄"
            print(f"  [{i + 1}/{total}] {type_badge} forge-{mc_version}-{forge_version}-installer.jar...", end=" ", flush=True)

        success, message, size = download_jar(mc_version, forge_version, url, filename, skip_existing)

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
            "mc_version": mc_version,
            "forge_version": forge_version,
            "success": success,
            "message": message,
            "size": size
        })

        # Small delay between downloads
        if success and message != "Already exists":
            time.sleep(0.3)

    if not json_output:
        print("-" * 60)
        print(f"\n📊 Download Summary:")
        print(f"   ✅ Downloaded: {downloaded} ({format_bytes(total_bytes)})")
        print(f"   ⏭️ Skipped (existing): {skipped}")
        print(f"   ❌ Failed: {failed}")
        print(f"\n📁 Files saved to: {SERVER_EXECUTABLES_DIR}")
        print(f"\n💡 To install a Forge server, run:")
        print(f"   java -jar forge-X.X.X-X.X.X-installer.jar --installServer")

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

    files = list(SERVER_EXECUTABLES_DIR.glob("forge-*-installer.jar"))
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

    files = list(SERVER_EXECUTABLES_DIR.glob("forge-*-installer.jar"))
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


def download_single_version(mc_version, forge_version=None, force=False, json_output=False):
    """Download a specific Forge version"""
    if forge_version:
        if not json_output:
            print(f"\n🔍 Downloading Forge {mc_version}-{forge_version}...")
    else:
        if not json_output:
            print(f"\n🔍 Fetching latest Forge for MC {mc_version}...")

        # Fetch versions to find the forge version
        promos = fetch_forge_versions(quiet=json_output)
        if not promos:
            if not json_output:
                print("❌ Could not fetch Forge versions")
            if json_output:
                return {"success": False, "error": "Could not fetch Forge versions"}
            return False

        # Try recommended first, then latest
        forge_version = promos.get(f"{mc_version}-recommended")
        if not forge_version:
            forge_version = promos.get(f"{mc_version}-latest")

        if not forge_version:
            if not json_output:
                print(f"❌ No Forge version found for MC {mc_version}")
            if json_output:
                return {"success": False, "error": f"No Forge version found for MC {mc_version}"}
            return False

        if not json_output:
            print(f"✅ Found Forge {forge_version}")

    url, filename = get_download_url(mc_version, forge_version)

    if not json_output:
        print(f"\n📥 Downloading forge-{mc_version}-{forge_version}-installer.jar...")

    success, message, size = download_jar(
        mc_version, forge_version, url, filename,
        skip_existing=not force
    )

    if success:
        if not json_output:
            if message == "Already exists":
                print(f"⏭️ {message} ({format_bytes(size)})")
            else:
                print(f"✅ {message} ({format_bytes(size)})")
            print(f"\n📁 File saved to: {SERVER_EXECUTABLES_DIR / f'forge-{mc_version}-{forge_version}-installer.jar'}")
            print(f"\n💡 To install the server, run:")
            print(f"   java -jar forge-{mc_version}-{forge_version}-installer.jar --installServer")
        if json_output:
            return {
                "success": True,
                "mode": "single",
                "mc_version": mc_version,
                "forge_version": forge_version,
                "message": message,
                "size": size,
                "path": str(SERVER_EXECUTABLES_DIR / f'forge-{mc_version}-{forge_version}-installer.jar')
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
Usage: python get_forge_jars.py [mode] [options]

Modes:
  --list              List all available Forge versions (default)
  --download          Download ALL Forge installer JARs
  --download-latest=N Download only the latest N versions
  --version=X.X.X     Download Forge for a specific MC version (e.g., --version=1.21.4)
  --list-downloaded   Show already downloaded files

Options:
  --recommended       Only show/download recommended (stable) versions
  --force             Re-download even if file exists
  --quiet, -q         Suppress progress output during URL fetching
  --verify            Verify URLs exist before listing (slower)
  --json              Output results as JSON (for programmatic use)

Examples:
  python get_forge_jars.py --list
  python get_forge_jars.py --list --recommended
  python get_forge_jars.py --download-latest=10
  python get_forge_jars.py --version=1.21.4
  python get_forge_jars.py --download --recommended
  python get_forge_jars.py --list-downloaded
  python get_forge_jars.py --list --json

Note: Forge provides installer JARs. After downloading, run:
      java -jar forge-X.X.X-X.X.X-installer.jar --installServer

Legend: ⭐ = Recommended (stable), 🔄 = Latest (may be unstable)
""")


def main():
    # Parse arguments
    args = sys.argv[1:]

    # Check for JSON output mode first
    json_output = '--json' in args

    if not json_output:
        print("=" * 60)
        print("🔧 Forge Server JAR Fetcher & Downloader")
        print("=" * 60)

    mode = 'list'  # default
    limit = None
    specific_version = None
    force_download = '--force' in args
    quiet = '--quiet' in args or '-q' in args or json_output
    recommended_only = '--recommended' in args
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
    promos = fetch_forge_versions(quiet=json_output)
    if not promos:
        if json_output:
            print(json.dumps({"success": False, "error": "Could not fetch Forge versions"}))
        else:
            print("\n❌ Could not fetch Forge versions. Exiting.")
        return

    # Parse into structured format
    versions = parse_versions(promos, recommended_only=recommended_only)

    if not versions:
        if json_output:
            print(json.dumps({"success": False, "error": "No Forge versions found"}))
        else:
            print("\n❌ No Forge versions found.")
        return

    if not json_output:
        print(f"✅ Found {len(versions)} Forge versions")
        if recommended_only:
            print("   (showing recommended versions only)")
        print(f"   Latest: MC {versions[0]['mc_version']} with Forge {versions[0]['forge_version']}")

    # Get server info
    server_info = get_server_info(
        versions,
        limit=limit,
        quiet=quiet,
        verify=verify
    )

    if not server_info:
        if json_output:
            print(json.dumps({"success": False, "error": "No Forge installers found"}))
        else:
            print("\n❌ No Forge installers found.")
        return

    if mode == 'list':
        if json_output:
            # JSON output format
            result = {
                "success": True,
                "mode": "list",
                "count": len(server_info),
                "versions": [{
                    "mc_version": item['mc_version'],
                    "forge_version": item['forge_version'],
                    "type": item['type'],
                    "url": item['url']
                } for item in server_info]
            }
            print(json.dumps(result))
        else:
            # Format and display output
            print("\n" + "=" * 60)
            print("📋 FORGE INSTALLER JARS (forge:<mc>-<forge>=URL)")
            print("=" * 60 + "\n")

            output_lines = format_output(server_info)
            for line in output_lines:
                print(line)

            # Save to file
            output_file = BASE_DIR / "forge_server_urls.txt"
            with open(output_file, 'w') as f:
                f.write("# Forge Server Installer JAR URLs\n")
                f.write(f"# Generated from {FORGE_PROMOTIONS_URL}\n")
                f.write(f"# Total: {len(output_lines)} versions\n")
                f.write("# Format: forge:<mc_version>-<forge_version>=URL\n")
                f.write("# Note: Run installer with: java -jar <file> --installServer\n\n")
                for line in output_lines:
                    f.write(line + "\n")

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
