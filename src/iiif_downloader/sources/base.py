"""Shared types and protocol for source adapters."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PageItem:
    """A single downloadable page/image from a source document.

    Attributes:
        index: Zero-based page index in download order.
        url: Absolute URL of the image file.
        label: Optional human-readable page label (e.g. folio number).
        mime_type: Optional MIME type from the source (e.g. image/jpeg).
        file_id: Optional source-specific file identifier.
    """

    index: int
    url: str
    label: str | None = None
    mime_type: str | None = None
    file_id: str | None = None


@dataclass
class SourceDocument:
    """Loaded source document ready for metadata extraction and download.

    Attributes:
        format_id: Adapter format identifier (e.g. "iiif", "mets").
        filename: Basename of the source file or URL path.
        content: Format-specific parsed content (dict, Element, etc.).
        title: Optional document title/label.
        pages: Ordered list of downloadable pages.
        metadata: Structured metadata fields for dumping.
        raw_path: Original source path or URL.
    """

    format_id: str
    filename: str
    content: Any
    title: str | None = None
    pages: list[PageItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw_path: str | None = None


class SourceAdapter(Protocol):
    """Protocol for pluggable source format adapters."""

    format_id: str

    def load(
        self, source: str, cookie_file: str | None = None
    ) -> SourceDocument | None:
        """Load and parse a source document from a URL or local path.

        Args:
            source: URL or filesystem path of the source document.
            cookie_file: Optional Netscape/Mozilla cookie file path.

        Returns:
            SourceDocument on success, or None on failure.
        """
        ...
