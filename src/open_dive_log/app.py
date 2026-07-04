"""Backwards-compatible shim.

Historically `open_dive_log.app` was the entry point. The real
implementation now lives in `open_dive_log.ui.main_window.MainWindow`.
Re-export here so older imports keep working, but prefer importing
from `open_dive_log.ui` directly.
"""

from open_dive_log.ui.main_window import MainWindow  # noqa: F401

__all__ = ["MainWindow"]
