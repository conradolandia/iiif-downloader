"""Tests for IIIFDownloader.download_one."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from iiif_downloader.downloader import IIIFDownloader

SAMPLE_MANIFEST: dict[str, Any] = {
    "@context": "http://iiif.io/api/presentation/2/context.json",
    "@type": "sc:Manifest",
    "@id": "https://example.com/manifest.json",
    "label": "Test Manifest",
    "sequences": [
        {
            "@type": "sc:Sequence",
            "canvases": [
                {
                    "@id": "https://example.com/canvas/1",
                    "@type": "sc:Canvas",
                    "label": "1r",
                    "width": 1000,
                    "height": 1500,
                    "images": [
                        {
                            "@type": "oa:Annotation",
                            "resource": {
                                "@id": "https://example.com/image/1.jpg",
                                "@type": "dctypes:Image",
                                "format": "image/jpeg",
                                "width": 1000,
                                "height": 1500,
                                "service": {
                                    "@context": "http://iiif.io/api/image/2/context.json",
                                    "@id": "https://example.com/iiif/image1",
                                    "profile": "http://iiif.io/api/image/2/level2.json",
                                },
                            },
                        }
                    ],
                }
            ],
        }
    ],
}

SAMPLE_IMAGE_INFO: dict[str, Any] = {
    "@id": "https://example.com/iiif/image1",
    "width": 1000,
    "height": 1500,
    "profile": "http://iiif.io/api/image/2/level2.json",
}


def _manifest_data(tmp_path: Path) -> dict[str, Any]:
    """Build manifest_data dict for IIIFDownloader."""
    return {
        "content": SAMPLE_MANIFEST,
        "filename": str(tmp_path / "test-manifest"),
        "source": "https://example.com/manifest.json",
    }


def test_download_one_passes_session_manager(tmp_path: Path) -> None:
    """download_one must pass session_manager to fetch_image_info, not headers.

    Regression: passing headers caused dict.get(..., timeout=30) and
    'dict.get() takes no keyword arguments'.
    """
    downloader = IIIFDownloader(_manifest_data(tmp_path), output_folder=str(tmp_path))

    with (
        patch(
            "iiif_downloader.downloader.fetch_image_info",
            return_value=SAMPLE_IMAGE_INFO,
        ) as mock_fetch,
        patch(
            "iiif_downloader.downloader.download_image_stream",
            return_value=(True, str(tmp_path / "out.jpeg"), 100, 1),
        ),
        patch("iiif_downloader.downloader.Progress") as mock_progress,
    ):
        mock_progress.return_value.__enter__ = MagicMock(
            return_value=MagicMock(
                add_task=MagicMock(return_value=0), update=MagicMock()
            )
        )
        mock_progress.return_value.__exit__ = MagicMock(return_value=False)

        downloader.download_one(1)

    mock_fetch.assert_called_once()
    args, _kwargs = mock_fetch.call_args
    assert args[0] == "https://example.com/iiif/image1"
    assert args[1] is downloader.session_manager
    assert args[1] is not downloader.headers
