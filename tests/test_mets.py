"""Tests for the METS source adapter and metadata dump."""

from __future__ import annotations

from pathlib import Path

from iiif_downloader.manifest import build_hybrid_filename
from iiif_downloader.metadata import save_mets_metadata
from iiif_downloader.sources import get_adapter, supported_formats
from iiif_downloader.sources.mets import MetsSourceAdapter, extension_for_page

FIXTURE = Path(__file__).parent / "fixtures" / "sample_mets.xml"


def test_supported_formats_includes_mets() -> None:
    """supported_formats lists iiif and mets."""
    formats = supported_formats()
    assert formats == ["iiif", "mets"]


def test_get_adapter_mets() -> None:
    """get_adapter returns the METS adapter."""
    adapter = get_adapter("mets")
    assert isinstance(adapter, MetsSourceAdapter)
    assert adapter.format_id == "mets"


def test_mets_parse_pages_from_struct_map() -> None:
    """METS adapter uses first fileGrp and structMap order/labels."""
    adapter = MetsSourceAdapter()
    document = adapter.load(str(FIXTURE))
    assert document is not None
    assert document.format_id == "mets"
    assert document.title == "[Liber commicus] / sample - Objeto digital"
    assert len(document.pages) == 4

    # Thumbnails from the second fileGrp must be ignored.
    assert all("thumbs" not in page.url for page in document.pages)

    assert document.pages[0].label == "[Cubierta]"
    assert document.pages[0].url == "https://example.com/images/0.jpg"
    assert document.pages[0].file_id == "FID0"

    assert document.pages[1].label is None
    assert document.pages[1].url == "https://example.com/images/1.jpg"

    assert document.pages[2].label == "1r"
    assert document.pages[3].label == "1v"
    assert document.pages[3].mime_type == "image/png"


def test_mets_marc_metadata_extracted() -> None:
    """METS adapter extracts LABEL and MARC record fields."""
    adapter = MetsSourceAdapter()
    document = adapter.load(str(FIXTURE))
    assert document is not None

    meta = document.metadata
    assert meta["label"] == document.title
    assert meta["objid"] == "1000017"
    assert meta["page_count"] == 4

    records = meta["marc_records"]
    assert len(records) == 2
    assert records[0]["controlfields"]["001"] == "BRM20090000711"
    assert records[0]["datafields"][0]["tag"] == "245"
    assert records[0]["datafields"][0]["subfields"][0] == {
        "code": "a",
        "value": "[Liber commicus]",
    }
    assert records[1]["controlfields"]["001"] == "BRMF20090000711"


def test_save_mets_metadata(tmp_path: Path) -> None:
    """save_mets_metadata writes LABEL and MARC fields."""
    adapter = MetsSourceAdapter()
    document = adapter.load(str(FIXTURE))
    assert document is not None

    out = tmp_path / "out"
    save_mets_metadata(document, output_folder=str(out))
    metadata_file = out / "metadata.txt"
    assert metadata_file.exists()
    text = metadata_file.read_text(encoding="utf-8")
    assert "METS Metadata" in text
    assert "LABEL: [Liber commicus] / sample - Objeto digital" in text
    assert "ControlField 001: BRM20090000711" in text
    assert "$a: [Liber commicus]" in text
    assert "DataField 852" in text


def test_build_hybrid_filename_page_prefix() -> None:
    """Hybrid filenames support a page index prefix."""
    assert (
        build_hybrid_filename("1r", 2, "jpeg", index_prefix="page")
        == "page-003_1r.jpeg"
    )
    assert (
        build_hybrid_filename(None, 1, "jpeg", fallback_prefix="page")
        == "page_002.jpeg"
    )


def test_extension_for_page() -> None:
    """MIME types map to file extensions."""
    adapter = MetsSourceAdapter()
    document = adapter.load(str(FIXTURE))
    assert document is not None
    assert extension_for_page(document.pages[0]) == "jpeg"
    assert extension_for_page(document.pages[3]) == "png"
