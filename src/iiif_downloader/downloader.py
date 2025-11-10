"""Main download orchestration functions.

This module provides backward-compatible function wrappers around the IIIFDownloader class.
For new code, consider using the IIIFDownloader class directly from downloader_class module.
"""

from iiif_downloader.downloader_class import IIIFDownloader


def download_iiif_images(
    manifest_data,
    size=None,
    output_folder=None,
    resume=False,
    rate_limit=None,
    verbose=False,
):
    """Download IIIF images with progress tracking and rate limiting.

    This is a backward-compatible wrapper around the IIIFDownloader class.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        size: Desired image width (optional)
        output_folder: Output directory for images (optional)
        resume: Whether to resume interrupted downloads
        rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        verbose: Whether to enable verbose output
    """
    downloader = IIIFDownloader(
        manifest_data=manifest_data,
        size=size,
        output_folder=output_folder,
        rate_limit=rate_limit,
        verbose=verbose,
    )
    downloader.download_all(resume=resume)


def download_single_canvas(
    manifest_data,
    canvas_index,
    size=None,
    output_folder=None,
    rate_limit=None,
    verbose=False,
):
    """Download a single canvas/page from a IIIF manifest.

    This is a backward-compatible wrapper around the IIIFDownloader class.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        canvas_index: 1-based index of the canvas to download
        size: Desired image width (optional)
        output_folder: Output directory for images (optional)
        rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        verbose: Whether to enable verbose output
    """
    downloader = IIIFDownloader(
        manifest_data=manifest_data,
        size=size,
        output_folder=output_folder,
        rate_limit=rate_limit,
        verbose=verbose,
    )
    downloader.download_one(canvas_index)
