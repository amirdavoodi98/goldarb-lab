"""HTTP transport + date chunking helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterator
from urllib.parse import quote

import httpx

DEFAULT_TIMEOUT = 60.0


def _parse_day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def iter_date_chunks(
    start: date | datetime | str,
    end: date | datetime | str,
    *,
    max_span_days: int,
) -> Iterator[tuple[date, date]]:
    """Yield inclusive [chunk_start, chunk_end] spans of at most ``max_span_days``."""
    a = _parse_day(start)
    b = _parse_day(end)
    if a > b:
        raise ValueError("start must be ≤ end")
    if max_span_days < 0:
        raise ValueError("max_span_days must be ≥ 0")
    cursor = a
    while cursor <= b:
        chunk_end = min(cursor + timedelta(days=max_span_days), b)
        yield cursor, chunk_end
        cursor = chunk_end + timedelta(days=1)


class LabHttp:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        base = base_url.rstrip("/")
        if not base:
            raise ValueError("base_url is required")
        if not token:
            raise ValueError("token is required")
        self.base_url = base
        self._client = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LabHttp:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._client.get(path, params=params or {})
        resp.raise_for_status()
        return resp.json()

    def get_paginated_results(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        results_key: str = "results",
    ) -> list[dict[str, Any]]:
        """Follow DRF page links until exhausted (or non-paginated list)."""
        params = dict(params or {})
        out: list[dict[str, Any]] = []
        next_url: str | None = path
        first = True
        while next_url:
            if first:
                payload = self.get_json(next_url, params)
                first = False
            else:
                # Absolute URL from DRF "next"
                resp = self._client.get(next_url)
                resp.raise_for_status()
                payload = resp.json()
            if isinstance(payload, list):
                out.extend(payload)
                break
            if not isinstance(payload, dict):
                break
            chunk = payload.get(results_key)
            if isinstance(chunk, list):
                out.extend(chunk)
            elif "bars" in payload and isinstance(payload["bars"], list):
                out.extend(payload["bars"])
                break
            else:
                # Non-paginated object — return once
                break
            nxt = payload.get("next")
            next_url = nxt if isinstance(nxt, str) and nxt else None
        return out


def encode_symbol(symbol: str) -> str:
    return quote(symbol, safe="")
