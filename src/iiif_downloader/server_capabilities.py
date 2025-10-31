"""Server capability detection for IIIF image services."""

from dataclasses import dataclass

import requests


@dataclass
class ServerCapabilities:
    """Capabilities discovered for a IIIF image server."""

    preferred_format: str  # "jpeg" or "jpg"
    supports_full_size: bool
    max_test_size: int | None = None  # Maximum size that worked in testing


def probe_server_capabilities(
    service_id: str, sample_image_size: int, headers: dict
) -> ServerCapabilities:
    """Probe server capabilities by testing a sample image request.

    Args:
        service_id: The image service ID (from image info)
        sample_image_size: The size to test (width in pixels)
        headers: HTTP headers to use for requests

    Returns:
        ServerCapabilities: Discovered server capabilities
    """
    # Test format support: try .jpeg first (spec recommendation)
    format_to_test = "jpeg"
    test_url = f"{service_id}/full/{sample_image_size},/0/default.{format_to_test}"

    try:
        response = requests.head(test_url, headers=headers, timeout=10)
        # If .jpeg is not supported, try .jpg
        if response.status_code in (400, 404, 415):
            format_to_test = "jpg"
            test_url = (
                f"{service_id}/full/{sample_image_size},/0/default.{format_to_test}"
            )
            response = requests.head(test_url, headers=headers, timeout=10)
            if response.status_code not in (200, 301, 302):
                # Try .jpg with a smaller size as fallback
                test_url = f"{service_id}/full/500,/0/default.jpg"
                response = requests.head(test_url, headers=headers, timeout=10)
    except requests.RequestException:
        # On exception, default to .jpg as safer option
        format_to_test = "jpg"

    # Determine if server supports the requested size
    supports_full_size = response.status_code == 200

    return ServerCapabilities(
        preferred_format=format_to_test,
        supports_full_size=supports_full_size,
        max_test_size=sample_image_size if supports_full_size else None,
    )
