"""Main TUI application for IIIF downloader."""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.events import Key
from textual.message import Message
from textual.widgets import Footer, Header, Label

from .downloader_tui import TUIDownloader
from .widgets import (
    ActivityLog,
    CurrentDownloadPanel,
    ProgressOverview,
    StatisticsPanel,
)


class DownloadStatusMessage(Message):
    """Message for download status updates."""

    def __init__(self, status: str, **kwargs) -> None:
        super().__init__()
        self.status = status
        self.kwargs = kwargs


class IIIFDownloaderApp(App):
    """Main TUI application for IIIF downloader."""

    CSS = """
    Screen {
        layout: vertical;
    }

    .header {
        height: 3;
        dock: top;
    }

    .footer {
        height: 3;
        dock: bottom;
    }

    .main {
        layout: vertical;
        height: 1fr;
    }

    .info-panel {
        height: 3;
        layout: horizontal;
    }

    .progress-panel {
        height: 3;
        layout: horizontal;
    }

    .stats-panel {
        height: 8;
        layout: horizontal;
    }

    .activity-panel {
        height: 1fr;
        layout: vertical;
    }

    .header {
        text-style: bold;
        color: $primary;
    }

    .status-downloading {
        color: $success;
    }

    .status-paused {
        color: $warning;
    }

    .status-stopped {
        color: $error;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.downloader: TUIDownloader | None = None
        self.manifest_data = None
        self.output_folder = ""
        self.size = None
        self.resume = False
        self.rate_limit = None

        # UI Components
        self.header_widget: Header | None = None
        self.footer_widget: Footer | None = None
        self.progress_overview: ProgressOverview | None = None
        self.statistics_panel: StatisticsPanel | None = None
        self.current_panel: CurrentDownloadPanel | None = None
        self.activity_log: ActivityLog | None = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        self.header_widget = Header()
        self.footer_widget = Footer()

        yield self.header_widget
        yield self.footer_widget

        with Container(classes="main"):
            # Info panel
            with Container(classes="info-panel"):
                yield Label("Manifest: Loading...", id="manifest-info")
                yield Label("Output: Loading...", id="output-info")

            # Progress panel
            with Container(classes="progress-panel"):
                self.progress_overview = ProgressOverview()
                yield self.progress_overview

            # Statistics and current download
            with Container(classes="stats-panel"):
                with Horizontal():
                    self.statistics_panel = StatisticsPanel()
                    self.current_panel = CurrentDownloadPanel()
                    yield self.statistics_panel
                    yield self.current_panel

            # Activity log
            with Container(classes="activity-panel"):
                self.activity_log = ActivityLog()
                yield self.activity_log

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.title = "IIIF Downloader v0.1.0"
        self.sub_title = "Download IIIF images with progress tracking"

        # Set up keyboard bindings
        self.bind("q", "quit", "Quit")
        self.bind("p", "pause_resume", "Pause/Resume")
        self.bind("s", "save_log", "Save Log")

        # Initialize downloader
        self.downloader = TUIDownloader(self)

        # Set up message handlers
        self.set_timer(0.1, self._update_ui)

    def on_key(self, event: Key) -> None:
        """Handle key events."""
        if event.key == "q":
            self.action_quit()
        elif event.key == "p":
            self.action_pause_resume()
        elif event.key == "s":
            self.action_save_log()

    def action_quit(self) -> None:
        """Quit the application."""
        if self.downloader and self.downloader.is_running:
            self.downloader.stop_download()
        self.exit()

    def action_pause_resume(self) -> None:
        """Pause or resume the download."""
        if not self.downloader:
            return

        if self.downloader.is_paused:
            self.downloader.resume_download()
        else:
            self.downloader.pause_download()

    def action_save_log(self) -> None:
        """Save activity log to file."""
        # TODO: Implement log saving
        self.notify("Log saving not yet implemented", severity="information")

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
        self.manifest_data = manifest_data
        self.output_folder = output_folder
        self.size = size
        self.resume = resume
        self.rate_limit = rate_limit

        # Update info panel
        manifest_name = manifest_data.get("filename", "Unknown")
        manifest_widget = self.query_one("#manifest-info", Label)
        manifest_widget.update(f"Manifest: {manifest_name}")

        output_widget = self.query_one("#output-info", Label)
        output_widget.update(f"Output: {output_folder}")

        # Start download
        if self.downloader:
            self.downloader.start_download(
                manifest_data=manifest_data,
                output_folder=output_folder,
                size=size,
                resume=resume,
                rate_limit=rate_limit,
            )

    def _update_ui(self) -> None:
        """Update UI components."""
        if not self.downloader:
            return

        # Update progress overview
        if self.progress_overview:
            total_images = (
                self.downloader.engine.total_images if self.downloader.engine else 0
            )
            completed = (
                self.downloader.downloaded_count
                + self.downloader.skipped_count
                + self.downloader.failed_count
            )

            if self.downloader.is_running:
                if self.downloader.is_paused:
                    status = "Paused"
                else:
                    status = "Downloading"
            else:
                status = "Stopped"

            self.progress_overview.update_overall(
                total_images=total_images,
                completed=completed,
                status=status,
            )

        # Update statistics
        if self.statistics_panel:
            total_images = (
                self.downloader.engine.total_images if self.downloader.engine else 0
            )
            remaining = max(
                0,
                total_images
                - (
                    self.downloader.downloaded_count
                    + self.downloader.skipped_count
                    + self.downloader.failed_count
                ),
            )

            self.statistics_panel.update_stats(
                downloaded=self.downloader.downloaded_count,
                skipped=self.downloader.skipped_count,
                failed=self.downloader.failed_count,
                remaining=remaining,
                total_bytes=self.downloader.total_bytes,
                rate=self.downloader.current_rate,
                elapsed=self.downloader.elapsed_time,
                eta=self.downloader.eta_time,
            )

        # Update current download
        if self.current_panel:
            if self.downloader.current_filename:
                self.current_panel.update_current(
                    filename=self.downloader.current_filename,
                    progress=self.downloader.current_progress,
                    speed=self.downloader.current_speed,
                    bytes_downloaded=self.downloader.current_bytes,
                    total_bytes=self.downloader.current_total,
                )
            else:
                self.current_panel.clear_current()

        # Schedule next update
        self.set_timer(0.1, self._update_ui)

    def handle_download_message(self, message: dict) -> None:
        """Handle download update messages."""
        if message["type"] == "status_update":
            # Update status in header
            status = message["status"]
            if self.header_widget:
                self.header_widget.sub_title = f"Status: {status.title()}"

        elif message["type"] == "current_update":
            # Update current download panel
            if self.current_panel:
                self.current_panel.update_current(
                    filename=message["filename"],
                    progress=message["progress"],
                    speed=message["speed"],
                    bytes_downloaded=message["bytes"],
                    total_bytes=message["total"],
                )

        elif message["type"] == "statistics_update":
            # Update statistics panel
            if self.statistics_panel:
                self.statistics_panel.update_stats(
                    downloaded=message["downloaded"],
                    skipped=message["skipped"],
                    failed=message["failed"],
                    remaining=message["remaining"],
                    total_bytes=message["total_bytes"],
                    rate=message["rate"],
                    elapsed=message["elapsed"],
                    eta=message["eta"],
                )

        elif message["type"] == "activity_update":
            # Add to activity log
            if self.activity_log:
                self.activity_log.add_activity(message["event"])
