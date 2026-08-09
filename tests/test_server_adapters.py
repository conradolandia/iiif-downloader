"""Tests for host-specific server adapters."""

from __future__ import annotations

from iiif_downloader.servers import (
    BODLEIAN_ADAPTER,
    DEFAULT_ADAPTER,
    resolve_adapter,
    resolve_adapter_for_host,
)


def test_resolve_bodleian_image_host() -> None:
    """Bodleian image service URLs select the Bodleian adapter."""
    url = (
        "https://iiif.bodleian.ox.ac.uk/iiif/image/c7eb3bf3-db95-4f75-8ef4-f19cecdd9c6b"
    )
    adapter = resolve_adapter(url)
    assert adapter is BODLEIAN_ADAPTER
    assert adapter.name == "bodleian"
    assert adapter.skip_content_length_head is True
    assert adapter.skip_capability_probe is True


def test_resolve_bodleian_manifest_host() -> None:
    """Bodleian manifest URLs also match the Bodleian adapter."""
    url = (
        "https://iiif.bodleian.ox.ac.uk/iiif/manifest/"
        "b6391fb2-a52e-4c69-bc13-02c04a9256a7.json"
    )
    assert resolve_adapter(url).name == "bodleian"


def test_resolve_unknown_host_uses_default() -> None:
    """Unknown hosts fall back to the default adapter."""
    adapter = resolve_adapter("https://example.org/iiif/image/abc")
    assert adapter is DEFAULT_ADAPTER
    assert adapter.name == "default"
    assert adapter.skip_content_length_head is False
    assert adapter.skip_capability_probe is True


def test_resolve_adapter_for_host() -> None:
    """Bare hostname matching works for Bodleian and others."""
    assert resolve_adapter_for_host("iiif.bodleian.ox.ac.uk") is BODLEIAN_ADAPTER
    assert resolve_adapter_for_host("digital.bodleian.ox.ac.uk") is BODLEIAN_ADAPTER
    assert resolve_adapter_for_host("example.com") is DEFAULT_ADAPTER


def test_bodleian_trusts_declared_limits() -> None:
    """Bodleian trusts declared max size caps when present."""
    assert BODLEIAN_ADAPTER.should_trust_declared_limits(True) is True
    assert BODLEIAN_ADAPTER.should_trust_declared_limits(False) is False


def test_bodleian_fallback_probe_sizes_are_conservative() -> None:
    """Bodleian fallback list prefers round widths under the desired size."""
    sizes = BODLEIAN_ADAPTER.fallback_probe_sizes(3363)
    assert sizes[0] == 3363
    assert 2000 in sizes
    assert 1000 in sizes
    assert 128 not in sizes  # default adapter includes 128; Bodleian omits it
