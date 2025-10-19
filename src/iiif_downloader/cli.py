"""Command-line interface for the IIIF downloader."""

import argparse
import sys

from iiif_downloader.downloader import download_iiif_images
from iiif_downloader.manifest import load_manifest
from iiif_downloader.metadata import save_metadata


def _detect_tui_capability() -> bool:
    """Detect if the terminal supports TUI mode."""
    # Check if we're in a proper terminal
    if not sys.stdout.isatty():
        return False

    # Check for common terminal emulators that support TUI
    term = sys.environ.get("TERM", "").lower()
    if term in ["", "dumb", "unknown"]:
        return False

    # Check for minimum terminal size
    try:
        import shutil

        size = shutil.get_terminal_size()
        if size.columns < 80 or size.lines < 24:
            return False
    except Exception:
        return False

    return True


def _run_tui_mode(
    manifest_data: dict,
    output_folder: str,
    size: int | None = None,
    resume: bool = False,
    rate_limit: float | None = None,
) -> None:
    """Run the TUI mode."""
    try:
        from iiif_downloader.tui.app import IIIFDownloaderApp

        app = IIIFDownloaderApp()
        app.start_download(
            manifest_data=manifest_data,
            output_folder=output_folder,
            size=size,
            resume=resume,
            rate_limit=rate_limit,
        )
        app.run()
    except ImportError:
        print("Error: TUI mode requires textual. Install with: pip install textual")
        sys.exit(1)
    except Exception as e:
        print(f"Error starting TUI mode: {e}")
        print("Falling back to CLI mode...")
        # Fall back to CLI mode
        download_iiif_images(
            manifest_data,
            size,
            output_folder,
            resume,
            rate_limit,
        )


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
        "--tui", action="store_true", help="Use TUI mode (interactive interface)"
    )
    parser.add_argument(
        "--no-tui", action="store_true", help="Force CLI mode (disable TUI)"
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
    if not manifest_data:
        sys.exit(1)

    # Save metadata if requested
    if args.metadata:
        save_metadata(manifest_data, args.output)

    # Determine UI mode
    use_tui = False
    if args.tui:
        use_tui = True
    elif args.no_tui:
        use_tui = False
    else:
        # Auto-detect
        use_tui = _detect_tui_capability()

    if use_tui:
        _run_tui_mode(
            manifest_data,
            args.output or "iiif_images",
            args.size,
            args.resume,
            rate_limit,
        )
    else:
        # Use CLI mode
        download_iiif_images(
            manifest_data, args.size, args.output, args.resume, rate_limit
        )
