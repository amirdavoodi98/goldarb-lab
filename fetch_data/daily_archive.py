#!/usr/bin/env python3
"""
daily_archive.py — Chunk 1 of the roadmap: point-in-time capture.

Appends (never overwrites) daily snapshots of fund holdings and issued
units for all 5 target funds, each stamped with the actual capture time.
This is the only way to build the point-in-time history that
fund.holdings()/issued_units() can't give you retroactively — every day
this doesn't run is a day of history permanently lost.

Run this once per day (cron, systemd timer, or a scheduled task in
your platform of choice). Safe to run more than once per day — it just
appends more capture points, which is harmless (and arguably useful for
intraday drift checks on issued_units, since that field updates more
than once daily on the platform side per its own docstring).

Output: append-only JSONL files under archive/, one per data type.
Never delete/rewrite these files — that defeats the whole point.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import get_fund_holdings, get_fund_issued_units

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")
ARCHIVE_DIR = Path("archive")

HOLDINGS_LOG = ARCHIVE_DIR / "holdings_history.jsonl"
UNITS_LOG = ARCHIVE_DIR / "issued_units_history.jsonl"


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def capture_once() -> None:
    captured_at = datetime.now(timezone.utc).isoformat()
    client = get_client()

    try:
        for symbol in FUND_SYMBOLS:
            try:
                holdings = get_fund_holdings(client, symbol)
                _append_jsonl(HOLDINGS_LOG, {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "payload": holdings,
                })
            except Exception as exc:
                print(f"[warn] holdings capture failed for {symbol}: {exc}")

            try:
                units = get_fund_issued_units(client, symbol)
                _append_jsonl(UNITS_LOG, {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "payload": units,
                })
            except Exception as exc:
                print(f"[warn] issued_units capture failed for {symbol}: {exc}")

        print(f"Captured {len(FUND_SYMBOLS)} funds at {captured_at}")
    finally:
        close_client()


if __name__ == "__main__":
    capture_once()