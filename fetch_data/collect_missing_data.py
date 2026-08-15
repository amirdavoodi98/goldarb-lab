#!/usr/bin/env python3
"""Collect available historical data and write coverage reports.

This script focuses on the gaps described in the reports:
- 1m fund bars for the five target funds
- holdings and issued-units snapshots
- IME CDC daily history

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

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import (
    get_fund_candles_1m,
    get_fund_holdings,
    get_fund_issued_units,
    get_gold_bar_history,
    get_gold_coin_history,
)

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")
IME_CONTRACTS = ("GoldBar", "GoldCoin")

BASE_DIR = Path("archive") / "missing_data"
FUND_BARS_DIR = BASE_DIR / "fund_bars_1m"
FUND_SNAPSHOTS_DIR = BASE_DIR / "fund_snapshots"
IME_DAILY_DIR = BASE_DIR / "ime_cdc_daily"
REPORT_PATH = BASE_DIR / "coverage_report.json"
MINUTE_GAP_PATH = BASE_DIR / "minute_gap_report.json"


@dataclass
class CoverageItem:
    name: str
    requested_from: str
    requested_to: str
    returned_rows: int
    unique_days: int
    missing_days: int
    notes: list[str]


@dataclass
class MinuteGapItem:
    symbol: str
    trade_date: str
    minute_at: str
    expected_minutes: int
    status_detail: str
    status: str


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
    minute_report: list[MinuteGapItem] = []
    day_bars: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for symbol in FUND_SYMBOLS:
        path = FUND_BARS_DIR / f"{symbol}.jsonl"
        existing = _load_existing_keys(path, "bar_at")
        bars = get_fund_candles_1m(client, symbol, start=start.isoformat(), end=end.isoformat())
        rows = 0
        days_seen: dict[str, list[str]] = defaultdict(list)
        captured_at = datetime.now(timezone.utc).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for bar in bars:
                bar_at = bar.get("bar_at")
                if not bar_at or bar_at in existing:
                    continue
                trade_date = str(bar_at)[:10]
                minute_at = str(bar_at)
                days_seen[trade_date].append(minute_at)
                day_bars[trade_date][minute_at][symbol] = bar
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
        missing_days = [d for d in all_days if d not in days_seen]
        report.append(
            CoverageItem(
                name=f"fund_bars_1m:{symbol}",
                requested_from=start.isoformat(),
                requested_to=end.isoformat(),
                returned_rows=rows,
                unique_days=len(days_seen),
                missing_days=len(missing_days),
                notes=[f"missing_days={missing_days[:20]}"] if missing_days else [],
            )
        )
    for trade_date in sorted(day_bars):
        minute_grid = sorted(day_bars[trade_date].keys())
        expected_minutes = len(minute_grid)
        for minute_at in minute_grid:
            present_symbols = set(day_bars[trade_date][minute_at].keys())
            for symbol in FUND_SYMBOLS:
                if symbol in present_symbols:
                    minute_report.append(
                        MinuteGapItem(
                            symbol=symbol,
                            trade_date=trade_date,
                            minute_at=minute_at,
                            expected_minutes=expected_minutes,
                            status_detail="bar_present",
                            status="available",
                        )
                    )
                else:
                    minute_report.append(
                        MinuteGapItem(
                            symbol=symbol,
                            trade_date=trade_date,
                            minute_at=minute_at,
                            expected_minutes=expected_minutes,
                            status_detail="no_trade_or_missing",
                            status="no_trade",
                        )
                    )
    for trade_date in _iter_dates(start, end):
        if trade_date not in day_bars:
            for symbol in FUND_SYMBOLS:
                minute_report.append(
                    MinuteGapItem(
                        symbol=symbol,
                        trade_date=trade_date,
                        minute_at="",
                        expected_minutes=0,
                        status_detail="no bars observed for any symbol on this date",
                        status="missing",
                    )
                )
    with open(MINUTE_GAP_PATH, "w", encoding="utf-8") as f:
        json.dump([asdict(item) for item in minute_report], f, ensure_ascii=False, indent=2)
    return report


def _collect_fund_snapshots(client) -> list[CoverageItem]:
    captured_at = datetime.now(timezone.utc).isoformat()
    report: list[CoverageItem] = []
    holdings_path = FUND_SNAPSHOTS_DIR / "holdings_history.jsonl"
    units_path = FUND_SNAPSHOTS_DIR / "issued_units_history.jsonl"
    for symbol in FUND_SYMBOLS:
        try:
            holdings = get_fund_holdings(client, symbol)
            payload = holdings if isinstance(holdings, dict) else {"raw": holdings}
            payload.setdefault("captured_at", captured_at)
            payload.setdefault("status", "snapshot")
            payload.setdefault("source_kind", "current_snapshot")
            _append_jsonl(
                holdings_path,
                {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "status": "snapshot",
                    "payload": payload,
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
            payload = units if isinstance(units, dict) else {"raw": units}
            payload.setdefault("captured_at", captured_at)
            payload.setdefault("status", "snapshot")
            payload.setdefault("source_kind", "current_snapshot")
            _append_jsonl(
                units_path,
                {
                    "captured_at": captured_at,
                    "symbol": symbol,
                    "status": "snapshot",
                    "payload": payload,
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
        if contract == "GoldBar":
            payload = get_gold_bar_history(client, days=days)
        else:
            payload = get_gold_coin_history(client, days=days)

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
        missing_days = [d for d in expected_days if d not in seen_days]
        report.append(
            CoverageItem(
                name=f"ime_cdc_daily:{contract}",
                requested_from=start.isoformat(),
                requested_to=end.isoformat(),
                returned_rows=rows_written,
                unique_days=len(seen_days),
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
    parser = argparse.ArgumentParser(description="Collect missing data into append-only archives.")
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
        return 0
    finally:
        close_client()


if __name__ == "__main__":
    raise SystemExit(main())
