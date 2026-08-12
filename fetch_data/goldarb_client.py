"""
goldarb_client.py — process-wide LabClient lifecycle.

CANONICAL LOCATION: fetch_data/goldarb_client.py (this file must live
inside the fetch_data/ package — most scripts import it with a relative
import: `from .goldarb_client import ...`).

Call get_client() anywhere you need to fetch data. Call close_client()
once, on app shutdown.

Auth: reads credentials from environment variables — never hardcode
them in source. Two supported modes:

  1) Token auth (preferred):
       GOLDARB_BASE_URL=https://goldarb.ir
       GOLDARB_TOKEN=xxxxx

  2) Username/password login (obtains a token via POST /api/v1/auth/token/):
       GOLDARB_BASE_URL=https://goldarb.ir
       GOLDARB_USERNAME=shahrzad
       GOLDARB_PASSWORD=xxxxx

If GOLDARB_TOKEN is set, it's used directly. Otherwise, falls back to
username/password login.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from goldarb import LabClient

try:
    from dotenv import load_dotenv

    load_dotenv()  # reads .env in the current working directory, if present
except ImportError:
    pass  # python-dotenv not installed — fall back to already-exported env vars

_client: LabClient | None = None


def _create_client() -> LabClient:
    base_url = os.environ.get("GOLDARB_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("Set GOLDARB_BASE_URL in the environment")

    token = os.environ.get("GOLDARB_TOKEN", "").strip()
    if token:
        return LabClient(base_url=base_url, token=token)

    username = os.environ.get("GOLDARB_USERNAME", "").strip()
    password = os.environ.get("GOLDARB_PASSWORD", "").strip()
    if username and password:
        return LabClient.login(base_url=base_url, username=username, password=password)

    raise RuntimeError(
        "Set GOLDARB_TOKEN, or GOLDARB_USERNAME + GOLDARB_PASSWORD, in the environment"
    )


def get_client() -> LabClient:
    """Return the shared LabClient, creating it (and logging in, if needed) on first use."""
    global _client
    if _client is None:
        _client = _create_client()
    return _client


def close_client() -> None:
    """Close the shared LabClient's connection pool (call on shutdown)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
