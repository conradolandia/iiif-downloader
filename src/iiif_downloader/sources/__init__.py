"""Pluggable source adapters for IIIF, METS, and future formats."""

from iiif_downloader.sources.base import PageItem, SourceAdapter, SourceDocument
from iiif_downloader.sources.iiif import IIIFSourceAdapter
from iiif_downloader.sources.mets import MetsSourceAdapter

_ADAPTERS: dict[str, SourceAdapter] = {
    "iiif": IIIFSourceAdapter(),
    "mets": MetsSourceAdapter(),
}


def get_adapter(format_id: str) -> SourceAdapter:
    """Return the source adapter for a format identifier.

    Args:
        format_id: Format name (e.g. "iiif", "mets").

    Returns:
        SourceAdapter instance for the format.

    Raises:
        ValueError: If the format is not supported.
    """
    key = format_id.lower().strip()
    adapter = _ADAPTERS.get(key)
    if adapter is None:
        supported = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"Unsupported format '{format_id}'. Supported: {supported}")
    return adapter


def supported_formats() -> list[str]:
    """Return sorted list of supported format identifiers.

    Returns:
        list: Supported format ids.
    """
    return sorted(_ADAPTERS)


__all__ = [
    "PageItem",
    "SourceAdapter",
    "SourceDocument",
    "IIIFSourceAdapter",
    "MetsSourceAdapter",
    "get_adapter",
    "supported_formats",
]
