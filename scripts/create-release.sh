#!/bin/bash
# Script to create a new release

set -e

# Check for help or non-interactive mode
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Usage: $0 [--non-interactive|-n VERSION]"
    echo ""
    echo "Create a new release by bumping the version in pyproject.toml"
    echo "and creating a git tag."
    echo ""
    echo "Options:"
    echo "  --non-interactive, -n VERSION  Use provided version without prompting"
    echo "  --help, -h                   Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                           # Interactive mode"
    echo "  $0 --non-interactive 1.2.3   # Non-interactive mode"
    exit 0
fi

NON_INTERACTIVE=false
if [ "$1" = "--non-interactive" ] || [ "$1" = "-n" ]; then
    NON_INTERACTIVE=true
    NEW_VERSION="$2"
fi

# Check if we're in a git repository
if ! git rev-parse --git-dir > /dev/null 2>&1; then
    echo "❌ Not in a git repository"
    exit 1
fi

# Check if we're on main branch
current_branch=$(git branch --show-current)
if [ "$current_branch" != "main" ]; then
    echo "❌ Not on main branch (currently on: $current_branch)"
    echo "Please switch to main branch first"
    exit 1
fi

# Check if there are uncommitted changes
if ! git diff-index --quiet HEAD --; then
    echo "❌ There are uncommitted changes"
    echo "Please commit or stash your changes first"
    exit 1
fi

# Get the current version from pyproject.toml
current_version=$(grep '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "📦 Current version: $current_version"

# Get new version
if [ "$NON_INTERACTIVE" = true ]; then
    new_version="$NEW_VERSION"
    echo "📦 Using provided version: $new_version"
else
    # Ask for new version
    echo "Enter new version (current: $current_version):"
    read -r new_version
fi

if [ -z "$new_version" ]; then
    echo "❌ Version cannot be empty"
    exit 1
fi

# Check if version is the same as current
if [ "$new_version" = "$current_version" ]; then
    echo "❌ New version cannot be the same as current version"
    exit 1
fi

# Validate version format (basic check)
if ! echo "$new_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "❌ Invalid version format. Use semantic versioning (e.g., 1.2.3)"
    exit 1
fi

echo "🚀 Creating release v$new_version..."

# Update version in pyproject.toml
echo "📝 Updating version in pyproject.toml..."
sed -i "s/version = \"$current_version\"/version = \"$new_version\"/" pyproject.toml

# Verify the change was made
if ! grep -q "version = \"$new_version\"" pyproject.toml; then
    echo "❌ Failed to update version in pyproject.toml"
    exit 1
fi

# Commit the version bump
echo "📝 Committing version bump..."
git add pyproject.toml
git commit --no-verify -m "Bump version to $new_version"

# Create and push tag
echo "🏷️  Creating and pushing tag..."
git tag "v$new_version"
git push origin main
git push origin "v$new_version"

echo "✅ Release v$new_version created and pushed!"
echo "🔗 Check the GitHub Actions tab to see the build progress"
echo "📦 The release will be available at: https://github.com/conradolandia/iiif-downloader/releases"
