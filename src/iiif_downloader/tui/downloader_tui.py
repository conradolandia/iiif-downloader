"""TUI-specific downloader wrapper with thread-safe communication."""

import threading

from textual.app import App

from ..download_engine import (
    DownloadCallback,
    DownloadEngine,
    DownloadEvent,
    DownloadEventType,
)


class TUIDownloader(DownloadCallback):
    """TUI-specific downloader wrapper with thread-safe communication."""

    def __init__(self, app: App):
        """Initialize the TUI downloader.

        Args:
            app: The textual app instance
        """
        self.app = app
        self.engine: DownloadEngine | None = None
        self.is_running = False
        self.is_paused = False

        # Statistics
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_bytes = 0
        self.current_rate = 0.0
        self.elapsed_time = 0.0
        self.eta_time = 0.0

        # Current download
        self.current_filename = ""
        self.current_progress = 0.0
        self.current_speed = 0.0
        self.current_bytes = 0
        self.current_total = 0

        # Thread-safe communication
        self._update_lock = threading.Lock()

    def start_download(
        self,
        manifest_data: dict,
        output_folder: str,
        size: int | None = None,
        resume: bool = False,
        rate_limit: float | None = None,
    ) -> None:
        """Start a download session.

        Args:
            manifest_data: Manifest data dict with 'content' and 'filename' keys
            output_folder: Output directory for images
            size: Desired image width (optional)
            resume: Whether to resume interrupted downloads
            rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        """
        if self.is_running:
            return

        # Create download engine
        self.engine = DownloadEngine(
            manifest_data=manifest_data,
            output_folder=output_folder,
            size=size,
            resume=resume,
            rate_limit=rate_limit,
        )

        # Add self as callback
        self.engine.add_callback(self)

        # Reset statistics
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_bytes = 0
        self.current_rate = 0.0
        self.elapsed_time = 0.0
        self.eta_time = 0.0

        # Start download
        self.is_running = True
        self.is_paused = False
        self.engine.start()

    def pause_download(self) -> None:
        """Pause the download."""
        if self.engine and self.is_running and not self.is_paused:
            self.engine.pause()
            self.is_paused = True

    def resume_download(self) -> None:
        """Resume the download."""
        if self.engine and self.is_running and self.is_paused:
            self.engine.resume()
            self.is_paused = False

    def stop_download(self) -> None:
        """Stop the download."""
        if self.engine and self.is_running:
            self.engine.stop()
            self.is_running = False
            self.is_paused = False

    def on_event(self, event: DownloadEvent) -> None:
        """Handle download events (thread-safe)."""
        with self._update_lock:
            if event.event_type == DownloadEventType.START:
                self._handle_start(event)
            elif event.event_type == DownloadEventType.PROGRESS:
                self._handle_progress(event)
            elif event.event_type == DownloadEventType.COMPLETE:
                self._handle_complete(event)
            elif event.event_type == DownloadEventType.ERROR:
                self._handle_error(event)
            elif event.event_type == DownloadEventType.SKIP:
                self._handle_skip(event)
            elif event.event_type == DownloadEventType.PAUSE:
                self._handle_pause(event)
            elif event.event_type == DownloadEventType.RESUME:
                self._handle_resume(event)
            elif event.event_type == DownloadEventType.STOP:
                self._handle_stop(event)

    def _handle_start(self, event: DownloadEvent) -> None:
        """Handle start event."""
        # Update app with initial state
        self.app.post_message(self._create_status_message("started"))

    def _handle_progress(self, event: DownloadEvent) -> None:
        """Handle progress event."""
        self.current_filename = event.filename or ""
        self.current_progress = (
            (event.bytes_downloaded / event.total_bytes)
            if event.total_bytes > 0
            else 0.0
        )
        self.current_speed = event.speed_mbps
        self.current_bytes = event.bytes_downloaded
        self.current_total = event.total_bytes
        self.elapsed_time = event.elapsed_time
        self.eta_time = event.eta_seconds

        # Update current download panel
        self.app.post_message(self._create_current_message())

    def _handle_complete(self, event: DownloadEvent) -> None:
        """Handle complete event."""
        self.downloaded_count += 1
        self.total_bytes += event.bytes_downloaded

        # Clear current download
        self.current_filename = ""
        self.current_progress = 0.0
        self.current_speed = 0.0
        self.current_bytes = 0
        self.current_total = 0

        # Update statistics
        self._update_statistics()

        # Add to activity log
        self.app.post_message(self._create_activity_message(event))

    def _handle_error(self, event: DownloadEvent) -> None:
        """Handle error event."""
        self.failed_count += 1

        # Update statistics
        self._update_statistics()

        # Add to activity log
        self.app.post_message(self._create_activity_message(event))

    def _handle_skip(self, event: DownloadEvent) -> None:
        """Handle skip event."""
        self.skipped_count += 1

        # Update statistics
        self._update_statistics()

        # Add to activity log
        self.app.post_message(self._create_activity_message(event))

    def _handle_pause(self, event: DownloadEvent) -> None:
        """Handle pause event."""
        self.app.post_message(self._create_status_message("paused"))

    def _handle_resume(self, event: DownloadEvent) -> None:
        """Handle resume event."""
        self.app.post_message(self._create_status_message("resumed"))

    def _handle_stop(self, event: DownloadEvent) -> None:
        """Handle stop event."""
        self.is_running = False
        self.is_paused = False
        self.app.post_message(self._create_status_message("stopped"))

    def _update_statistics(self) -> None:
        """Update statistics and send to app."""
        total_images = self.downloaded_count + self.skipped_count + self.failed_count
        remaining = max(
            0, (self.engine.total_images if self.engine else 0) - total_images
        )

        # Calculate rate (requests per minute)
        if self.elapsed_time > 0:
            self.current_rate = (total_images / self.elapsed_time) * 60
        else:
            self.current_rate = 0.0

        # Send statistics update
        self.app.post_message(
            self._create_statistics_message(
                downloaded=self.downloaded_count,
                skipped=self.skipped_count,
                failed=self.failed_count,
                remaining=remaining,
                total_bytes=self.total_bytes,
                rate=self.current_rate,
                elapsed=self.elapsed_time,
                eta=self.eta_time,
            )
        )

    def _create_status_message(self, status: str):
        """Create a status update message."""
        return {
            "type": "status_update",
            "status": status,
            "downloaded": self.downloaded_count,
            "skipped": self.skipped_count,
            "failed": self.failed_count,
        }

    def _create_current_message(self):
        """Create a current download update message."""
        return {
            "type": "current_update",
            "filename": self.current_filename,
            "progress": self.current_progress,
            "speed": self.current_speed,
            "bytes": self.current_bytes,
            "total": self.current_total,
        }

    def _create_statistics_message(self, **kwargs):
        """Create a statistics update message."""
        return {
            "type": "statistics_update",
            **kwargs,
        }

    def _create_activity_message(self, event: DownloadEvent):
        """Create an activity log message."""
        return {
            "type": "activity_update",
            "event": event,
        }
