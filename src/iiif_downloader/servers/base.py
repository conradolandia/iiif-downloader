"""Default IIIF server adapter and shared probe/download policy."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from iiif_downloader.constants import (
    HEAD_CONTENT_LENGTH_TIMEOUT,
    PROBE_HEAD_TIMEOUT,
)


@dataclass(frozen=True)
class ServerAdapter:
    """Host-family policy for capability probes and downloads.

    Specific adapters override fields or methods. The default adapter is used
    when no host-specific adapter matches.
    """

    name: str = "default"
    host_suffixes: tuple[str, ...] = ()
    probe_head_timeout: tuple[float, float] = PROBE_HEAD_TIMEOUT
    head_content_length_timeout: tuple[float, float] = HEAD_CONTENT_LENGTH_TIMEOUT
    skip_content_length_head: bool = False
    # When True, skip HEAD capability probes; size is negotiated on GET fallback.
    skip_capability_probe: bool = True
    default_format: str = "jpg"
    # Subtract from limit-derived widths (Bodleian hangs on some exact max sizes).
    size_limit_slack: int = 0

    def matches_host(self, hostname: str) -> bool:
        """Return True if ``hostname`` belongs to this adapter's host family.

        Args:
            hostname: URL hostname (no scheme or path).

        Returns:
            bool: Whether this adapter should handle the host.
        """
        host = (hostname or "").lower().rstrip(".")
        if not host or not self.host_suffixes:
            return False
        for suffix in self.host_suffixes:
            suffix = suffix.lower()
            if host == suffix or host.endswith("." + suffix):
                return True
        return False

    def matches_url(self, url: str) -> bool:
        """Return True if the URL's host matches this adapter.

        Args:
            url: Absolute URL (image service, info.json, or image request).

        Returns:
            bool: Whether this adapter should handle the URL.
        """
        hostname = urlparse(url).hostname or ""
        return self.matches_host(hostname)

    def should_trust_declared_limits(self, has_declared_limits: bool) -> bool:
        """Whether to keep a declared max size when HEAD probes are inconclusive.

        Args:
            has_declared_limits: True if info.json declared maxWidth/maxHeight/maxArea.

        Returns:
            bool: Whether to trust the declared capped size.
        """
        return has_declared_limits

    def fallback_probe_sizes(self, hi: int) -> list[int]:
        """Return safe widths to try when the desired width HEAD fails.

        Args:
            hi: Inclusive upper width to probe.

        Returns:
            list[int]: Candidate widths in preference order.
        """
        candidates: list[int] = []
        for size in (hi, min(hi, 2000), min(hi, 1000), 500, 256, 128):
            if 1 <= size <= hi and size not in candidates:
                candidates.append(size)
        return candidates


DEFAULT_ADAPTER = ServerAdapter()
