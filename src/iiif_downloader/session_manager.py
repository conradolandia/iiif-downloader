"""HTTP session management with cookie support."""

import http.cookiejar
import os
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from iiif_downloader.download_helpers import get_default_headers


class SessionManager:
    """Manages HTTP sessions with cookie loading and retry logic.

    Cookie files passed via ``--cookies`` are treated as read-only so a failed
    request cannot overwrite a browser-exported jar.
    """

    def __init__(self, cookie_file: str | None = None):
        """Initialize the session manager.

        Args:
            cookie_file: Optional path to a Netscape/Mozilla cookie file to load

        Raises:
            FileNotFoundError: If cookie_file is set but does not exist
            OSError: If the cookie file cannot be read
            http.cookiejar.LoadError: If the cookie file format is invalid
        """
        self.cookie_file = cookie_file
        self.session = requests.Session()
        self.cookies_loaded = 0

        # Set default headers
        self.session.headers.update(get_default_headers())

        # Retry GETs on transient server errors. Do not retry HEAD: capability
        # probes and Content-Length checks must fail fast on timeouts.
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        if cookie_file:
            if not os.path.exists(cookie_file):
                raise FileNotFoundError(f"Cookie file not found: {cookie_file}")
            self._load_cookies()

    def _load_cookies(self) -> None:
        """Load cookies from a Netscape/Mozilla cookie file into the session.

        The file is never modified. Load errors are raised so callers see why
        credentials were not applied.
        """
        if not self.cookie_file:
            return

        jar = http.cookiejar.MozillaCookieJar(self.cookie_file)
        # Keep expired cookies: Cloudflare clearance can look expired to cookielib
        # depending on clock skew / export format, and ignore_expires still
        # loads them for sending.
        jar.load(ignore_discard=True, ignore_expires=True)
        self.session.cookies.update(jar)
        self.cookies_loaded = len(jar)

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Make a GET request using the session.

        Args:
            url: URL to request
            **kwargs: Additional arguments to pass to requests.get

        Returns:
            requests.Response: Response object
        """
        return self.session.get(url, **kwargs)

    def head(self, url: str, **kwargs: Any) -> requests.Response:
        """Make a HEAD request using the session.

        Args:
            url: URL to request
            **kwargs: Additional arguments to pass to requests.head

        Returns:
            requests.Response: Response object
        """
        return self.session.head(url, **kwargs)

    def close(self) -> None:
        """Close the session without writing the cookie file."""
        self.session.close()

    def __enter__(self) -> "SessionManager":
        """Context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit."""
        self.close()
