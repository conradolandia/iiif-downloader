# IIIF Downloader

[![CI](https://github.com/conradolandia/iiif-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/conradolandia/iiif-downloader/actions/workflows/ci.yml)
[![Release](https://github.com/conradolandia/iiif-downloader/actions/workflows/build-release.yml/badge.svg)](https://github.com/conradolandia/iiif-downloader/actions/workflows/build-release.yml)

A Python tool for downloading images from IIIF (International Image Interoperability Framework) manifests and METS documents, with progress tracking, rate limiting, and resume support.

## Features

- Download images from IIIF manifests (URL or local file)
- Download images from METS XML documents via `--format mets`
- Support for both IIIF Presentation API v2.1 and v3.0
- Automatic IIIF version detection
- Progress tracking with rich terminal output
- Adaptive rate limiting to be respectful to servers
- Resume interrupted downloads
- Extract and save source metadata
- Configurable image sizes (IIIF)
- Download single canvas/page with `--canvas` option
- Canvas/page label-based filename generation (e.g., "folio_001r", "folio_001v")
- File size estimation when Content-Length header is missing
- Automatic filename migration when resuming with old naming scheme
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

# Download from a local METS XML file
iiif-downloader --format mets --source "document.xml" --output "mets_images"

# Save METS LABEL + MARC record metadata
iiif-downloader --format mets --source "document.xml" --metadata --output "mets_images"
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

# Download a single specific canvas/page (1-based index)
iiif-downloader --source "https://example.com/manifest.json" --canvas 5
```

### METS Support

METS downloads use direct image URLs from the first `fileGrp` under `fileSec`. Page order and labels come from the PHYSICAL `structMap` when present.

```bash
iiif-downloader \
  --format mets \
  --source "BRM20090000711_1.xml" \
  --output "liber_commicus" \
  --metadata \
  --resume
```

Notes:

- Default `--format` is `iiif`. Pass `--format mets` explicitly (no auto-detection).
- `--size` is ignored for METS (images are fetched at the published `FLocat` URL).
- `--canvas` selects a 1-based page index from the structMap order.
- Filenames use `page-007_1r.jpeg` when a structMap `LABEL` exists.
- `--metadata` writes the METS `@LABEL` and MARC `record` fields from `dmdSec`.

### Rate Limiting

The downloader includes intelligent rate limiting to be respectful to servers:

- **Adaptive mode (default)**: Automatically adjusts request rate based on server responses
  - Starts with a base delay of 0.5 seconds between requests
  - Increases delay on HTTP 429/503 errors (rate limiting)
  - Gradually reduces delay on successful requests
  - Maximum backoff of 30 seconds

- **Fixed rate mode**: Use `--rate-limit` to set a fixed requests-per-minute limit
- **Base delay mode**: Use `--no-adaptive-rate` to disable adaptive behavior

### IIIF Version Support

The downloader supports both IIIF Presentation API versions:

- **IIIF v2.1**: Traditional manifests with `sequences[0].canvases` structure
- **IIIF v3.0**: Modern manifests with `items` structure
- **Automatic detection**: The tool automatically detects the manifest version
- **Backward compatibility**: All existing v2.1 manifests continue to work

### Resume Functionality

When using `--resume`, the downloader:
- Creates a `.iiif-download-state.json` file to track progress
- Skips already downloaded images
- Maintains fast O(1) lookups for existing files
- Automatically detects and skips completed downloads
- Automatically migrates old filenames to new hybrid naming scheme
- Supports both old numeric naming (`image_001.jpeg`) and new hybrid naming (`canvas-005_folio003r.jpeg`)

### Single Canvas Download

Use the `--canvas` option to download a specific page:
- **1-based indexing**: Canvas 1 is the first page, canvas 2 is the second, etc.
- **Validation**: Automatically validates the canvas index against available pages
- **Progress tracking**: Shows progress for the single download
- **Rate limiting**: Respects the same rate limiting as full downloads

```bash
# Download only the 5th page
iiif-downloader --source "https://example.com/manifest.json" --canvas 5

# Download with specific size and output folder
iiif-downloader --source "https://example.com/manifest.json" --canvas 3 --size 2048 --output "page3"
```

### Filename Generation

The downloader uses a hybrid approach combining canvas index with labels from the manifest:

- **Hybrid naming**: If a canvas has a label, files use format `canvas-005_folio003r.jpeg` (index + label)
- **Fallback naming**: If no label is available, files use numeric naming (`image_001.jpeg`, `image_002.jpeg`)
- **Automatic sanitization**: Labels are automatically sanitized to be filesystem-safe
- **Backward compatibility**: Old numeric filenames are automatically migrated to hybrid names when resuming

Example:
- Canvas 5 with label `"folio003r"` → saved as `canvas-005_folio003r.jpeg`
- Canvas 10 with label `"Page 5"` → saved as `canvas-010_Page_5.jpeg`
- Canvas 3 without label → saved as `image_003.jpeg`

### File Size Estimation

When servers don't provide a `Content-Length` header, the downloader estimates file size using:

- **HEAD request**: Attempts to get Content-Length from a lightweight HEAD request
- **Dimension-based estimation**: Estimates size from image dimensions and format (JPEG, PNG, TIFF)
- **Adaptive estimation**: Refines size estimate as data is downloaded
- **Progress tracking**: Shows percentage progress even when exact size is unknown

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
│   ├── __main__.py              # CLI entry point
│   ├── cli.py                   # Argument parsing
│   ├── downloader.py            # IIIFDownloader class
│   ├── mets_downloader.py       # MetsDownloader class
│   ├── sources/                 # Pluggable source adapters
│   │   ├── base.py              # PageItem / SourceDocument / protocol
│   │   ├── iiif.py              # IIIF adapter
│   │   └── mets.py              # METS adapter
│   ├── manifest.py              # IIIF manifest loading/parsing
│   ├── metadata.py              # Metadata extraction
│   ├── image_downloader.py      # Image downloading with size estimation
│   ├── rate_limiter.py          # Rate limiting logic
│   ├── file_tracker.py          # File existence tracking and migration
│   ├── progress_columns.py      # Custom progress bar columns
│   ├── server_capabilities.py   # Server capability detection
│   └── download_helpers.py      # Helper functions
├── tests/
│   ├── fixtures/
│   └── test_mets.py
├── pyproject.toml               # Package configuration
├── pixi.toml                    # Pixi configuration
└── iiif-downloader.spec         # PyInstaller spec
```

### Running Tests

```bash
pixi run test
```

## TODO / Known Gaps

Items deferred from the initial METS work; review later as needed:

- Auto-detect source format from content (currently requires `--format`)
- Multiple `fileGrp` selection (v1 uses the first group only; `USE` filtering for thumbnails/masters)
- Relative `FLocat` paths and local file resolution
- Non-MARC descriptive metadata in `dmdSec` (MODS, DC, Digibis/OTHER blocks)
- METS derivative / size selection when only full-resolution URLs are published
- Additional source adapters beyond IIIF and METS
- Package rename to reflect multi-format support
- Broader adapter coverage in CI (METS live download smoke tests)

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

### Download Single Page

```bash
# Download just the first page
iiif-downloader \
  --source "https://example.com/manuscript/manifest.json" \
  --canvas 1 \
  --size 2048 \
  --output "first_page"
```

## License

This project is licensed under the MIT License.
