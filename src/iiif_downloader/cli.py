"""Command-line interface for the IIIF downloader."""

from __future__ import annotations

import argparse
import sys

from iiif_downloader.downloader import IIIFDownloader
from iiif_downloader.metadata import save_source_metadata
from iiif_downloader.mets_downloader import MetsDownloader
from iiif_downloader.sources import get_adapter, supported_formats


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Download images from IIIF manifests or METS documents (URL or local file)."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        help="URL or file path of the manifest/document",
    )
    parser.add_argument(
        "--format",
        choices=supported_formats(),
        default="iiif",
        help="Source format (default: iiif)",
    )
    parser.add_argument("--size", type=int, help="Desired image width (IIIF only)")
    parser.add_argument("--output", help="Output folder for images (optional)")
    parser.add_argument(
        "--metadata",
        action="store_true",
        help="Save source metadata to a text file",
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
    parser.add_argument(
        "--cookies",
        help=(
            "Path to a Netscape/Mozilla cookie file (read-only; useful for "
            "servers with bot protection)"
        ),
    )

    args = parser.parse_args()

    # Determine rate limiting mode
    if args.rate_limit:
        rate_limit = args.rate_limit
    elif args.no_adaptive_rate:
        rate_limit = None  # Use fixed base delay
    else:
        rate_limit = None  # Use adaptive mode

    if args.format == "mets" and args.size is not None:
        print(
            "Warning: --size is ignored for METS sources "
            "(images are downloaded at their published URL)."
        )

    # Add progress feedback for startup
    print("🔄 Loading source...", end="", flush=True)
    sys.stdout.flush()

    try:
        adapter = get_adapter(args.format)
    except ValueError as exc:
        print(" ❌")
        print(f"Error: {exc}")
        sys.exit(1)

    document = adapter.load(args.source, cookie_file=args.cookies)
    if not document:
        print(" ❌")
        sys.exit(1)

    print(" ✅")

    if args.metadata:
        save_source_metadata(document, args.output)

    if args.format == "iiif":
        downloader = IIIFDownloader(
            manifest_data={
                "content": document.content,
                "filename": document.filename,
            },
            size=args.size,
            output_folder=args.output,
            rate_limit=rate_limit,
            verbose=args.verbose,
            cookie_file=args.cookies,
        )
    else:
        downloader = MetsDownloader(
            source_document=document,
            output_folder=args.output,
            rate_limit=rate_limit,
            verbose=args.verbose,
            cookie_file=args.cookies,
        )

    if args.canvas:
        print(f"📥 Downloading page {args.canvas}...")
        downloader.download_one(args.canvas)
    else:
        print("📥 Starting download...")
        downloader.download_all(resume=args.resume)


if __name__ == "__main__":
    main()
