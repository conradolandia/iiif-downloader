"""IIIF downloader class for orchestrating image downloads."""

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
from iiif_downloader.image_downloader import download_image_stream, fetch_image_info
from iiif_downloader.manifest import (
    detect_manifest_version,
    get_canvases_from_manifest,
    get_filename_from_canvas,
    get_image_service_from_canvas,
    get_image_service_id_from_info,
    get_image_size_from_info,
)
from iiif_downloader.progress_columns import CompletedTotalColumn, FixedWidthTextColumn
from iiif_downloader.rate_limiter import RateLimiter
from iiif_downloader.server_capabilities import probe_server_capabilities


class IIIFDownloader:
    """Orchestrates IIIF image downloads with progress tracking and rate limiting."""

    def __init__(
        self,
        manifest_data: dict[str, Any],
        size: int | None = None,
        output_folder: str | None = None,
        rate_limit: float | None = None,
        verbose: bool = False,
    ):
        """Initialize the IIIF downloader.

        Args:
            manifest_data: Manifest data dict with 'content' and 'filename' keys
            size: Desired image width (optional)
            output_folder: Output directory for images (optional)
            rate_limit: Fixed rate limit in requests per minute (None for adaptive)
            verbose: Whether to enable verbose output
        """
        self.manifest_data = manifest_data
        self.size = size
        self.output_folder = output_folder
        self.rate_limit = rate_limit
        self.verbose = verbose

        self.console = Console()
        self.headers = get_default_headers()
        self.base_filename = setup_output_directory(manifest_data, output_folder)

        self.manifest = manifest_data["content"]
        self.version = detect_manifest_version(self.manifest)
        self.canvases = get_canvases_from_manifest(self.manifest)
        self.total_images = len(self.canvases)

        self.rate_limiter = RateLimiter(fixed_rate=rate_limit)
        self.server_capabilities: Any | None = None
        self.probed_image_info: dict[str, Any] | None = None
        self.probed_image_idx: int | None = None

    def _display_version(self) -> None:
        """Display the detected IIIF version."""
        self.console.print(
            f"[bold blue]Detected IIIF version:[/bold blue] {self.version}"
        )

    def _validate_canvases(self) -> bool:
        """Validate that canvases exist in the manifest.

        Returns:
            bool: True if canvases are valid, False otherwise
        """
        if not self.canvases:
            self.console.print(
                "[bold red]Error: No canvases found in manifest[/bold red]"
            )
            return False
        return True

    def _probe_server_capabilities(
        self, resume: bool, file_tracker: FileTracker | None
    ) -> None:
        """Probe server capabilities with the first image.

        Args:
            resume: Whether resume mode is enabled
            file_tracker: File tracker instance (optional)
        """
        if not self.canvases:
            return

        self.console.print("[dim]Probing server capabilities...[/dim]")

        # Find first canvas that will be downloaded (not skipped)
        probe_canvas_idx = None
        probe_canvas = None
        for idx, canvas in enumerate(self.canvases):
            if not resume or (file_tracker and not file_tracker.is_downloaded(idx)):
                probe_canvas_idx = idx
                probe_canvas = canvas
                break

        if probe_canvas_idx is None or probe_canvas is None:
            return

        try:
            image_service_url = get_image_service_from_canvas(
                probe_canvas, self.version
            )
            if not image_service_url:
                return

            info = fetch_image_info(image_service_url, self.headers, self.verbose)
            if not info:
                return

            # Cache the probed image info to avoid fetching again
            self.probed_image_info = info
            self.probed_image_idx = probe_canvas_idx

            service_id = get_image_service_id_from_info(info)
            image_size = get_image_size_from_info(info, self.size)

            if service_id and image_size:
                self.server_capabilities = probe_server_capabilities(
                    service_id, image_size, self.headers
                )
                self._display_server_capabilities()

        except Exception:
            # If probing fails, default to safe settings
            pass

    def _display_server_capabilities(self) -> None:
        """Display discovered server capabilities."""
        if not self.server_capabilities:
            return

        self.console.print(
            f"[dim]Server capabilities:[/dim] "
            f"format=.{self.server_capabilities.preferred_format}"
        )
        if self.server_capabilities.max_test_size:
            self.console.print(
                f"[dim]  Max tested size: {self.server_capabilities.max_test_size}px[/dim]"
            )
        if self.server_capabilities.supported_qualities:
            qualities_str = ", ".join(self.server_capabilities.supported_qualities)
            self.console.print(f"[dim]  Supported qualities: {qualities_str}[/dim]")
        if self.server_capabilities.requires_authentication:
            self.console.print("[yellow]  ⚠ Authentication may be required[/yellow]")
        if self.server_capabilities.rate_limit_detected:
            self.console.print(
                "[yellow]  ⚠ Rate limiting detected - using conservative limits[/yellow]"
            )

    def _get_image_info(
        self, canvas: dict[str, Any], idx: int
    ) -> dict[str, Any] | None:
        """Get image info for a canvas, using cached info if available.

        Args:
            canvas: Canvas object
            idx: Canvas index

        Returns:
            dict: Image info, or None if error
        """
        # Reuse cached info if this is the probed image
        if idx == self.probed_image_idx and self.probed_image_info is not None:
            if self.verbose:
                self.console.print(
                    f"[dim]Using cached image info for image {idx + 1}[/dim]"
                )
            return self.probed_image_info

        image_service_url = get_image_service_from_canvas(canvas, self.version)
        if not image_service_url:
            self.console.print(
                f"[bold red]Error: Could not find image service URL for canvas {idx + 1}[/bold red]"
            )
            return None

        info = fetch_image_info(image_service_url, self.headers, self.verbose)
        return info

    def _prepare_image_download(
        self, info: dict[str, Any], idx: int
    ) -> tuple[str, int] | None:
        """Prepare image download parameters.

        Args:
            info: Image info dict
            idx: Canvas index

        Returns:
            tuple: (service_id, image_size) or None if error
        """
        # Determine the size to use
        image_size = get_image_size_from_info(info, self.size)
        if image_size is None:
            self.console.print(
                f"[bold red]Error: No size information available for image {idx + 1}[/bold red]"
            )
            return None

        # Adjust size if server has a maximum tested size limit
        if (
            self.server_capabilities
            and self.server_capabilities.max_test_size
            and image_size > self.server_capabilities.max_test_size
        ):
            image_size = self.server_capabilities.max_test_size

        # Construct the image URL
        service_id = get_image_service_id_from_info(info)
        if not service_id:
            self.console.print(
                f"[bold red]Error: No service ID found in image info for image {idx + 1}[/bold red]"
            )
            return None

        return service_id, image_size

    def _download_single_image(
        self,
        service_id: str,
        image_size: int,
        idx: int,
        progress: Progress,
        main_task: Any,
        image_info: dict[str, Any] | None = None,
        canvas: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Download a single image.

        Args:
            service_id: Image service ID
            image_size: Image size to download
            idx: Canvas index
            progress: Rich Progress object
            main_task: Main progress task
            image_info: Image info dict for size estimation (optional)
            canvas: Canvas object for label extraction (optional)

        Returns:
            tuple: (success: bool, filename: str)
        """
        # Determine initial format and filename
        image_format = (
            self.server_capabilities.preferred_format
            if self.server_capabilities
            else "jpeg"
        )

        # Generate filename from canvas label if available, otherwise use numeric
        if canvas:
            filename_base = get_filename_from_canvas(canvas, idx, image_format)
        else:
            filename_base = f"image_{idx + 1:03d}.{image_format}"

        filename = os.path.join(self.base_filename, filename_base)

        # Download the image with streaming progress
        download_task = progress.add_task(
            f"Downloading image {idx + 1}",
            total=None,  # Unknown size, will update as we go
        )

        (
            success,
            final_filename,
            downloaded_bytes,
            chunk_count,
        ) = download_image_stream(
            service_id,
            image_size,
            filename,
            self.headers,
            self.server_capabilities,
            progress,
            download_task,
            self.verbose,
            image_info=image_info,
        )

        if not success:
            progress.remove_task(download_task)
            return False, filename

        # Update filename in case format fallback occurred
        filename = final_filename

        # Log download statistics in verbose mode
        if self.verbose:
            file_size = os.path.getsize(filename)
            size_str = (
                f"{file_size / 1024 / 1024:.1f} MB"
                if file_size > 1024 * 1024
                else f"{file_size / 1024:.1f} KB"
            )
            self.console.print(
                f"[dim]Image {idx + 1}: {size_str} "
                f"({downloaded_bytes} bytes, {chunk_count} chunks)[/dim]"
            )

        progress.remove_task(download_task)
        return True, filename

    def _handle_download_error(
        self, e: Exception, idx: int, progress: Progress, main_task: Any
    ) -> None:
        """Handle download errors.

        Args:
            e: Exception that occurred
            idx: Canvas index
            progress: Rich Progress object
            main_task: Main progress task
        """
        if isinstance(e, requests.RequestException):
            self.console.print(
                f"[bold red]Error downloading image {idx + 1}:[/bold red] {e}"
            )
            status_code = None
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
            self.rate_limiter.handle_error(status_code)
        elif isinstance(e, KeyError):
            self.console.print(
                f"[bold red]Error accessing manifest data for image {idx + 1}:[/bold red] {e}"
            )
        else:
            self.console.print(
                f"[bold red]Unexpected error processing image {idx + 1}:[/bold red] {e}"
            )
        progress.update(main_task, advance=1)

    def download_all(self, resume: bool = False) -> None:
        """Download all images from the manifest.

        Args:
            resume: Whether to resume interrupted downloads
        """
        self._display_version()

        if not self._validate_canvases():
            return

        # Initialize file tracker (pass canvases for label-based naming)
        file_tracker = FileTracker(
            self.base_filename, self.total_images, canvases=self.canvases
        )

        # Display initial status
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

        # Probe server capabilities
        self._probe_server_capabilities(resume, file_tracker)

        # Initialize progress tracking
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
            # Track statistics
            skipped_count = 0
            failed_count = 0
            newly_downloaded_count = 0

            # Main progress task with initial statistics
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

            # Iterate through the canvases
            for idx, canvas in enumerate(self.canvases):
                try:
                    # Check if file already exists and resume is enabled
                    if resume and file_tracker.is_downloaded(idx):
                        # Try to migrate old filename to new naming scheme if needed
                        image_format = (
                            self.server_capabilities.preferred_format
                            if self.server_capabilities
                            else "jpeg"
                        )
                        target_filename_base = get_filename_from_canvas(
                            canvas, idx, image_format
                        )
                        target_filename = os.path.join(
                            self.base_filename, target_filename_base
                        )
                        migrated = file_tracker.migrate_filename_if_needed(
                            idx, target_filename
                        )
                        if migrated and self.verbose:
                            self.console.print(
                                f"[dim]Migrated old filename to: {target_filename_base}[/dim]"
                            )
                        skipped_count += 1
                        update_status_description()
                        continue

                    # Rate limiting
                    self.rate_limiter.wait_if_needed()

                    # Fetch image info
                    info = self._get_image_info(canvas, idx)
                    if not info:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        update_status_description()
                        continue

                    # Prepare download parameters
                    result = self._prepare_image_download(info, idx)
                    if result is None:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        update_status_description()
                        continue

                    service_id, image_size = result

                    # Download the image (pass image_info for size estimation and canvas for label)
                    canvas = self.canvases[idx]
                    success, filename = self._download_single_image(
                        service_id,
                        image_size,
                        idx,
                        progress,
                        main_task,
                        image_info=info,
                        canvas=canvas,
                    )

                    if not success:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        update_status_description()
                        continue

                    # Mark as downloaded and update progress
                    file_tracker.mark_downloaded(idx)
                    newly_downloaded_count += 1
                    self.rate_limiter.handle_success()
                    progress.update(main_task, advance=1)
                    update_status_description()

                except Exception as e:
                    self._handle_download_error(e, idx, progress, main_task)
                    failed_count += 1
                    update_status_description()

            # Final status
            self.console.print("\n[bold green]Download completed![/bold green]")
            self.console.print(f"Downloaded: {newly_downloaded_count}")
            self.console.print(f"Skipped: {skipped_count}")
            self.console.print(f"Failed: {failed_count}")
            self.console.print(
                f"Total: {file_tracker.get_downloaded_count()}/{self.total_images}"
            )

    def download_one(self, canvas_index: int) -> None:
        """Download a single canvas/page from the manifest.

        Args:
            canvas_index: 1-based index of the canvas to download
        """
        self._display_version()

        if not self._validate_canvases():
            return

        # Validate canvas index
        if canvas_index < 1 or canvas_index > self.total_images:
            self.console.print(
                f"[bold red]Error: Canvas index {canvas_index} is out of range "
                f"(1-{self.total_images})[/bold red]"
            )
            return

        # Get the specific canvas (convert to 0-based index)
        canvas = self.canvases[canvas_index - 1]

        self.console.print(
            f"[bold blue]Downloading canvas {canvas_index} of {self.total_images}[/bold blue]"
        )

        try:
            # Rate limiting
            self.rate_limiter.wait_if_needed()

            # Fetch image info
            image_service_url = get_image_service_from_canvas(canvas, self.version)
            if not image_service_url:
                self.console.print(
                    f"[bold red]Error: Could not find image service URL for canvas "
                    f"{canvas_index}[/bold red]"
                )
                return

            self.console.print("[dim]Fetching image info...[/dim]")
            info = fetch_image_info(image_service_url, self.headers, self.verbose)
            if not info:
                self.console.print(
                    f"[bold red]Error: Could not fetch image info for canvas "
                    f"{canvas_index}[/bold red]"
                )
                return

            # Determine image size
            image_size = get_image_size_from_info(info, self.size)
            if image_size is None:
                self.console.print(
                    f"[bold red]Error: No size information available for canvas "
                    f"{canvas_index}[/bold red]"
                )
                return

            # Construct image URL
            service_id = get_image_service_id_from_info(info)
            if not service_id:
                self.console.print(
                    f"[bold red]Error: No service ID found in image info for canvas "
                    f"{canvas_index}[/bold red]"
                )
                return

            # Generate filename from canvas label if available
            canvas = self.canvases[canvas_index - 1]
            filename_base = get_filename_from_canvas(
                canvas, canvas_index - 1, "jpeg", fallback_prefix="canvas"
            )
            filename = os.path.join(self.base_filename, filename_base)

            self.console.print("[dim]Downloading image...[/dim]")

            # Download with progress tracking
            with Progress(
                TextColumn("[bold blue]Downloading canvas"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                console=self.console,
                expand=True,
            ) as progress:
                task = progress.add_task("Downloading", total=None)

                (
                    success,
                    final_filename,
                    downloaded_bytes,
                    chunk_count,
                ) = download_image_stream(
                    service_id,
                    image_size,
                    filename,
                    self.headers,
                    None,  # No server capabilities for single canvas
                    progress,
                    task,
                    self.verbose,
                    image_info=info,  # Pass image_info for size estimation
                )

                if not success:
                    self.console.print(
                        f"[bold red]Error downloading canvas {canvas_index}[/bold red]"
                    )
                    return

                # Update filename in case format fallback occurred
                filename = final_filename

                # Update progress to 100% for completion
                progress.update(task, completed=100)

            self.console.print(
                f"[bold green]✅ Canvas {canvas_index} downloaded successfully![/bold green]"
            )
            self.console.print(f"[dim]Saved as: {filename}[/dim]")

            # Show file size and download statistics
            if os.path.exists(filename):
                file_size = os.path.getsize(filename)
                if file_size > 1024 * 1024:
                    size_str = f"{file_size / 1024 / 1024:.1f} MB"
                else:
                    size_str = f"{file_size / 1024:.1f} KB"
                self.console.print(f"[dim]File size: {size_str}[/dim]")
                if self.verbose:
                    self.console.print(
                        f"[dim]Downloaded: {downloaded_bytes} bytes in {chunk_count} chunks[/dim]"
                    )

        except requests.RequestException as e:
            self.console.print(
                f"[bold red]Error downloading canvas {canvas_index}:[/bold red] {e}"
            )
        except KeyError as e:
            self.console.print(
                f"[bold red]Error accessing manifest data:[/bold red] {e}"
            )
        except Exception as e:
            self.console.print(f"[bold red]Unexpected error:[/bold red] {e}")
