"""Bodleian Libraries IIIF host adapter.

Observed quirks on ``*.bodleian.ox.ac.uk``:

- HEAD requests for some widths hang or time out (including off-by-one sizes
  below a working probe). Capability probing is skipped; size comes from
  declared ``maxWidth`` / ``maxHeight`` / ``maxArea`` in info.json.
- Content-Length HEAD before GET is often useless or hang-prone; skip it.
"""

from __future__ import annotations

from dataclasses import dataclass

from iiif_downloader.servers.base import ServerAdapter


@dataclass(frozen=True)
class BodleianAdapter(ServerAdapter):
    """Policy overrides for Bodleian Digital / Oxford IIIF image hosts."""

    name: str = "bodleian"
    host_suffixes: tuple[str, ...] = ("bodleian.ox.ac.uk",)
    probe_head_timeout: tuple[float, float] = (2.0, 3.0)
    head_content_length_timeout: tuple[float, float] = (2.0, 3.0)
    skip_content_length_head: bool = True
    skip_capability_probe: bool = True
    default_format: str = "jpg"
    # Exact maxWidth/maxHeight math can land on sizes that hang (504); stay 1px under.
    size_limit_slack: int = 1

    def should_trust_declared_limits(self, has_declared_limits: bool) -> bool:
        """Trust Bodleian declared size caps whenever they are present.

        Args:
            has_declared_limits: True if info.json declared maxWidth/maxHeight/maxArea.

        Returns:
            bool: Always True when limits are declared.
        """
        return has_declared_limits

    def fallback_probe_sizes(self, hi: int) -> list[int]:
        """Prefer round widths; avoid dense probes near hang-prone sizes.

        Unused when ``skip_capability_probe`` is True; kept for API parity.

        Args:
            hi: Inclusive upper width to probe.

        Returns:
            list[int]: Candidate widths in preference order.
        """
        candidates: list[int] = []
        for size in (hi, min(hi, 2000), min(hi, 1000), 500, 256):
            if 1 <= size <= hi and size not in candidates:
                candidates.append(size)
        return candidates


BODLEIAN_ADAPTER = BodleianAdapter()
