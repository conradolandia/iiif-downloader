"""Tests for IIIF size limit and max_edge derivation."""

from __future__ import annotations

from typing import Any

from iiif_downloader.manifest import (
    ImageSizeLimits,
    get_image_size_from_info,
    max_requestable_width,
)
from iiif_downloader.server_capabilities import (
    _derive_max_edge,
    capabilities_from_info,
)
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


def test_derive_max_edge_uses_ceil_not_truncation() -> None:
    """Probed width must survive reverse max_edge application.

    Truncation gave max_edge=3999 → request width 3362, which hung on Bodleian.
    Ceil gives max_edge=4000 → width 3363 (the probed working size).
    """
    probed_width = 3363
    max_edge = _derive_max_edge(probed_width, BODLEIAN_WIDTH, BODLEIAN_HEIGHT)
    assert max_edge == 4000

    # Old truncation behavior (regression guard)
    truncated_edge = int(probed_width * BODLEIAN_HEIGHT / BODLEIAN_WIDTH)
    assert truncated_edge == 3999
    assert int(truncated_edge * BODLEIAN_WIDTH / BODLEIAN_HEIGHT) == 3362

    capped = max_requestable_width(
        BODLEIAN_WIDTH,
        BODLEIAN_HEIGHT,
        ImageSizeLimits(max_width=4000, max_height=4000, max_area=None),
        max_edge=max_edge,
    )
    assert capped == probed_width


def test_bodleian_image_size_with_probed_max_edge() -> None:
    """Full download path must request the probed width, not one pixel less."""
    probed_width = 3363
    max_edge = _derive_max_edge(probed_width, BODLEIAN_WIDTH, BODLEIAN_HEIGHT)
    size = get_image_size_from_info(
        BODLEIAN_INFO, requested_size=None, max_edge=max_edge
    )
    assert size == probed_width


def test_bodleian_declared_limits_without_probe() -> None:
    """Skip-probe path sizes from info.json alone (no global max_edge)."""
    size = get_image_size_from_info(BODLEIAN_INFO, requested_size=None, max_edge=None)
    # maxHeight 4000 → width int(4000 * 5412 / 6437) == 3363 (same as probed)
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
