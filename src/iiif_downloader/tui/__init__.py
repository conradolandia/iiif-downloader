"""TUI package for IIIF downloader."""

from .app import IIIFDownloaderApp
from .downloader_tui import TUIDownloader
from .widgets import (
    ActivityLog,
    CurrentDownloadPanel,
    ProgressOverview,
    StatisticsPanel,
)

__all__ = [
    "IIIFDownloaderApp",
    "ActivityLog",
    "CurrentDownloadPanel",
    "ProgressOverview",
    "StatisticsPanel",
    "TUIDownloader",
]
