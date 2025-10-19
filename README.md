# IIIF Downloader

A Python tool for downloading images from IIIF (International Image Interoperability Framework) manifests with progress tracking, rate limiting, and resume capabilities.

## Features

- Download images from IIIF manifests (URL or local file)
- **Interactive TUI mode** with real-time statistics and controls
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

### TUI Mode (Interactive Interface)

The IIIF downloader includes a modern TUI (Text User Interface) for an enhanced interactive experience:

```bash
# Use TUI mode (auto-detected in proper terminals)
iiif-downloader --source "https://example.com/manifest.json" --tui

# Force CLI mode (disable TUI)
iiif-downloader --source "https://example.com/manifest.json" --no-tui
```

#### TUI Features

- **Real-time Statistics**: Live updates of download progress, speed, and ETA
- **Interactive Controls**: Pause/resume downloads with keyboard shortcuts
- **Activity Log**: Scrollable log of recent download activities
- **Progress Visualization**: Both overall and per-image progress bars
- **Keyboard Shortcuts**:
  - `Q` - Quit the application
  - `P` - Pause/Resume downloads
  - `S` - Save activity log (planned feature)

#### TUI Layout

```
┌─────────────────────────────────────────────────────────────┐
│ IIIF Downloader v0.1.0                    [Q]uit [P]ause    │
├─────────────────────────────────────────────────────────────┤
│ Manifest: manuscript_images                                 │
│ Output: ./manuscript_images/                                │
│ Status: Downloading... [████████░░] 45/100 (45%)            │
├─────────────────────────────────────────────────────────────┤
│ Statistics                                                  │
│ ├─ Downloaded: 45 images (234.5 MB)                         │
│ ├─ Skipped: 12 images (already exist)                       │
│ ├─ Failed: 2 images                                         │
│ ├─ Remaining: 55 images                                     │
│ ├─ Rate: 15.3 req/min (adaptive)                            │
│ └─ Elapsed: 00:03:24 | ETA: 00:04:12                        │
├─────────────────────────────────────────────────────────────┤
│ Current Download                                            │
│ ├─ Image: 046/100 (image_046.jpg)                           │
│ ├─ Size: 5.2 MB / 5.2 MB [████████████] 100%                │
│ └─ Speed: 1.8 MB/s                                          │
├─────────────────────────────────────────────────────────────┤
│ Recent Activity                                             │
│ ├─ ✓ Downloaded image_045.jpg (4.8 MB)                     │
│ ├─ ✓ Downloaded image_044.jpg (5.1 MB)                     │
│ ├─ ⊘ Skipped image_043.jpg (exists)                        │
│ └─ ✗ Failed image_042.jpg (timeout)                        │
└─────────────────────────────────────────────────────────────┘
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
│   ├── download_engine.py    # Event-driven download engine
│   ├── manifest.py           # Manifest loading/parsing
│   ├── metadata.py           # Metadata extraction
│   ├── rate_limiter.py       # Rate limiting logic
│   ├── file_tracker.py       # File existence tracking
│   └── tui/                  # TUI package
│       ├── __init__.py
│       ├── app.py            # Main TUI application
│       ├── widgets.py        # Custom widgets
│       ├── downloader_tui.py # TUI-specific downloader
│       └── themes.py            # Color themes
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
