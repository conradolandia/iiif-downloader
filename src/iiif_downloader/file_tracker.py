"""File tracking functionality for efficient resume operations."""

import json
import os


class FileTracker:
    """Tracks downloaded files using a manifest file and set-based lookups."""

    def __init__(self, output_dir: str, total_images: int):
        """Initialize the file tracker.

        Args:
            output_dir: Output directory for images
            total_images: Total number of images expected
        """
        self.output_dir = output_dir
        self.total_images = total_images
        self.manifest_file = os.path.join(output_dir, ".iiif-download-state.json")
        self.downloaded_indices: set[int] = set()
        self._load_state()

    def _load_state(self):
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
        for idx in range(self.total_images):
            filename = os.path.join(self.output_dir, f"image_{idx + 1:03d}.jpg")
            if os.path.exists(filename):
                self.downloaded_indices.add(idx)

        # Save updated state
        self._save_state()

    def _save_state(self):
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

    def mark_downloaded(self, index: int):
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
