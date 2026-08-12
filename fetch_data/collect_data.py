#!/usr/bin/env python3
"""Collect available historical data and write a coverage report.

THIS IS THE SINGLE CONSOLIDATED CRON SCRIPT — supersedes running
daily_archive.py, minute_bar_archive.py, and ime_cdc_archive.py
separately. Those three files are kept for reference/manual one-off
runs, but should NOT be scheduled alongside this one — running both
would create two diverging archives of the same data.

Writes into the SAME archive/ paths those three scripts already used,
so it continues your existing archive rather than starting a new one:
  - archive/fund_bars_1m/{symbol}.jsonl
  - archive/holdings_history.jsonl
  - archive/issued_units_history.jsonl
  - archive/ime_cdc_daily/{contract}.jsonl
  - archive/coverage_report.json   (NEW — Chunk 4: expected vs actual rows)

NOTE ON SCHEMA: holdings/issued_units records written by this script
include a "status" field that daily_archive.py's earlier records don't
have. This is harmless (JSONL is line-independent, and any reader
should use .get("status") rather than assuming it's always present),
but worth knowing if you ever inspect the file and see mixed shapes.

It does two things:
1. stores what the platform currently returns
2. records simple coverage metadata so missing periods are visible

It is append-only for archive outputs and safe to rerun.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import (
        get_fund_candles_1m,
        get_fund_holdings,
        get_fund_issued_units,
        get_gold_bar_history,
        get_gold_coin_history,
        get_silver_bar_history,
    )
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import (
        get_fund_candles_1m,
        get_fund_holdings,
        get_fund_issued_units,
        get_gold_bar_history,
        get_gold_coin_history,
        get_silver_bar_history,
    )

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")
IME_CONTRACTS = ("GoldBar", "GoldCoin", "SilverBar")
IME_HISTORY_FETCHERS = {
    "GoldBar": get_gold_bar_history,
    "GoldCoin": get_gold_coin_history,
    "SilverBar": get_silver_bar_history,
}

# Point directly at the existing archive/ layout — continues the archive
# already built by daily_archive.py / minute_bar_archive.py / ime_cdc_archive.py
ARCHIVE_DIR = Path("archive")
FUND_BARS_DIR = ARCHIVE_DIR / "fund_bars_1m"
HOLDINGS_LOG = ARCHIVE_DIR / "holdings_history.jsonl"
UNITS_LOG = ARCHIVE_DIR / "issued_units_history.jsonl"
IME_DAILY_DIR = ARCHIVE_DIR / "ime_cdc_daily"
REPORT_PATH = ARCHIVE_DIR / "coverage_report.json"


@dataclass
class CoverageItem:
    name: str
    requested_from: str
    requested_to: str
    returned_rows: int
    unique_days: int
    missing_days: int
    notes: list[str]


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_existing_keys(path: Path, key_field: str) -> set[str]:
    if not path.exists():
        return set()
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = rec.get(key_field)
            if key:
                seen.add(str(key))
    return seen


def _iter_dates(start: date, end: date) -> list[str]:
    out: list[str] = []
    cur = start
    while cur <= end:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _collect_fund_bars(client, *, start: date, end: date) -> list[CoverageItem]:
    report: list[CoverageItem] = []
    for symbol in FUND_SYMBOLS:
        path = FUND_BARS_DIR / f"{symbol}.jsonl"
        existing = _load_existing_keys(path, "bar_at")
        bars = get_fund_candles_1m(client, symbol, start=start.isoformat(), end=end.isoformat())
        rows = 0
        days_seen: set[str] = set()
        captured_at = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for bar in bars:
                bar_at = bar.get("bar_at")
                if not bar_at or bar_at in existing:
                    continue
                days_seen.add(str(bar_at)[:10])
                record = {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "status": bar.get("status", "available"),
                    "is_stale": bar.get("is_stale"),
                    **bar,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing.add(str(bar_at))
                rows += 1

        all_days = _iter_dates(start, end)
        existing_days = {str(bar_at)[:10] for bar_at in existing}
        covered_days = days_seen | existing_days
        missing_days = [d for d in all_days if d not in covered_days]
        report.append(
            CoverageItem(
                name=f"fund_bars_1m:{symbol}",
                requested_from=start.isoformat(),
                requested_to=end.isoformat(),
                returned_rows=rows,
                unique_days=len(covered_days & set(all_days)),
                missing_days=len(missing_days),
                notes=[f"missing_days={missing_days[:20]}"] if missing_days else [],
            )
        )
    return report


def _collect_fund_snapshots(client) -> list[CoverageItem]:
    captured_at = datetime.now(timezone.utc).isoformat()
    report: list[CoverageItem] = []
    for symbol in FUND_SYMBOLS:
        try:
            holdings = get_fund_holdings(client, symbol)
            _append_jsonl(
                HOLDINGS_LOG,
                {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "status": "snapshot",
                    "payload": holdings,
                },
            )
            report.append(
                CoverageItem(
                    name=f"holdings:{symbol}",
                    requested_from=captured_at,
                    requested_to=captured_at,
                    returned_rows=1,
                    unique_days=1,
                    missing_days=0,
                    notes=[],
                )
            )
        except Exception as exc:
            report.append(
                CoverageItem(
                    name=f"holdings:{symbol}",
                    requested_from=captured_at,
                    requested_to=captured_at,
                    returned_rows=0,
                    unique_days=0,
                    missing_days=1,
                    notes=[str(exc)],
                )
            )

        try:
            units = get_fund_issued_units(client, symbol)
            _append_jsonl(
                UNITS_LOG,
                {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "status": "snapshot",
                    "payload": units,
                },
            )
            report.append(
                CoverageItem(
                    name=f"issued_units:{symbol}",
                    requested_from=captured_at,
                    requested_to=captured_at,
                    returned_rows=1,
                    unique_days=1,
                    missing_days=0,
                    notes=[],
                )
            )
        except Exception as exc:
            report.append(
                CoverageItem(
                    name=f"issued_units:{symbol}",
                    requested_from=captured_at,
                    requested_to=captured_at,
                    returned_rows=0,
                    unique_days=0,
                    missing_days=1,
                    notes=[str(exc)],
                )
            )
    return report


def _collect_ime_daily(client, *, days: int) -> list[CoverageItem]:
    report: list[CoverageItem] = []
    end = date.today()
    start = end - timedelta(days=days)
    for contract in IME_CONTRACTS:
        path = IME_DAILY_DIR / f"{contract}.jsonl"
        existing = _load_existing_keys(path, "trade_date")
        fetcher = IME_HISTORY_FETCHERS[contract]
        payload = fetcher(client, days=days)

        rows = payload.get("stats") or [] if isinstance(payload, dict) else []
        rows_written = 0
        seen_days: set[str] = set()
        captured_at = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for row in rows:
                trade_date = row.get("trade_date")
                if not trade_date or trade_date in existing:
                    continue
                seen_days.add(str(trade_date))
                record = {
                    "captured_at": captured_at,
                    "contract_code": payload.get("contract_code", contract) if isinstance(payload, dict) else contract,
                    "status": "available",
                    **row,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing.add(str(trade_date))
                rows_written += 1

        expected_days = _iter_dates(start, end)
        covered_days = seen_days | existing
        missing_days = [d for d in expected_days if d not in covered_days]
        report.append(
            CoverageItem(
                name=f"ime_cdc_daily:{contract}",
                requested_from=start.isoformat(),
                requested_to=end.isoformat(),
                returned_rows=rows_written,
                unique_days=len(covered_days & set(expected_days)),
                missing_days=len(missing_days),
                notes=[f"missing_days={missing_days[:20]}"] if missing_days else [],
            )
        )
    return report


def _summarize(report: list[CoverageItem]) -> dict:
    counters = Counter()
    missing_by_kind = defaultdict(int)
    for item in report:
        counters["items"] += 1
        counters["rows"] += item.returned_rows
        counters["missing_days"] += item.missing_days
        kind = item.name.split(":", 1)[0]
        missing_by_kind[kind] += item.missing_days
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": [asdict(item) for item in report],
        "totals": {
            "items": counters["items"],
            "rows": counters["rows"],
            "missing_days": counters["missing_days"],
        },
        "missing_by_kind": dict(missing_by_kind),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect all archive data into the existing archive/ tree.")
    parser.add_argument("--days", type=int, default=30, help="lookback window for bars and IME daily data")
    args = parser.parse_args()

    client = get_client()
    try:
        end = date.today()
        start = end - timedelta(days=max(1, args.days))
        report: list[CoverageItem] = []
        report.extend(_collect_fund_bars(client, start=start, end=end))
        report.extend(_collect_fund_snapshots(client))
        report.extend(_collect_ime_daily(client, days=max(1, args.days)))

        summary = _summarize(report)
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        print(f"Saved coverage report to {REPORT_PATH}")
        print(
            f"Collected {summary['totals']['rows']} new rows across "
            f"{summary['totals']['items']} collection items"
        )
        if summary["totals"]["missing_days"] > 0:
            print(f"Missing-day count by kind: {summary['missing_by_kind']}")
        return 0
    finally:
        close_client()


if __name__ == "__main__":
    raise SystemExit(main())