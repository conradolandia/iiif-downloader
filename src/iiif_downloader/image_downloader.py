"""Core image downloading logic with streaming and progress tracking."""

import json
import os
import time

import requests
from rich.console import Console

from .auth_detector import (
    get_auth_error_message,
    is_authentication_required,
    is_recaptcha_page,
)
from .constants import (
    DOWNLOAD_RETRY_BACKOFF_SECONDS,
    JSON_CONTENT_TYPES,
    MAX_DOWNLOAD_RETRIES,
    MIN_VALID_IMAGE_BYTES,
)


def remove_incomplete_file(filename: str) -> None:
    """Remove a partial or empty download target if it exists.

    Args:
        filename: Path to the file that may be incomplete
    """
    try:
        if os.path.exists(filename):
            os.remove(filename)
    except OSError:
        pass


def is_download_complete(
    downloaded_bytes: int, content_length: int | None
) -> tuple[bool, str | None]:
    """Check whether a downloaded file looks complete.

    Args:
        downloaded_bytes: Number of bytes written
        content_length: Expected size from Content-Length, if known

    Returns:
        tuple: (is_complete, reason_if_incomplete)
    """
    if downloaded_bytes < MIN_VALID_IMAGE_BYTES:
        return False, (
            f"downloaded only {downloaded_bytes} bytes "
            f"(minimum {MIN_VALID_IMAGE_BYTES})"
        )

    if content_length is not None and downloaded_bytes < content_length:
        return False, (
            f"truncated download: got {downloaded_bytes:,} of {content_length:,} bytes"
        )

    return True, None


def estimate_file_size_from_dimensions(
    width: int, height: int, image_format: str = "jpeg"
) -> int:
    """Estimate file size based on image dimensions and format.

    Uses typical compression ratios for different image formats:
    - JPEG: ~0.1-0.3 compression ratio (10-30% of uncompressed size)
    - PNG: ~0.5-1.0 compression ratio (50-100% of uncompressed size)
    - TIFF: ~1.0 compression ratio (100% of uncompressed size)

    Args:
        width: Image width in pixels
        height: Image height in pixels
        image_format: Image format (jpeg, jpg, png, tiff)

    Returns:
        int: Estimated file size in bytes
    """
    # Calculate uncompressed size (width × height × 3 bytes for RGB)
    uncompressed_size = width * height * 3

    # Apply format-specific compression ratios
    format_lower = image_format.lower()
    if format_lower in ("jpeg", "jpg"):
        # JPEG typically compresses to 10-20% of original size for high quality
        # Use 15% as a reasonable estimate
        compression_ratio = 0.15
    elif format_lower == "png":
        # PNG compression varies widely, use 60% as average
        compression_ratio = 0.6
    elif format_lower in ("tiff", "tif"):
        # TIFF is usually uncompressed or lightly compressed
        compression_ratio = 1.0
    else:
        # Default to JPEG-like compression
        compression_ratio = 0.15

    estimated_size = int(uncompressed_size * compression_ratio)
    return max(estimated_size, 1024)  # Minimum 1KB estimate


def get_content_length_from_head(
    image_url: str, session_manager, timeout: tuple[int, int] = (30, 60)
) -> int | None:
    """Get Content-Length from HEAD request.

    Args:
        image_url: URL of the image to download
        session_manager: SessionManager instance for making requests
        timeout: Connection and read timeout tuple

    Returns:
        int: Content-Length in bytes, or None if not available
    """
    try:
        response = session_manager.head(image_url, timeout=timeout)
        response.raise_for_status()

        # Check for authentication/bot protection
        if is_authentication_required(response):
            # Don't print error here, it will be caught in download_image_stream
            return None

        content_length = response.headers.get("content-length")
        if content_length:
            return int(content_length)
    except requests.RequestException:
        # HEAD request failed, return None
        pass
    return None


def fetch_image_info(image_service_url, session_manager, verbose=False):
    """Fetch and parse image info from IIIF image service.

    Args:
        image_service_url: URL of the image service
        session_manager: SessionManager instance for making requests
        verbose: Whether to print verbose output

    Returns:
        dict: Parsed image info JSON, or None if error
    """
    console = Console()
    image_info_url = image_service_url + "/info.json"

    if verbose:
        console.print(f"[dim]Fetching image info: {image_info_url}[/dim]")

    try:
        response = session_manager.get(image_info_url, timeout=30)
        response.raise_for_status()

        # Check for authentication/bot protection
        if is_authentication_required(response):
            error_msg = get_auth_error_message(
                image_info_url, session_manager.cookie_file, response
            )
            console.print(error_msg)
            return None

        # Check if the content type is JSON (including JSON-LD and other JSON variants)
        content_type = response.headers.get("Content-Type", "")
        if not any(
            json_type in content_type.lower() for json_type in JSON_CONTENT_TYPES
        ):
            # Check if it's HTML (might be an error page)
            if "text/html" in content_type.lower():
                if is_recaptcha_page(response):
                    error_msg = get_auth_error_message(
                        image_info_url, session_manager.cookie_file, response
                    )
                    console.print(error_msg)
                else:
                    console.print(
                        f"[yellow]Warning:[/yellow] Server returned HTML instead of JSON. "
                        f"Content-Type: {content_type}"
                    )
            else:
                if verbose:
                    console.print(
                        f"[yellow]Warning:[/yellow] Image info response not JSON. "
                        f"Content-Type: {content_type}"
                    )
            return None

        # Parse JSON
        info = json.loads(response.text)
        return info
    except requests.RequestException as e:
        if verbose:
            console.print(f"[red]Error fetching image info:[/red] {e}")
        return None
    except json.JSONDecodeError as e:
        if verbose:
            console.print(f"[red]Error decoding image info JSON:[/red] {e}")
        return None


def download_image_stream(
    service_id,
    image_size,
    filename,
    session_manager,
    server_capabilities=None,
    progress=None,
    task=None,
    verbose=False,
    image_info=None,
    max_retries: int = MAX_DOWNLOAD_RETRIES,
):
    """Download an image with streaming, validation, and retries.

    Args:
        service_id: Image service ID
        image_size: Desired image width
        filename: Output filename
        session_manager: SessionManager instance for making requests
        server_capabilities: Server capabilities (optional)
        progress: Rich Progress object (optional)
        task: Progress task ID (optional)
        verbose: Whether to print verbose output
        image_info: Image info dict with width/height for size estimation (optional)
        max_retries: Number of attempts for empty/truncated/network failures

    Returns:
        tuple: (success: bool, final_filename: str, downloaded_bytes: int, chunk_count: int)
    """
    console = Console()

    # Use format from server capabilities or default to .jpeg
    image_format = (
        server_capabilities.preferred_format if server_capabilities else "jpeg"
    )
    image_url = f"{service_id}/full/{image_size},/0/default.{image_format}"

    if verbose:
        console.print(f"[dim]Connecting to: {image_url}[/dim]")

    # Set timeout for connection and read operations
    timeout = (30, 60)  # (connect timeout, read timeout)

    # Try to get Content-Length from HEAD request first
    estimated_size = None
    head_content_length = get_content_length_from_head(
        image_url, session_manager, timeout
    )

    # If HEAD request didn't provide Content-Length, try to estimate from image info
    if head_content_length is None and image_info:
        width = image_info.get("width")
        height = image_info.get("height")
        if width and height:
            # Calculate height based on aspect ratio if we're requesting a specific width
            if image_size and width != image_size:
                # Maintain aspect ratio
                aspect_ratio = height / width
                estimated_height = int(image_size * aspect_ratio)
                estimated_size = estimate_file_size_from_dimensions(
                    image_size, estimated_height, image_format
                )
            else:
                estimated_size = estimate_file_size_from_dimensions(
                    width, height, image_format
                )
            if verbose and estimated_size:
                console.print(
                    f"[dim]Estimated size from dimensions: {estimated_size:,} bytes "
                    f"({estimated_size / 1024 / 1024:.1f} MB)[/dim]"
                )

    last_filename = filename
    last_downloaded_bytes = 0
    last_chunk_count = 0

    for attempt in range(1, max_retries + 1):
        if progress and task is not None:
            progress.update(task, completed=0)

        (
            success,
            last_filename,
            last_downloaded_bytes,
            last_chunk_count,
            retryable,
            failure_reason,
        ) = _download_image_stream_once(
            image_url=image_url,
            filename=last_filename,
            session_manager=session_manager,
            server_capabilities=server_capabilities,
            progress=progress,
            task=task,
            verbose=verbose,
            timeout=timeout,
            estimated_size=estimated_size,
            head_content_length=head_content_length,
            image_size=image_size,
            service_id=service_id,
            console=console,
        )

        if success:
            return True, last_filename, last_downloaded_bytes, last_chunk_count

        if not retryable:
            return False, last_filename, last_downloaded_bytes, last_chunk_count

        if attempt < max_retries:
            delay = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
            reason = failure_reason or "download failed"
            console.print(
                f"[yellow]Incomplete download ({reason}). "
                f"Retrying in {delay:.0f}s ({attempt}/{max_retries})...[/yellow]"
            )
            time.sleep(delay)

    return False, last_filename, last_downloaded_bytes, last_chunk_count


def _download_image_stream_once(
    image_url: str,
    filename: str,
    session_manager,
    server_capabilities,
    progress,
    task,
    verbose: bool,
    timeout: tuple[int, int],
    estimated_size: int | None,
    head_content_length: int | None,
    image_size,
    service_id: str,
    console: Console,
) -> tuple[bool, str, int, int, bool, str | None]:
    """Perform a single streaming download attempt.

    Returns:
        tuple: (success, filename, downloaded_bytes, chunk_count, retryable, failure_reason)
    """
    content_length = head_content_length
    expected_bytes: int | None = None

    try:
        response = session_manager.get(image_url, stream=True, timeout=timeout)

        # Check for authentication/bot protection before processing
        if is_authentication_required(response):
            error_msg = get_auth_error_message(
                image_url, session_manager.cookie_file, response
            )
            console.print(error_msg)
            return False, filename, 0, 0, False, "authentication required"

        # If format fails and we haven't probed, try fallback
        if not server_capabilities and response.status_code in (400, 404, 415):
            image_format = "jpg"
            image_url = f"{service_id}/full/{image_size},/0/default.{image_format}"
            # Update filename to match format
            base, _ext = os.path.splitext(filename)
            filename = f"{base}.{image_format}"
            if verbose:
                console.print(f"[dim]Format fallback, retrying with: {image_url}[/dim]")
            response = session_manager.get(image_url, stream=True, timeout=timeout)

            # Check again after retry
            if is_authentication_required(response):
                error_msg = get_auth_error_message(
                    image_url, session_manager.cookie_file, response
                )
                console.print(error_msg)
                return False, filename, 0, 0, False, "authentication required"

        response.raise_for_status()

        # Check if response is actually an image
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            if is_recaptcha_page(response):
                error_msg = get_auth_error_message(
                    image_url, session_manager.cookie_file, response
                )
                console.print(error_msg)
            else:
                console.print(
                    f"[red]Error:[/red] Server returned HTML instead of image. "
                    f"Content-Type: {content_type}"
                )
            return False, filename, 0, 0, False, "html response"

        if verbose:
            console.print(
                f"[dim]Response status: {response.status_code}, "
                f"Content-Type: {response.headers.get('content-type', 'N/A')}, "
                f"Content-Length: {response.headers.get('content-length', 'N/A')}[/dim]"
            )

        # Get content length from response headers (most reliable)
        content_length_from_response = response.headers.get("content-length")
        if content_length_from_response:
            content_length = int(content_length_from_response)
            expected_bytes = content_length
        # If still no content length, use estimated size for progress only
        elif estimated_size:
            content_length = estimated_size
        else:
            content_length = None

        # Set progress total if we have an estimate
        if content_length and progress and task is not None:
            progress.update(task, total=content_length)
            if verbose:
                if content_length_from_response:
                    console.print(f"[dim]Expected size: {content_length:,} bytes[/dim]")
                else:
                    console.print(
                        f"[dim]Using estimated size: {content_length:,} bytes "
                        f"({content_length / 1024 / 1024:.1f} MB)[/dim]"
                    )

        # Download with progress tracking
        downloaded_bytes = 0
        chunk_count = 0
        # Store base description for updates when Content-Length is missing
        base_description = None
        if progress and task is not None:
            try:
                base_description = progress.tasks[task].description
            except (KeyError, AttributeError, IndexError):
                # If we can't get the description, use a default
                base_description = "Downloading"

        # Adaptive estimation: refine estimate as we download
        adaptive_estimate = content_length
        samples_for_estimation: list[int] = []
        min_samples_for_estimate = 5  # Need at least 5 chunks to estimate

        try:
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        chunk_count += 1

                        # Collect samples for adaptive estimation
                        if not content_length_from_response and chunk_count <= 20:
                            samples_for_estimation.append(len(chunk))

                        # Adaptive estimation: if we don't have a reliable size,
                        # estimate based on average chunk size and download rate
                        if (
                            not content_length_from_response
                            and chunk_count >= min_samples_for_estimate
                            and len(samples_for_estimation) >= min_samples_for_estimate
                        ):
                            # Estimate total based on downloaded bytes
                            # This is a rough estimate that improves as we download
                            if not adaptive_estimate or chunk_count % 10 == 0:
                                # Refine estimate every 10 chunks
                                # Assume we're about 10-20% through the file
                                # (conservative estimate)
                                estimated_total = int(
                                    downloaded_bytes * 8
                                )  # Assume we're ~12.5% done
                                if estimated_total > downloaded_bytes:
                                    adaptive_estimate = estimated_total
                                    if progress and task is not None:
                                        progress.update(task, total=adaptive_estimate)
                                    if verbose and chunk_count % 20 == 0:
                                        console.print(
                                            f"[dim]Refined size estimate: "
                                            f"{adaptive_estimate:,} bytes "
                                            f"({adaptive_estimate / 1024 / 1024:.1f} MB)[/dim]"
                                        )

                        # Update progress (safely handle any progress update errors)
                        try:
                            if progress and task is not None:
                                # Use adaptive estimate if available, otherwise use content_length
                                total_to_use = adaptive_estimate or content_length
                                if total_to_use:
                                    progress.update(task, completed=downloaded_bytes)
                                else:
                                    # Update progress even without content-length
                                    # Show bytes in readable format in the description
                                    # (update every 10 chunks)
                                    if chunk_count % 10 == 0:
                                        if downloaded_bytes > 1024 * 1024:
                                            size_str = f"{downloaded_bytes / 1024 / 1024:.1f} MB"
                                        elif downloaded_bytes > 1024:
                                            size_str = (
                                                f"{downloaded_bytes / 1024:.1f} KB"
                                            )
                                        else:
                                            size_str = f"{downloaded_bytes} B"

                                        # Update description with size
                                        if base_description:
                                            # Extract base description if it already has size info
                                            desc = (
                                                base_description.split(" (")[0]
                                                if " (" in base_description
                                                else base_description
                                            )
                                            progress.update(
                                                task,
                                                completed=downloaded_bytes,
                                                description=f"{desc} ({size_str})",
                                            )

                                        if verbose:
                                            console.print(
                                                f"[dim]Downloaded: {downloaded_bytes:,} bytes "
                                                f"({chunk_count} chunks)[/dim]"
                                            )
                                    else:
                                        # Update completed bytes without changing description
                                        progress.update(
                                            task, completed=downloaded_bytes
                                        )
                        except Exception:
                            # If progress update fails, continue downloading
                            # Don't let progress update errors break the download
                            pass

                        # Flush to ensure data is written
                        f.flush()

            # After loop completes, iter_content() has finished
            # This means the stream has ended
            if verbose:
                console.print(f"[dim]Stream ended after {chunk_count} chunks[/dim]")

            file_size = (
                os.path.getsize(filename)
                if os.path.exists(filename)
                else downloaded_bytes
            )
            if verbose:
                console.print(
                    f"[dim]Download complete: {file_size} bytes written "
                    f"({chunk_count} chunks)[/dim]"
                )

            complete, reason = is_download_complete(file_size, expected_bytes)
            if not complete:
                remove_incomplete_file(filename)
                return False, filename, file_size, chunk_count, True, reason

            return True, filename, downloaded_bytes, chunk_count, False, None

        finally:
            # Explicitly close the connection
            response.close()
            if verbose:
                console.print("[dim]Connection closed[/dim]")

    except requests.RequestException as e:
        remove_incomplete_file(filename)
        if verbose:
            console.print(f"[red]Error downloading image:[/red] {e}")
        return False, filename, 0, 0, True, str(e)
    except OSError as e:
        remove_incomplete_file(filename)
        if verbose:
            console.print(f"[red]Error writing image:[/red] {e}")
        return False, filename, 0, 0, True, str(e)
