"""Metadata extraction and saving functionality."""

from __future__ import annotations

import os
from typing import Any

from iiif_downloader.sources.base import SourceDocument


def _output_dir_from_filename(filename: str | None, output_folder: str | None) -> str:
    """Resolve the metadata output directory.

    Args:
        filename: Source basename, if known.
        output_folder: Explicit output folder override.

    Returns:
        str: Output directory path.
    """
    if output_folder:
        return output_folder
    if filename:
        return os.path.splitext(filename)[0]
    return "iiif_images"


def save_metadata(
    manifest_data: dict[str, Any], output_folder: str | None = None
) -> None:
    """Extract and save metadata from an IIIF manifest to a text file.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        output_folder: Optional output directory path
    """
    manifest = manifest_data["content"]
    base_filename = _output_dir_from_filename(
        manifest_data.get("filename"), output_folder
    )
    os.makedirs(base_filename, exist_ok=True)
    metadata_file = os.path.join(base_filename, "metadata.txt")

    with open(metadata_file, "w", encoding="utf-8") as f:
        f.write("IIIF Manifest Metadata\n")
        f.write("=" * 50 + "\n\n")

        # Basic manifest information
        if "label" in manifest:
            f.write(f"Title: {manifest['label']}\n")
        if "description" in manifest:
            f.write(f"Description: {manifest['description']}\n")
        if "@id" in manifest:
            f.write(f"Manifest ID: {manifest['@id']}\n")
        if "attribution" in manifest:
            f.write(f"Attribution: {manifest['attribution']}\n")
        if "license" in manifest:
            f.write(f"License: {manifest['license']}\n")

        f.write("\n")

        # Sequence information
        if "sequences" in manifest and manifest["sequences"]:
            sequence = manifest["sequences"][0]
            if "label" in sequence:
                f.write(f"Sequence: {sequence['label']}\n")

            # Canvas count
            if "canvases" in sequence:
                f.write(f"Number of pages/canvases: {len(sequence['canvases'])}\n")

                # Canvas details
                f.write("\nCanvas Details:\n")
                f.write("-" * 30 + "\n")
                for idx, canvas in enumerate(sequence["canvases"]):
                    f.write(f"\nCanvas {idx + 1}:\n")
                    if "label" in canvas:
                        f.write(f"  Label: {canvas['label']}\n")
                    if "width" in canvas and "height" in canvas:
                        f.write(
                            f"  Dimensions: {canvas['width']} x {canvas['height']}\n"
                        )
                    if "images" in canvas and canvas["images"]:
                        image = canvas["images"][0]
                        if "resource" in image and "service" in image["resource"]:
                            service_id = image["resource"]["service"]["@id"]
                            f.write(f"  Image service: {service_id}\n")

        # Metadata section if available
        if "metadata" in manifest:
            f.write("\nAdditional Metadata:\n")
            f.write("-" * 30 + "\n")
            for item in manifest["metadata"]:
                if "label" in item and "value" in item:
                    f.write(f"{item['label']}: {item['value']}\n")

        # Rights information
        if "rights" in manifest:
            f.write(f"\nRights: {manifest['rights']}\n")

        # Viewing direction
        if "viewingDirection" in manifest:
            f.write(f"Viewing Direction: {manifest['viewingDirection']}\n")

        # Viewing hint
        if "viewingHint" in manifest:
            f.write(f"Viewing Hint: {manifest['viewingHint']}\n")

    print(f"Metadata saved to: {metadata_file}")


def _write_marc_record(handle: Any, record: dict[str, Any], record_index: int) -> None:
    """Write one parsed MARC record to a metadata file handle.

    Args:
        handle: Open text file handle.
        record: Parsed MARC record dict.
        record_index: 1-based record index for headings.
    """
    handle.write(f"\nMARC Record {record_index}\n")
    handle.write("-" * 30 + "\n")

    leader = record.get("leader")
    if leader:
        handle.write(f"Leader: {leader}\n")

    controlfields = record.get("controlfields") or {}
    for tag, value in controlfields.items():
        handle.write(f"ControlField {tag}: {value}\n")

    for datafield in record.get("datafields") or []:
        tag = datafield.get("tag", "???")
        ind1 = datafield.get("ind1", " ")
        ind2 = datafield.get("ind2", " ")
        handle.write(f"DataField {tag} ind1={ind1!r} ind2={ind2!r}\n")
        for subfield in datafield.get("subfields") or []:
            code = subfield.get("code", "?")
            value = subfield.get("value", "")
            handle.write(f"  ${code}: {value}\n")


def save_source_metadata(
    document: SourceDocument, output_folder: str | None = None
) -> None:
    """Save metadata from a SourceDocument (IIIF or METS).

    Args:
        document: Loaded source document.
        output_folder: Optional output directory path.
    """
    if document.format_id == "iiif" and isinstance(document.content, dict):
        save_metadata(
            {"content": document.content, "filename": document.filename},
            output_folder=output_folder,
        )
        return

    if document.format_id == "mets":
        save_mets_metadata(document, output_folder=output_folder)
        return

    # Fallback: dump structured metadata dict.
    base_filename = _output_dir_from_filename(document.filename, output_folder)
    os.makedirs(base_filename, exist_ok=True)
    metadata_file = os.path.join(base_filename, "metadata.txt")
    with open(metadata_file, "w", encoding="utf-8") as handle:
        handle.write(f"{document.format_id.upper()} Metadata\n")
        handle.write("=" * 50 + "\n\n")
        if document.title:
            handle.write(f"Title: {document.title}\n")
        handle.write(f"Pages: {len(document.pages)}\n")
        for key, value in document.metadata.items():
            if key in {"marc_records", "manifest"}:
                continue
            handle.write(f"{key}: {value}\n")
    print(f"Metadata saved to: {metadata_file}")


def save_mets_metadata(
    document: SourceDocument, output_folder: str | None = None
) -> None:
    """Save METS LABEL and MARC record fields to a text file.

    Args:
        document: Loaded METS SourceDocument.
        output_folder: Optional output directory path.
    """
    base_filename = _output_dir_from_filename(document.filename, output_folder)
    os.makedirs(base_filename, exist_ok=True)
    metadata_file = os.path.join(base_filename, "metadata.txt")
    meta = document.metadata

    with open(metadata_file, "w", encoding="utf-8") as handle:
        handle.write("METS Metadata\n")
        handle.write("=" * 50 + "\n\n")

        label = meta.get("label") or document.title
        if label:
            handle.write(f"LABEL: {label}\n")
        if meta.get("objid"):
            handle.write(f"OBJID: {meta['objid']}\n")
        if meta.get("profile"):
            handle.write(f"Profile: {meta['profile']}\n")
        handle.write(
            f"Number of pages: {meta.get('page_count', len(document.pages))}\n"
        )

        marc_records = meta.get("marc_records") or []
        if marc_records:
            handle.write("\nMARC Records\n")
            handle.write("=" * 50 + "\n")
            for idx, record in enumerate(marc_records, start=1):
                _write_marc_record(handle, record, idx)
        else:
            handle.write("\nNo MARC records found in dmdSec.\n")

    print(f"Metadata saved to: {metadata_file}")
