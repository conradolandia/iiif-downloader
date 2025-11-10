"""Core image downloading logic with streaming and progress tracking."""

import json
import os

import requests
from rich.console import Console

from .constants import JSON_CONTENT_TYPES


def fetch_image_info(image_service_url, headers, verbose=False):
    """Fetch and parse image info from IIIF image service.

    Args:
        image_service_url: URL of the image service
        headers: HTTP headers to use
        verbose: Whether to print verbose output

    Returns:
        dict: Parsed image info JSON, or None if error
    """
    console = Console()
    image_info_url = image_service_url + "/info.json"

    if verbose:
        console.print(f"[dim]Fetching image info: {image_info_url}[/dim]")

    try:
        response = requests.get(image_info_url, headers=headers, timeout=30)
        response.raise_for_status()

        # Check if the content type is JSON (including JSON-LD and other JSON variants)
        content_type = response.headers.get("Content-Type", "")
        if not any(
            json_type in content_type.lower() for json_type in JSON_CONTENT_TYPES
        ):
            if verbose:
                console.print(
                    f"[yellow]Warning:[/yellow] Image info response not JSON. Content-Type: {content_type}"
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
    headers,
    server_capabilities=None,
    progress=None,
    task=None,
    verbose=False,
):
    """Download an image with streaming and progress tracking.

    Args:
        service_id: Image service ID
        image_size: Desired image width
        filename: Output filename
        headers: HTTP headers to use
        server_capabilities: Server capabilities (optional)
        progress: Rich Progress object (optional)
        task: Progress task ID (optional)
        verbose: Whether to print verbose output

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

    try:
        response = requests.get(
            image_url, headers=headers, stream=True, timeout=timeout
        )

        # If format fails and we haven't probed, try fallback
        if not server_capabilities and response.status_code in (400, 404, 415):
            image_format = "jpg"
            image_url = f"{service_id}/full/{image_size},/0/default.{image_format}"
            # Update filename to match format
            base, ext = os.path.splitext(filename)
            filename = f"{base}.{image_format}"
            if verbose:
                console.print(f"[dim]Format fallback, retrying with: {image_url}[/dim]")
            response = requests.get(
                image_url, headers=headers, stream=True, timeout=timeout
            )

        response.raise_for_status()

        if verbose:
            console.print(
                f"[dim]Response status: {response.status_code}, "
                f"Content-Type: {response.headers.get('content-type', 'N/A')}, "
                f"Content-Length: {response.headers.get('content-length', 'N/A')}[/dim]"
            )

        # Get content length if available
        content_length = response.headers.get("content-length")
        if content_length:
            content_length = int(content_length)
            if progress and task is not None:
                progress.update(task, total=content_length)
            if verbose:
                console.print(f"[dim]Expected size: {content_length} bytes[/dim]")
        else:
            content_length = None

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

        try:
            with open(filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        chunk_count += 1

                        # Update progress (safely handle any progress update errors)
                        try:
                            if content_length and progress and task is not None:
                                progress.update(task, completed=downloaded_bytes)
                            elif progress and task is not None:
                                # Update progress even without content-length
                                # Show bytes in readable format in the description (update every 10 chunks)
                                if chunk_count % 10 == 0:
                                    if downloaded_bytes > 1024 * 1024:
                                        size_str = (
                                            f"{downloaded_bytes / 1024 / 1024:.1f} MB"
                                        )
                                    elif downloaded_bytes > 1024:
                                        size_str = f"{downloaded_bytes / 1024:.1f} KB"
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
                                            f"[dim]Downloaded: {downloaded_bytes} bytes "
                                            f"({chunk_count} chunks)[/dim]"
                                        )
                                else:
                                    # Update completed bytes without changing description
                                    progress.update(task, completed=downloaded_bytes)
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

            if verbose:
                file_size = os.path.getsize(filename)
                console.print(
                    f"[dim]Download complete: {file_size} bytes written "
                    f"({chunk_count} chunks)[/dim]"
                )
                if content_length and file_size != content_length:
                    console.print(
                        f"[yellow]Warning: File size ({file_size}) doesn't match "
                        f"Content-Length ({content_length})[/yellow]"
                    )

            return True, filename, downloaded_bytes, chunk_count

        finally:
            # Explicitly close the connection
            response.close()
            if verbose:
                console.print("[dim]Connection closed[/dim]")

    except requests.RequestException as e:
        if verbose:
            console.print(f"[red]Error downloading image:[/red] {e}")
        return False, filename, 0, 0
