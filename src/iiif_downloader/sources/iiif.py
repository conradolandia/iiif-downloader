"""IIIF Presentation API source adapter."""

from typing import Any

from iiif_downloader.manifest import (
    detect_manifest_version,
    get_canvas_label,
    get_canvases_from_manifest,
    get_image_service_from_canvas,
    load_manifest,
)
from iiif_downloader.sources.base import PageItem, SourceDocument


class IIIFSourceAdapter:
    """Load IIIF Presentation API manifests (v2.1 / v3.0)."""

    format_id: str = "iiif"

    def load(
        self, source: str, cookie_file: str | None = None
    ) -> SourceDocument | None:
        """Load an IIIF manifest and build a SourceDocument.

        Args:
            source: URL or file path of the IIIF manifest.
            cookie_file: Optional cookie file for protected hosts.

        Returns:
            SourceDocument with pages derived from canvases, or None on error.
        """
        manifest_data = load_manifest(source, cookie_file=cookie_file)
        if not manifest_data:
            return None

        content = manifest_data["content"]
        version = detect_manifest_version(content)
        canvases = get_canvases_from_manifest(content)
        pages = self._pages_from_canvases(canvases, version)

        title = self._extract_title(content)
        metadata = self._build_metadata(content, version, len(pages))

        return SourceDocument(
            format_id=self.format_id,
            filename=manifest_data["filename"],
            content=content,
            title=title,
            pages=pages,
            metadata=metadata,
            raw_path=source,
        )

    def _pages_from_canvases(
        self, canvases: list[dict[str, Any]], version: str
    ) -> list[PageItem]:
        """Convert IIIF canvases into PageItem entries.

        Note:
            IIIF downloads still resolve the final image URL via info.json
            in IIIFDownloader. Here we store the image service URL when found.

        Args:
            canvases: Canvas objects from the manifest.
            version: Detected IIIF version string.

        Returns:
            list: PageItem entries in canvas order.
        """
        pages: list[PageItem] = []
        for idx, canvas in enumerate(canvases):
            service_url = get_image_service_from_canvas(canvas, version)
            pages.append(
                PageItem(
                    index=idx,
                    url=service_url or "",
                    label=get_canvas_label(canvas),
                    mime_type=None,
                    file_id=canvas.get("@id") or canvas.get("id"),
                )
            )
        return pages

    def _extract_title(self, content: dict[str, Any]) -> str | None:
        """Extract a human-readable title from the manifest.

        Args:
            content: Parsed IIIF manifest dict.

        Returns:
            Title string, or None if unavailable.
        """
        label = content.get("label")
        if label is None:
            return None
        if isinstance(label, str):
            return label
        if isinstance(label, dict):
            for lang in ("en", "none", "default"):
                if lang in label and label[lang]:
                    value = label[lang]
                    return value[0] if isinstance(value, list) else str(value)
            if label:
                first = next(iter(label.values()))
                return first[0] if isinstance(first, list) else str(first)
        if isinstance(label, list) and label:
            first = label[0]
            return first if isinstance(first, str) else str(first)
        return None

    def _build_metadata(
        self, content: dict[str, Any], version: str, page_count: int
    ) -> dict[str, Any]:
        """Build a metadata payload for dumping.

        Args:
            content: Parsed IIIF manifest dict.
            version: Detected IIIF version.
            page_count: Number of pages/canvases.

        Returns:
            dict: Structured metadata for save_metadata.
        """
        return {
            "format": "iiif",
            "version": version,
            "title": self._extract_title(content),
            "page_count": page_count,
            "manifest": content,
        }
