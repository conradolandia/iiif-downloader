# IIIF Downloader

[![CI](https://github.com/conradolandia/iiif-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/conradolandia/iiif-downloader/actions/workflows/ci.yml)
[![Release](https://github.com/conradolandia/iiif-downloader/actions/workflows/build-release.yml/badge.svg)](https://github.com/conradolandia/iiif-downloader/actions/workflows/build-release.yml)

Download images from [IIIF](https://iiif.io/) manifests and METS documents. Supports resume, rate limiting, metadata export, and single-page download.

## Table of contents

- [IIIF Downloader](#iiif-downloader)
  - [Table of contents](#table-of-contents)
  - [Install](#install)
    - [Prebuilt binary](#prebuilt-binary)
    - [From source (pixi or pip)](#from-source-pixi-or-pip)
  - [Quick start](#quick-start)
  - [Options](#options)
  - [IIIF](#iiif)
  - [METS](#mets)
  - [Output files](#output-files)
  - [Rate limiting](#rate-limiting)
  - [Cookies](#cookies)
  - [Technical notes](#technical-notes)
    - [Supported formats](#supported-formats)
    - [Building a local executable](#building-a-local-executable)
    - [Development](#development)
    - [Known gaps](#known-gaps)
  - [License](#license)

## Install

### Prebuilt binary

Download the executable for your platform from the [Releases](https://github.com/conradolandia/iiif-downloader/releases) page.

```bash
chmod +x iiif-downloader   # Linux / macOS
./iiif-downloader --help
```

### From source (pixi or pip)

```bash
# pixi
curl -fsSL https://pixi.sh/install.sh | bash
pixi install
pixi run iiif-downloader --help

# or pip (editable)
pip install -e .
```

## Quick start

```bash
# IIIF manifest (URL or local file)
iiif-downloader --source "https://example.com/manifest.json" --output "images"

# Single page (1-based index)
iiif-downloader --source "https://example.com/manifest.json" --canvas 5 --output "page5"

# Resume an interrupted download
iiif-downloader --source "https://example.com/manifest.json" --output "images" --resume

# METS document
iiif-downloader --format mets --source "document.xml" --output "mets_images" --metadata
```

## Options

| Option | Description |
| --- | --- |
| `--source` | Manifest/document URL or local path (required) |
| `--format` | `iiif` (default) or `mets` |
| `--output` | Output directory |
| `--size` | Target image width in pixels (IIIF only; ignored for METS) |
| `--canvas` | Download one page only (1-based index) |
| `--resume` | Skip files already present in the output directory |
| `--metadata` | Write source metadata to a text file |
| `--rate-limit` | Fixed requests per minute (disables adaptive limiting) |
| `--no-adaptive-rate` | Use a fixed base delay instead of adaptive limiting |
| `--cookies` | Netscape/Mozilla cookie file (read-only) for authenticated or bot-protected servers |
| `--verbose` / `-v` | Extra connection and download detail |

## IIIF

Pass a Presentation API manifest URL or a local JSON file. Presentation API v2.1 and v3.0 are both accepted; the version is detected from the document.

```bash
iiif-downloader \
  --source "https://example.com/manuscript/manifest.json" \
  --output "manuscript_images" \
  --size 2048 \
  --metadata \
  --resume
```

`--size` requests that width from the Image API when the server allows it. If omitted, the tool uses the largest available size within server limits.

## METS

Pass `--format mets`. Images are taken from the first `fileGrp` under `fileSec`. Page order and labels come from the PHYSICAL `structMap` when present.

```bash
iiif-downloader \
  --format mets \
  --source "document.xml" \
  --output "liber_commicus" \
  --metadata \
  --resume
```

Notes:

- Format is not auto-detected; `--format mets` is required.
- `--size` has no effect; images are fetched at the published `FLocat` URL.
- `--canvas` selects a page by structMap order (1-based).
- `--metadata` writes the METS `@LABEL` and MARC fields from `dmdSec`.

## Output files

Filenames combine page index and label when a label exists:

| Source | Example |
| --- | --- |
| IIIF with label | `canvas-005_folio003r.jpeg` |
| IIIF without label | `image_003.jpeg` |
| METS with label | `page-007_1r.jpeg` |

With `--resume`, already downloaded files are skipped. Older numeric names may be migrated to the hybrid scheme when a match is found. Progress is tracked in `.iiif-download-state.json` in the output directory.

## Rate limiting

By default the client adapts delay from server responses (including HTTP 429/503). Use `--rate-limit N` for a fixed requests-per-minute cap, or `--no-adaptive-rate` for a fixed base delay.

## Cookies

If a server requires login or shows bot protection, export cookies from a browser session (Netscape format) and pass them with `--cookies /path/to/cookies.txt`. The file is read-only.

## Technical notes

### Supported formats

- IIIF Presentation API v2.1 (`sequences[0].canvases`) and v3.0 (`items`)
- IIIF Image API size negotiation when `info.json` is available; falls back to canvas resource data when it is not
- METS: first `fileGrp`, PHYSICAL `structMap`, MARC in `dmdSec`

### Building a local executable

```bash
pixi run build-exe
./dist/iiif-downloader --help
```

### Development

```bash
pixi run test
pixi run check
```

```
src/iiif_downloader/
├── cli.py                 # Argument parsing
├── downloader.py          # IIIF orchestration
├── mets_downloader.py     # METS orchestration
├── sources/               # Source adapters (iiif, mets)
├── manifest.py            # IIIF parsing / sizing
├── image_downloader.py    # HTTP download / size estimation
├── session_manager.py     # Session and cookies
├── rate_limiter.py
├── file_tracker.py
└── metadata.py
```

### Known gaps

- No auto-detection of source format (`--format` required for METS)
- METS uses the first `fileGrp` only (no `USE` filtering)
- No relative `FLocat` / local file resolution for METS
- Non-MARC `dmdSec` blocks (MODS, DC, etc.) are not exported
- No METS derivative/size selection beyond the published URL

## License

MIT
