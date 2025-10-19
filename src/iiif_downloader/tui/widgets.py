"""Custom widgets for the TUI interface."""

import time

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, ProgressBar, Static

from .download_engine import DownloadEvent, DownloadEventType


class StatisticsPanel(Static):
    """Panel displaying download statistics."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.downloaded = 0
        self.skipped = 0
        self.failed = 0
        self.remaining = 0
        self.total_bytes = 0
        self.rate = 0.0
        self.elapsed = 0.0
        self.eta = 0.0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Statistics", classes="header")
            yield Label("", id="stats-content")

    def update_stats(
        self,
        downloaded: int,
        skipped: int,
        failed: int,
        remaining: int,
        total_bytes: int,
        rate: float,
        elapsed: float,
        eta: float,
    ) -> None:
        """Update the statistics display."""
        self.downloaded = downloaded
        self.skipped = skipped
        self.failed = failed
        self.remaining = remaining
        self.total_bytes = total_bytes
        self.rate = rate
        self.elapsed = elapsed
        self.eta = eta

        # Format bytes
        if total_bytes > 1024 * 1024:
            size_str = f"{total_bytes / 1024 / 1024:.1f} MB"
        else:
            size_str = f"{total_bytes / 1024:.1f} KB"

        # Format time
        elapsed_str = self._format_time(elapsed)
        eta_str = self._format_time(eta)

        content = f"""├─ Downloaded: {downloaded} images ({size_str})
├─ Skipped: {skipped} images (already exist)
├─ Failed: {failed} images
├─ Remaining: {remaining} images
├─ Rate: {rate:.1f} req/min (adaptive)
└─ Elapsed: {elapsed_str} | ETA: {eta_str}"""

        stats_widget = self.query_one("#stats-content", Label)
        stats_widget.update(content)

    def _format_time(self, seconds: float) -> str:
        """Format time in seconds to HH:MM:SS."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class CurrentDownloadPanel(Static):
    """Panel showing current download progress."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.current_filename = ""
        self.current_progress = 0.0
        self.current_speed = 0.0
        self.current_bytes = 0
        self.current_total = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Current Download", classes="header")
            yield Label("", id="current-content")
            yield ProgressBar(id="current-progress")

    def update_current(
        self,
        filename: str,
        progress: float,
        speed: float,
        bytes_downloaded: int,
        total_bytes: int,
    ) -> None:
        """Update the current download display."""
        self.current_filename = filename
        self.current_progress = progress
        self.current_speed = speed
        self.current_bytes = bytes_downloaded
        self.current_total = total_bytes

        # Format bytes
        if total_bytes > 0:
            if total_bytes > 1024 * 1024:
                size_str = f"{bytes_downloaded / 1024 / 1024:.1f} MB / {total_bytes / 1024 / 1024:.1f} MB"
            else:
                size_str = (
                    f"{bytes_downloaded / 1024:.1f} KB / {total_bytes / 1024:.1f} KB"
                )
        else:
            size_str = f"{bytes_downloaded / 1024 / 1024:.1f} MB"

        speed_str = f"{speed:.1f} MB/s" if speed > 0 else "0.0 MB/s"

        content = f"""├─ Image: {filename}
├─ Size: {size_str}
└─ Speed: {speed_str}"""

        current_widget = self.query_one("#current-content", Label)
        current_widget.update(content)

        progress_widget = self.query_one("#current-progress", ProgressBar)
        progress_widget.update(progress=progress)

    def clear_current(self) -> None:
        """Clear the current download display."""
        current_widget = self.query_one("#current-content", Label)
        current_widget.update("No active download")

        progress_widget = self.query_one("#current-progress", ProgressBar)
        progress_widget.update(progress=0.0)


class ProgressOverview(Static):
    """Overall progress visualization."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.total_images = 0
        self.completed = 0
        self.status = "Stopped"

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label("", id="status-text")
            yield ProgressBar(id="overall-progress")

    def update_overall(
        self,
        total_images: int,
        completed: int,
        status: str,
    ) -> None:
        """Update the overall progress display."""
        self.total_images = total_images
        self.completed = completed
        self.status = status

        percentage = (completed / total_images * 100) if total_images > 0 else 0

        status_text = (
            f"Status: {status} [{completed}/{total_images} ({percentage:.0f}%)]"
        )

        status_widget = self.query_one("#status-text", Label)
        status_widget.update(status_text)

        progress_widget = self.query_one("#overall-progress", ProgressBar)
        progress_widget.update(progress=percentage / 100)


class ActivityLog(Static):
    """Scrollable log of recent activities."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.activities = []
        self.max_activities = 20

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Recent Activity", classes="header")
            yield Label("", id="activity-content")

    def add_activity(self, event: DownloadEvent) -> None:
        """Add an activity to the log."""
        timestamp = time.strftime("%H:%M:%S")

        if event.event_type == DownloadEventType.COMPLETE:
            icon = "✓"
            status = "Downloaded"
            size = (
                f"({event.bytes_downloaded / 1024 / 1024:.1f} MB)"
                if event.bytes_downloaded > 0
                else ""
            )
            activity = f"{icon} {status} {event.filename} {size}"
        elif event.event_type == DownloadEventType.SKIP:
            icon = "⊘"
            status = "Skipped"
            activity = f"{icon} {status} {event.filename} (exists)"
        elif event.event_type == DownloadEventType.ERROR:
            icon = "✗"
            status = "Failed"
            activity = f"{icon} {status} {event.filename} ({event.error_message})"
        else:
            return  # Don't log other event types

        self.activities.append(f"{timestamp} {activity}")

        # Keep only recent activities
        if len(self.activities) > self.max_activities:
            self.activities = self.activities[-self.max_activities :]

        self._update_display()

    def _update_display(self) -> None:
        """Update the activity display."""
        content = "\n".join([f"├─ {activity}" for activity in self.activities])
        if not content:
            content = "├─ No activities yet"

        activity_widget = self.query_one("#activity-content", Label)
        activity_widget.update(content)
