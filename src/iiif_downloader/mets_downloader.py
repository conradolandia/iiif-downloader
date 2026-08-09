"""METS downloader for direct image URL downloads."""

from __future__ import annotations

import os
from typing import Any

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from iiif_downloader.download_helpers import get_default_headers, setup_output_directory
from iiif_downloader.file_tracker import FileTracker
from iiif_downloader.image_downloader import download_url_stream
from iiif_downloader.manifest import build_hybrid_filename
from iiif_downloader.progress_columns import CompletedTotalColumn, FixedWidthTextColumn
from iiif_downloader.rate_limiter import RateLimiter
from iiif_downloader.session_manager import SessionManager
from iiif_downloader.sources.base import PageItem, SourceDocument
from iiif_downloader.sources.mets import extension_for_page


class MetsDownloader:
    """Download images listed in a METS SourceDocument."""

    def __init__(
        self,
        source_document: SourceDocument,
        output_folder: str | None = None,
        rate_limit: float | None = None,
        verbose: bool = False,
        cookie_file: str | None = None,
    ) -> None:
        """Initialize the METS downloader.

        Args:
            source_document: Loaded METS SourceDocument.
            output_folder: Output directory for images (optional).
            rate_limit: Fixed rate limit in requests per minute (None for adaptive).
            verbose: Whether to enable verbose output.
            cookie_file: Optional path to a cookie file for session persistence.
        """
        self.source_document = source_document
        self.output_folder = output_folder
        self.rate_limit = rate_limit
        self.verbose = verbose
        self.cookie_file = cookie_file

        self.console = Console()
        self.session_manager = SessionManager(cookie_file=cookie_file)
        self.headers = get_default_headers()

        manifest_data = {
            "filename": source_document.filename,
            "content": source_document.metadata,
        }
        self.base_filename = setup_output_directory(manifest_data, output_folder)
        self.pages = source_document.pages
        self.total_images = len(self.pages)
        self.rate_limiter = RateLimiter(fixed_rate=rate_limit)

        # Canvas-like dicts so FileTracker can resolve hybrid names.
        self._label_canvases: list[dict[str, Any]] = [
            {"label": page.label} if page.label else {} for page in self.pages
        ]

    def _validate_pages(self) -> bool:
        """Validate that pages exist in the source document.

        Returns:
            bool: True if pages are present.
        """
        if not self.pages:
            self.console.print(
                "[bold red]Error: No pages found in METS document[/bold red]"
            )
            return False
        return True

    def _page_filename(self, page: PageItem) -> str:
        """Build the output filename for a METS page.

        Args:
            page: Page item to name.

        Returns:
            str: Absolute path under the output directory.
        """
        image_format = extension_for_page(page)
        filename_base = build_hybrid_filename(
            label=page.label,
            idx=page.index,
            image_format=image_format,
            index_prefix="page",
            fallback_prefix="page",
        )
        return os.path.join(self.base_filename, filename_base)

    def _download_single_page(
        self,
        page: PageItem,
        progress: Progress,
    ) -> tuple[bool, str]:
        """Download a single METS page image.

        Args:
            page: Page item with a direct image URL.
            progress: Rich Progress object.

        Returns:
            tuple: (success, filename)
        """
        if not page.url:
            self.console.print(
                f"[bold red]Error: Missing URL for page {page.index + 1}[/bold red]"
            )
            return False, ""

        filename = self._page_filename(page)
        download_task = progress.add_task(
            f"Downloading page {page.index + 1}",
            total=None,
        )

        success, final_filename, downloaded_bytes, chunk_count = download_url_stream(
            image_url=page.url,
            filename=filename,
            session_manager=self.session_manager,
            progress=progress,
            task=download_task,
            verbose=self.verbose,
        )

        progress.remove_task(download_task)

        if not success:
            return False, filename

        if self.verbose:
            file_size = os.path.getsize(final_filename)
            size_str = (
                f"{file_size / 1024 / 1024:.1f} MB"
                if file_size > 1024 * 1024
                else f"{file_size / 1024:.1f} KB"
            )
            self.console.print(
                f"[dim]Page {page.index + 1}: {size_str} "
                f"({downloaded_bytes} bytes, {chunk_count} chunks)[/dim]"
            )

        return True, final_filename

    def download_all(self, resume: bool = False) -> None:
        """Download all pages from the METS document.

        Args:
            resume: Whether to resume interrupted downloads.
        """
        self.console.print("[bold blue]Detected format:[/bold blue] METS")

        if not self._validate_pages():
            return

        file_tracker = FileTracker(
            self.base_filename,
            self.total_images,
            canvases=self._label_canvases,
            index_prefix="page",
            fallback_prefix="page",
        )

        downloaded_count = file_tracker.get_downloaded_count()
        remaining_count = file_tracker.get_remaining_count()

        self.console.print(
            f"[bold blue]Total images to process:[/bold blue] {self.total_images}"
        )
        if resume and downloaded_count > 0:
            self.console.print(
                f"[bold green]Found {downloaded_count} existing files, will skip them[/bold green]"
            )
            self.console.print(
                f"[bold yellow]Will download {remaining_count} remaining images[/bold yellow]"
            )

        with Progress(
            FixedWidthTextColumn(width=50),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            CompletedTotalColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TimeRemainingColumn(),
            console=self.console,
            expand=True,
        ) as progress:
            skipped_count = 0
            failed_count = 0
            newly_downloaded_count = 0

            initial_desc = (
                f"DL:{newly_downloaded_count:3d} "
                f"SK:{skipped_count:3d} "
                f"FL:{failed_count:2d} "
                f"T:{downloaded_count:3d}/{self.total_images} "
                f"R:  0.0"
            )
            main_task = progress.add_task(
                initial_desc,
                total=self.total_images,
                completed=downloaded_count,
            )

            def update_status_description() -> None:
                """Update the progress bar description with current statistics."""
                current_rate = self.rate_limiter.get_current_rate()
                desc = (
                    f"DL:{newly_downloaded_count:3d} "
                    f"SK:{skipped_count:3d} "
                    f"FL:{failed_count:2d} "
                    f"T:{file_tracker.get_downloaded_count():3d}/{self.total_images} "
                    f"R:{current_rate:5.1f}"
                )
                progress.update(main_task, description=desc)

            for page in self.pages:
                idx = page.index
                try:
                    if resume and file_tracker.is_downloaded(idx):
                        skipped_count += 1
                        update_status_description()
                        continue

                    self.rate_limiter.wait_if_needed()
                    success, _filename = self._download_single_page(page, progress)
                    if not success:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        update_status_description()
                        continue

                    file_tracker.mark_downloaded(idx)
                    newly_downloaded_count += 1
                    self.rate_limiter.handle_success()
                    progress.update(main_task, advance=1)
                    update_status_description()

                except requests.RequestException as exc:
                    progress.console.print(
                        f"[bold red]Error downloading page {idx + 1}:[/bold red] {exc}"
                    )
                    status_code = None
                    if hasattr(exc, "response") and exc.response is not None:
                        status_code = exc.response.status_code
                    backoff_msg = self.rate_limiter.handle_error(status_code)
                    if backoff_msg:
                        progress.console.print(f"[yellow]{backoff_msg}[/yellow]")
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    update_status_description()
                except Exception as exc:
                    progress.console.print(
                        f"[bold red]Unexpected error processing page {idx + 1}:"
                        f"[/bold red] {exc}"
                    )
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    update_status_description()

            self.console.print("\n[bold green]Download completed![/bold green]")
            self.console.print(f"Downloaded: {newly_downloaded_count}")
            self.console.print(f"Skipped: {skipped_count}")
            self.console.print(f"Failed: {failed_count}")
            self.console.print(
                f"Total: {file_tracker.get_downloaded_count()}/{self.total_images}"
            )

    def download_one(self, page_index: int) -> None:
        """Download a single page from the METS document.

        Args:
            page_index: 1-based page index.
        """
        self.console.print("[bold blue]Detected format:[/bold blue] METS")

        if not self._validate_pages():
            return

        if page_index < 1 or page_index > self.total_images:
            self.console.print(
                f"[bold red]Error: Page index {page_index} is out of range "
                f"(1-{self.total_images})[/bold red]"
            )
            return

        page = self.pages[page_index - 1]
        self.console.print(
            f"[bold blue]Downloading page {page_index} of {self.total_images}[/bold blue]"
        )

        try:
            self.rate_limiter.wait_if_needed()
            with Progress(
                TextColumn("[bold blue]Downloading page"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=self.console,
                expand=True,
            ) as progress:
                success, filename = self._download_single_page(page, progress)

            if not success:
                self.console.print(
                    f"[bold red]Error downloading page {page_index}[/bold red]"
                )
                return

            self.console.print(
                f"[bold green]Page {page_index} downloaded successfully![/bold green]"
            )
            self.console.print(f"[dim]Saved as: {filename}[/dim]")
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                size_str = (
                    f"{file_size / 1024 / 1024:.1f} MB"
                    if file_size > 1024 * 1024
                    else f"{file_size / 1024:.1f} KB"
                )
                self.console.print(f"[dim]File size: {size_str}[/dim]")

        except requests.RequestException as exc:
            self.console.print(
                f"[bold red]Error downloading page {page_index}:[/bold red] {exc}"
            )
        except Exception as exc:
            self.console.print(f"[bold red]Unexpected error:[/bold red] {exc}")
