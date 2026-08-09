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
    is_size_limit_rejection,
)
from .constants import (
    DOWNLOAD_RETRY_BACKOFF_SECONDS,
    JSON_CONTENT_TYPES,
    MAX_DOWNLOAD_RETRIES,
    MIN_VALID_IMAGE_BYTES,
    SIZE_STATUS_CHECK_TIMEOUT,
)
from .server_capabilities import _derive_max_edge
from .servers import ServerAdapter, resolve_adapter

# HTTP statuses used by some IIIF hosts when a requested size is too large.
# 400 is handled as format first, then as size if every extension fails.
_SIZE_REJECTION_STATUSES = frozenset({403, 413})
_FORMAT_REJECTION_STATUSES = frozenset({400, 404, 415})
_MIN_FALLBACK_WIDTH = 256


def _format_byte_size(num_bytes: int) -> str:
    """Format a byte count for progress display.

    Args:
        num_bytes: Number of bytes

    Returns:
        str: Human-readable size string
    """
    if num_bytes > 1024 * 1024:
        return f"{num_bytes / 1024 / 1024:.1f} MB"
    if num_bytes > 1024:
        return f"{num_bytes / 1024:.1f} KB"
    return f"{num_bytes} B"


def _progress_print(progress, console: Console, message: str) -> None:
    """Print a message without corrupting a live Rich Progress display.

    Args:
        progress: Rich Progress object, or None
        console: Fallback Console when progress is not active
        message: Markup message to print
    """
    if progress is not None:
        progress.console.print(message)
    else:
        console.print(message)


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
    image_url: str,
    session_manager,
    timeout: tuple[float, float] | None = None,
    adapter: ServerAdapter | None = None,
) -> int | None:
    """Get Content-Length from a short HEAD request.

    Uses a short timeout and fails open: many IIIF servers omit Content-Length
    or hang on HEAD for some sizes. Download proceeds with GET regardless.
    Host adapters may skip this HEAD entirely.

    Args:
        image_url: URL of the image to download
        session_manager: SessionManager instance for making requests
        timeout: Connection and read timeout tuple; adapter default when None
        adapter: Host adapter; resolved from ``image_url`` when omitted

    Returns:
        int: Content-Length in bytes, or None if not available
    """
    adapter = adapter or resolve_adapter(image_url)
    if adapter.skip_content_length_head:
        return None

    head_timeout = (
        timeout if timeout is not None else adapter.head_content_length_timeout
    )
    try:
        response = session_manager.head(image_url, timeout=head_timeout)
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


def _iiif_image_url(service_id: str, width: int, image_format: str) -> str:
    """Build a full-region IIIF Image API request URL for a given width.

    Args:
        service_id: Image service base URL
        width: Requested width in pixels
        image_format: File extension without dot (jpg/jpeg)

    Returns:
        str: Absolute image request URL
    """
    return f"{service_id}/full/{width},/0/default.{image_format}"


def _listed_widths_below(image_info: dict | None, upper: int) -> list[int]:
    """Return descending widths from info.json ``sizes`` strictly below ``upper``.

    Args:
        image_info: Parsed info.json (optional)
        upper: Exclusive upper bound

    Returns:
        list[int]: Candidate widths, largest first
    """
    if not image_info or "sizes" not in image_info:
        return []
    widths: list[int] = []
    for entry in image_info.get("sizes") or []:
        try:
            width = int(entry.get("width"))
        except (TypeError, ValueError, AttributeError):
            continue
        if _MIN_FALLBACK_WIDTH <= width < upper and width not in widths:
            widths.append(width)
    widths.sort(reverse=True)
    return widths


def _request_status(
    image_url: str,
    session_manager,
    timeout: tuple[float, float] = SIZE_STATUS_CHECK_TIMEOUT,
) -> int | None:
    """Return HTTP status for an image URL without reading the body.

    Args:
        image_url: Absolute image request URL
        session_manager: SessionManager instance
        timeout: Connect/read timeout

    Returns:
        int | None: Status code, or None on transport failure
    """
    response = None
    try:
        response = session_manager.get(image_url, stream=True, timeout=timeout)
        return int(response.status_code)
    except requests.RequestException:
        return None
    finally:
        if response is not None:
            response.close()


def _width_is_allowed(
    service_id: str,
    width: int,
    image_format: str,
    session_manager,
) -> bool:
    """Return True if the server accepts a full-region request at ``width``.

    Args:
        service_id: Image service base URL
        width: Width to test
        image_format: jpg/jpeg extension
        session_manager: SessionManager instance

    Returns:
        bool: True when status is 200
    """
    status = _request_status(
        _iiif_image_url(service_id, width, image_format), session_manager
    )
    return status == 200


def find_max_requestable_width(
    service_id: str,
    desired_width: int,
    image_format: str,
    session_manager,
    image_info: dict | None = None,
) -> int | None:
    """Find the largest working width at or below ``desired_width`` via GET status.

    Used when the preferred size is rejected (403/400/413). Prefers listed
    ``sizes`` as a known-good floor, then binary-searches upward.

    Args:
        service_id: Image service base URL
        desired_width: Width that was rejected (search is below this)
        image_format: jpg/jpeg extension
        session_manager: SessionManager instance
        image_info: Optional info.json for listed sizes

    Returns:
        int | None: Largest accepted width, or None if none work
    """
    if desired_width < _MIN_FALLBACK_WIDTH:
        return None

    best: int | None = None
    for listed in _listed_widths_below(image_info, desired_width):
        if _width_is_allowed(service_id, listed, image_format, session_manager):
            best = listed
            break

    lo = best if best is not None else _MIN_FALLBACK_WIDTH
    hi = desired_width - 1
    if best is None and _width_is_allowed(
        service_id, lo, image_format, session_manager
    ):
        best = lo

    while lo <= hi:
        mid = (lo + hi + 1) // 2
        if _width_is_allowed(service_id, mid, image_format, session_manager):
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1

    return best


def _remember_working_width(
    server_capabilities,
    working_width: int,
    image_info: dict | None,
) -> None:
    """Tighten shared capabilities after a size rejection forced a smaller width.

    Only lowers ``max_test_size`` / ``max_edge``. A successful download at the
    originally requested size must not invent a ceiling.

    Args:
        server_capabilities: Mutable ServerCapabilities or None
        working_width: Width that returned HTTP 200 after negotiation
        image_info: Optional info.json for max_edge derivation
    """
    if server_capabilities is None:
        return
    previous = server_capabilities.max_test_size
    if previous is not None and working_width >= previous:
        return
    server_capabilities.max_test_size = working_width
    width = image_info.get("width") if image_info else None
    height = image_info.get("height") if image_info else None
    try:
        w = int(width) if width is not None else None
        h = int(height) if height is not None else None
    except (TypeError, ValueError):
        w, h = None, None
    server_capabilities.max_edge = _derive_max_edge(working_width, w, h)


def fetch_image_info(
    image_service_url,
    session_manager,
    verbose=False,
    console: Console | None = None,
):
    """Fetch and parse image info from IIIF image service.

    Args:
        image_service_url: URL of the image service
        session_manager: SessionManager instance for making requests
        verbose: Whether to print verbose output
        console: Console to use for messages (defaults to a new Console)

    Returns:
        dict: Parsed image info JSON, or None if error
    """
    console = console or Console()
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


def _is_gateway_timeout_failure(failure_reason: str | None) -> bool:
    """Return True if a transport error looks like a gateway timeout (504/502).

    Bodleian often returns 504 for hang-prone exact max sizes; treat those as
    size rejections so we can negotiate a smaller width.

    Args:
        failure_reason: Exception text or failure label from a download attempt

    Returns:
        bool: Whether the failure should trigger size negotiation
    """
    if not failure_reason:
        return False
    lower = failure_reason.lower()
    return "504" in lower or "502" in lower or "gateway time" in lower


def download_url_stream(
    image_url: str,
    filename: str,
    session_manager,
    progress=None,
    task=None,
    verbose: bool = False,
    max_retries: int = MAX_DOWNLOAD_RETRIES,
) -> tuple[bool, str, int, int]:
    """Download an image from a direct URL with streaming and retries.

    Used for non-IIIF sources (e.g. METS FLocat URLs) where the image URL
    is already absolute and size negotiation does not apply.

    Args:
        image_url: Absolute image URL.
        filename: Output filename.
        session_manager: SessionManager instance for making requests.
        progress: Rich Progress object (optional).
        task: Progress task ID (optional).
        verbose: Whether to print verbose output.
        max_retries: Number of attempts for empty/truncated/network failures.

    Returns:
        tuple: (success, final_filename, downloaded_bytes, chunk_count)
    """
    console = Console()
    timeout = (30, 60)

    if verbose:
        _progress_print(progress, console, f"[dim]Connecting to: {image_url}[/dim]")

    head_content_length = get_content_length_from_head(image_url, session_manager)

    last_filename = filename
    last_downloaded_bytes = 0
    last_chunk_count = 0

    for attempt in range(1, max_retries + 1):
        if progress and task is not None:
            progress.update(task, completed=0, total=None)

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
            server_capabilities=None,
            progress=progress,
            task=task,
            verbose=verbose,
            timeout=timeout,
            head_content_length=head_content_length,
            image_size=None,
            service_id="",
            console=console,
            allow_iiif_format_fallback=False,
        )

        if success:
            return True, last_filename, last_downloaded_bytes, last_chunk_count

        if not retryable:
            return False, last_filename, last_downloaded_bytes, last_chunk_count

        if attempt < max_retries:
            delay = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
            reason = failure_reason or "download failed"
            _progress_print(
                progress,
                console,
                f"[yellow]Incomplete download ({reason}). "
                f"Retrying in {delay:.0f}s ({attempt}/{max_retries})...[/yellow]",
            )
            time.sleep(delay)

    return False, last_filename, last_downloaded_bytes, last_chunk_count


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
    adapter: ServerAdapter | None = None,
):
    """Download an image with streaming, validation, and retries.

    When the preferred width is rejected (HTTP 400/403/413), negotiates a
    smaller working width via GET status checks and retries the download.

    Args:
        service_id: Image service ID
        image_size: Desired image width
        filename: Output filename
        session_manager: SessionManager instance for making requests
        server_capabilities: Server capabilities (optional)
        progress: Rich Progress object (optional)
        task: Progress task ID (optional)
        verbose: Whether to print verbose output
        image_info: Parsed info.json for size fallback candidates (optional)
        max_retries: Number of attempts for empty/truncated/network failures
        adapter: Host adapter; resolved from ``service_id`` when omitted

    Returns:
        tuple: (success: bool, final_filename: str, downloaded_bytes: int, chunk_count: int)
    """
    console = Console()
    adapter = adapter or resolve_adapter(service_id)

    preferred = server_capabilities.preferred_format if server_capabilities else "jpg"
    formats: list[str] = []
    for candidate in (preferred, "jpg", "jpeg"):
        if candidate and candidate not in formats:
            formats.append(candidate)

    current_size = int(image_size)
    if server_capabilities and server_capabilities.max_test_size:
        current_size = min(current_size, int(server_capabilities.max_test_size))

    timeout = (30, 60)
    last_filename = filename
    last_downloaded_bytes = 0
    last_chunk_count = 0
    size_negotiated = False

    while True:
        size_rejected = False
        all_formats_rejected = True
        last_failure: str | None = None

        for image_format in formats:
            base, _ext = os.path.splitext(last_filename)
            last_filename = f"{base}.{image_format}"
            image_url = _iiif_image_url(service_id, current_size, image_format)

            if verbose:
                _progress_print(
                    progress, console, f"[dim]Connecting to: {image_url}[/dim]"
                )

            head_content_length = get_content_length_from_head(
                image_url, session_manager, adapter=adapter
            )

            for attempt in range(1, max_retries + 1):
                if progress and task is not None:
                    progress.update(task, completed=0, total=None)

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
                    head_content_length=head_content_length,
                    image_size=current_size,
                    service_id=service_id,
                    console=console,
                )
                last_failure = failure_reason

                if success:
                    return (
                        True,
                        last_filename,
                        last_downloaded_bytes,
                        last_chunk_count,
                    )

                if failure_reason == "size_rejected" or _is_gateway_timeout_failure(
                    failure_reason
                ):
                    size_rejected = True
                    all_formats_rejected = False
                    break

                if failure_reason == "format_rejected":
                    break  # try next format

                all_formats_rejected = False

                if not retryable:
                    return (
                        False,
                        last_filename,
                        last_downloaded_bytes,
                        last_chunk_count,
                    )

                if attempt < max_retries:
                    delay = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
                    reason = failure_reason or "download failed"
                    _progress_print(
                        progress,
                        console,
                        f"[yellow]Incomplete download ({reason}). "
                        f"Retrying in {delay:.0f}s "
                        f"({attempt}/{max_retries})...[/yellow]",
                    )
                    time.sleep(delay)
            else:
                # retries exhausted for this format
                all_formats_rejected = False
                continue

            if size_rejected:
                break

        # 400 on every extension often means the size is invalid for this host
        if all_formats_rejected and last_failure == "format_rejected":
            size_rejected = True

        if size_rejected and not size_negotiated:
            negotiated = find_max_requestable_width(
                service_id,
                current_size,
                formats[0],
                session_manager,
                image_info=image_info,
            )
            # If preferred format failed status checks, try alternate formats
            if negotiated is None:
                for alt_format in formats[1:]:
                    negotiated = find_max_requestable_width(
                        service_id,
                        current_size,
                        alt_format,
                        session_manager,
                        image_info=image_info,
                    )
                    if negotiated is not None:
                        formats = [alt_format] + [f for f in formats if f != alt_format]
                        break

            if negotiated is None:
                _progress_print(
                    progress,
                    console,
                    f"[red]Error:[/red] Server rejected size {current_size}px "
                    "and no smaller width succeeded.",
                )
                return (
                    False,
                    last_filename,
                    last_downloaded_bytes,
                    last_chunk_count,
                )

            _progress_print(
                progress,
                console,
                f"[yellow]Size {current_size}px rejected; "
                f"retrying at {negotiated}px[/yellow]",
            )
            current_size = negotiated
            size_negotiated = True
            _remember_working_width(server_capabilities, current_size, image_info)
            continue

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
    head_content_length: int | None,
    image_size,
    service_id: str,
    console: Console,
    allow_iiif_format_fallback: bool = True,
) -> tuple[bool, str, int, int, bool, str | None]:
    """Perform a single streaming download attempt.

    Returns:
        tuple: (success, filename, downloaded_bytes, chunk_count, retryable, failure_reason)

        ``failure_reason`` may be ``size_rejected`` or ``format_rejected`` so the
        caller can negotiate a different IIIF size or file extension.
    """
    _ = (allow_iiif_format_fallback, image_size, service_id, server_capabilities)
    expected_bytes: int | None = None

    try:
        response = session_manager.get(image_url, stream=True, timeout=timeout)

        status = response.status_code

        # Digirati-style plain-text size errors use HTTP 403 — detect before auth
        if is_size_limit_rejection(response):
            response.close()
            return False, filename, 0, 0, False, "size_rejected"

        # Check for authentication/bot protection before processing
        if is_authentication_required(response):
            error_msg = get_auth_error_message(
                image_url, session_manager.cookie_file, response
            )
            _progress_print(progress, console, error_msg)
            return False, filename, 0, 0, False, "authentication required"

        if status in _SIZE_REJECTION_STATUSES:
            response.close()
            return False, filename, 0, 0, False, "size_rejected"

        if status in _FORMAT_REJECTION_STATUSES:
            response.close()
            return False, filename, 0, 0, False, "format_rejected"

        response.raise_for_status()
        # Check if response is actually an image
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type:
            if is_recaptcha_page(response):
                error_msg = get_auth_error_message(
                    image_url, session_manager.cookie_file, response
                )
                _progress_print(progress, console, error_msg)
            else:
                _progress_print(
                    progress,
                    console,
                    f"[red]Error:[/red] Server returned HTML instead of image. "
                    f"Content-Type: {content_type}",
                )
            return False, filename, 0, 0, False, "html response"

        if verbose:
            _progress_print(
                progress,
                console,
                f"[dim]Response status: {response.status_code}, "
                f"Content-Type: {response.headers.get('content-type', 'N/A')}, "
                f"Content-Length: {response.headers.get('content-length', 'N/A')}[/dim]",
            )

        # Only trust Content-Length for progress totals and completeness checks
        content_length_from_response = response.headers.get("content-length")
        if content_length_from_response:
            expected_bytes = int(content_length_from_response)
        elif head_content_length is not None:
            expected_bytes = head_content_length

        base_description = "Downloading"
        if progress and task is not None:
            try:
                base_description = progress.tasks[task].description or base_description
            except (KeyError, AttributeError, IndexError):
                pass
            base_description = (
                base_description.split(" (")[0]
                if " (" in base_description
                else base_description
            )
            if expected_bytes is not None:
                progress.update(task, total=expected_bytes, completed=0)
                if verbose:
                    _progress_print(
                        progress,
                        console,
                        f"[dim]Expected size: {expected_bytes:,} bytes[/dim]",
                    )
            else:
                progress.update(task, total=None, completed=0)

        downloaded_bytes = 0
        chunk_count = 0

        try:
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        chunk_count += 1

                        if progress and task is not None:
                            try:
                                if expected_bytes is not None:
                                    progress.update(task, completed=downloaded_bytes)
                                elif chunk_count % 10 == 0:
                                    size_str = _format_byte_size(downloaded_bytes)
                                    progress.update(
                                        task,
                                        description=f"{base_description} ({size_str})",
                                    )
                            except Exception:
                                pass

                        f.flush()

            if verbose:
                _progress_print(
                    progress,
                    console,
                    f"[dim]Stream ended after {chunk_count} chunks[/dim]",
                )

            file_size = (
                os.path.getsize(filename)
                if os.path.exists(filename)
                else downloaded_bytes
            )
            if verbose:
                _progress_print(
                    progress,
                    console,
                    f"[dim]Download complete: {file_size} bytes written "
                    f"({chunk_count} chunks)[/dim]",
                )

            complete, reason = is_download_complete(file_size, expected_bytes)
            if not complete:
                remove_incomplete_file(filename)
                return False, filename, file_size, chunk_count, True, reason

            return True, filename, downloaded_bytes, chunk_count, False, None

        finally:
            response.close()
            if verbose:
                _progress_print(progress, console, "[dim]Connection closed[/dim]")

    except requests.RequestException as e:
        remove_incomplete_file(filename)
        if verbose:
            _progress_print(
                progress, console, f"[red]Error downloading image:[/red] {e}"
            )
        return False, filename, 0, 0, True, str(e)
    except OSError as e:
        remove_incomplete_file(filename)
        if verbose:
            _progress_print(progress, console, f"[red]Error writing image:[/red] {e}")
        return False, filename, 0, 0, True, str(e)
