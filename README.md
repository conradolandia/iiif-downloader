# IIIF Downloader

A Python tool for downloading images from IIIF (International Image Interoperability Framework) manifests with progress tracking, rate limiting, and resume capabilities.

## Features

- Download images from IIIF manifests (URL or local file)
- Progress tracking with rich terminal output
- Adaptive rate limiting to be respectful to servers
- Resume interrupted downloads
- Extract and save manifest metadata
- Configurable image sizes
- Build standalone executables

## Installation

### Using Pixi (Recommended)

```bash
# Install pixi if you haven't already
curl -fsSL https://pixi.sh/install.sh | bash

# Install the package
pixi install

# Run the downloader
pixi run iiif-downloader --help
```

### Using pip

```bash
pip install -e .
```

## Usage

### Basic Usage

```bash
# Download from a manifest URL
iiif-downloader --source "https://example.com/manifest.json"

# Download from a local manifest file
iiif-downloader --source "manifest.json"

# Specify output directory
iiif-downloader --source "https://example.com/manifest.json" --output "my_images"

# Download with specific image size
iiif-downloader --source "https://example.com/manifest.json" --size 1024
```

### Advanced Options

```bash
# Resume interrupted downloads
iiif-downloader --source "https://example.com/manifest.json" --resume

# Save manifest metadata
iiif-downloader --source "https://example.com/manifest.json" --metadata

# Set fixed rate limit (requests per minute)
iiif-downloader --source "https://example.com/manifest.json" --rate-limit 30

# Disable adaptive rate limiting (use fixed base delay)
iiif-downloader --source "https://example.com/manifest.json" --no-adaptive-rate
```

### Rate Limiting

The downloader includes intelligent rate limiting to be respectful to servers:

- **Adaptive mode (default)**: Automatically adjusts request rate based on server responses
  - Starts with a base delay of 0.5 seconds between requests
  - Increases delay on HTTP 429/503 errors (rate limiting)
  - Gradually reduces delay on successful requests
  - Maximum backoff of 30 seconds

- **Fixed rate mode**: Use `--rate-limit` to set a fixed requests-per-minute limit
- **Base delay mode**: Use `--no-adaptive-rate` to disable adaptive behavior

### Resume Functionality

When using `--resume`, the downloader:
- Creates a `.iiif-download-state.json` file to track progress
- Skips already downloaded images
- Maintains fast O(1) lookups for existing files
- Automatically detects and skips completed downloads

## Building Executable

Create a standalone executable using PyInstaller:

```bash
# Build executable
pixi run build-exe

# The executable will be created in dist/iiif-downloader
./dist/iiif-downloader --help
```

## Development

### Project Structure

```
iiif-downloader/
├── src/iiif_downloader/
│   ├── __init__.py
│   ├── __main__.py          # CLI entry point
│   ├── cli.py                # Argument parsing
│   ├── downloader.py         # Core download logic
│   ├── manifest.py           # Manifest loading/parsing
│   ├── metadata.py           # Metadata extraction
│   ├── rate_limiter.py       # Rate limiting logic
│   └── file_tracker.py       # File existence tracking
├── pyproject.toml            # Package configuration
├── pixi.toml                 # Pixi configuration
└── iiif-downloader.spec     # PyInstaller spec
```

### Running Tests

```bash
# Install in development mode
pixi run install

# Run the downloader
pixi run run --help
```

## Examples

### Download a Manuscript

```bash
iiif-downloader \
  --source "https://example.com/manuscript/manifest.json" \
  --output "manuscript_images" \
  --size 2048 \
  --metadata \
  --resume
```

### Batch Download with Rate Limiting

```bash
iiif-downloader \
  --source "https://example.com/collection/manifest.json" \
  --rate-limit 20 \
  --output "collection_images"
```

## License

This project is licensed under the MIT License.
