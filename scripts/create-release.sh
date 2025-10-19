#!/bin/bash
# Script to create a new release

set -e

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

# Ask for new version
echo "Enter new version (current: $current_version):"
read -r new_version

if [ -z "$new_version" ]; then
    echo "❌ Version cannot be empty"
    exit 1
fi

# Validate version format (basic check)
if ! echo "$new_version" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "❌ Invalid version format. Use semantic versioning (e.g., 1.2.3)"
    exit 1
fi

echo "🚀 Creating release v$new_version..."

# Update version in pyproject.toml
sed -i "s/version = \"$current_version\"/version = \"$new_version\"/" pyproject.toml

# Commit the version bump
git add pyproject.toml
git commit -m "Bump version to $new_version"

# Create and push tag
git tag "v$new_version"
git push origin main
git push origin "v$new_version"

echo "✅ Release v$new_version created and pushed!"
echo "🔗 Check the GitHub Actions tab to see the build progress"
echo "📦 The release will be available at: https://github.com/conradolandia/iiif-downloader/releases"
