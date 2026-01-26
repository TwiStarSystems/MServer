# Release Versioning Guide

**Last Updated:** 2026-01-26
**Status:** ✅ Production Ready

---

## Overview

MServerController uses automated GitHub releases to track versions and provide users with update notifications. When you push a version tag, GitHub Actions automatically creates a release with changelog and installation instructions.

---

## Table of Contents

1. [Version Numbering Scheme](#version-numbering-scheme)
2. [Creating a Release](#creating-a-release)
3. [Automatic Release Workflow](#automatic-release-workflow)
4. [Manual Release Creation](#manual-release-creation)
5. [Best Practices](#best-practices)
6. [Troubleshooting](#troubleshooting)

---

## Version Numbering Scheme

MServerController follows **Semantic Versioning** (SemVer):

```
vMAJOR.MINOR.PATCH

Examples:
  v3.1.0    - Major version 3, minor version 1, patch 0
  v3.1.1    - Bug fix release
  v3.2.0    - New features added
  v4.0.0    - Breaking changes
```

### Version Components

| Component | When to Increment | Example |
|-----------|-------------------|---------|
| **MAJOR** | Breaking changes, incompatible API changes | v3.x.x → v4.0.0 |
| **MINOR** | New features, backwards-compatible | v3.1.x → v3.2.0 |
| **PATCH** | Bug fixes, security patches | v3.1.0 → v3.1.1 |

### Version Format

- **Production releases**: `v3.1.0`, `v3.2.0`
- **Pre-releases** (optional): `v3.2.0-beta.1`, `v3.2.0-rc.1`

---

## Creating a Release

### Step 1: Prepare Your Changes

Ensure all changes are committed and pushed to the `main` branch:

```bash
git add .
git commit -m "Prepare for v3.2.0 release"
git push origin main
```

### Step 2: Create and Push a Version Tag

```bash
# Create a tag with version number
git tag -a v3.2.0 -m "Release version 3.2.0"

# Push the tag to GitHub
git push origin v3.2.0
```

**That's it!** The GitHub Actions workflow will automatically:
- Create a GitHub release
- Generate a changelog from commits
- Include installation instructions
- Make it available to users

### Step 3: Verify Release

1. Go to your repository on GitHub
2. Click on **"Releases"** (right sidebar)
3. You should see your new release with:
   - Version number
   - Auto-generated changelog
   - Installation instructions
   - Download links

---

## Automatic Release Workflow

### Workflow File Location

```
.github/workflows/release.yml
```

### Trigger Conditions

The workflow automatically runs when:
1. **Tag Push**: You push a tag matching `v*` pattern (e.g., `v3.2.0`)
2. **Manual Trigger**: You manually trigger from GitHub Actions tab

### What the Workflow Does

```
1. Checkout Code
   └─> Fetches all history for changelog

2. Extract Version Info
   └─> Parses tag name (v3.2.0 → 3.2.0)

3. Generate Changelog
   └─> Lists commits since previous release

4. Create Release Notes
   └─> Formats changelog with installation instructions

5. Create GitHub Release
   └─> Publishes release with notes

6. Output Summary
   └─> Displays release URL and stats
```

### Example Workflow Output

```
✅ Release created successfully!
📦 Version: v3.2.0
📝 Commits: 15
🔗 https://github.com/TwiStarSystems/MServerController/releases/tag/v3.2.0
```

---

## Manual Release Creation

### Using GitHub Actions UI

If you need to create a release without pushing a tag:

1. Go to **Actions** tab in your GitHub repository
2. Click **"Create Release"** workflow
3. Click **"Run workflow"**
4. Enter the tag name (e.g., `v3.2.0`)
5. Click **"Run workflow"** button

### Using GitHub CLI

```bash
# Create release with gh CLI
gh release create v3.2.0 \
  --title "Release v3.2.0" \
  --notes "Release notes here"
```

---

## Best Practices

### 1. Version Tag Format

✅ **Good:**
```bash
git tag -a v3.2.0 -m "Release version 3.2.0"
git tag -a v3.2.1 -m "Bug fix: Fix encryption key handling"
```

❌ **Bad:**
```bash
git tag v3.2.0              # Missing annotation (-a flag)
git tag 3.2.0               # Missing 'v' prefix
git tag release-3.2.0       # Wrong format
```

### 2. Commit Messages

Write clear commit messages that will appear in changelogs:

✅ **Good:**
```
Add auto-update system with Master-Slave coordination
Fix orphaned state reconnection timeout
Update Node Manager UI with health indicators
```

❌ **Bad:**
```
fix
update stuff
changes
```

### 3. Pre-Release Testing

Before tagging a release:

```bash
# 1. Test on development system
sudo ./install.sh quick-update --non-interactive

# 2. Verify Master node
systemctl status mservercontroller

# 3. Test Slave node
# (on slave machine)
sudo ./install.sh quick-update --non-interactive

# 4. Check node connectivity
curl http://master-ip/api/clients
```

### 4. Release Cadence

| Release Type | Frequency | Example |
|--------------|-----------|---------|
| **Major** | 6-12 months | v4.0.0 |
| **Minor** | 1-3 months | v3.2.0 |
| **Patch** | As needed | v3.2.1 |

### 5. Changelog Quality

Include meaningful information:

```markdown
## v3.2.0

### New Features
- Auto-update system with web UI
- Master-Slave update coordination
- Version checking from GitHub

### Improvements
- Faster startup time
- Better error messages
- Enhanced logging

### Bug Fixes
- Fixed encryption key preservation during update
- Resolved orphaned state timeout issue
- Corrected Node Manager health scoring
```

---

## Release Workflow Details

### Generated Release Notes Format

The workflow automatically creates release notes with:

```markdown
# MServerController {version}

## 🚀 What's New
[Commit count and summary]

## 📝 Changelog
[List of commits with hashes]

## 📦 Installation
[Installation instructions for Master and Slave]

## 🔒 Security Notes
[Security considerations]

## 📚 Documentation
[Links to guides]

## ⚙️ System Requirements
[Requirements list]

---
Full Changelog: [link to compare]
```

### Permissions Required

The workflow requires `contents: write` permission to create releases. This is automatically granted by GitHub for repository workflows.

---

## Troubleshooting

### Release Not Created

**Problem:** Pushed tag but no release appeared

**Solutions:**
```bash
# 1. Check workflow status
# Go to GitHub Actions tab and check for errors

# 2. Verify tag format
git tag -l "v*"

# 3. Ensure workflow file exists
ls .github/workflows/release.yml

# 4. Check workflow syntax
# GitHub validates YAML automatically
```

### Wrong Version Number

**Problem:** Tagged with wrong version

**Solutions:**
```bash
# 1. Delete tag locally
git tag -d v3.2.0

# 2. Delete tag on GitHub
git push origin :refs/tags/v3.2.0

# 3. Create correct tag
git tag -a v3.2.1 -m "Release version 3.2.1"
git push origin v3.2.1
```

### Changelog Missing Commits

**Problem:** Some commits not in changelog

**Solutions:**
- Ensure commits are between previous tag and new tag
- Check if commits are merge commits (excluded by default)
- Verify git history: `git log prev-tag..new-tag`

### Auto-Update Not Finding Release

**Problem:** Update checker doesn't see new release

**Solutions:**
```bash
# 1. Ensure tag is on main branch
git branch --contains v3.2.0

# 2. Verify release is published (not draft)
gh release list

# 3. Check git remote
git remote -v
cd /opt/mservercontroller
git fetch origin main
```

---

## Integration with Auto-Update System

### How Users Get Updates

1. **User clicks "Check For Updates"** in web UI
2. **System fetches latest tag** from GitHub
3. **Compares with current version**
4. **Shows changelog** if update available
5. **User clicks "Install Update"**
6. **System runs quick-update**
7. **Auto-reconnects** after restart

### Version Detection

The auto-update system detects versions using:

```bash
# Current version
git describe --tags --always --abbrev=7

# Latest version
git rev-parse origin/main
```

### Update Flow

```
User: Check For Updates
  ↓
API: /api/system/updates/check
  ↓
Git: fetch origin main
  ↓
Compare: current_commit vs latest_commit
  ↓
Show: Changelog from releases
  ↓
User: Install Update
  ↓
API: /api/system/updates/install
  ↓
Master: Notify all Slaves
  ↓
All: sudo ./install.sh quick-update --non-interactive
  ↓
All: Restart service
  ↓
All: Auto-reconnect
  ↓
✅ Updated!
```

---

## Example: Complete Release Process

### Scenario: Releasing v3.2.0

```bash
# 1. Ensure all changes are committed
git status
git add .
git commit -m "Add auto-update system and Node Manager improvements"
git push origin main

# 2. Update documentation (if needed)
vim docs/DEVELOPMENT_GUIDE.md
# Update version number and last updated date
git add docs/DEVELOPMENT_GUIDE.md
git commit -m "Update documentation for v3.2.0"
git push origin main

# 3. Create and push version tag
git tag -a v3.2.0 -m "Release v3.2.0 - Auto-update system and improvements"
git push origin v3.2.0

# 4. Wait 30-60 seconds for workflow to complete

# 5. Verify release on GitHub
gh release view v3.2.0

# 6. Test auto-update on development system
# Go to Settings → Tools → Auto-Update
# Click "Check For Updates"
# Should show v3.2.0 available

# 7. Announce release (optional)
# - Update Discord/Slack
# - Send email to users
# - Update project website
```

### Expected Timeline

- **Tag Push**: Instant
- **Workflow Start**: 10-30 seconds
- **Workflow Complete**: 30-60 seconds
- **Release Available**: Immediately after workflow
- **Auto-Update Detection**: Next check (user-initiated)

---

## Quick Reference

### Create Release
```bash
git tag -a v3.2.0 -m "Release v3.2.0"
git push origin v3.2.0
```

### Delete Release
```bash
# Delete local tag
git tag -d v3.2.0

# Delete remote tag
git push origin :refs/tags/v3.2.0

# Delete GitHub release
gh release delete v3.2.0
```

### View Releases
```bash
# List all releases
gh release list

# View specific release
gh release view v3.2.0

# List all tags
git tag -l "v*"
```

### Test Version Detection
```bash
# Get current version
git describe --tags --always --abbrev=7

# Get latest remote version
git fetch origin main
git describe --tags --always --abbrev=7 origin/main
```

---

## Support

For issues with the release workflow:

1. Check [GitHub Actions documentation](https://docs.github.com/en/actions)
2. Review workflow logs in Actions tab
3. Check repository Issues for known problems
4. Verify permissions in repository settings

---

## Summary

✅ **Automated release creation** via GitHub Actions
✅ **Semantic versioning** for clear version tracking
✅ **Auto-generated changelogs** from git commits
✅ **Integration with auto-update system**
✅ **Manual and automatic trigger options**
✅ **Complete installation instructions** in every release

---

**The release system is fully integrated with the auto-update system, allowing users to update with one click!**
