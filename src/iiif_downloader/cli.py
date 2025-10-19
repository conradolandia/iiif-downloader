"""Command-line interface for the IIIF downloader."""

import argparse

from iiif_downloader.downloader import download_iiif_images
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

    args = parser.parse_args()

    # Determine rate limiting mode
    if args.rate_limit:
        rate_limit = args.rate_limit
    elif args.no_adaptive_rate:
        rate_limit = None  # Use fixed base delay
    else:
        rate_limit = None  # Use adaptive mode

    manifest_data = load_manifest(args.source)
    if manifest_data:
        # Save metadata if requested
        if args.metadata:
            save_metadata(manifest_data, args.output)

        # Download images
        download_iiif_images(
            manifest_data, args.size, args.output, args.resume, rate_limit
        )
