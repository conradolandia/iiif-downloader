"""Host-specific IIIF server adapters (quirks behind hostname matching)."""

from __future__ import annotations

from urllib.parse import urlparse

from iiif_downloader.servers.base import DEFAULT_ADAPTER, ServerAdapter
from iiif_downloader.servers.bodleian import BODLEIAN_ADAPTER, BodleianAdapter

# Most-specific adapters first; DEFAULT_ADAPTER is the fallback.
_ADAPTERS: tuple[ServerAdapter, ...] = (BODLEIAN_ADAPTER,)


def resolve_adapter(url: str) -> ServerAdapter:
    """Return the server adapter for a URL's hostname.

    Args:
        url: Absolute URL (manifest, image service, or image request).

    Returns:
        ServerAdapter: Matching host adapter, or the default adapter.
    """
    hostname = urlparse(url).hostname or ""
    for adapter in _ADAPTERS:
        if adapter.matches_host(hostname):
            return adapter
    return DEFAULT_ADAPTER


def resolve_adapter_for_host(hostname: str) -> ServerAdapter:
    """Return the server adapter for a bare hostname.

    Args:
        hostname: Hostname without scheme or path.

    Returns:
        ServerAdapter: Matching host adapter, or the default adapter.
    """
    for adapter in _ADAPTERS:
        if adapter.matches_host(hostname):
            return adapter
    return DEFAULT_ADAPTER


__all__ = [
    "ServerAdapter",
    "DEFAULT_ADAPTER",
    "BodleianAdapter",
    "BODLEIAN_ADAPTER",
    "resolve_adapter",
    "resolve_adapter_for_host",
]
