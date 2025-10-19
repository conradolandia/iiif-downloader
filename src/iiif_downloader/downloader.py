"""Core download functionality with progress tracking."""

import json
import os

import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from iiif_downloader.file_tracker import FileTracker
from iiif_downloader.rate_limiter import RateLimiter


def download_iiif_images(
    manifest_data, size=None, output_folder=None, resume=False, rate_limit=None
):
    """Download IIIF images with progress tracking and rate limiting.

    Args:
        manifest_data: Manifest data dict with 'content' and 'filename' keys
        size: Desired image width (optional)
        output_folder: Output directory for images (optional)
        resume: Whether to resume interrupted downloads
        rate_limit: Fixed rate limit in requests per minute (None for adaptive)
    """
    console = Console()

    # Headers to mimic a browser
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # Determine output directory
    if output_folder:
        base_filename = output_folder
    else:
        # Extract the base filename
        if "filename" in manifest_data:
            base_filename = os.path.splitext(manifest_data["filename"])[0]
        else:
            base_filename = "iiif_images"

    # Create a directory to store the downloaded images
    os.makedirs(base_filename, exist_ok=True)

    manifest = manifest_data["content"]
    canvases = manifest["sequences"][0]["canvases"]
    total_images = len(canvases)

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
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("•"),
        TextColumn("[bold green]{task.completed}/{task.total}"),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    ) as progress:
        # Main progress task
        main_task = progress.add_task(
            "[bold blue]Downloading images",
            total=total_images,
            completed=downloaded_count,
        )

        # Track statistics
        skipped_count = 0
        failed_count = 0

        # Iterate through the canvases in the manifest
        for idx, canvas in enumerate(canvases):
            try:
                # Check if file already exists and resume is enabled
                if resume and file_tracker.is_downloaded(idx):
                    skipped_count += 1
                    progress.update(main_task, advance=1)
                    continue

                # Rate limiting
                rate_limiter.wait_if_needed()

                # Fetch image info
                image_info_url = (
                    canvas["images"][0]["resource"]["service"]["@id"] + "/info.json"
                )

                response = requests.get(image_info_url, headers=headers)
                response.raise_for_status()

                # Check if the content type is JSON
                content_type = response.headers.get("Content-Type", "")
                if "application/json" not in content_type.lower():
                    console.print(
                        f"[bold red]Warning:[/bold red] Image info response not JSON. Content-Type: {content_type}"
                    )
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    continue

                # Try to parse JSON
                try:
                    info = json.loads(response.text)
                except json.JSONDecodeError as e:
                    console.print(
                        f"[bold red]Error decoding image info JSON:[/bold red] {e}"
                    )
                    failed_count += 1
                    progress.update(main_task, advance=1)
                    continue

                # Determine the size to use
                if size:
                    image_size = size
                else:
                    # Use the largest available size
                    image_size = max(info["sizes"], key=lambda x: x["width"])["width"]

                # Construct the image URL
                image_url = f"{info['@id']}/full/{image_size},/0/default.jpg"
                filename = os.path.join(base_filename, f"image_{idx + 1:03d}.jpg")

                # Download the image with streaming progress
                with progress:
                    download_task = progress.add_task(
                        f"[bold cyan]Downloading image {idx + 1}",
                        total=None,  # Unknown size, will update as we go
                    )

                    response = requests.get(image_url, headers=headers, stream=True)
                    response.raise_for_status()

                    # Get content length if available
                    content_length = response.headers.get("content-length")
                    if content_length:
                        progress.update(download_task, total=int(content_length))

                    # Download with progress tracking
                    downloaded_bytes = 0
                    with open(filename, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_bytes += len(chunk)
                                if content_length:
                                    progress.update(
                                        download_task, completed=downloaded_bytes
                                    )

                    # Remove the download task
                    progress.remove_task(download_task)

                # Mark as downloaded and update progress
                file_tracker.mark_downloaded(idx)
                rate_limiter.handle_success()
                progress.update(main_task, advance=1)

                # Update status
                current_rate = rate_limiter.get_current_rate()
                status_text = f"Downloaded: {file_tracker.get_downloaded_count()}/{total_images} | "
                status_text += f"Skipped: {skipped_count} | Failed: {failed_count} | "
                status_text += f"Rate: {current_rate:.1f} req/min"

                progress.update(
                    main_task,
                    description=f"[bold blue]Downloading images - {status_text}",
                )

            except requests.RequestException as e:
                console.print(
                    f"[bold red]Error downloading image {idx + 1}:[/bold red] {e}"
                )
                rate_limiter.handle_error(getattr(e, "response", {}).get("status_code"))
                failed_count += 1
                progress.update(main_task, advance=1)
            except KeyError as e:
                console.print(
                    f"[bold red]Error accessing manifest data for image {idx + 1}:[/bold red] {e}"
                )
                failed_count += 1
                progress.update(main_task, advance=1)
            except Exception as e:
                console.print(
                    f"[bold red]Unexpected error processing image {idx + 1}:[/bold red] {e}"
                )
                failed_count += 1
                progress.update(main_task, advance=1)

        # Final status
        console.print("\n[bold green]Download completed![/bold green]")
        console.print(
            f"Downloaded: {file_tracker.get_downloaded_count() - skipped_count}"
        )
        console.print(f"Skipped: {skipped_count}")
        console.print(f"Failed: {failed_count}")
