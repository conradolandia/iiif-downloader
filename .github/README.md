# GitHub Actions CI/CD

This repository uses GitHub Actions for continuous integration and deployment.

## Workflows

### 1. CI (`ci.yml`)
- **Triggers**: Push to `main`, Pull Requests to `main`
- **Purpose**: Run tests, linting, and basic executable build
- **Runs on**: Ubuntu Latest
- **Python**: 3.12

### 2. Build and Release (`build-release.yml`)
- **Triggers**: Git tags starting with `v*`, Manual dispatch
- **Purpose**: Build executables for multiple Python versions and create releases
- **Runs on**: Ubuntu Latest
- **Python**: 3.11, 3.12, 3.13

### 3. Build Matrix (`build-matrix.yml`)
- **Triggers**: Manual dispatch only
- **Purpose**: Build executables for multiple platforms and Python versions
- **Runs on**: Ubuntu, Windows, macOS
- **Python**: 3.11, 3.12, 3.13

## Creating Releases

### Automatic Release (Recommended)

1. **Update version** in `pyproject.toml`:
   ```toml
   [project]
   version = "1.2.3"
   ```

2. **Commit and push**:
   ```bash
   git add pyproject.toml
   git commit -m "Bump version to 1.2.3"
   git push origin main
   ```

3. **Create and push tag**:
   ```bash
   git tag v1.2.3
   git push origin v1.2.3
   ```

4. **GitHub Actions will automatically**:
   - Build executables for Python 3.11, 3.12, 3.13
   - Create a GitHub release
   - Upload all executables as release assets
   - Generate checksums

### Using the Release Script

Use the provided script for easier release creation:

```bash
./scripts/create-release.sh
```

The script will:
- Check you're on the main branch
- Check for uncommitted changes
- Ask for the new version
- Update `pyproject.toml`
- Commit the version bump
- Create and push the tag
- Trigger the GitHub Actions workflow

### Manual Release

1. Go to GitHub Actions
2. Select "Build and Release" workflow
3. Click "Run workflow"
4. Choose the branch and click "Run workflow"

## Release Assets

Each release includes:

- `iiif-downloader-linux-x86_64` - Main executable (Python 3.12)
- `iiif-downloader-linux-x86_64-python3.11` - Python 3.11 version
- `iiif-downloader-linux-x86_64-python3.12` - Python 3.12 version
- `iiif-downloader-linux-x86_64-python3.13` - Python 3.13 version
- `checksums.txt` - SHA256 checksums for all files
- `README.md` - Release documentation

## Build Matrix

For testing across multiple platforms, use the Build Matrix workflow:

1. Go to GitHub Actions
2. Select "Build Matrix" workflow
3. Click "Run workflow"
4. Optionally customize platforms and Python versions

This will build executables for:
- Ubuntu (Linux x86_64)
- Windows (Windows x86_64)
- macOS (macOS x86_64/ARM64)

## Troubleshooting

### Build Failures

1. **Check the Actions tab** for detailed error logs
2. **Common issues**:
   - Missing dependencies in `pyproject.toml`
   - PyInstaller issues with specific Python versions
   - Platform-specific build problems

### Release Issues

1. **Tag not triggering release**: Ensure tag starts with `v` (e.g., `v1.2.3`)
2. **Missing assets**: Check that all build jobs completed successfully
3. **Permission issues**: Ensure the repository has proper GitHub Actions permissions

### Local Testing

Test the executable build locally:

```bash
# Install dependencies
pixi install

# Build executable
pixi run build-exe

# Test executable
./dist/iiif-downloader --help

# Test single canvas download
./dist/iiif-downloader --source "https://example.com/manifest.json" --canvas 1 --output "test"
```

## Configuration

### Workflow Configuration

- **Build timeout**: 30 minutes per job
- **Artifact retention**: 30 days
- **Concurrent builds**: Limited by GitHub Actions limits

### Customization

To modify the build process:

1. **Edit workflow files** in `.github/workflows/`
2. **Update dependencies** in `pyproject.toml`
3. **Modify build commands** in `pixi.toml`

### Adding New Platforms

To add support for new platforms:

1. Add the platform to the matrix in `build-matrix.yml`
2. Update PyInstaller configuration if needed
3. Test locally with the target platform
4. Update release asset handling in `build-release.yml`
