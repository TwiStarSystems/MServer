# Git Release Script Guide

**Script:** `git-release.sh`
**Version:** 1.0.0
**Purpose:** Automate git commit, versioning, tagging, and pushing

---

## Features

✅ **Smart Version Management**
- Reads version from `version` file
- Auto-increments build number (X.X.X → X.X.X+1)
- Allows custom version input
- Validates version format

✅ **Automated Git Workflow**
- Stage all changes
- Create commit with custom message
- Create annotated git tag
- Push commits and tags to remote

✅ **Safety Features**
- Shows git status before committing
- Review changes before pushing
- Validates version format
- Handles errors gracefully

✅ **Universal Design**
- Works with any git repository
- Supports multiple version file formats
- Colorful, user-friendly output

---

## Quick Start

### 1. Run the Script

```bash
./git-release.sh
```

### 2. Follow the Prompts

The script will guide you through:
1. **Commit Message** - Enter a description of your changes
2. **Version Number** - Accept suggested version or enter custom
3. **Confirmation** - Review and confirm before pushing

### Example Session

```
═══════════════════════════════════════════
  Git Release Automation Script
═══════════════════════════════════════════

ℹ Current git status:
 M version
 M server.py
?? new_feature.py

ℹ Enter commit message:
> Add new auto-update feature

ℹ Current version: 3.2.0
ℹ Suggested version: 3.2.1 (build +1)

Enter new version (press Enter for 3.2.1):

✓ Using suggested version: 3.2.1

═══════════════════════════════════════════
  Review Changes
═══════════════════════════════════════════
Commit message: Add new auto-update feature
Version:        3.2.0 → 3.2.1
Tag:            v3.2.1

Proceed with commit, tag, and push? (Y/n): y

ℹ Updating version file...
✓ Version file updated to 3.2.1
ℹ Staging changes...
✓ All changes staged
ℹ Creating commit...
✓ Commit created
ℹ Creating version tag v3.2.1...
✓ Tag v3.2.1 created
ℹ Pushing commits to origin/main...
✓ Commits pushed successfully
ℹ Pushing tags...
✓ Tag v3.2.1 pushed successfully

═══════════════════════════════════════════
  Release Complete! 🎉
═══════════════════════════════════════════
Version:  v3.2.1
Commit:   Add new auto-update feature
Branch:   main

ℹ Your release is now available on GitHub!
ℹ Check the Actions tab for automated release creation.
```

---

## Versioning Scheme

The script uses semantic versioning with three components:

```
MAJOR.MINOR.BUILD

Examples:
  3.2.0   - Current version
  3.2.1   - Build increment (default)
  3.3.0   - Minor version change
  4.0.0   - Major version change
```

### When to Increment

| Component | When to Use | Example |
|-----------|-------------|---------|
| **MAJOR** | Breaking changes, major features | 3.2.0 → 4.0.0 |
| **MINOR** | New features, enhancements | 3.2.0 → 3.3.0 |
| **BUILD** | Bug fixes, small updates | 3.2.0 → 3.2.1 |

---

## Version File Format

The script supports two version file formats:

### Format 1: Key-Value (Recommended)
```bash
version=3.2.0
```

### Format 2: Plain Version
```bash
3.2.0
```

The script automatically detects and preserves the format.

---

## Using in Other Projects

### Step 1: Copy the Script

```bash
# Copy to your project root
cp git-release.sh /path/to/your/project/
cd /path/to/your/project
chmod +x git-release.sh
```

### Step 2: Create Version File

If you don't have a `version` file, the script will create one automatically:

```bash
# Will be created automatically with version 0.1.0
# Or create it manually:
echo "version=1.0.0" > version
```

### Step 3: (Optional) Customize

Edit the script to change configuration:

```bash
# Line 14-15 in git-release.sh
VERSION_FILE="version"      # Change version file name
DEFAULT_BRANCH="main"       # Change default branch
```

### Step 4: Run

```bash
./git-release.sh
```

---

## Advanced Usage

### Custom Version File Name

Edit the script and change `VERSION_FILE`:

```bash
VERSION_FILE="VERSION.txt"  # or any other name
```

### Different Default Branch

Edit the script and change `DEFAULT_BRANCH`:

```bash
DEFAULT_BRANCH="master"  # or "develop", "production", etc.
```

### Skip Auto-Increment

When prompted, simply type your desired version:

```
Enter new version (press Enter for 3.2.1): 3.3.0
```

### Abort the Process

Press `n` at the confirmation prompt:

```
Proceed with commit, tag, and push? (Y/n): n
⚠ Aborted by user.
```

---

## Integration with GitHub Actions

If you have the GitHub release workflow (`.github/workflows/release.yml`), this script automatically triggers it when pushing a tag.

**Workflow:**
```
1. Run ./git-release.sh
2. Script creates tag (e.g., v3.2.1)
3. Tag is pushed to GitHub
4. GitHub Actions detects tag
5. Automated release is created
6. Users can update via auto-update system
```

---

## Troubleshooting

### Error: "Not a git repository!"

**Solution:** Make sure you're in a git repository:
```bash
git init  # If not initialized
git remote add origin <your-repo-url>
```

### Error: "Invalid version format in version"

**Solution:** Check your version file format:
```bash
cat version
# Should be: version=X.X.X or X.X.X
```

### Error: "Failed to push commits"

**Solution:** Check your git remote and credentials:
```bash
git remote -v
git pull origin main  # Sync first
./git-release.sh
```

### Script Shows "No changes detected"

**Solution:** Either make changes or confirm to continue anyway:
- The script will still create a tag and push
- Useful for creating releases without code changes

### Version Not Incrementing Correctly

**Solution:** The script increments the BUILD number by default:
- 3.2.0 → 3.2.1 (not 3.3.0)
- For minor/major changes, enter manually when prompted

---

## Best Practices

### 1. Commit Message Guidelines

✅ **Good:**
```
Add auto-update system with Master-Slave coordination
Fix encryption key preservation during updates
Update Node Manager UI with health indicators
```

❌ **Bad:**
```
fix
update
changes
```

### 2. Version Selection

- **Build (X.X.+1)**: Bug fixes, documentation, minor tweaks
- **Minor (X.+1.0)**: New features, enhancements
- **Major (+1.0.0)**: Breaking changes, major releases

### 3. Before Running

```bash
# Always check status first
git status

# Run the script
./git-release.sh
```

### 4. Test Before Major Releases

For major releases (X.0.0), consider:
- Creating a release candidate: `3.0.0-rc.1`
- Testing thoroughly
- Then creating the final release: `3.0.0`

---

## Script Configuration

You can customize these variables at the top of the script:

```bash
# Configuration (lines 14-15)
VERSION_FILE="version"      # Name of version file
DEFAULT_BRANCH="main"       # Default git branch

# Colors can be disabled by commenting out color codes
```

---

## Command Flow

The script executes these steps in order:

```
1. Check if in git repository
   ├─> Yes: Continue
   └─> No: Exit with error

2. Check for changes
   ├─> Changes exist: Show status
   └─> No changes: Warn and ask to continue

3. Prompt for commit message
   └─> Validate not empty

4. Read current version from file
   ├─> File exists: Parse version
   └─> No file: Create with 0.1.0

5. Calculate suggested version
   └─> Increment build number

6. Prompt for new version
   ├─> Empty: Use suggested
   └─> Custom: Validate format

7. Show review screen
   └─> Ask for confirmation

8. Update version file
   └─> Preserve format

9. Stage all changes
   └─> git add -A

10. Create commit
    └─> git commit -m "message"

11. Create annotated tag
    └─> git tag -a vX.X.X -m "Release version X.X.X"

12. Push commits
    └─> git push origin main

13. Push tags
    └─> git push origin vX.X.X

14. Show success message
```

---

## Examples

### Example 1: Standard Release (Build Increment)

```bash
./git-release.sh
# Commit: "Fix bug in server startup"
# Version: Accept default (3.2.0 → 3.2.1)
# Result: v3.2.1 pushed and tagged
```

### Example 2: Minor Version Release

```bash
./git-release.sh
# Commit: "Add new backup system"
# Version: Enter 3.3.0
# Result: v3.3.0 pushed and tagged
```

### Example 3: Major Version Release

```bash
./git-release.sh
# Commit: "Complete rewrite with breaking changes"
# Version: Enter 4.0.0
# Result: v4.0.0 pushed and tagged
```

### Example 4: Hotfix Release

```bash
./git-release.sh
# Commit: "Critical security fix"
# Version: Accept default (3.2.5 → 3.2.6)
# Result: v3.2.6 pushed and tagged immediately
```

---

## FAQ

**Q: Can I use this with private repositories?**
A: Yes! Works with any git repository (public or private).

**Q: What if I make a mistake with the version?**
A: Delete the tag and retry:
```bash
git tag -d v3.2.1
git push origin :refs/tags/v3.2.1
./git-release.sh
```

**Q: Can I customize the tag format?**
A: Yes, edit line 184 in the script:
```bash
git tag -a "release-$new_version" -m "Release $new_version"
```

**Q: Does it work with branches other than main?**
A: Yes, change `DEFAULT_BRANCH` variable in the script.

**Q: What if I don't want to create a tag?**
A: You'll need to modify the script to skip the tagging step. Or use regular git commands.

**Q: Can I run this in CI/CD?**
A: Not recommended - it's designed for interactive use. For CI/CD, use standard git commands.

---

## Summary

The `git-release.sh` script provides a streamlined workflow for:
- ✅ Committing changes with meaningful messages
- ✅ Managing semantic versions automatically
- ✅ Creating git tags for releases
- ✅ Pushing to remote with error handling
- ✅ Universal design for any project

**One command to commit, version, tag, and push!**

---

## Support

For issues or questions:
1. Check this guide's troubleshooting section
2. Review the script comments (well-documented)
3. Test in a non-production branch first

---

**Pro Tip:** Add an alias to your `.bashrc` or `.zshrc` for quick access:

```bash
alias release='./git-release.sh'
```

Then just run:
```bash
release
```

---

**Version:** 1.0.0
**Last Updated:** 2026-01-26
**Status:** ✅ Production Ready
