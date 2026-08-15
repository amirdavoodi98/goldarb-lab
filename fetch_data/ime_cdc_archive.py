#!/usr/bin/env python3
"""
ime_cdc_archive.py — independent long-term archive for IME CDC daily
history (GoldBar, GoldCoin, SilverBar), addressing the exact gap flagged
in Report 2 §8:

  "در بازه Q3 سال ۲۰۲۵، تاریخچه موردنیاز GoldBar و GoldCoin از API فعلی
  در دسترس نبود. محدودیت ۱۸۰ روزه endpoint برای بک‌تست چندساله کافی
  نیست و باید آرشیو بلندمدت مستقل ایجاد شود."

The platform's ime_cdc_stats() endpoint is a ROLLING 180-day window —
no matter when you call it, you only ever see the last 180 days. It has
no date_from/date_to, so there is no way to page further back in a
single call (confirmed in market.py: "Platform clamps days to 1…180").

The only way to build real multi-year coverage is this script's
approach: run it daily (or as often as practical), and each run's
180-day window will overlap with the previous run's — append only the
NEW trade_dates, and the archive keeps growing past 180 days over time,
even though any single API call never could.

Same limitation as daily_archive.py / minute_bar_archive.py: this only
builds history GOING FORWARD from whenever you start running it. It
cannot retroactively recover Q3 2025 — that data is permanently gone
unless the platform team builds the "independent long-term archive"
the report calls for on their side (see roadmap.md Chunk 7). This
script is the client-side half of that same idea: start capturing now,
so the same gap never recurs for a future date range.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import get_gold_bar_history, get_gold_coin_history

CONTRACTS = ("GoldBar", "GoldCoin")  # SilverBar already covered separately if you have that file
MAX_DAYS = 180  # platform's hard cap per request — see market.py

ARCHIVE_DIR = Path("archive") / "ime_cdc_daily"


def _archive_path(contract: str) -> Path:
    return ARCHIVE_DIR / f"{contract}.jsonl"


def _load_existing_trade_dates(path: Path) -> set[str]:
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
                td = rec.get("trade_date")
                if td:
                    seen.add(td)
            except json.JSONDecodeError:
                continue
    return seen


def capture_contract(client, contract: str) -> int:
    path = _archive_path(contract)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_trade_dates(path)

    if contract == "GoldBar":
        payload = get_gold_bar_history(client, days=MAX_DAYS)
    elif contract == "GoldCoin":
        payload = get_gold_coin_history(client, days=MAX_DAYS)
    else:
        raise ValueError(f"Unsupported contract: {contract}")

    contract_code = payload.get("contract_code", contract) if isinstance(payload, dict) else contract
    rows = payload.get("stats") or [] if isinstance(payload, dict) else []

    captured_at = datetime.now(timezone.utc).isoformat()
    new_count = 0
    with open(path, "a", encoding="utf-8") as f:
        for row in rows:
            trade_date = row.get("trade_date")
            if trade_date is None or trade_date in existing:
                continue
            record = {
                "captured_at": captured_at,
                "contract_code": contract_code,
                **row,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            existing.add(trade_date)
            new_count += 1

    return new_count


def main() -> None:
    client = get_client()
    try:
        for contract in CONTRACTS:
            try:
                new_count = capture_contract(client, contract)
                print(f"{contract}: +{new_count} new daily rows")
            except Exception as exc:
                print(f"[warn] {contract} failed: {exc}")
    finally:
        close_client()


if __name__ == "__main__":
    main()