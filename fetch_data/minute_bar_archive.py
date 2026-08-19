#!/usr/bin/env python3
"""
minute_bar_archive.py — Chunk 2 of the roadmap: minute-level fund bar capture.

Appends new 1-minute bars for the 5 target funds to a growing local
archive, one JSONL file per fund. Safe to run repeatedly (e.g. daily
via cron) — deduplicates by bar_at before appending, so re-fetching an
overlapping window doesn't create duplicate rows.

This only builds history GOING FORWARD from whenever you start running
it. It cannot recover bars for dates before you started — same
limitation as daily_archive.py, for the same reason: the platform has
no historical replay for anything beyond what its own bars endpoint
already stores at the time you ask.

Recommended: run daily, requesting the last LOOKBACK_DAYS days each
time (covers weekends/any missed runs without re-fetching your entire
history every time).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import get_fund_candles_1m

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")
ARCHIVE_DIR = Path("archive") / "fund_bars_1m"
LOOKBACK_DAYS = 3  # re-fetch a small overlapping window each run; dedup handles the rest


def _archive_path(symbol: str) -> Path:
    return ARCHIVE_DIR / f"{symbol}.jsonl"


def _load_existing_bar_ats(path: Path) -> set[str]:
    if not path.exists():
        return set()
    seen = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                bar_at = rec.get("bar_at")
                if bar_at:
                    seen.add(bar_at)
            except json.JSONDecodeError:
                continue
    return seen


def capture_symbol(client, symbol: str) -> int:
    path = _archive_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_bar_ats(path)

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)

    bars = get_fund_candles_1m(client, symbol, start=start.isoformat(), end=end.isoformat())

    captured_at = datetime.now(timezone.utc).isoformat()
    new_count = 0
    with open(path, "a", encoding="utf-8") as f:
        for bar in bars:
            bar_at = bar.get("bar_at")
            if bar_at is None or bar_at in existing:
                continue
            record = {"captured_at": captured_at, "symbol": symbol, **bar}
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing.add(bar_at)
            new_count += 1

    return new_count


def main() -> None:
    client = get_client()
    try:
        for symbol in FUND_SYMBOLS:
            try:
                new_count = capture_symbol(client, symbol)
                print(f"{symbol}: +{new_count} new bars")
            except Exception as exc:
                print(f"[warn] {symbol} failed: {exc}")
    finally:
        close_client()


if __name__ == "__main__":
    main()