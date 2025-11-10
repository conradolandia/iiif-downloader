"""HTTP session management with cookie support."""

import http.cookiejar
import os
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from iiif_downloader.download_helpers import get_default_headers


class SessionManager:
    """Manages HTTP sessions with cookie persistence and retry logic."""

    def __init__(self, cookie_file: str | None = None):
        """Initialize the session manager.

        Args:
            cookie_file: Optional path to a cookie file for persistence
        """
        self.cookie_file = cookie_file
        self.session = requests.Session()

        # Set default headers
        self.session.headers.update(get_default_headers())

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        # Load cookies if file exists
        if cookie_file and os.path.exists(cookie_file):
            self._load_cookies()

    def _load_cookies(self) -> None:
        """Load cookies from file."""
        if not self.cookie_file:
            return

        try:
            # Use MozillaCookieJar for compatibility
            jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
            jar.load(ignore_discard=True, ignore_expires=False)
            self.session.cookies.update(jar)
        except Exception:
            # If loading fails, continue without cookies
            pass

    def _save_cookies(self) -> None:
        """Save cookies to file."""
        if not self.cookie_file:
            return

        try:
            # Ensure directory exists
            cookie_path = Path(self.cookie_file)
            cookie_path.parent.mkdir(parents=True, exist_ok=True)

            # Save cookies using MozillaCookieJar format
            jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
            for cookie in self.session.cookies:
                jar.set_cookie(cookie)
            jar.save(ignore_discard=True, ignore_expires=False)
        except Exception:
            # If saving fails, continue without saving
            pass

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Make a GET request using the session.

        Args:
            url: URL to request
            **kwargs: Additional arguments to pass to requests.get

        Returns:
            requests.Response: Response object
        """
        response = self.session.get(url, **kwargs)
        # Save cookies after each request
        if self.cookie_file:
            self._save_cookies()
        return response

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        """Make a HEAD request using the session.

        Args:
            url: URL to request
            **kwargs: Additional arguments to pass to requests.head

        Returns:
            requests.Response: Response object
        """
        response = self.session.head(url, **kwargs)
        # Save cookies after each request
        if self.cookie_file:
            self._save_cookies()
        return response

    def close(self) -> None:
        """Close the session and save cookies."""
        if self.cookie_file:
            self._save_cookies()
        self.session.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
