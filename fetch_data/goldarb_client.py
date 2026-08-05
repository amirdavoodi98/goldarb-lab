"""Compatibility shim for package-relative imports in `fetch_data`."""

from __future__ import annotations

from goldarb_client import close_client, get_client

__all__ = ["get_client", "close_client"]

