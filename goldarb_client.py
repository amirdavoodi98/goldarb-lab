"""
goldarb_client.py — process-wide LabClient lifecycle for the project.

Call get_client() anywhere you need to fetch data. Call close_client() once,
on app shutdown (e.g. in a signal handler, Django AppConfig.ready()/atexit,
or your main loop's finally block).

Auth: reads credentials from environment variables — never hardcode them
in source. Two supported modes:

  1) Username/password login (obtains a token via POST /api/v1/auth/token/):
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

import httpx

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from goldarb import LabClient

try:
    from dotenv import load_dotenv

    load_dotenv()  # cwd .env, if present
    load_dotenv(dotenv_path=Path(__file__).resolve().with_name(".env"))  # repo-root .env
except ImportError:
    pass  # python-dotenv not installed — fall back to already-exported env vars

_client: LabClient | None = None


def _create_client() -> LabClient:
    base_url = os.environ.get("GOLDARB_BASE_URL", "").strip()
    if not base_url:
        raise RuntimeError("Set GOLDARB_BASE_URL in the environment")
    if "://" not in base_url:
        raise RuntimeError(
            "GOLDARB_BASE_URL must include a scheme, for example https://goldarb.ir"
        )

    token = os.environ.get("GOLDARB_TOKEN", "").strip()
    if token:
        return LabClient(base_url=base_url, token=token)

    username = os.environ.get("GOLDARB_USERNAME", "").strip()
    password = os.environ.get("GOLDARB_PASSWORD", "").strip()
    if username and password:
        try:
            return LabClient.login(base_url=base_url, username=username, password=password)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Failed to reach or authenticate against {base_url}. "
                "Check network access, DNS, and your GOLDARB_BASE_URL / credentials."
            ) from exc

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
