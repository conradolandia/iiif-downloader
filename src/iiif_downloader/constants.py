"""
Constants for the IIIF downloader.
"""

# JSON content types that are accepted for IIIF image info responses
JSON_CONTENT_TYPES = [
    "application/json",
    "application/ld+json",
    "application/vnd.api+json",
    "text/json",
    "application/javascript",
]

# Treat files smaller than this as incomplete (empty/corrupt leftovers)
MIN_VALID_IMAGE_BYTES = 1024 * 16  # 16 KB

# Retry empty/truncated/failed image downloads
MAX_DOWNLOAD_RETRIES = 3
DOWNLOAD_RETRY_BACKOFF_SECONDS = 2.0
