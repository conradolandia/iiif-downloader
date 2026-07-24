"""Manifest loading and parsing functionality."""

import http.cookiejar
import json
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests
from rich.console import Console

from iiif_downloader.auth_detector import (
    get_auth_error_message,
    is_authentication_required,
)
from iiif_downloader.session_manager import SessionManager


@dataclass(frozen=True)
class ImageSizeLimits:
    """Maximum size constraints declared by an IIIF Image API service."""

    max_width: int | None = None
    max_height: int | None = None
    max_area: int | None = None

    @property
    def has_limits(self) -> bool:
        """Return True if any size constraint is set."""
        return (
            self.max_width is not None
            or self.max_height is not None
            or self.max_area is not None
        )


def detect_manifest_version(manifest_content):
    """Detect the IIIF Presentation API version of a manifest.

    Args:
        manifest_content: The parsed manifest JSON content

    Returns:
        str: The detected version ('2.1' or '3.0') or 'unknown'
    """
    # Check for explicit version in @context
    if "@context" in manifest_content:
        context = manifest_content["@context"]
        if isinstance(context, str):
            if "presentation/3" in context:
                return "3.0"
            elif "presentation/2" in context:
                return "2.1"
        elif isinstance(context, list):
            for ctx in context:
                if isinstance(ctx, str) and "presentation/3" in ctx:
                    return "3.0"
                elif isinstance(ctx, str) and "presentation/2" in ctx:
                    return "2.1"

    # Check for structural differences
    if "items" in manifest_content:
        return "3.0"
    elif "sequences" in manifest_content:
        return "2.1"

    return "unknown"


def get_canvases_from_manifest(manifest_content):
    """Extract canvases from a IIIF manifest, supporting both v2.1 and v3.0.

    Args:
        manifest_content: The parsed manifest JSON content

    Returns:
        list: List of canvas objects
    """
    version = detect_manifest_version(manifest_content)

    if version == "3.0":
        # IIIF v3.0: canvases are in 'items'
        return manifest_content.get("items", [])
    elif version == "2.1":
        # IIIF v2.1: canvases are in 'sequences[0].canvases'
        sequences = manifest_content.get("sequences", [])
        if sequences and "canvases" in sequences[0]:
            return sequences[0]["canvases"]
        return []
    else:
        # Fallback: try both structures
        if "items" in manifest_content:
            return manifest_content.get("items", [])
        elif "sequences" in manifest_content:
            sequences = manifest_content.get("sequences", [])
            if sequences and "canvases" in sequences[0]:
                return sequences[0]["canvases"]
        return []


def get_image_service_from_canvas(canvas, version):
    """Extract the image service URL from a canvas, supporting both v2.1 and v3.0.

    Args:
        canvas: The canvas object
        version: The detected IIIF version ('2.1' or '3.0')

    Returns:
        str: The image service URL, or None if not found
    """
    if version == "3.0":
        # IIIF v3.0: images are in items[0].items[0].body.service
        items = canvas.get("items", [])
        if items:
            first_item = items[0]
            if "items" in first_item and first_item["items"]:
                annotation = first_item["items"][0]
                if "body" in annotation and "service" in annotation["body"]:
                    service = annotation["body"]["service"]
                    if isinstance(service, list) and service:
                        # Prefer ImageService3 (with "id") over ImageService2 (with "@id")
                        for svc in service:
                            # Check for ImageService3 first (uses "id")
                            if svc.get("id"):
                                return svc.get("id")
                        # Fallback to ImageService2 (uses "@id")
                        for svc in service:
                            if svc.get("@id"):
                                return svc.get("@id")
                    elif isinstance(service, dict):
                        # Check both "id" (v3) and "@id" (v2)
                        return service.get("id") or service.get("@id")
    elif version == "2.1":
        # IIIF v2.1: images are in images[0].resource.service.@id
        images = canvas.get("images", [])
        if images and "resource" in images[0]:
            resource = images[0]["resource"]
            if "service" in resource:
                service = resource["service"]
                if isinstance(service, list) and service:
                    return service[0].get("@id")
                elif isinstance(service, dict):
                    return service.get("@id")

    return None


def detect_image_api_version(image_info):
    """Detect the IIIF Image API version from image info response.

    Args:
        image_info: The parsed image info JSON response

    Returns:
        str: The detected version ('1.1', '2.0', '2.1', '3.0') or 'unknown'
    """
    # Check for explicit version in profile
    if "profile" in image_info:
        profile = image_info["profile"]
        if isinstance(profile, str):
            if "image-api/3" in profile:
                return "3.0"
            elif "image-api/2" in profile:
                return "2.1"
            elif "image-api/1" in profile:
                return "1.1"
        elif isinstance(profile, list):
            for prof in profile:
                if isinstance(prof, str):
                    if "image-api/3" in prof:
                        return "3.0"
                    elif "image-api/2" in prof:
                        return "2.1"
                    elif "image-api/1" in prof:
                        return "1.1"

    # Check for structural differences
    if "sizes" in image_info:
        return "2.1"  # IIIF Image API 2.x has sizes array
    elif "width" in image_info and "height" in image_info:
        return "1.1"  # IIIF Image API 1.x has basic width/height

    return "unknown"


def get_image_info_from_canvas_resource(
    canvas: dict, version: str
) -> dict[str, Any] | None:
    """Extract image info from canvas resource when info.json is unavailable.

    Args:
        canvas: Canvas object from IIIF manifest
        version: The detected IIIF version ('2.1' or '3.0')

    Returns:
        dict: Pseudo image info dict with width, height, format, and service ID, or None
    """
    if version == "2.1":
        # IIIF v2.1: images are in images[0].resource
        images = canvas.get("images", [])
        if images and "resource" in images[0]:
            resource = images[0]["resource"]
            width = resource.get("width")
            height = resource.get("height")
            format_str = resource.get("format", "jpg")

            # Get service ID
            service_id = None
            if "service" in resource:
                service = resource["service"]
                if isinstance(service, list) and service:
                    service_id = service[0].get("@id")
                elif isinstance(service, dict):
                    service_id = service.get("@id")

            if width and height and service_id:
                # Create pseudo image_info dict
                return {
                    "width": width,
                    "height": height,
                    "@id": service_id,
                    "id": service_id,
                    "format": format_str,
                }
    elif version == "3.0":
        # IIIF v3.0: images are in items[0].items[0].body
        items = canvas.get("items", [])
        if items:
            first_item = items[0]
            if "items" in first_item and first_item["items"]:
                annotation = first_item["items"][0]
                if "body" in annotation:
                    body = annotation["body"]
                    width = body.get("width")
                    height = body.get("height")
                    format_str = body.get("format", "jpg")

                    # Get service ID
                    service_id = None
                    if "service" in body:
                        service = body["service"]
                        if isinstance(service, list) and service:
                            # Prefer ImageService3 (with "id") over ImageService2 (with "@id")
                            for svc in service:
                                if svc.get("id"):
                                    service_id = svc.get("id")
                                    break
                            if not service_id:
                                for svc in service:
                                    if svc.get("@id"):
                                        service_id = svc.get("@id")
                                        break
                        elif isinstance(service, dict):
                            service_id = service.get("id") or service.get("@id")

                    if width and height and service_id:
                        # Create pseudo image_info dict
                        return {
                            "width": width,
                            "height": height,
                            "@id": service_id,
                            "id": service_id,
                            "format": format_str,
                        }

    return None


def get_image_service_id_from_info(image_info: dict[str, Any]) -> str | None:
    """Extract the image service ID from image info, handling both v2 and v3 formats.

    Args:
        image_info: The parsed image info JSON response

    Returns:
        str: The image service ID, or None if not found
    """
    # IIIF Image API v3 uses "id", v2 uses "@id"
    return image_info.get("id") or image_info.get("@id")


def get_size_limits_from_info(image_info: dict[str, Any]) -> ImageSizeLimits:
    """Extract maxWidth, maxHeight, and maxArea from IIIF image info.

    Image API 3.0 declares these at the top level. Image API 2.x may nest them
    in a profile description object inside the profile array.

    Args:
        image_info: The parsed image info JSON response

    Returns:
        ImageSizeLimits: Declared size constraints (fields may be None)
    """
    max_width = image_info.get("maxWidth")
    max_height = image_info.get("maxHeight")
    max_area = image_info.get("maxArea")

    profile = image_info.get("profile")
    profile_objects: list[dict[str, Any]] = []
    if isinstance(profile, list):
        profile_objects = [p for p in profile if isinstance(p, dict)]
    elif isinstance(profile, dict):
        profile_objects = [profile]

    for item in profile_objects:
        if max_width is None and "maxWidth" in item:
            max_width = item.get("maxWidth")
        if max_height is None and "maxHeight" in item:
            max_height = item.get("maxHeight")
        if max_area is None and "maxArea" in item:
            max_area = item.get("maxArea")

    def _as_positive_int(value: Any) -> int | None:
        """Convert a value to a positive int, or None if invalid."""
        if value is None:
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    return ImageSizeLimits(
        max_width=_as_positive_int(max_width),
        max_height=_as_positive_int(max_height),
        max_area=_as_positive_int(max_area),
    )


def max_requestable_width(
    image_width: int,
    image_height: int,
    limits: ImageSizeLimits | None = None,
    max_edge: int | None = None,
) -> int:
    """Compute the maximum requestable width for an image under size constraints.

    Applies IIIF maxWidth, maxHeight, and maxArea. When ``max_edge`` is set
    (from probing), both resulting width and height are capped to that edge.

    Args:
        image_width: Full image width in pixels
        image_height: Full image height in pixels
        limits: Declared service size limits (optional)
        max_edge: Maximum allowed edge length discovered by probing (optional)

    Returns:
        int: Maximum requestable width (at least 1)
    """
    if image_width <= 0:
        return 1

    candidates: list[int] = [image_width]

    if limits is not None:
        if limits.max_width is not None:
            candidates.append(limits.max_width)
        if limits.max_height is not None and image_height > 0:
            candidates.append(int(limits.max_height * image_width / image_height))
        if limits.max_area is not None and image_height > 0:
            # width * height_scaled <= max_area
            # height_scaled = width * image_height / image_width
            area_cap = int(math.sqrt(limits.max_area * image_width / image_height))
            candidates.append(max(1, area_cap))

    if max_edge is not None and max_edge > 0:
        candidates.append(max_edge)
        if image_height > 0:
            candidates.append(int(max_edge * image_width / image_height))

    return max(1, min(candidates))


def get_image_size_from_info(
    image_info: dict[str, Any],
    requested_size: int | None = None,
    max_edge: int | None = None,
) -> int | None:
    """Extract the appropriate image size from image info, handling different API versions.

    Honors maxWidth/maxHeight/maxArea from the service and an optional probed
    max edge so portrait images are not requested wider than the server allows.

    Args:
        image_info: The parsed image info JSON response
        requested_size: Specific size requested by user (optional)
        max_edge: Maximum allowed edge length from server probing (optional)

    Returns:
        int: The width to use for the image, or None if no size information available
    """
    full_width = image_info.get("width")
    full_height = image_info.get("height")
    target_size: int | None = None

    if requested_size:
        target_size = requested_size
    elif "sizes" in image_info and full_width:
        # IIIF Image API 2.x - try to use a reasonable large size
        largest_listed = max(image_info["sizes"], key=lambda x: x["width"])["width"]

        # Try to use a size between the largest listed and full resolution
        if full_width > largest_listed:
            # Prefer full width when limits will cap it; otherwise use a
            # reasonable intermediate size.
            limits = get_size_limits_from_info(image_info)
            if limits.has_limits or max_edge is not None:
                target_size = full_width
            else:
                intermediate = min(2500, full_width // 2)
                target_size = max(intermediate, largest_listed)
        else:
            target_size = largest_listed
    elif "sizes" in image_info:
        # IIIF Image API 2.x - use the largest available size from sizes array
        target_size = max(image_info["sizes"], key=lambda x: x["width"])["width"]
    elif full_width:
        # IIIF Image API 1.x or fallback - use full width
        target_size = full_width

    if target_size is None:
        return None

    limits = get_size_limits_from_info(image_info)
    if full_width and full_height:
        capped = max_requestable_width(
            int(full_width), int(full_height), limits, max_edge
        )
        target_size = min(int(target_size), capped)
    elif limits.max_width is not None:
        target_size = min(int(target_size), limits.max_width)
    elif max_edge is not None:
        target_size = min(int(target_size), max_edge)

    return max(1, int(target_size))


def get_canvas_label(canvas: dict) -> str | None:
    """Extract label from a canvas, handling both string and language map formats.

    Args:
        canvas: Canvas object from IIIF manifest

    Returns:
        str: Canvas label, or None if not available
    """
    if "label" not in canvas:
        return None

    label = canvas["label"]

    # Handle language map format (dict with language codes as keys)
    if isinstance(label, dict):
        # Try common language codes in order of preference
        for lang_code in ["en", "none", "default"]:
            if lang_code in label:
                label = label[lang_code]
                break
        # If no preferred language found, use the first value
        if isinstance(label, dict) and label:
            label = list(label.values())[0]
        # If still a dict, return None
        if isinstance(label, dict):
            return None

    # Handle list format (array of strings or language maps)
    if isinstance(label, list):
        if not label:
            return None
        # Get first item
        label = label[0]
        # If it's a dict, extract the value
        if isinstance(label, dict):
            for lang_code in ["en", "none", "default"]:
                if lang_code in label:
                    label = label[lang_code]
                    break
            if isinstance(label, dict) and label:
                label = list(label.values())[0]
            if isinstance(label, dict):
                return None

    # Convert to string if not already
    if not isinstance(label, str):
        return None

    return label.strip() if label else None


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a string to be filesystem-safe.

    Args:
        name: String to sanitize
        max_length: Maximum length for the filename (default: 200)

    Returns:
        str: Sanitized filename-safe string
    """
    import re

    # Remove or replace problematic characters
    # Keep alphanumeric, spaces, hyphens, underscores, dots, and common unicode chars
    # Replace other characters with underscores
    sanitized = re.sub(r"[^\w\s\-\.]", "_", name)

    # Replace multiple spaces/underscores with single underscore
    sanitized = re.sub(r"[\s_]+", "_", sanitized)

    # Remove leading/trailing underscores and dots
    sanitized = sanitized.strip("_.")

    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip("_.")

    # Ensure it's not empty
    if not sanitized:
        return "unnamed"

    return sanitized


def build_hybrid_filename(
    label: str | None,
    idx: int,
    image_format: str,
    index_prefix: str = "canvas",
    fallback_prefix: str = "image",
) -> str:
    """Build a hybrid or numeric filename for a page/canvas.

    Args:
        label: Optional human-readable label.
        idx: Zero-based index.
        image_format: Image format extension (e.g., "jpeg", "png").
        index_prefix: Prefix used with labels (e.g. "canvas", "page").
        fallback_prefix: Prefix used when no label is available.

    Returns:
        str: Filename (without path, with extension).
    """
    if label:
        sanitized_label = sanitize_filename(label)
        return f"{index_prefix}-{idx + 1:03d}_{sanitized_label}.{image_format}"
    return f"{fallback_prefix}_{idx + 1:03d}.{image_format}"


def get_filename_from_canvas(
    canvas: dict,
    idx: int,
    image_format: str,
    fallback_prefix: str = "image",
    index_prefix: str = "canvas",
) -> str:
    """Generate a filename from a canvas, using hybrid approach with label if available.

    Args:
        canvas: Canvas object from IIIF manifest
        idx: Zero-based index of the canvas
        image_format: Image format extension (e.g., "jpeg", "png")
        fallback_prefix: Prefix to use if no label is available (default: "image")
        index_prefix: Prefix used with labels (default: "canvas")

    Returns:
        str: Filename (without path, with extension)
    """
    return build_hybrid_filename(
        label=get_canvas_label(canvas),
        idx=idx,
        image_format=image_format,
        index_prefix=index_prefix,
        fallback_prefix=fallback_prefix,
    )


def load_manifest(source: str, cookie_file: str | None = None) -> dict[str, Any] | None:
    """Load a IIIF manifest from URL or local file.

    Args:
        source: URL or file path of the IIIF manifest
        cookie_file: Optional path to a cookie file for bot-protected hosts

    Returns:
        dict: Manifest data with 'content' and 'filename' keys, or None if error
    """
    if source.startswith("http://") or source.startswith("https://"):
        console = Console()
        try:
            with SessionManager(cookie_file=cookie_file) as session_manager:
                response = session_manager.get(source, timeout=30)

                if is_authentication_required(response):
                    print()  # end the CLI "Loading manifest..." line
                    console.print(get_auth_error_message(source, cookie_file, response))
                    return None

                response.raise_for_status()
                content = json.loads(response.text)
                return {
                    "content": content,
                    "filename": os.path.basename(urlparse(source).path),
                }
        except (FileNotFoundError, OSError, http.cookiejar.LoadError) as e:
            print()
            print(f"Error loading cookie file: {e}")
            return None
        except requests.RequestException as e:
            print(f"Error fetching the manifest: {e}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from URL: {e}")
            return None
    else:
        # It's a local file
        try:
            with open(source) as file:
                content = json.load(file)
            return {"content": content, "filename": os.path.basename(source)}
        except FileNotFoundError:
            print(f"File not found: {source}")
            return None
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from file: {e}")
            return None
