"""Metadata extraction and saving functionality."""

import os


def save_metadata(manifest_data, output_folder=None):
    """Extract and save metadata from the IIIF manifest to a text file.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        output_folder: Optional output directory path
    """
    manifest = manifest_data["content"]

    # Determine output directory
    if output_folder:
        base_filename = output_folder
    else:
        if "filename" in manifest_data:
            base_filename = os.path.splitext(manifest_data["filename"])[0]
        else:
            base_filename = "iiif_images"

    # Create output directory if it doesn't exist
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
