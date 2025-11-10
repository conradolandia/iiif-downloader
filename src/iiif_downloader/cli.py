"""Command-line interface for the IIIF downloader."""

import argparse
import sys

from iiif_downloader.downloader import IIIFDownloader
from iiif_downloader.manifest import load_manifest
from iiif_downloader.metadata import save_metadata


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Download IIIF images from a manifest URL or local file."
    )
    parser.add_argument(
        "--source", required=True, help="URL or file path of the IIIF manifest"
    )
    parser.add_argument("--size", type=int, help="Desired image width (optional)")
    parser.add_argument("--output", help="Output folder for images (optional)")
    parser.add_argument(
        "--metadata", action="store_true", help="Save manifest metadata to a text file"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume interrupted downloads by skipping existing files",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        help="Fixed rate limit in requests per minute (overrides adaptive mode)",
    )
    parser.add_argument(
        "--no-adaptive-rate",
        action="store_true",
        help="Disable adaptive rate limiting (use fixed base delay)",
    )
    parser.add_argument(
        "--canvas",
        type=int,
        help="Download only a specific canvas/page (1-based index)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output showing connection details and download progress",
    )

    args = parser.parse_args()

    # Determine rate limiting mode
    if args.rate_limit:
        rate_limit = args.rate_limit
    elif args.no_adaptive_rate:
        rate_limit = None  # Use fixed base delay
    else:
        rate_limit = None  # Use adaptive mode

    # Add progress feedback for startup
    print("🔄 Loading manifest...", end="", flush=True)
    sys.stdout.flush()

    manifest_data = load_manifest(args.source)
    if manifest_data:
        print(" ✅")

        # Save metadata if requested
        if args.metadata:
            save_metadata(manifest_data, args.output)

        # Download images
        downloader = IIIFDownloader(
            manifest_data=manifest_data,
            size=args.size,
            output_folder=args.output,
            rate_limit=rate_limit,
            verbose=args.verbose,
        )

        if args.canvas:
            print(f"📥 Downloading canvas {args.canvas}...")
            downloader.download_one(args.canvas)
        else:
            print("📥 Starting download...")
            downloader.download_all(resume=args.resume)
    else:
        print(" ❌")
        sys.exit(1)
