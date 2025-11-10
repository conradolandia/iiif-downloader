"""Main download orchestration functions."""

import os

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.text import Text

from iiif_downloader.download_helpers import get_default_headers, setup_output_directory
from iiif_downloader.file_tracker import FileTracker
from iiif_downloader.image_downloader import download_image_stream, fetch_image_info
from iiif_downloader.manifest import (
    detect_manifest_version,
    get_canvases_from_manifest,
    get_image_service_from_canvas,
    get_image_service_id_from_info,
    get_image_size_from_info,
)
from iiif_downloader.rate_limiter import RateLimiter
from iiif_downloader.server_capabilities import probe_server_capabilities


class CompletedTotalColumn(ProgressColumn):
    """Custom column that shows 'Unknown' instead of 'None' when total is None."""

    def render(self, task):
        """Render the completed/total display."""
        completed = task.completed or 0
        total = task.total
        if total is None:
            return Text(f"{completed}/Unknown", style="bold green")
        return Text(f"{completed}/{total}", style="bold green")


class FixedWidthTextColumn(ProgressColumn):
    """Text column with fixed width to maintain alignment."""

    def __init__(self, width=30, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.width = width

    def render(self, task):
        """Render text with fixed width."""
        text = task.description or ""
        # Truncate or pad to fixed width
        if len(text) > self.width:
            text = text[: self.width - 3] + "..."
        else:
            text = text.ljust(self.width)
        return Text(text, style="bold blue")


def download_iiif_images(
    manifest_data,
    size=None,
    output_folder=None,
    resume=False,
    rate_limit=None,
    verbose=False,
):
    """Download IIIF images with progress tracking and rate limiting.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        size: Desired image width (optional)
        output_folder: Output directory for images (optional)
        resume: Whether to resume interrupted downloads
        rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        verbose: Whether to enable verbose output
    """
    console = Console()

    # Get headers and setup output directory
    headers = get_default_headers()
    base_filename = setup_output_directory(manifest_data, output_folder)

    manifest = manifest_data["content"]
    version = detect_manifest_version(manifest)
    canvases = get_canvases_from_manifest(manifest)
    total_images = len(canvases)

    # Display detected version
    console.print(f"[bold blue]Detected IIIF version:[/bold blue] {version}")

    if not canvases:
        console.print("[bold red]Error: No canvases found in manifest[/bold red]")
        return

    # Initialize file tracker and rate limiter
    file_tracker = FileTracker(base_filename, total_images)
    rate_limiter = RateLimiter(fixed_rate=rate_limit)

    # Display initial status
    downloaded_count = file_tracker.get_downloaded_count()
    remaining_count = file_tracker.get_remaining_count()

    console.print(f"[bold blue]Total images to process:[/bold blue] {total_images}")
    if resume and downloaded_count > 0:
        console.print(
            f"[bold green]Found {downloaded_count} existing files, will skip them[/bold green]"
        )
        console.print(
            f"[bold yellow]Will download {remaining_count} remaining images[/bold yellow]"
        )

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
        console=console,
        expand=True,
    ) as progress:
        # Track statistics
        skipped_count = 0
        failed_count = 0
        newly_downloaded_count = 0  # Track only files downloaded in this run

        # Main progress task with initial statistics
        initial_desc = (
            f"DL:{newly_downloaded_count:3d} "
            f"SK:{skipped_count:3d} "
            f"FL:{failed_count:2d} "
            f"T:{downloaded_count:3d}/{total_images} "
            f"R:  0.0"
        )
        main_task = progress.add_task(
            initial_desc,
            total=total_images,
            completed=downloaded_count,
        )

        def update_status_description():
            """Update the progress bar description with current statistics."""
            current_rate = rate_limiter.get_current_rate()
            desc = (
                f"DL:{newly_downloaded_count:3d} "
                f"SK:{skipped_count:3d} "
                f"FL:{failed_count:2d} "
                f"T:{file_tracker.get_downloaded_count():3d}/{total_images} "
                f"R:{current_rate:5.1f}"
            )
            progress.update(main_task, description=desc)

        # Probe server capabilities with the first image
        server_capabilities = None
        probed_image_info = None  # Cache the probed image info
        probed_image_idx = None  # Track which image was probed
        if canvases:
            console.print("[dim]Probing server capabilities...[/dim]")
            # Find first canvas that will be downloaded (not skipped)
            probe_canvas_idx = None
            probe_canvas = None
            for idx, canvas in enumerate(canvases):
                if not resume or not file_tracker.is_downloaded(idx):
                    probe_canvas_idx = idx
                    probe_canvas = canvas
                    break

            if probe_canvas_idx is not None and probe_canvas is not None:
                try:
                    image_service_url = get_image_service_from_canvas(
                        probe_canvas, version
                    )
                    if image_service_url:
                        info = fetch_image_info(image_service_url, headers, verbose)
                        if info:
                            # Cache the probed image info to avoid fetching again
                            probed_image_info = info
                            probed_image_idx = probe_canvas_idx

                            service_id = get_image_service_id_from_info(info)
                            image_size = get_image_size_from_info(info, size)

                            if service_id and image_size:
                                server_capabilities = probe_server_capabilities(
                                    service_id, image_size, headers
                                )
                                # Display discovered capabilities
                                console.print(
                                    f"[dim]Server capabilities:[/dim] "
                                    f"format=.{server_capabilities.preferred_format}"
                                )
                                if server_capabilities.max_test_size:
                                    console.print(
                                        f"[dim]  Max tested size: {server_capabilities.max_test_size}px[/dim]"
                                    )
                                if server_capabilities.supported_qualities:
                                    qualities_str = ", ".join(
                                        server_capabilities.supported_qualities
                                    )
                                    console.print(
                                        f"[dim]  Supported qualities: {qualities_str}[/dim]"
                                    )
                                if server_capabilities.requires_authentication:
                                    console.print(
                                        "[yellow]  ⚠ Authentication may be required[/yellow]"
                                    )
                                if server_capabilities.rate_limit_detected:
                                    console.print(
                                        "[yellow]  ⚠ Rate limiting detected - using conservative limits[/yellow]"
                                    )
                except Exception:
                    # If probing fails, default to safe settings
                    pass

        # Iterate through the canvases in the manifest
        for idx, canvas in enumerate(canvases):
            try:
                # Check if file already exists and resume is enabled
                if resume and file_tracker.is_downloaded(idx):
                    skipped_count += 1
                    # Don't advance progress bar - these files were already counted
                    # in the initial completed count
                    # Update description with current statistics
                    update_status_description()
                    continue

                # Rate limiting
                rate_limiter.wait_if_needed()

                # Fetch image info (reuse cached info if this is the probed image)
                if idx == probed_image_idx and probed_image_info is not None:
                    info = probed_image_info
                    if verbose:
                        console.print(
                            f"[dim]Using cached image info for image {idx + 1}[/dim]"
                        )
                else:
                    image_service_url = get_image_service_from_canvas(canvas, version)
                    if not image_service_url:
                        console.print(
                            f"[bold red]Error: Could not find image service URL for canvas {idx + 1}[/bold red]"
                        )
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        continue

                    # Fetch image info
                    info = fetch_image_info(image_service_url, headers, verbose)
                    if not info:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        continue

                # Determine the size to use using modular function
                image_size = get_image_size_from_info(info, size)
                if image_size is None:
                    console.print(
                        f"[bold red]Error: No size information available for image {idx + 1}[/bold red]"
                    )
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    continue

                # Adjust size if server has a maximum tested size limit
                if (
                    server_capabilities
                    and server_capabilities.max_test_size
                    and image_size > server_capabilities.max_test_size
                ):
                    image_size = server_capabilities.max_test_size

                # Construct the image URL
                service_id = get_image_service_id_from_info(info)
                if not service_id:
                    console.print(
                        f"[bold red]Error: No service ID found in image info for image {idx + 1}[/bold red]"
                    )
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    continue

                # Determine initial format and filename
                image_format = (
                    server_capabilities.preferred_format
                    if server_capabilities
                    else "jpeg"
                )
                filename = os.path.join(
                    base_filename, f"image_{idx + 1:03d}.{image_format}"
                )

                # Download the image with streaming progress
                with progress:
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
                        headers,
                        server_capabilities,
                        progress,
                        download_task,
                        verbose,
                    )

                    if not success:
                        failed_count += 1
                        progress.update(main_task, advance=1)
                        progress.remove_task(download_task)
                        continue

                    # Update filename in case format fallback occurred
                    filename = final_filename

                    # Log download statistics in verbose mode
                    if verbose:
                        file_size = os.path.getsize(filename)
                        size_str = (
                            f"{file_size / 1024 / 1024:.1f} MB"
                            if file_size > 1024 * 1024
                            else f"{file_size / 1024:.1f} KB"
                        )
                        console.print(
                            f"[dim]Image {idx + 1}: {size_str} "
                            f"({downloaded_bytes} bytes, {chunk_count} chunks)[/dim]"
                        )

                    # Remove the download task
                    progress.remove_task(download_task)

                # Mark as downloaded and update progress
                file_tracker.mark_downloaded(idx)
                newly_downloaded_count += 1
                rate_limiter.handle_success()
                progress.update(main_task, advance=1)

                # Update status with fixed-width format for alignment
                update_status_description()

            except requests.RequestException as e:
                console.print(
                    f"[bold red]Error downloading image {idx + 1}:[/bold red] {e}"
                )
                # Get status code from response if available
                status_code = None
                if hasattr(e, "response") and e.response is not None:
                    status_code = e.response.status_code
                rate_limiter.handle_error(status_code)
                failed_count += 1
                progress.update(main_task, advance=1)
                # Update description with current statistics
                update_status_description()
            except KeyError as e:
                console.print(
                    f"[bold red]Error accessing manifest data for image {idx + 1}:[/bold red] {e}"
                )
                failed_count += 1
                progress.update(main_task, advance=1)
                # Update description with current statistics
                update_status_description()
            except Exception as e:
                console.print(
                    f"[bold red]Unexpected error processing image {idx + 1}:[/bold red] {e}"
                )
                failed_count += 1
                progress.update(main_task, advance=1)
                # Update description with current statistics
                update_status_description()

        # Final status
        console.print("\n[bold green]Download completed![/bold green]")
        console.print(f"Downloaded: {newly_downloaded_count}")
        console.print(f"Skipped: {skipped_count}")
        console.print(f"Failed: {failed_count}")
        console.print(f"Total: {file_tracker.get_downloaded_count()}/{total_images}")


def download_single_canvas(
    manifest_data,
    canvas_index,
    size=None,
    output_folder=None,
    rate_limit=None,
    verbose=False,
):
    """Download a single canvas/page from a IIIF manifest.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        canvas_index: 1-based index of the canvas to download
        size: Desired image width (optional)
        output_folder: Output directory for images (optional)
        rate_limit: Fixed rate limit in requests per minute (None for adaptive)
        verbose: Whether to enable verbose output
    """
    console = Console()

    # Get headers and setup output directory
    headers = get_default_headers()
    base_filename = setup_output_directory(manifest_data, output_folder)

    manifest = manifest_data["content"]
    version = detect_manifest_version(manifest)
    canvases = get_canvases_from_manifest(manifest)
    total_images = len(canvases)

    # Display detected version
    console.print(f"[bold blue]Detected IIIF version:[/bold blue] {version}")

    if not canvases:
        console.print("[bold red]Error: No canvases found in manifest[/bold red]")
        return

    # Validate canvas index
    if canvas_index < 1 or canvas_index > total_images:
        console.print(
            f"[bold red]Error: Canvas index {canvas_index} is out of range (1-{total_images})[/bold red]"
        )
        return

    # Initialize rate limiter
    rate_limiter = RateLimiter(fixed_rate=rate_limit)

    # Get the specific canvas (convert to 0-based index)
    canvas = canvases[canvas_index - 1]

    console.print(
        f"[bold blue]Downloading canvas {canvas_index} of {total_images}[/bold blue]"
    )

    try:
        # Rate limiting
        rate_limiter.wait_if_needed()

        # Fetch image info
        image_service_url = get_image_service_from_canvas(canvas, version)
        if not image_service_url:
            console.print(
                f"[bold red]Error: Could not find image service URL for canvas {canvas_index}[/bold red]"
            )
            return

        console.print("[dim]Fetching image info...[/dim]")
        info = fetch_image_info(image_service_url, headers, verbose)
        if not info:
            console.print(
                f"[bold red]Error: Could not fetch image info for canvas {canvas_index}[/bold red]"
            )
            return

        # Determine image size using modular function
        image_size = get_image_size_from_info(info, size)
        if image_size is None:
            console.print(
                f"[bold red]Error: No size information available for canvas {canvas_index}[/bold red]"
            )
            return

        # Construct image URL
        service_id = get_image_service_id_from_info(info)
        if not service_id:
            console.print(
                f"[bold red]Error: No service ID found in image info for canvas {canvas_index}[/bold red]"
            )
            return

        # Try .jpeg first (spec recommendation), fall back to .jpg if needed
        filename = os.path.join(base_filename, f"canvas_{canvas_index:03d}.jpeg")

        console.print("[dim]Downloading image...[/dim]")

        # Download with progress tracking
        with Progress(
            TextColumn("[bold blue]Downloading canvas"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console,
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
                headers,
                None,  # No server capabilities for single canvas
                progress,
                task,
                verbose,
            )

            if not success:
                console.print(
                    f"[bold red]Error downloading canvas {canvas_index}[/bold red]"
                )
                return

            # Update filename in case format fallback occurred
            filename = final_filename

            # Update progress to 100% for completion
            progress.update(task, completed=100)

        console.print(
            f"[bold green]✅ Canvas {canvas_index} downloaded successfully![/bold green]"
        )
        console.print(f"[dim]Saved as: {filename}[/dim]")

        # Show file size and download statistics
        if os.path.exists(filename):
            file_size = os.path.getsize(filename)
            if file_size > 1024 * 1024:
                size_str = f"{file_size / 1024 / 1024:.1f} MB"
            else:
                size_str = f"{file_size / 1024:.1f} KB"
            console.print(f"[dim]File size: {size_str}[/dim]")
            if verbose:
                console.print(
                    f"[dim]Downloaded: {downloaded_bytes} bytes in {chunk_count} chunks[/dim]"
                )

    except requests.RequestException as e:
        console.print(
            f"[bold red]Error downloading canvas {canvas_index}:[/bold red] {e}"
        )
    except KeyError as e:
        console.print(f"[bold red]Error accessing manifest data:[/bold red] {e}")
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
