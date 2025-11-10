"""Shared helper functions for downloading."""

import os


def get_default_headers():
    """Get default HTTP headers to mimic a browser.

    Returns:
        dict: Dictionary of HTTP headers
    """
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


def setup_output_directory(manifest_data, output_folder=None):
    """Set up the output directory for downloaded images.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        output_folder: Optional output folder name

    Returns:
        str: Path to the output directory
    """
    if output_folder:
        base_filename = output_folder
    else:
        # Extract the base filename
        if "filename" in manifest_data:
            base_filename = os.path.splitext(manifest_data["filename"])[0]
        else:
            base_filename = "iiif_images"

    # Create a directory to store the downloaded images
    os.makedirs(base_filename, exist_ok=True)

    return base_filename
