"""Server capability detection for IIIF image services."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests


@dataclass
class ServerCapabilities:
    """Capabilities discovered for a IIIF image server."""

    preferred_format: str  # "jpeg" or "jpg"
    supports_full_size: bool
    max_test_size: int | None = None  # Maximum size that worked in testing
    supported_qualities: list[str] = field(default_factory=lambda: ["default"])
    requires_authentication: bool = False  # Whether authentication is required
    rate_limit_detected: bool = False  # Whether rate limiting is detected
    server_domain: str | None = None  # Server domain for caching


def _get_cache_path(server_domain: str) -> Path:
    """Get the cache file path for a server domain."""
    cache_dir = Path.home() / ".iiif-downloader" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Hash the domain to create a safe filename
    domain_hash = hashlib.md5(server_domain.encode()).hexdigest()
    return cache_dir / f"{domain_hash}.json"


def _load_cached_capabilities(server_domain: str) -> ServerCapabilities | None:
    """Load cached capabilities for a server domain."""
    cache_path = _get_cache_path(server_domain)
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                data = json.load(f)
            # Reconstruct ServerCapabilities from dict
            return ServerCapabilities(**data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
    return None


def _save_cached_capabilities(
    server_domain: str, capabilities: ServerCapabilities
) -> None:
    """Save capabilities to cache."""
    cache_path = _get_cache_path(server_domain)
    try:
        # Convert dataclass to dict for JSON serialization
        data = {
            "preferred_format": capabilities.preferred_format,
            "supports_full_size": capabilities.supports_full_size,
            "max_test_size": capabilities.max_test_size,
            "supported_qualities": capabilities.supported_qualities,
            "requires_authentication": capabilities.requires_authentication,
            "rate_limit_detected": capabilities.rate_limit_detected,
            "server_domain": capabilities.server_domain,
        }
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # Silently fail if cache write fails


def _test_format(service_id: str, test_size: int, session_manager) -> tuple[str, bool]:
    """Test format support and return (format, success)."""
    for format_option in ["jpeg", "jpg"]:
        test_url = f"{service_id}/full/{test_size},/0/default.{format_option}"
        try:
            response = session_manager.head(test_url, timeout=5)
            if response.status_code == 200:
                return format_option, True
        except requests.RequestException:
            continue
    return "jpg", False  # Default fallback


def _test_maximum_size(
    service_id: str, format_str: str, start_size: int, session_manager
) -> int | None:
    """Test progressively larger sizes to find maximum supported."""
    # Test sizes: start_size, 5000, 10000, full if available
    test_sizes = [start_size, 5000, 10000]

    max_working_size = None
    for test_size in test_sizes:
        test_url = f"{service_id}/full/{test_size},/0/default.{format_str}"
        try:
            response = session_manager.head(test_url, timeout=5)
            if response.status_code == 200:
                max_working_size = test_size
            else:
                break  # Stop testing larger sizes if current fails
        except requests.RequestException:
            break

    return max_working_size


def _test_quality_levels(
    service_id: str, format_str: str, test_size: int, session_manager
) -> list[str]:
    """Test which quality levels are supported."""
    qualities = ["default", "color", "gray", "bitonal"]
    supported = []

    for quality in qualities:
        test_url = f"{service_id}/full/{test_size},/0/{quality}.{format_str}"
        try:
            response = session_manager.head(test_url, timeout=5)
            if response.status_code == 200:
                supported.append(quality)
        except requests.RequestException:
            continue

    return supported if supported else ["default"]


def _test_authentication(
    service_id: str, format_str: str, test_size: int, session_manager
) -> bool:
    """Test if authentication is required."""
    test_url = f"{service_id}/full/{test_size},/0/default.{format_str}"
    try:
        response = session_manager.head(test_url, timeout=5)
        # Check for authentication-related status codes
        if response.status_code == 401:
            return True
        # Check for authentication headers
        if "www-authenticate" in response.headers:
            return True
    except requests.RequestException:
        pass
    return False


def _test_rate_limiting(
    service_id: str, format_str: str, test_size: int, session_manager
) -> bool:
    """Test if rate limiting is detected by making rapid requests."""
    test_url = f"{service_id}/full/{test_size},/0/default.{format_str}"

    try:
        # Make 3 rapid requests
        responses = []
        for _ in range(3):
            response = session_manager.head(test_url, timeout=5)
            responses.append(response.status_code)

        # Check if we got 429 (Too Many Requests) or consistent delays
        if 429 in responses:
            return True

        # Check if later requests got different status codes (possible rate limiting)
        if len(set(responses)) > 1:
            return True
    except requests.RequestException:
        pass

    return False


def probe_server_capabilities(
    service_id: str, sample_image_size: int, session_manager, use_cache: bool = True
) -> ServerCapabilities:
    """Probe server capabilities by testing a sample image request.

    Args:
        service_id: The image service ID (from image info)
        sample_image_size: The size to test (width in pixels)
        session_manager: SessionManager instance for making requests
        use_cache: Whether to use cached capabilities if available

    Returns:
        ServerCapabilities: Discovered server capabilities
    """
    # Extract server domain for caching
    parsed_url = urlparse(service_id)
    server_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

    # Try to load from cache
    if use_cache:
        cached = _load_cached_capabilities(server_domain)
        if cached:
            cached.server_domain = server_domain  # Ensure domain is set
            return cached

    # Test format support
    format_to_test, format_works = _test_format(
        service_id, sample_image_size, session_manager
    )

    # If format doesn't work at requested size, try smaller size
    test_size = sample_image_size
    if not format_works:
        format_to_test, _ = _test_format(service_id, 500, session_manager)
        test_size = 500

    # Test maximum supported size
    max_size = _test_maximum_size(
        service_id, format_to_test, test_size, session_manager
    )

    # Determine if server supports the requested full size
    supports_full_size = max_size is not None and max_size >= sample_image_size

    # Test quality levels
    supported_qualities = _test_quality_levels(
        service_id, format_to_test, test_size, session_manager
    )

    # Test authentication
    requires_auth = _test_authentication(
        service_id, format_to_test, test_size, session_manager
    )

    # Test rate limiting
    rate_limit_detected = _test_rate_limiting(
        service_id, format_to_test, test_size, session_manager
    )

    capabilities = ServerCapabilities(
        preferred_format=format_to_test,
        supports_full_size=supports_full_size,
        max_test_size=max_size,
        supported_qualities=supported_qualities,
        requires_authentication=requires_auth,
        rate_limit_detected=rate_limit_detected,
        server_domain=server_domain,
    )

    # Cache the capabilities
    if use_cache:
        _save_cached_capabilities(server_domain, capabilities)

    return capabilities
