"""Platformaga mos OS adapterini tanlash."""

from __future__ import annotations

import sys

from .base import AutostartStatus, NullAdapter, OSAdapter

__all__ = ["OSAdapter", "NullAdapter", "AutostartStatus", "get_adapter"]


def get_adapter() -> OSAdapter:
    if sys.platform == "win32":
        from .windows import WindowsAdapter, enable_dpi_awareness, prepare_comtypes

        enable_dpi_awareness()
        prepare_comtypes()
        return WindowsAdapter()
    if sys.platform == "darwin":
        from .macos import MacAdapter

        return MacAdapter()
    return NullAdapter()
