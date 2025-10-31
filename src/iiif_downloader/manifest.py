"""Manifest loading and parsing functionality."""

import json
import os
from urllib.parse import urlparse

import requests


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


def get_image_service_id_from_info(image_info):
    """Extract the image service ID from image info, handling both v2 and v3 formats.

    Args:
        image_info: The parsed image info JSON response

    Returns:
        str: The image service ID, or None if not found
    """
    # IIIF Image API v3 uses "id", v2 uses "@id"
    return image_info.get("id") or image_info.get("@id")


def get_image_size_from_info(image_info, requested_size=None):
    """Extract the appropriate image size from image info, handling different API versions.

    Args:
        image_info: The parsed image info JSON response
        requested_size: Specific size requested by user (optional)

    Returns:
        int: The width to use for the image, or None if no size information available
    """
    if requested_size:
        return requested_size

    # Handle different IIIF Image API versions
    if "sizes" in image_info and "width" in image_info:
        # IIIF Image API 2.x - try to use a reasonable large size
        # First, get the largest size from the sizes array
        largest_listed = max(image_info["sizes"], key=lambda x: x["width"])["width"]
        full_width = image_info["width"]

        # Try to use a size between the largest listed and full resolution
        # This gives us better quality while respecting server capabilities
        if full_width > largest_listed:
            # Use a reasonable intermediate size (e.g., 2500px or 50% of full width)
            target_size = min(2500, full_width // 2)
            # But don't go smaller than the largest listed size
            return max(target_size, largest_listed)
        else:
            return largest_listed
    elif "sizes" in image_info:
        # IIIF Image API 2.x - use the largest available size from sizes array
        return max(image_info["sizes"], key=lambda x: x["width"])["width"]
    elif "width" in image_info:
        # IIIF Image API 1.x or fallback - use full width
        return image_info["width"]

    return None


def load_manifest(source):
    """Load a IIIF manifest from URL or local file.

    Args:
        source: URL or file path of the IIIF manifest

    Returns:
        dict: Manifest data with 'content' and 'filename' keys, or None if error
    """
    if source.startswith("http://") or source.startswith("https://"):
        # It's a URL
        try:
            response = requests.get(source)
            response.raise_for_status()
            content = json.loads(response.text)
            return {
                "content": content,
                "filename": os.path.basename(urlparse(source).path),
            }
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
