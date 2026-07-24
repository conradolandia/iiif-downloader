"""METS source adapter."""

from __future__ import annotations

import http.cookiejar
import os
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from rich.console import Console

from iiif_downloader.auth_detector import (
    get_auth_error_message,
    is_authentication_required,
)
from iiif_downloader.session_manager import SessionManager
from iiif_downloader.sources.base import PageItem, SourceDocument

METS_NS = "http://www.loc.gov/METS/"
XLINK_NS = "http://www.w3.org/1999/xlink"
MARC_NS = "http://www.loc.gov/MARC21/slim"

NS = {
    "mets": METS_NS,
    "xlink": XLINK_NS,
    "marc": MARC_NS,
}


def _local(tag: str) -> str:
    """Return a Clark-notation tag in the METS namespace.

    Args:
        tag: Local element name.

    Returns:
        str: Namespaced tag.
    """
    return f"{{{METS_NS}}}{tag}"


def _find_first(parent: ET.Element, *tags: str) -> ET.Element | None:
    """Return the first matching child by tag, ignoring Element truthiness.

    Empty elements (e.g. ``FLocat``) are falsy in ElementTree, so callers must
    not use ``elem or other``.

    Args:
        parent: Parent XML element.
        *tags: Candidate tags in preference order.

    Returns:
        Matching element, or None.
    """
    for tag in tags:
        found = parent.find(tag)
        if found is not None:
            return found
    return None


def _findall_first(parent: ET.Element, *tags: str) -> list[ET.Element]:
    """Return findall results for the first tag that matches any elements.

    Args:
        parent: Parent XML element.
        *tags: Candidate tags in preference order.

    Returns:
        list: Matching elements (possibly empty).
    """
    for tag in tags:
        found = list(parent.findall(tag))
        if found:
            return found
    return []


def _xlink_href(element: ET.Element) -> str | None:
    """Read an xlink:href attribute from an element.

    Args:
        element: XML element that may carry xlink:href.

    Returns:
        Href string, or None if missing.
    """
    return element.get(f"{{{XLINK_NS}}}href") or element.get("href")


def _mime_to_extension(mime_type: str | None) -> str:
    """Map a MIME type to a file extension.

    Args:
        mime_type: MIME type string, or None.

    Returns:
        str: File extension without a leading dot.
    """
    if not mime_type:
        return "jpeg"
    mapping = {
        "image/jpeg": "jpeg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/tiff": "tiff",
        "image/tif": "tif",
        "image/jp2": "jp2",
        "image/jpx": "jpx",
        "application/pdf": "pdf",
    }
    return mapping.get(mime_type.lower(), mime_type.split("/")[-1] or "jpeg")


def _text(element: ET.Element | None) -> str | None:
    """Return stripped element text, or None if empty.

    Args:
        element: XML element or None.

    Returns:
        Stripped text, or None.
    """
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def parse_marc_record(record: ET.Element) -> dict[str, Any]:
    """Parse a MARC21 XML record into a structured dict.

    Args:
        record: ``<record>`` element (MARC or un-namespaced).

    Returns:
        dict: Parsed leader, control fields, and data fields.
    """

    # Support both namespaced and bare MARC elements.
    def findall(tag: str) -> list[ET.Element]:
        return _findall_first(record, f"{{{MARC_NS}}}{tag}", tag)

    def find(tag: str) -> ET.Element | None:
        return _find_first(record, f"{{{MARC_NS}}}{tag}", tag)

    parsed: dict[str, Any] = {"controlfields": {}, "datafields": []}

    leader = find("leader")
    if leader is not None:
        parsed["leader"] = _text(leader)

    for control in findall("controlfield"):
        tag = control.get("tag")
        if tag:
            parsed["controlfields"][tag] = _text(control)

    for datafield in findall("datafield"):
        tag = datafield.get("tag")
        if not tag:
            continue
        subfields: list[dict[str, str]] = []
        for sub in _findall_first(datafield, f"{{{MARC_NS}}}subfield", "subfield"):
            code = sub.get("code")
            value = _text(sub)
            if code and value is not None:
                subfields.append({"code": code, "value": value})
        parsed["datafields"].append(
            {
                "tag": tag,
                "ind1": datafield.get("ind1", " "),
                "ind2": datafield.get("ind2", " "),
                "subfields": subfields,
            }
        )

    return parsed


class MetsSourceAdapter:
    """Load METS XML documents and extract main fileGrp image pages."""

    format_id: str = "mets"

    def load(
        self, source: str, cookie_file: str | None = None
    ) -> SourceDocument | None:
        """Load a METS document from a URL or local file.

        Args:
            source: URL or filesystem path of the METS XML.
            cookie_file: Optional cookie file for protected hosts.

        Returns:
            SourceDocument on success, or None on failure.
        """
        xml_text = self._read_source(source, cookie_file=cookie_file)
        if xml_text is None:
            return None

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            print(f"Error parsing METS XML: {exc}")
            return None

        if not self._is_mets_root(root):
            print("Error: root element is not a METS document")
            return None

        files_by_id = self._parse_first_file_group(root)
        if not files_by_id:
            print("Error: no files found in the first METS fileGrp")
            return None

        pages = self._pages_from_struct_map(root, files_by_id)
        if not pages:
            # Fall back to fileGrp order when structMap is missing.
            pages = [
                PageItem(
                    index=idx,
                    url=info["url"],
                    label=None,
                    mime_type=info.get("mime_type"),
                    file_id=file_id,
                )
                for idx, (file_id, info) in enumerate(files_by_id.items())
            ]

        title = root.get("LABEL")
        marc_records = self._extract_marc_records(root)
        metadata = {
            "format": "mets",
            "label": title,
            "objid": root.get("OBJID"),
            "profile": root.get("PROFILE"),
            "page_count": len(pages),
            "marc_records": marc_records,
        }

        filename = (
            os.path.basename(urlparse(source).path)
            if source.startswith(("http://", "https://"))
            else os.path.basename(source)
        )

        return SourceDocument(
            format_id=self.format_id,
            filename=filename or "mets.xml",
            content=root,
            title=title,
            pages=pages,
            metadata=metadata,
            raw_path=source,
        )

    def _is_mets_root(self, root: ET.Element) -> bool:
        """Return True if the element looks like a METS root.

        Args:
            root: Parsed XML root element.

        Returns:
            bool: True when the tag is mets:mets (with or without namespace).
        """
        return root.tag in {_local("mets"), "mets"}

    def _read_source(self, source: str, cookie_file: str | None = None) -> str | None:
        """Read METS XML text from a URL or local path.

        Args:
            source: URL or filesystem path.
            cookie_file: Optional cookie file path.

        Returns:
            XML text, or None on error.
        """
        if source.startswith("http://") or source.startswith("https://"):
            console = Console()
            try:
                with SessionManager(cookie_file=cookie_file) as session_manager:
                    response = session_manager.get(source, timeout=30)
                    if is_authentication_required(response):
                        print()
                        console.print(
                            get_auth_error_message(source, cookie_file, response)
                        )
                        return None
                    response.raise_for_status()
                    return response.text
            except (FileNotFoundError, OSError, http.cookiejar.LoadError) as exc:
                print()
                print(f"Error loading cookie file: {exc}")
                return None
            except requests.RequestException as exc:
                print(f"Error fetching the METS document: {exc}")
                return None
        try:
            with open(source, encoding="utf-8") as handle:
                return handle.read()
        except FileNotFoundError:
            print(f"File not found: {source}")
            return None
        except OSError as exc:
            print(f"Error reading file: {exc}")
            return None

    def _parse_first_file_group(
        self, root: ET.Element
    ) -> dict[str, dict[str, str | None]]:
        """Parse files from the first fileGrp under fileSec.

        v1 rule: when multiple fileGrps exist (and USE is absent or ignored),
        only the first group is used.

        Args:
            root: METS root element.

        Returns:
            dict: Mapping of file ID -> {url, mime_type, seq}.
        """
        file_sec = _find_first(root, _local("fileSec"), "fileSec")
        if file_sec is None:
            return {}

        file_groups = _findall_first(file_sec, _local("fileGrp"), "fileGrp")
        if not file_groups:
            return {}

        first_group = file_groups[0]
        files: dict[str, dict[str, str | None]] = {}

        for file_el in _findall_first(first_group, _local("file"), "file"):
            file_id = file_el.get("ID")
            if not file_id:
                continue
            flocat = _find_first(file_el, _local("FLocat"), "FLocat")
            if flocat is None:
                continue
            href = _xlink_href(flocat)
            if not href:
                continue
            files[file_id] = {
                "url": href,
                "mime_type": file_el.get("MIMETYPE"),
                "seq": file_el.get("SEQ"),
            }

        return files

    def _pages_from_struct_map(
        self,
        root: ET.Element,
        files_by_id: dict[str, dict[str, str | None]],
    ) -> list[PageItem]:
        """Build ordered pages from the physical structMap.

        Args:
            root: METS root element.
            files_by_id: File ID map from the first fileGrp.

        Returns:
            list: PageItem entries in structMap order.
        """
        struct_maps = _findall_first(root, _local("structMap"), "structMap")
        if not struct_maps:
            return []

        # Prefer PHYSICAL structMap when present.
        struct_map = next(
            (sm for sm in struct_maps if (sm.get("TYPE") or "").upper() == "PHYSICAL"),
            struct_maps[0],
        )

        pages: list[PageItem] = []
        seen_file_ids: set[str] = set()

        for div in struct_map.iter():
            if div.tag not in {_local("div"), "div"}:
                continue
            if (div.get("TYPE") or "").lower() != "page":
                continue

            fptr = _find_first(div, _local("fptr"), "fptr")
            if fptr is None:
                continue
            file_id = fptr.get("FILEID")
            if not file_id or file_id not in files_by_id:
                continue
            if file_id in seen_file_ids:
                continue

            info = files_by_id[file_id]
            url = info.get("url")
            if not url:
                continue

            seen_file_ids.add(file_id)
            pages.append(
                PageItem(
                    index=len(pages),
                    url=url,
                    label=div.get("LABEL"),
                    mime_type=info.get("mime_type"),
                    file_id=file_id,
                )
            )

        return pages

    def _extract_marc_records(self, root: ET.Element) -> list[dict[str, Any]]:
        """Extract MARC records from dmdSec mdWrap blocks.

        Args:
            root: METS root element.

        Returns:
            list: Parsed MARC record dicts.
        """
        records: list[dict[str, Any]] = []

        for dmd in _findall_first(root, _local("dmdSec"), "dmdSec"):
            for md_wrap in _findall_first(dmd, _local("mdWrap"), "mdWrap"):
                md_type = (md_wrap.get("MDTYPE") or "").upper()
                if md_type != "MARC":
                    continue
                xml_data = _find_first(md_wrap, _local("xmlData"), "xmlData")
                if xml_data is None:
                    continue
                for record in xml_data.iter():
                    if record.tag in {f"{{{MARC_NS}}}record", "record"}:
                        records.append(parse_marc_record(record))

        return records


def extension_for_page(page: PageItem) -> str:
    """Return a file extension for a METS page.

    Args:
        page: Page item with optional mime_type.

    Returns:
        str: Extension without a leading dot.
    """
    return _mime_to_extension(page.mime_type)
