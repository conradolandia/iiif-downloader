"""Detection of authentication and bot protection pages."""

from typing import Any


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


def is_authentication_required(response: Any) -> bool:
    """Check if authentication is required based on response.

    Args:
        response: requests.Response object

    Returns:
        bool: True if authentication appears to be required, False otherwise
    """
    # Check status code
    if response.status_code in (401, 403):
        return True

    # Check for authentication headers
    if "www-authenticate" in response.headers:
        return True

    # Check if it's a Cloudflare or reCAPTCHA challenge
    if is_cloudflare_challenge(response) or is_recaptcha_page(response):
        return True

    # Check for common authentication page indicators
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
