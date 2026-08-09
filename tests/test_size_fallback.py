"""Tests for download-time IIIF size negotiation and canvas fallbacks."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from iiif_downloader.image_downloader import (
    _remember_working_width,
    find_max_requestable_width,
)
from iiif_downloader.manifest import (
    get_image_info_from_canvas_resource,
    get_image_size_from_info,
)
from iiif_downloader.server_capabilities import ServerCapabilities

# Digirati / BL-style info: full size declared, sizes[] only lists small levels,
# maxWidth higher than what GET actually allows.
DIGIRATI_INFO: dict[str, Any] = {
    "@id": "https://bl.digirati.io/images/ark:/81055/example",
    "width": 4511,
    "height": 6041,
    "sizes": [
        {"width": 765, "height": 1024},
        {"width": 299, "height": 400},
        {"width": 150, "height": 200},
        {"width": 75, "height": 100},
    ],
    "profile": [
        "http://iiif.io/api/image/2/level2.json",
        {
            "formats": ["jpg", "tif", "gif", "png"],
            "maxWidth": 5000,
            "qualities": ["default", "color"],
        },
    ],
}


def test_digirati_declared_size_prefers_full_width() -> None:
    """Level2 + maxWidth must not collapse to the largest sizes[] entry."""
    size = get_image_size_from_info(DIGIRATI_INFO, requested_size=None, max_edge=None)
    # Portrait page: height 6041 > maxWidth 5000 → width capped as max edge
    expected = int(5000 * 4511 / 6041)
    assert size == expected
    assert size > 765  # not the largest sizes[] thumbnail
    assert size * 6041 / 4511 <= 5000 + 1  # scaled height near max edge


def test_digirati_portrait_page_caps_height_via_max_width() -> None:
    """Digirati rejects w, when scaled height would exceed maxWidth."""
    info: dict[str, Any] = {
        "width": 4781,
        "height": 6666,
        "profile": ["http://iiif.io/api/image/2/level2.json", {"maxWidth": 5000}],
    }
    size = get_image_size_from_info(info, requested_size=None, max_edge=None)
    assert size == int(5000 * 4781 / 6666)
    assert size * 6666 / 4781 <= 5000


def test_canvas_fallback_prefers_canvas_dimensions_over_body() -> None:
    """Presentation body often embeds a small default rendering; use canvas size."""
    canvas: dict[str, Any] = {
        "width": 4511,
        "height": 6041,
        "items": [
            {
                "items": [
                    {
                        "body": {
                            "width": 765,
                            "height": 1024,
                            "format": "image/jpeg",
                            "service": [
                                {
                                    "id": "https://example.com/iiif/img1",
                                    "type": "ImageService3",
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    info = get_image_info_from_canvas_resource(canvas, "3.0")
    assert info is not None
    assert info["width"] == 4511
    assert info["height"] == 6041
    assert get_image_size_from_info(info) == 4511


def test_find_max_requestable_width_binary_searches(monkeypatch: Any) -> None:
    """After rejection, find the largest width the server still accepts."""
    allowed_max = 3000

    def fake_allowed(
        service_id: str, width: int, image_format: str, session_manager: Any
    ) -> bool:
        _ = (service_id, image_format, session_manager)
        return width <= allowed_max

    monkeypatch.setattr(
        "iiif_downloader.image_downloader._width_is_allowed", fake_allowed
    )

    result = find_max_requestable_width(
        "https://example.com/iiif/img1",
        4511,
        "jpg",
        session_manager=MagicMock(),
        image_info=DIGIRATI_INFO,
    )
    assert result == allowed_max


def test_remember_working_width_tightens_capabilities() -> None:
    """Negotiated ceilings are stored for later images in the same run."""
    caps = ServerCapabilities(preferred_format="jpg", supports_full_size=False)
    _remember_working_width(caps, 3000, DIGIRATI_INFO)
    assert caps.max_test_size == 3000
    assert caps.max_edge is not None
    assert caps.max_edge >= 3000

    _remember_working_width(caps, 2800, DIGIRATI_INFO)
    assert caps.max_test_size == 2800

    _remember_working_width(caps, 3200, DIGIRATI_INFO)
    assert caps.max_test_size == 2800  # do not raise the ceiling
