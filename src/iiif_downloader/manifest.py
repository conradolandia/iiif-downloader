"""Manifest loading and parsing functionality."""

import json
import os
from urllib.parse import urlparse

import requests


def load_manifest(source):
    """Load a IIIF manifest from URL or local file.

    Args:
        source: URL or file path of the IIIF manifest

    Returns:
        dict: Manifest data with 'content' and 'filename' keys, or None if error
    """
    if source.startswith("http://") or source.startswith("https://"):
        # It's a URL
        try:
            response = requests.get(source)
            response.raise_for_status()
            content = json.loads(response.text)
            return {
                "content": content,
                "filename": os.path.basename(urlparse(source).path),
            }
        except requests.RequestException as e:
            print(f"Error fetching the manifest: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from URL: {e}")
            return None
    else:
        # It's a local file
        try:
            with open(source) as file:
                content = json.load(file)
            return {"content": content, "filename": os.path.basename(source)}
        except FileNotFoundError:
            print(f"File not found: {source}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from file: {e}")
            return None
