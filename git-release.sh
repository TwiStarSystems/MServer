#!/bin/bash

# Universal Git Release Script
# Automates git commit, versioning, tagging, and pushing
# Version: 1.0.0

set -e  # Exit on error

# Color codes for pretty output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
VERSION_FILE="version"
DEFAULT_BRANCH="main"

# Function to print colored messages
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_header() {
    echo ""
    echo -e "${CYAN}═══════════════════════════════════════════${NC}"
    echo -e "${CYAN}  $1${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════${NC}"
    echo ""
}

# Check if we're in a git repository
check_git_repo() {
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        print_error "Not a git repository!"
        exit 1
    fi
}

# Check if there are changes to commit
check_changes() {
    if ! git diff-index --quiet HEAD --; then
        return 0  # Changes exist
    elif [ -n "$(git ls-files --others --exclude-standard)" ]; then
        return 0  # Untracked files exist
    else
        return 1  # No changes
    fi
}

# Read current version from version file
read_version() {
    if [ ! -f "$VERSION_FILE" ]; then
        print_warning "Version file not found. Creating default version file..."
        echo "version=0.1.0" > "$VERSION_FILE"
        print_success "Created $VERSION_FILE with version 0.1.0"
        echo "0.1.0"
        return
    fi

    # Try to read version from file (supports both "version=X.X.X" and "X.X.X" formats)
    local version_content=$(cat "$VERSION_FILE")

    # Check if format is "version=X.X.X"
    if [[ $version_content =~ version=([0-9]+\.[0-9]+\.[0-9]+) ]]; then
        echo "${BASH_REMATCH[1]}"
    # Check if format is just "X.X.X"
    elif [[ $version_content =~ ^([0-9]+\.[0-9]+\.[0-9]+) ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        print_error "Invalid version format in $VERSION_FILE"
        echo "Expected format: X.X.X (e.g., 3.2.0) or version=X.X.X"
        exit 1
    fi
}

# Parse version components
parse_version() {
    local version=$1
    IFS='.' read -r MAJOR MINOR BUILD <<< "$version"

    if [ -z "$MAJOR" ] || [ -z "$MINOR" ] || [ -z "$BUILD" ]; then
        print_error "Invalid version format: $version"
        exit 1
    fi
}

# Increment build number
increment_build() {
    local version=$1
    parse_version "$version"
    echo "$MAJOR.$MINOR.$((BUILD + 1))"
}

# Write version to file
write_version() {
    local new_version=$1
    local version_content=$(cat "$VERSION_FILE")

    # Preserve the format (version=X.X.X or just X.X.X)
    if [[ $version_content =~ version= ]]; then
        echo "version=$new_version" > "$VERSION_FILE"
    else
        echo "$new_version" > "$VERSION_FILE"
    fi
}

# Main script
main() {
    print_header "Git Release Automation Script"

    # Check if we're in a git repo
    check_git_repo

    # Check for uncommitted changes
    if ! check_changes; then
        print_warning "No changes detected in the repository."
        read -p "Do you want to continue anyway? (y/N): " continue_choice
        if [[ ! $continue_choice =~ ^[Yy]$ ]]; then
            print_info "Aborted by user."
            exit 0
        fi
    fi

    # Show git status
    print_info "Current git status:"
    git status --short
    echo ""

    # Get commit message
    print_info "Enter commit message:"
    read -p "> " commit_message

    if [ -z "$commit_message" ]; then
        print_error "Commit message cannot be empty!"
        exit 1
    fi

    # Read current version
    current_version=$(read_version)
    suggested_version=$(increment_build "$current_version")

    echo ""
    print_info "Current version: ${GREEN}$current_version${NC}"
    print_info "Suggested version: ${CYAN}$suggested_version${NC} (build +1)"
    echo ""

    # Get new version
    read -p "Enter new version (press Enter for $suggested_version): " new_version

    # Use suggested version if empty
    if [ -z "$new_version" ]; then
        new_version=$suggested_version
        print_success "Using suggested version: $new_version"
    else
        # Validate version format
        if ! [[ $new_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            print_error "Invalid version format!"
            echo "Expected format: MAJOR.MINOR.BUILD (e.g., 3.2.1)"
            exit 1
        fi
        print_success "Using custom version: $new_version"
    fi

    echo ""
    print_header "Review Changes"
    echo "Commit message: ${CYAN}$commit_message${NC}"
    echo "Version:        ${GREEN}$current_version${NC} → ${GREEN}$new_version${NC}"
    echo "Tag:            ${YELLOW}v$new_version${NC}"
    echo ""

    read -p "Proceed with commit, tag, and push? (Y/n): " confirm
    if [[ $confirm =~ ^[Nn]$ ]]; then
        print_warning "Aborted by user."
        exit 0
    fi

    # Update version file
    print_info "Updating version file..."
    write_version "$new_version"
    print_success "Version file updated to $new_version"

    # Stage all changes
    print_info "Staging changes..."
    git add -A
    print_success "All changes staged"

    # Commit changes
    print_info "Creating commit..."
    git commit -m "$commit_message"
    print_success "Commit created"

    # Create tag
    print_info "Creating version tag v$new_version..."
    git tag -a "v$new_version" -m "Release version $new_version"
    print_success "Tag v$new_version created"

    # Push commits
    print_info "Pushing commits to origin/$DEFAULT_BRANCH..."
    if git push origin "$DEFAULT_BRANCH"; then
        print_success "Commits pushed successfully"
    else
        print_error "Failed to push commits"
        print_warning "Tag v$new_version not pushed yet"
        exit 1
    fi

    # Push tags
    print_info "Pushing tags..."
    if git push origin "v$new_version"; then
        print_success "Tag v$new_version pushed successfully"
    else
        print_error "Failed to push tag"
        exit 1
    fi

    echo ""
    print_header "Release Complete! 🎉"
    echo "Version:  ${GREEN}v$new_version${NC}"
    echo "Commit:   ${CYAN}$commit_message${NC}"
    echo "Branch:   ${BLUE}$DEFAULT_BRANCH${NC}"
    echo ""
    print_info "Your release is now available on GitHub!"
    print_info "Check the Actions tab for automated release creation."
    echo ""
}

# Run main function
main
