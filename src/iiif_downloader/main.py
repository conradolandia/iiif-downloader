#!/usr/bin/env python3
"""Main entry point for the IIIF downloader executable."""

import os
import sys

from iiif_downloader.cli import main

# Add the src directory to the path for proper imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


if __name__ == "__main__":
    main()
