"""Core download engine with event-driven architecture."""

import json
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from queue import Queue

import requests

from .file_tracker import FileTracker
from .rate_limiter import RateLimiter


class DownloadEventType(Enum):
    """Types of download events."""

    START = "start"
    PROGRESS = "progress"
    COMPLETE = "complete"
    ERROR = "error"
    SKIP = "skip"
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"


@dataclass
class DownloadEvent:
    """Download event data."""

    event_type: DownloadEventType
    image_index: int
    total_images: int
    filename: str | None = None
    bytes_downloaded: int = 0
    total_bytes: int = 0
    error_message: str | None = None
    speed_mbps: float = 0.0
    elapsed_time: float = 0.0
    eta_seconds: float = 0.0


class DownloadCallback:
    """Protocol for download event callbacks."""

    def on_event(self, event: DownloadEvent) -> None:
        """Handle a download event."""
        ...


class DownloadEngine:
    """Event-driven download engine."""

    def __init__(
        self,
        manifest_data: dict,
        output_folder: str,
        size: int | None = None,
        resume: bool = False,
        rate_limit: float | None = None,
    ):
        """Initialize the download engine.

        Args:
            manifest_data: Manifest data dict with 'content' and 'filename' keys
            output_folder: Output directory for images
            size: Desired image width (optional)
            resume: Whether to resume interrupted downloads
            rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        """
        self.manifest_data = manifest_data
        self.output_folder = output_folder
        self.size = size
        self.resume = resume
        self.rate_limit = rate_limit

        # Initialize components
        self.manifest = manifest_data["content"]
        self.canvases = self.manifest["sequences"][0]["canvases"]
        self.total_images = len(self.canvases)

        self.file_tracker = FileTracker(output_folder, self.total_images)
        self.rate_limiter = RateLimiter(fixed_rate=rate_limit)

        # State management
        self.is_running = False
        self.is_paused = False
        self.should_stop = False
        self.download_thread: threading.Thread | None = None

        # Event system
        self.callbacks: list[DownloadCallback] = []
        self.event_queue: Queue[DownloadEvent] = Queue()

        # Statistics
        self.start_time = 0.0
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_bytes_downloaded = 0

        # Headers to mimic a browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def add_callback(self, callback: DownloadCallback) -> None:
        """Add a callback for download events."""
        self.callbacks.append(callback)

    def remove_callback(self, callback: DownloadCallback) -> None:
        """Remove a callback."""
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def _emit_event(self, event: DownloadEvent) -> None:
        """Emit an event to all callbacks."""
        self.event_queue.put(event)
        for callback in self.callbacks:
            callback.on_event(event)

    def start(self) -> None:
        """Start the download process."""
        if self.is_running:
            return

        self.is_running = True
        self.is_paused = False
        self.should_stop = False
        self.start_time = time.time()

        # Reset statistics
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_bytes_downloaded = 0

        # Start download thread
        self.download_thread = threading.Thread(target=self._download_loop, daemon=True)
        self.download_thread.start()

        self._emit_event(
            DownloadEvent(
                event_type=DownloadEventType.START,
                image_index=0,
                total_images=self.total_images,
            )
        )

    def pause(self) -> None:
        """Pause the download process."""
        if self.is_running and not self.is_paused:
            self.is_paused = True
            self._emit_event(
                DownloadEvent(
                    event_type=DownloadEventType.PAUSE,
                    image_index=self.downloaded_count
                    + self.skipped_count
                    + self.failed_count,
                    total_images=self.total_images,
                )
            )

    def resume(self) -> None:
        """Resume the download process."""
        if self.is_running and self.is_paused:
            self.is_paused = False
            self._emit_event(
                DownloadEvent(
                    event_type=DownloadEventType.RESUME,
                    image_index=self.downloaded_count
                    + self.skipped_count
                    + self.failed_count,
                    total_images=self.total_images,
                )
            )

    def stop(self) -> None:
        """Stop the download process."""
        self.should_stop = True
        self.is_running = False
        self.is_paused = False

        if self.download_thread and self.download_thread.is_alive():
            self.download_thread.join(timeout=5.0)

        self._emit_event(
            DownloadEvent(
                event_type=DownloadEventType.STOP,
                image_index=self.downloaded_count
                + self.skipped_count
                + self.failed_count,
                total_images=self.total_images,
            )
        )

    def _download_loop(self) -> None:
        """Main download loop."""
        for idx, canvas in enumerate(self.canvases):
            if self.should_stop:
                break

            # Wait if paused
            while self.is_paused and not self.should_stop:
                time.sleep(0.1)

            if self.should_stop:
                break

            # Check if file already exists and resume is enabled
            if self.resume and self.file_tracker.is_downloaded(idx):
                self.skipped_count += 1
                self._emit_event(
                    DownloadEvent(
                        event_type=DownloadEventType.SKIP,
                        image_index=idx,
                        total_images=self.total_images,
                        filename=f"image_{idx + 1:03d}.jpg",
                    )
                )
                continue

            # Download the image
            self._download_single_image(idx, canvas)

    def _download_single_image(self, idx: int, canvas: dict) -> None:
        """Download a single image."""
        try:
            # Rate limiting
            self.rate_limiter.wait_if_needed()

            # Fetch image info
            image_info_url = (
                canvas["images"][0]["resource"]["service"]["@id"] + "/info.json"
            )
            response = requests.get(image_info_url, headers=self.headers)
            response.raise_for_status()

            # Parse image info
            info = json.loads(response.text)

            # Determine image size
            if self.size:
                image_size = self.size
            else:
                image_size = max(info["sizes"], key=lambda x: x["width"])["width"]

            # Construct image URL
            image_url = f"{info['@id']}/full/{image_size},/0/default.jpg"
            filename = os.path.join(self.output_folder, f"image_{idx + 1:03d}.jpg")

            # Download with progress tracking
            self._download_with_progress(idx, image_url, filename)

        except Exception as e:
            self.failed_count += 1
            self._emit_event(
                DownloadEvent(
                    event_type=DownloadEventType.ERROR,
                    image_index=idx,
                    total_images=self.total_images,
                    filename=f"image_{idx + 1:03d}.jpg",
                    error_message=str(e),
                )
            )
            self.rate_limiter.handle_error()

    def _download_with_progress(self, idx: int, image_url: str, filename: str) -> None:
        """Download an image with progress tracking."""
        response = requests.get(image_url, headers=self.headers, stream=True)
        response.raise_for_status()

        content_length = response.headers.get("content-length")
        total_bytes = int(content_length) if content_length else 0

        downloaded_bytes = 0
        start_time = time.time()

        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if self.should_stop:
                    break

                # Wait if paused
                while self.is_paused and not self.should_stop:
                    time.sleep(0.1)

                if self.should_stop:
                    break

                if chunk:
                    f.write(chunk)
                    downloaded_bytes += len(chunk)
                    self.total_bytes_downloaded += len(chunk)

                    # Calculate speed and ETA
                    elapsed = time.time() - start_time
                    speed_mbps = (
                        (downloaded_bytes / 1024 / 1024) / elapsed if elapsed > 0 else 0
                    )

                    remaining_images = self.total_images - (
                        self.downloaded_count + self.skipped_count + self.failed_count
                    )
                    eta_seconds = (
                        (remaining_images * elapsed) if self.downloaded_count > 0 else 0
                    )

                    # Emit progress event
                    self._emit_event(
                        DownloadEvent(
                            event_type=DownloadEventType.PROGRESS,
                            image_index=idx,
                            total_images=self.total_images,
                            filename=os.path.basename(filename),
                            bytes_downloaded=downloaded_bytes,
                            total_bytes=total_bytes,
                            speed_mbps=speed_mbps,
                            elapsed_time=time.time() - self.start_time,
                            eta_seconds=eta_seconds,
                        )
                    )

        if not self.should_stop:
            # Mark as downloaded
            self.file_tracker.mark_downloaded(idx)
            self.downloaded_count += 1
            self.rate_limiter.handle_success()

            # Emit complete event
            self._emit_event(
                DownloadEvent(
                    event_type=DownloadEventType.COMPLETE,
                    image_index=idx,
                    total_images=self.total_images,
                    filename=os.path.basename(filename),
                    bytes_downloaded=downloaded_bytes,
                    total_bytes=total_bytes,
                    speed_mbps=speed_mbps,
                    elapsed_time=time.time() - self.start_time,
                )
            )
