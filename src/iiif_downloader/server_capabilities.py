"""Server capability detection for IIIF image services."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from iiif_downloader.servers import ServerAdapter, resolve_adapter

# Fields that depend on a specific image and must not be reused from domain cache
_IMAGE_SPECIFIC_CACHE_KEYS = frozenset(
    {"max_test_size", "supports_full_size", "max_edge"}
)


@dataclass
class ServerCapabilities:
    """Capabilities discovered for a IIIF image server."""

    preferred_format: str  # "jpeg" or "jpg"
    supports_full_size: bool
    max_test_size: int | None = None  # Maximum width that worked for the probed image
    max_edge: int | None = None  # Max resulting edge (W or H) from probing
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
    """Load cached domain-level capabilities (format, auth, qualities only).

    Image-specific fields (max size / edge) are stripped so they are always
    re-probed for the current image.
    """
    cache_path = _get_cache_path(server_domain)
    if cache_path.exists():
        try:
            with open(cache_path) as f:
                data = json.load(f)
            for key in _IMAGE_SPECIFIC_CACHE_KEYS:
                data.pop(key, None)
            # Reconstruct with safe defaults for image-specific fields
            data.setdefault("supports_full_size", False)
            data.setdefault("max_test_size", None)
            data.setdefault("max_edge", None)
            return ServerCapabilities(**data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None
    return None


def _save_cached_capabilities(
    server_domain: str, capabilities: ServerCapabilities
) -> None:
    """Save domain-level capabilities to cache (excludes per-image size limits)."""
    cache_path = _get_cache_path(server_domain)
    try:
        data = {
            "preferred_format": capabilities.preferred_format,
            "supported_qualities": capabilities.supported_qualities,
            "requires_authentication": capabilities.requires_authentication,
            "rate_limit_detected": capabilities.rate_limit_detected,
            "server_domain": capabilities.server_domain,
            # Kept for backward-compatible cache readers; always re-probed
            "supports_full_size": False,
            "max_test_size": None,
            "max_edge": None,
        }
        with open(cache_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # Silently fail if cache write fails


def _size_request_ok(
    service_id: str,
    format_str: str,
    size: int,
    session_manager,
    adapter: ServerAdapter,
) -> bool:
    """Return True if a short HEAD request for the given width succeeds.

    Uses the adapter probe timeout so a hung IIIF size cannot stall probing.
    """
    test_url = f"{service_id}/full/{size},/0/default.{format_str}"
    try:
        response = session_manager.head(test_url, timeout=adapter.probe_head_timeout)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _test_format(
    service_id: str,
    test_size: int,
    session_manager,
    adapter: ServerAdapter,
) -> tuple[str, bool]:
    """Test format support and return (format, success)."""
    for format_option in ["jpeg", "jpg"]:
        if _size_request_ok(
            service_id, format_option, test_size, session_manager, adapter
        ):
            return format_option, True
    return "jpg", False  # Default fallback


def _test_maximum_size(
    service_id: str,
    format_str: str,
    desired_size: int,
    session_manager,
    adapter: ServerAdapter,
    upper_bound: int | None = None,
    trust_declared_limits: bool = False,
) -> int | None:
    """Find a usable request width without exhaustive binary search.

    Prefer a single verify of the desired width, then adapter fallback sizes.
    Some hosts hang on HEAD for certain widths; adapters encode that policy.

    Args:
        service_id: Image service base URL
        format_str: Image format extension (jpg/jpeg)
        desired_size: Target width to try (inclusive upper goal)
        session_manager: Session manager for HTTP requests
        adapter: Host adapter providing timeouts and fallback sizes
        upper_bound: Optional hard cap (e.g. declared maxWidth)
        trust_declared_limits: If True and HEAD is inconclusive, still return ``hi``

    Returns:
        int | None: Chosen width, or None if no size works
    """
    hi = desired_size
    if upper_bound is not None:
        hi = min(hi, upper_bound)
    if hi < 1:
        return None

    if _size_request_ok(service_id, format_str, hi, session_manager, adapter):
        return hi

    for size in adapter.fallback_probe_sizes(hi):
        if size == hi:
            continue
        if _size_request_ok(service_id, format_str, size, session_manager, adapter):
            return size

    # Declared info.json limits already capped ``hi``; GET often works when HEAD hangs
    if trust_declared_limits:
        return hi

    return None


def _test_quality_levels(
    service_id: str,
    format_str: str,
    test_size: int,
    session_manager,
    adapter: ServerAdapter,
) -> list[str]:
    """Test which quality levels are supported."""
    qualities = ["default", "color", "gray", "bitonal"]
    supported = []

    for quality in qualities:
        test_url = f"{service_id}/full/{test_size},/0/{quality}.{format_str}"
        try:
            response = session_manager.head(
                test_url, timeout=adapter.probe_head_timeout
            )
            if response.status_code == 200:
                supported.append(quality)
        except requests.RequestException:
            continue

    return supported if supported else ["default"]


def _test_authentication(
    service_id: str,
    format_str: str,
    test_size: int,
    session_manager,
    adapter: ServerAdapter,
) -> bool:
    """Test if authentication is required."""
    test_url = f"{service_id}/full/{test_size},/0/default.{format_str}"
    try:
        response = session_manager.head(test_url, timeout=adapter.probe_head_timeout)
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
    service_id: str,
    format_str: str,
    test_size: int,
    session_manager,
    adapter: ServerAdapter,
) -> bool:
    """Test if rate limiting is detected by making rapid requests."""
    test_url = f"{service_id}/full/{test_size},/0/default.{format_str}"

    try:
        # Make 3 rapid requests
        responses = []
        for _ in range(3):
            response = session_manager.head(
                test_url, timeout=adapter.probe_head_timeout
            )
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


def _derive_max_edge(
    max_width: int, image_width: int | None, image_height: int | None
) -> int:
    """Derive the maximum allowed edge length from a probed width.

    Uses ceil for the scaled height so reverse-applying ``max_edge`` does not
    undercut the probed width (truncation would request a smaller, untested size).

    Args:
        max_width: Maximum requestable width found by probing
        image_width: Full width of the probed image
        image_height: Full height of the probed image

    Returns:
        int: Maximum of probed width and resulting scaled height
    """
    if image_width and image_height and image_width > 0:
        resulting_height = math.ceil(max_width * image_height / image_width)
        return max(max_width, resulting_height)
    return max_width


def _preferred_format_from_info(
    image_info: dict[str, Any], adapter: ServerAdapter
) -> str:
    """Pick jpg/jpeg from info.json profile formats, else adapter default.

    Args:
        image_info: Parsed info.json body
        adapter: Host adapter providing ``default_format``

    Returns:
        str: ``jpg`` or ``jpeg``
    """
    candidates: list[str] = []

    profile = image_info.get("profile")
    profile_objects: list[dict[str, Any]] = []
    if isinstance(profile, list):
        profile_objects = [p for p in profile if isinstance(p, dict)]
    elif isinstance(profile, dict):
        profile_objects = [profile]

    for item in profile_objects:
        formats = item.get("formats")
        if isinstance(formats, list):
            candidates.extend(str(f).lower() for f in formats)

    for key in ("preferredFormats", "extraFormats"):
        formats = image_info.get(key)
        if isinstance(formats, list):
            candidates.extend(str(f).lower() for f in formats)

    for preferred in ("jpg", "jpeg"):
        if preferred in candidates:
            return preferred

    default = (adapter.default_format or "jpg").lower()
    return default if default in ("jpg", "jpeg") else "jpg"


def capabilities_from_info(
    service_id: str,
    image_info: dict[str, Any],
    adapter: ServerAdapter | None = None,
) -> ServerCapabilities:
    """Build capabilities from info.json without HEAD probes.

    Size limits stay per-image via ``get_image_size_from_info``; this only
    records domain-level format defaults. ``max_edge`` is left unset so each
    image uses its own declared maxWidth/maxHeight/maxArea.

    Args:
        service_id: Image service base URL
        image_info: Parsed info.json body
        adapter: Host adapter; resolved from ``service_id`` when omitted

    Returns:
        ServerCapabilities: Format and domain metadata from JSON
    """
    adapter = adapter or resolve_adapter(service_id)
    parsed_url = urlparse(service_id)
    server_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

    return ServerCapabilities(
        preferred_format=_preferred_format_from_info(image_info, adapter),
        supports_full_size=False,
        max_test_size=None,
        max_edge=None,
        supported_qualities=["default"],
        requires_authentication=False,
        rate_limit_detected=False,
        server_domain=server_domain,
    )


def probe_server_capabilities(
    service_id: str,
    sample_image_size: int,
    session_manager,
    use_cache: bool = True,
    upper_bound: int | None = None,
    image_width: int | None = None,
    image_height: int | None = None,
    trust_declared_limits: bool | None = None,
    adapter: ServerAdapter | None = None,
) -> ServerCapabilities:
    """Probe server capabilities by testing a sample image request.

    Domain-level results (format, qualities, auth) may be cached. Per-image
    size limits are always probed for the current sample. Host adapters supply
    timeouts, fallback sizes, and declared-limit trust policy.

    Args:
        service_id: The image service ID (from image info)
        sample_image_size: The size to test (width in pixels)
        session_manager: SessionManager instance for making requests
        use_cache: Whether to use cached domain capabilities if available
        upper_bound: Optional hard cap for size probing (e.g. declared maxWidth)
        image_width: Full width of the sample image (for max_edge derivation)
        image_height: Full height of the sample image (for max_edge derivation)
        trust_declared_limits: Override adapter trust policy; None uses adapter
        adapter: Host adapter; resolved from ``service_id`` when omitted

    Returns:
        ServerCapabilities: Discovered server capabilities
    """
    adapter = adapter or resolve_adapter(service_id)

    # Extract server domain for caching
    parsed_url = urlparse(service_id)
    server_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"

    cached: ServerCapabilities | None = None
    if use_cache:
        cached = _load_cached_capabilities(server_domain)

    format_probe_size = min(500, max(1, sample_image_size))
    if cached is not None and cached.preferred_format:
        format_to_test = cached.preferred_format
        format_works = _size_request_ok(
            service_id, format_to_test, format_probe_size, session_manager, adapter
        )
        if not format_works:
            format_to_test, format_works = _test_format(
                service_id, format_probe_size, session_manager, adapter
            )
    else:
        format_to_test, format_works = _test_format(
            service_id, format_probe_size, session_manager, adapter
        )

    if not format_works:
        format_to_test = "jpg"

    has_declared_limits = upper_bound is not None
    if trust_declared_limits is None:
        trust_limits = adapter.should_trust_declared_limits(has_declared_limits)
    else:
        trust_limits = trust_declared_limits

    # When info.json declared limits capped sample_image_size, trust that width
    # even if HEAD is flaky rather than searching hang-prone sizes.
    max_size = _test_maximum_size(
        service_id,
        format_to_test,
        sample_image_size,
        session_manager,
        adapter,
        upper_bound=upper_bound,
        trust_declared_limits=trust_limits or has_declared_limits,
    )

    supports_full_size = max_size is not None and max_size >= sample_image_size
    max_edge = (
        _derive_max_edge(max_size, image_width, image_height) if max_size else None
    )
    # Use a small width for quality/auth/rate probes (faster, fewer server hangs)
    quality_test_size = format_probe_size

    if cached is not None:
        supported_qualities = cached.supported_qualities or ["default"]
        requires_auth = cached.requires_authentication
        rate_limit_detected = cached.rate_limit_detected
    else:
        supported_qualities = _test_quality_levels(
            service_id, format_to_test, quality_test_size, session_manager, adapter
        )
        requires_auth = _test_authentication(
            service_id, format_to_test, quality_test_size, session_manager, adapter
        )
        rate_limit_detected = _test_rate_limiting(
            service_id, format_to_test, quality_test_size, session_manager, adapter
        )

    capabilities = ServerCapabilities(
        preferred_format=format_to_test,
        supports_full_size=supports_full_size,
        max_test_size=max_size,
        max_edge=max_edge,
        supported_qualities=supported_qualities,
        requires_authentication=requires_auth,
        rate_limit_detected=rate_limit_detected,
        server_domain=server_domain,
    )

    # Cache domain-level capabilities only
    if use_cache:
        _save_cached_capabilities(server_domain, capabilities)

    return capabilities
