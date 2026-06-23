# Version File Guide

**File:** `version`
**Location:** Project root directory
**Purpose:** Track application version for auto-update system

---

## Overview

The `version` file in the project root stores the current version of MServer. This file is used by:
- The auto-update system to detect new versions
- The web UI to display current version
- The API endpoints for version information
- The git-release script for automated versioning

---

## File Format

The version file supports two formats:

### Format 1: Key-Value (Recommended)
```
version=3.2.1
```

### Format 2: Plain Version
```
3.2.1
```

Both formats are automatically detected and parsed correctly.

---

## Version Scheme

MServer uses semantic versioning with three components:

```
MAJOR.MINOR.BUILD

Examples:
  3.2.0   - Major 3, Minor 2, Build 0
  3.2.1   - Build increment
  3.3.0   - Minor version increase
  4.0.0   - Major version change
```

### When to Increment

| Component | When to Use | Example |
|-----------|-------------|---------|
| **MAJOR** | Breaking changes, incompatible API changes | 3.2.0 → 4.0.0 |
| **MINOR** | New features, backwards-compatible | 3.2.0 → 3.3.0 |
| **BUILD** | Bug fixes, security patches, small updates | 3.2.0 → 3.2.1 |

---

## How It's Used

### 1. Auto-Update System

When checking for updates:
```python
# Read current version from version file
current_version = read_version_file()  # e.g., "3.2.1"

# Fetch remote version file from GitHub
latest_version = get_remote_version_file()  # e.g., "3.2.2"

# Compare versions
if current_version != latest_version:
    update_available = True
```

### 2. Web UI Display

The Settings → Tools → Auto-Update page shows:
- **Current Version:** Read from local version file
- **Latest Version:** Fetched from GitHub's version file
- **Changelog:** Git commits between versions

### 3. API Endpoints

**GET `/api/system/version`**
```json
{
  "version": "3.2.1",
  "version_source": "file",
  "commit_date": "2026-01-26 10:30:00 +0000",
  "deployment_mode": "master",
  "installed_at": "/opt/mserver"
}
```

**GET `/api/system/updates/check`**
```json
{
  "update_available": true,
  "current_version": "3.2.1",
  "latest_version": "3.2.2",
  "changelog": [
    "abc1234 Fix encryption bug",
    "def5678 Add new feature"
  ]
}
```

### 4. Git Release Script

The `git-release.sh` script automatically:
1. Reads current version from file
2. Suggests next version (increment build)
3. Updates version file with new version
4. Creates git commit and tag
5. Pushes to GitHub

---

## File Lifecycle

### Fresh Installation
```bash
# During installation
cd /opt/mserver
# version file is copied from repository
cat version
# Output: version=3.2.1
```

### During Updates
```bash
# 1. Install script reads current version file
current_version="3.2.1"

# 2. Git pulls new code (includes updated version file)
git pull origin main

# 3. Version file is updated
cat version
# Output: version=3.2.2

# 4. Server detects new version on next API call
```

### Manual Update
```bash
# Edit version file
echo "version=3.3.0" > version

# Restart service
sudo systemctl restart mserver

# Version is now 3.3.0
```

---

## Integration with Install Script

### Fresh Install (`install.sh install`)
```bash
# Copies entire repository including version file
cp -r /path/to/repo/* /opt/mserver/
```

### Full Update (`install.sh update`)
```bash
# Updates application files including version file
git pull origin main
# OR
cp /path/to/repo/version /opt/mserver/
```

### Quick Update (`install.sh quick-update`)
```bash
# Updates application files including version file
cp /path/to/repo/version /opt/mserver/
```

**Important:** The version file is NOT preserved during updates - it's intentionally updated to reflect the new version.

---

## Version Detection Fallback

If the version file is missing or invalid, the system falls back to git:

```python
def get_current_version():
    # Try version file first
    version = read_version_file()
    if version:
        return (version, 'file')

    # Fallback to git
    result = subprocess.run(['git', 'describe', '--tags', '--always'])
    if result.returncode == 0:
        return (result.stdout.strip(), 'git')

    # Last resort
    return ('unknown', 'unknown')
```

The API response includes `version_source` to indicate where the version came from:
- `"file"` - Read from version file (preferred)
- `"git"` - Fallback to git describe
- `"unknown"` - Could not determine version

---

## Troubleshooting

### Version File Missing

**Symptom:** API returns `version_source: "git"` instead of `version_source: "file"`

**Solution:**
```bash
# Create version file
echo "version=3.2.1" > /opt/mserver/version

# Restart service
sudo systemctl restart mserver
```

### Wrong Version Displayed

**Symptom:** Web UI shows old version after update

**Solution:**
```bash
# Check version file
cat /opt/mserver/version

# If incorrect, verify git pulled correctly
cd /opt/mserver
git log -1
git status

# Re-pull if needed
git pull origin main

# Restart service
sudo systemctl restart mserver
```

### Version File Format Error

**Symptom:** API returns `version: "unknown"`

**Solution:**
```bash
# Check file content
cat /opt/mserver/version

# Fix format (should be X.X.X)
echo "version=3.2.1" > /opt/mserver/version

# Restart service
sudo systemctl restart mserver
```

### Auto-Update Not Detecting New Version

**Symptom:** "Check For Updates" says no update available, but GitHub has new version

**Solution:**
```bash
# Check if git can fetch remote
cd /opt/mserver
git fetch origin main

# Check remote version file
git show origin/main:version

# If different from local, update is available
# Click "Check For Updates" again in UI
```

---

## Best Practices

### 1. Always Use git-release.sh

Use the automated release script instead of manually editing:
```bash
./git-release.sh
# Automatically updates version file, commits, tags, and pushes
```

### 2. Keep Version File in Git

The version file should always be tracked by git:
```bash
git add version
git commit -m "Bump version to 3.2.2"
git push origin main
```

### 3. Version Matches Git Tag

Ensure version file matches the git tag:
```bash
# Version file: version=3.2.1
# Git tag: v3.2.1
```

### 4. Test After Version Change

After changing version, test the API:
```bash
curl http://localhost:3000/api/system/version | jq
```

---

## Example Workflow

### Releasing a New Version

```bash
# 1. Make your code changes
git add .
git commit -m "Add new feature"

# 2. Run release script
./git-release.sh
# Prompts for commit message
# Suggests version 3.2.2 (incremented from 3.2.1)
# Updates version file
# Creates tag v3.2.2
# Pushes to GitHub

# 3. GitHub Actions automatically creates release

# 4. Users see update available
# Settings → Tools → Auto-Update shows "3.2.2 available"

# 5. Users click "Install Update"
# System pulls new code including updated version file
# Service restarts with new version
```

---

## API Integration

### JavaScript Example

```javascript
// Get current version
async function getCurrentVersion() {
  const response = await fetch('/api/system/version');
  const data = await response.json();
  return data.version;  // "3.2.1"
}

// Check for updates
async function checkForUpdates() {
  const response = await fetch('/api/system/updates/check');
  const data = await response.json();

  if (data.update_available) {
    console.log(`Update available: ${data.latest_version}`);
    console.log('Changelog:', data.changelog);
  }
}
```

### Python Example

```python
import requests

# Get current version
response = requests.get('http://localhost:3000/api/system/version')
version = response.json()['version']
print(f"Current version: {version}")

# Check for updates
response = requests.get('http://localhost:3000/api/system/updates/check')
data = response.json()

if data['update_available']:
    print(f"Update available: {data['latest_version']}")
    for commit in data['changelog']:
        print(f"  - {commit}")
```

---

## Summary

✅ **Version file location:** Project root (`version`)
✅ **Format:** `version=X.X.X` or `X.X.X`
✅ **Updated during:** Git pulls, quick-updates, releases
✅ **Used by:** Auto-update system, Web UI, API
✅ **Fallback:** Git describe if file missing
✅ **Managed by:** `git-release.sh` script

---

**Always use `git-release.sh` for version management!**
