"""Tests for IIIF size limit and max_edge derivation."""

from __future__ import annotations

from typing import Any

from iiif_downloader.manifest import (
    ImageSizeLimits,
    get_image_size_from_info,
    max_requestable_width,
)
from iiif_downloader.server_capabilities import capabilities_from_info
from iiif_downloader.servers import BODLEIAN_ADAPTER

# Bodleian Ashmole 304 canvas 49 dimensions / limits
BODLEIAN_WIDTH = 5412
BODLEIAN_HEIGHT = 6437
BODLEIAN_INFO: dict[str, Any] = {
    "width": BODLEIAN_WIDTH,
    "height": BODLEIAN_HEIGHT,
    "sizes": [
        {"width": 169, "height": 201},
        {"width": 338, "height": 402},
        {"width": 676, "height": 804},
        {"width": 1353, "height": 1609},
        {"width": 2706, "height": 3218},
    ],
    "profile": [
        "http://iiif.io/api/image/2/level2.json",
        {"maxWidth": 4000, "maxHeight": 4000},
    ],
}


def test_bodleian_declared_limits_use_integer_math() -> None:
    """Declared maxHeight must not float-overshoot into a hang-prone width."""
    capped = max_requestable_width(
        BODLEIAN_WIDTH,
        BODLEIAN_HEIGHT,
        ImageSizeLimits(max_width=4000, max_height=4000, max_area=None),
    )
    # Integer path yields 3363; Bodleian slack then selects 3362
    assert capped == 3363
    assert (capped * BODLEIAN_HEIGHT + BODLEIAN_WIDTH - 1) // BODLEIAN_WIDTH <= 4000


def test_bodleian_slack_requests_3362() -> None:
    """Bodleian adapter slack avoids exact max size that 504s for some images."""
    size = get_image_size_from_info(
        BODLEIAN_INFO,
        requested_size=None,
        max_edge=None,
        size_slack=BODLEIAN_ADAPTER.size_limit_slack,
    )
    assert BODLEIAN_ADAPTER.size_limit_slack == 1
    assert size == 3362


def test_bodleian_declared_limits_without_slack() -> None:
    """Without slack, integer cap is 3363 (still within ceil height 4000)."""
    size = get_image_size_from_info(BODLEIAN_INFO, requested_size=None, max_edge=None)
    assert size == 3363


def test_capabilities_from_info_skips_size_fields() -> None:
    """Declared capabilities leave max_edge unset for per-image sizing."""
    service_id = (
        "https://iiif.bodleian.ox.ac.uk/iiif/image/c7eb3bf3-db95-4f75-8ef4-f19cecdd9c6b"
    )
    caps = capabilities_from_info(service_id, BODLEIAN_INFO, adapter=BODLEIAN_ADAPTER)
    assert caps.preferred_format == "jpg"
    assert caps.max_edge is None
    assert caps.max_test_size is None
    assert caps.server_domain == "https://iiif.bodleian.ox.ac.uk"
