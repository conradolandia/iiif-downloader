"""Detection of authentication and bot protection pages."""

from typing import Any

# Plain-text / JSON IIIF errors that are size limits, not bot walls.
_SIZE_LIMIT_BODY_MARKERS = (
    "maxwidth",
    "maxheight",
    "maxarea",
    "requested size",
    "exceeds max",
    "size exceeds",
    "invalid size",
)


def is_html_response(response: Any) -> bool:
    """Check if a response is HTML (not JSON or image).

    Args:
        response: requests.Response object

    Returns:
        bool: True if response is HTML, False otherwise
    """
    content_type = response.headers.get("Content-Type", "").lower()
    return "text/html" in content_type or (
        "html" in content_type and "json" not in content_type
    )


def is_cloudflare_challenge(response: Any) -> bool:
    """Check if a response is a Cloudflare bot challenge.

    Args:
        response: requests.Response object

    Returns:
        bool: True if a Cloudflare challenge is detected, False otherwise
    """
    headers = response.headers
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True

    server = headers.get("server", "").lower()
    if "cloudflare" in server and response.status_code in (403, 503):
        if is_html_response(response):
            text = response.text.lower()
            cloudflare_indicators = [
                "just a moment...",
                "cf-browser-verification",
                "cf-challenge",
                "challenge-platform",
                "cdn-cgi/challenge",
                "attention required",
            ]
            return any(indicator in text for indicator in cloudflare_indicators)

    return False


def is_recaptcha_page(response: Any) -> bool:
    """Check if a response contains a reCAPTCHA challenge.

    Args:
        response: requests.Response object

    Returns:
        bool: True if reCAPTCHA is detected, False otherwise
    """
    if not is_html_response(response):
        return False

    # Check response text for reCAPTCHA indicators
    text = response.text.lower()
    recaptcha_indicators = [
        "recaptcha",
        "g-recaptcha",
        "verifycallback",
        "grecaptcha.render",
        "sitekey",
        "captcha",
    ]

    return any(indicator in text for indicator in recaptcha_indicators)


def is_size_limit_rejection(response: Any) -> bool:
    """Return True if the response is an IIIF max size rejection.

    Some hosts (e.g. Digirati DLCS) return HTTP 403 with a plain-text body such
    as ``Requested size '4781,' exceeds maxWidth of 5000``. That must not be
    treated as bot protection.

    Args:
        response: requests.Response object

    Returns:
        bool: True when the body indicates a size / maxWidth limit error
    """
    if response.status_code not in (400, 403, 413):
        return False

    content_type = response.headers.get("Content-Type", "").lower()
    if is_html_response(response):
        return False
    # Images are never size-error messages
    if content_type.startswith("image/"):
        return False

    try:
        text = (response.text or "").lower()
    except Exception:
        return False

    return any(marker in text for marker in _SIZE_LIMIT_BODY_MARKERS)


def is_authentication_required(response: Any) -> bool:
    """Check if authentication or a bot challenge is required.

    HTTP 403 alone is not treated as auth: IIIF servers often use 403 for
    size-limit errors. Prefer Cloudflare/reCAPTCHA/HTML login signals.

    Args:
        response: requests.Response object

    Returns:
        bool: True if authentication appears to be required, False otherwise
    """
    if is_size_limit_rejection(response):
        return False

    # Check status code — 401 is authoritative; bare 403 is not
    if response.status_code == 401:
        return True

    # Check for authentication headers
    if "www-authenticate" in response.headers:
        return True

    # Check if it's a Cloudflare or reCAPTCHA challenge
    if is_cloudflare_challenge(response) or is_recaptcha_page(response):
        return True

    # HTML 403 with login wording
    if response.status_code == 403 and is_html_response(response):
        text = response.text.lower()
        auth_indicators = [
            "login",
            "sign in",
            "authentication required",
            "access denied",
            "unauthorized",
            "forbidden",
        ]
        return any(indicator in text for indicator in auth_indicators)

    # Other HTML pages that look like login walls
    if is_html_response(response):
        text = response.text.lower()
        auth_indicators = [
            "login",
            "sign in",
            "authentication required",
            "access denied",
            "unauthorized",
        ]
        return any(indicator in text for indicator in auth_indicators)

    return False


def get_auth_error_message(
    url: str, cookie_file: str | None = None, response: Any | None = None
) -> str:
    """Generate a helpful error message for authentication issues.

    Args:
        url: The URL that failed
        cookie_file: Optional cookie file path
        response: Optional response object for more details

    Returns:
        str: Error message with instructions
    """
    message = "\n[bold red]Authentication or Bot Protection Detected[/bold red]\n"
    message += "=" * 70 + "\n\n"
    message += (
        "The server is blocking automated requests "
        "(bot protection / Cloudflare / reCAPTCHA).\n\n"
    )

    if response is not None:
        if is_cloudflare_challenge(response):
            message += "[yellow]Detected: Cloudflare challenge[/yellow]\n\n"
        elif is_recaptcha_page(response):
            message += "[yellow]Detected: reCAPTCHA challenge[/yellow]\n\n"

    message += "[bold]Solution:[/bold]\n"
    message += "1. Open this URL in your browser:\n"
    message += f"   {url}\n\n"
    message += "2. Complete any Cloudflare, reCAPTCHA, or login challenge\n"
    message += "3. Either:\n"
    message += "   a) Save the manifest JSON from the browser and pass the local file\n"
    message += "      as --source, or\n"
    message += "   b) Export cookies from your browser:\n"
    message += "      - Chrome/Edge: Use extension 'Get cookies.txt LOCALLY'\n"
    message += "      - Firefox: Use extension 'cookies.txt' or 'Cookie-Editor'\n\n"

    if cookie_file:
        message += f"4. Save cookies to: {cookie_file}\n"
        message += "5. Run the downloader again with --cookies option\n\n"
    else:
        message += "4. Save cookies to a file (Netscape/Mozilla format)\n"
        message += "5. Run the downloader with: --cookies /path/to/cookies.txt\n\n"

    message += (
        "[dim]Note: --cookies is read-only (your export file is not overwritten). "
        "Cookies are used for both manifest fetch and image downloads.[/dim]\n"
    )
    message += "=" * 70 + "\n"

    return message
