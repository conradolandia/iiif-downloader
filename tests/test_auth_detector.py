"""Tests for auth vs IIIF size-limit response classification."""

from __future__ import annotations

from unittest.mock import MagicMock

from iiif_downloader.auth_detector import (
    is_authentication_required,
    is_size_limit_rejection,
)


def _response(
    status: int,
    content_type: str,
    body: str,
    headers: dict[str, str] | None = None,
) -> MagicMock:
    """Build a minimal response mock."""
    response = MagicMock()
    response.status_code = status
    merged = {"Content-Type": content_type}
    if headers:
        merged.update(headers)
    response.headers = merged
    response.text = body
    return response


def test_digirati_size_error_is_not_auth() -> None:
    """Plain-text Digirati maxWidth 403 must not trigger bot-protection help."""
    response = _response(
        403,
        "text/plain; charset=utf-8",
        "Requested size '4781,' exceeds maxWidth of 5000",
    )
    assert is_size_limit_rejection(response) is True
    assert is_authentication_required(response) is False


def test_bare_403_without_body_markers_is_not_auth() -> None:
    """A non-HTML 403 with no auth signals is not treated as login required."""
    response = _response(403, "text/plain", "forbidden")
    assert is_size_limit_rejection(response) is False
    assert is_authentication_required(response) is False


def test_401_is_auth() -> None:
    """HTTP 401 remains an authentication signal."""
    response = _response(401, "text/plain", "unauthorized")
    assert is_authentication_required(response) is True


def test_html_403_login_page_is_auth() -> None:
    """HTML 403 with login wording is treated as authentication."""
    response = _response(
        403,
        "text/html",
        "<html><body>Please sign in to continue</body></html>",
    )
    assert is_size_limit_rejection(response) is False
    assert is_authentication_required(response) is True
