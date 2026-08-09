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

# Optional HEAD for Content-Length: fail fast so a hung HEAD cannot block GET.
# Host adapters in ``servers/`` may override these per hostname.
HEAD_CONTENT_LENGTH_TIMEOUT = (3, 5)

# Capability probes: short timeouts so a hung HEAD cannot stall probing.
# Host adapters in ``servers/`` may override these per hostname.
PROBE_HEAD_TIMEOUT = (2, 3)

# Quick GET status checks when negotiating a smaller IIIF size after rejection.
SIZE_STATUS_CHECK_TIMEOUT = (5, 15)
