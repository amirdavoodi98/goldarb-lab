"""Normalize source clocks without borrowing acquisition or polling clocks."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

_TEHRAN = ZoneInfo("Asia/Tehran")


def parse_source_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def price_source_time(payload: Mapping[str, Any]) -> tuple[datetime | None, str]:
    """Return source time and verification status for the same price observation.

    An explicit source_timestamp, including null, is authoritative. Legacy
    date/clock pairs are candidates only: some servers infer d_even's date.
    Never infer a missing date from fetched_at, last_update, as_of or now.
    """
    if "source_timestamp" in payload:
        stamp = parse_source_timestamp(payload["source_timestamp"])
        status = str(payload.get("source_time_status") or (
            "unverified" if stamp is not None else "missing"
        ))
        return stamp, status
    day = str(payload.get("d_even") or "").strip()
    clock = str(payload.get("h_even") or "").strip()
    if ":" in clock:
        parts = clock.split(":")
        if len(parts) != 3 or any(len(part) != 2 for part in parts):
            return None, "missing"
        clock = "".join(parts)
    if len(day) != 8 or not day.isascii() or not day.isdigit():
        return None, "missing"
    if clock == "0" or not 1 <= len(clock) <= 6 or not clock.isascii() or not clock.isdigit():
        return None, "missing"
    clock = clock.zfill(6)
    try:
        stamp = datetime(
            int(day[:4]), int(day[4:6]), int(day[6:]),
            int(clock[:2]), int(clock[2:4]), int(clock[4:]), tzinfo=_TEHRAN,
        )
    except ValueError:
        return None, "missing"
    return stamp, "unverified"


def with_price_source_time(row: dict[str, Any]) -> dict[str, Any]:
    stamp, status = price_source_time(row)
    result = dict(row)
    # Preserve the server's original ISO spelling (e.g. Z) when valid.
    result["source_timestamp"] = (
        row["source_timestamp"] if stamp is not None and "source_timestamp" in row
        else stamp.isoformat() if stamp is not None else None
    )
    result["source_time_status"] = status
    return result


def with_bulk_price_source_time(payload: Any) -> Any:
    """Preserve list/envelope/symbol-map shapes and their non-price metadata."""
    if isinstance(payload, list):
        return [with_price_source_time(row) if isinstance(row, dict) else row for row in payload]
    if not isinstance(payload, dict):
        return payload
    result = dict(payload)
    for key in ("funds", "results", "data", "items"):
        if isinstance(payload.get(key), (list, dict)):
            result[key] = with_bulk_price_source_time(payload[key])
            return result
    for key, row in payload.items():
        if isinstance(row, dict) and key not in {"session", "raw"}:
            result[key] = with_price_source_time(row)
    return result
