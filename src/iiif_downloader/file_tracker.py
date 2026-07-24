"""File tracking functionality for efficient resume operations."""

import json
import os
from typing import Any

from iiif_downloader.constants import MIN_VALID_IMAGE_BYTES


class FileTracker:
    """Tracks downloaded files using a manifest file and set-based lookups."""

    def __init__(
        self,
        output_dir: str,
        total_images: int,
        canvases: list[dict[str, Any]] | None = None,
        index_prefix: str = "canvas",
        fallback_prefix: str = "image",
    ):
        """Initialize the file tracker.

        Args:
            output_dir: Output directory for images
            total_images: Total number of images expected
            canvases: List of canvas objects for label-based naming (optional)
            index_prefix: Prefix for hybrid filenames (default: canvas)
            fallback_prefix: Prefix for numeric filenames (default: image)
        """
        self.output_dir = output_dir
        self.total_images = total_images
        self.canvases = canvases
        self.index_prefix = index_prefix
        self.fallback_prefix = fallback_prefix
        self.manifest_file = os.path.join(output_dir, ".iiif-download-state.json")
        self.downloaded_indices: set[int] = set()
        self._load_state()

    def _get_filename_for_index(
        self, idx: int, extensions: list[str] | None = None
    ) -> list[str]:
        """Get possible filenames for a given index.

        Args:
            idx: Zero-based index
            extensions: List of extensions to check (default: ['jpeg', 'jpg'])

        Returns:
            list: List of possible filenames
        """
        if extensions is None:
            extensions = ["jpeg", "jpg"]

        filenames = []

        # Try label-based naming if canvas is available
        if self.canvases and idx < len(self.canvases):
            from iiif_downloader.manifest import (
                get_canvas_label,
                get_filename_from_canvas,
                sanitize_filename,
            )

            canvas = self.canvases[idx]
            # Check hybrid naming (prefix-XXX_label.ext)
            for ext in extensions:
                filename = get_filename_from_canvas(
                    canvas,
                    idx,
                    ext,
                    fallback_prefix=self.fallback_prefix,
                    index_prefix=self.index_prefix,
                )
                filenames.append(os.path.join(self.output_dir, filename))

            # Also check old label-only naming (just label.ext) for migration
            label = get_canvas_label(canvas)
            if label:
                sanitized_label = sanitize_filename(label)
                for ext in extensions:
                    old_label_filename = os.path.join(
                        self.output_dir, f"{sanitized_label}.{ext}"
                    )
                    if old_label_filename not in filenames:
                        filenames.append(old_label_filename)

        # Always check numeric naming for backward compatibility
        for ext in extensions:
            for prefix in {self.fallback_prefix, "image", "page"}:
                filename = os.path.join(
                    self.output_dir, f"{prefix}_{idx + 1:03d}.{ext}"
                )
                if filename not in filenames:
                    filenames.append(filename)

        return filenames

    def _is_valid_image_file(self, filename: str) -> bool:
        """Return True if filename exists and is large enough to be a real image.

        Args:
            filename: Path to check

        Returns:
            bool: True if the file looks complete
        """
        try:
            return (
                os.path.exists(filename)
                and os.path.getsize(filename) >= MIN_VALID_IMAGE_BYTES
            )
        except OSError:
            return False

    def _remove_incomplete_file(self, filename: str) -> bool:
        """Remove an empty/tiny leftover download file.

        Args:
            filename: Path to remove if incomplete

        Returns:
            bool: True if a file was removed
        """
        try:
            if os.path.exists(filename) and not self._is_valid_image_file(filename):
                os.remove(filename)
                return True
        except OSError:
            pass
        return False

    def _load_state(self) -> None:
        """Load existing state from manifest file and scan directory."""
        # Load from manifest file if it exists
        if os.path.exists(self.manifest_file):
            try:
                with open(self.manifest_file) as f:
                    state = json.load(f)
                    self.downloaded_indices = set(state.get("downloaded_indices", []))
            except (json.JSONDecodeError, KeyError) as e:
                print(f"Warning: Could not load state file: {e}")
                self.downloaded_indices = set()

        # Scan directory for existing files and update state
        # Check both label-based and numeric naming for backward compatibility
        valid_indices: set[int] = set()
        for idx in range(self.total_images):
            possible_filenames = self._get_filename_for_index(idx)
            found_valid = False
            for fname in possible_filenames:
                if self._is_valid_image_file(fname):
                    found_valid = True
                elif self._remove_incomplete_file(fname):
                    print(
                        f"Warning: Removed incomplete download "
                        f"({os.path.basename(fname)})"
                    )
            if found_valid:
                valid_indices.add(idx)

        self.downloaded_indices = valid_indices

        # Save updated state
        self._save_state()

    def _save_state(self) -> None:
        """Save current state to manifest file."""
        state = {
            "downloaded_indices": list(self.downloaded_indices),
            "total_images": self.total_images,
            "last_update": os.path.getmtime(self.manifest_file)
            if os.path.exists(self.manifest_file)
            else None,
        }

        try:
            with open(self.manifest_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save state file: {e}")

    def is_downloaded(self, index: int) -> bool:
        """Check if an image at the given index is already downloaded.

        Args:
            index: Zero-based index of the image

        Returns:
            bool: True if the image is downloaded
        """
        return index in self.downloaded_indices

    def get_existing_filename(self, index: int) -> str | None:
        """Get the filename of an existing file for the given index.

        Args:
            index: Zero-based index of the image

        Returns:
            str: Full path to existing file, or None if not found
        """
        possible_filenames = self._get_filename_for_index(index)
        for filename in possible_filenames:
            if self._is_valid_image_file(filename):
                return filename
        return None

    def migrate_filename_if_needed(self, index: int, target_filename: str) -> bool:
        """Migrate old filename to new filename if needed.

        If a file exists with old naming scheme but target uses new naming,
        rename it to maintain consistency.

        Args:
            index: Zero-based index of the image
            target_filename: Desired filename (full path)

        Returns:
            bool: True if migration occurred, False otherwise
        """
        existing = self.get_existing_filename(index)
        if existing and existing != target_filename:
            existing_basename = os.path.basename(existing)
            target_basename = os.path.basename(target_filename)

            # Check if existing uses old naming (image_XXX) and target uses new naming
            old_pattern = f"image_{index + 1:03d}."
            # Also check for old label-only naming (without canvas prefix)
            # This handles migration from the previous label-only approach
            if old_pattern in existing_basename or (
                # Check if existing is label-only (no canvas prefix) and target has canvas prefix
                not existing_basename.startswith("canvas-")
                and target_basename.startswith("canvas-")
            ):
                try:
                    # Ensure target directory exists
                    os.makedirs(os.path.dirname(target_filename), exist_ok=True)
                    # Rename the file
                    os.rename(existing, target_filename)
                    return True
                except OSError:
                    # If rename fails (e.g., target exists), don't migrate
                    pass
        return False

    def mark_downloaded(self, index: int) -> None:
        """Mark an image as downloaded.

        Args:
            index: Zero-based index of the image
        """
        self.downloaded_indices.add(index)
        self._save_state()

    def get_downloaded_count(self) -> int:
        """Get the number of downloaded images.

        Returns:
            int: Number of downloaded images
        """
        return len(self.downloaded_indices)

    def get_remaining_count(self) -> int:
        """Get the number of remaining images to download.

        Returns:
            int: Number of remaining images
        """
        return self.total_images - len(self.downloaded_indices)
