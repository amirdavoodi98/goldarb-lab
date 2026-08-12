#!/usr/bin/env python3
"""Run the fetch flows in this package with one authenticated client."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pprint import pprint

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import (
    get_all_funds_holdings,
    get_all_funds_nav_live,
    get_fund_holdings,
    get_fund_issued_units,
    get_gold_bar_live,
    get_gold_coin_live,
    get_usdt_live,
    get_xau_xag_live,
)
from .daily_archive import FUND_SYMBOLS as DAILY_FUND_SYMBOLS
from .daily_archive import HOLDINGS_LOG, UNITS_LOG
from .fetch_all_funds_portfolio import fetch_all_portfolios
from .fetch_ime_cdc_history import CONTRACTS as IME_HISTORY_CONTRACTS
from .fetch_ime_cdc_history import FIELDS as IME_HISTORY_FIELDS
from .fetch_ime_cdc_history import MAX_DAYS as IME_HISTORY_MAX_DAYS
from .ime_cdc_archive import ARCHIVE_DIR as IME_ARCHIVE_DIR
from .ime_cdc_archive import CONTRACTS as IME_ARCHIVE_CONTRACTS
from .ime_cdc_archive import MAX_DAYS as IME_ARCHIVE_MAX_DAYS
from .minute_bar_archive import ARCHIVE_DIR as MINUTE_ARCHIVE_DIR
from .minute_bar_archive import FUND_SYMBOLS as MINUTE_FUND_SYMBOLS
from .minute_bar_archive import LOOKBACK_DAYS as MINUTE_LOOKBACK_DAYS
from .check_session_start_gap import CHECK_DATE, FUND_SYMBOLS as GAP_FUND_SYMBOLS
from .inspect_ime_cdc_stats import CONTRACTS as INSPECT_CONTRACTS


def _run_step(name: str, func) -> object:
    print(f"\n==> {name}")
    result = func()
    if result is not None:
        pprint(result)
    return result


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    client = get_client()
    try:
        steps = [
            ("xau_xag_live", lambda: get_xau_xag_live(client)),
            ("usdt_live", lambda: get_usdt_live(client)),
            ("gold_coin_live", lambda: get_gold_coin_live(client)),
            ("gold_bar_live", lambda: get_gold_bar_live(client)),
            ("fund_holdings", lambda: {"طلا": get_fund_holdings(client, "طلا")}),
            ("fund_issued_units", lambda: {"طلا": get_fund_issued_units(client, "طلا")}),
            ("all_funds_portfolio", lambda: fetch_all_portfolios(client)),
            ("all_funds_holdings", lambda: get_all_funds_holdings(client)),
            ("all_funds_nav_live", lambda: get_all_funds_nav_live(client)),
            (
                "fetch_ime_cdc_history",
                lambda: _fetch_ime_cdc_history(client),
            ),
            ("ime_cdc_archive", lambda: _capture_ime_cdc_archive(client)),
            ("daily_archive", lambda: _capture_daily_archive(client)),
            ("minute_bar_archive", lambda: _capture_minute_bar_archive(client)),
            ("check_session_start_gap", lambda: _check_session_start_gap(client)),
            ("inspect_ime_cdc_stats", lambda: _inspect_ime_cdc_stats(client)),
        ]

        for name, func in steps:
            try:
                _run_step(name, func)
            except SystemExit as exc:
                print(f"[warn] {name} exited with code {exc.code}")
            except Exception as exc:
                print(f"[warn] {name} failed: {exc}")

        print("\nAll fetch flows completed successfully.")
        return 0
    finally:
        close_client()


def _fetch_ime_cdc_history(client) -> None:
    all_records: list[dict] = []
    for code in IME_HISTORY_CONTRACTS:
        payload = client.market.ime_cdc_stats(code, days=IME_HISTORY_MAX_DAYS)
        contract_code = payload.get("contract_code", code)
        rows = payload.get("stats") or []
        records = []
        for row in rows:
            records.append(
                {
                    "contract_code": contract_code,
                    "trade_date": row.get("trade_date"),
                    "bar_at": None,
                    "last_price": row.get("last_price"),
                    "settlement_price": row.get("today_settlement_price"),
                    "best_bid": None,
                    "best_ask": None,
                    "trades_volume": row.get("trades_volume"),
                    "price_unit": None,
                    "currency": None,
                    "contract_multiplier": None,
                    "underlying_quantity": None,
                    "purity": None,
                    "source": None,
                    "published_at": None,
                }
            )
        print(f"{code}: {len(records)} daily rows")
        all_records.extend(records)

    with open("ime_cdc_history.jsonl", "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with open("ime_cdc_history.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=IME_HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows(all_records)

    print(f"Saved {len(all_records)} total rows to ime_cdc_history.jsonl / .csv")


def _capture_ime_cdc_archive(client) -> None:
    for contract in IME_ARCHIVE_CONTRACTS:
        path = IME_ARCHIVE_DIR / f"{contract}.jsonl"
        existing = set()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        td = rec.get("trade_date")
                        if td:
                            existing.add(td)
                    except json.JSONDecodeError:
                        continue

        if contract == "GoldBar":
            payload = client.market.ime_cdc_stats(contract, days=IME_ARCHIVE_MAX_DAYS)
        elif contract == "GoldCoin":
            payload = client.market.ime_cdc_stats(contract, days=IME_ARCHIVE_MAX_DAYS)
        else:
            continue

        rows = payload.get("stats") or []
        contract_code = payload.get("contract_code", contract)
        captured_at = datetime.now(timezone.utc).isoformat()
        new_count = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for row in rows:
                trade_date = row.get("trade_date")
                if trade_date is None or trade_date in existing:
                    continue
                record = {"captured_at": captured_at, "contract_code": contract_code, **row}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                existing.add(trade_date)
                new_count += 1
        print(f"{contract}: +{new_count} new daily rows")


def _capture_daily_archive(client) -> None:
    captured_at = datetime.now(timezone.utc).isoformat()
    for symbol in DAILY_FUND_SYMBOLS:
        try:
            holdings = get_fund_holdings(client, symbol)
            _append_jsonl(HOLDINGS_LOG, {"captured_at": captured_at, "symbol": symbol, "payload": holdings})
        except Exception as exc:
            print(f"[warn] holdings capture failed for {symbol}: {exc}")
        try:
            units = get_fund_issued_units(client, symbol)
            _append_jsonl(UNITS_LOG, {"captured_at": captured_at, "symbol": symbol, "payload": units})
        except Exception as exc:
            print(f"[warn] issued_units capture failed for {symbol}: {exc}")
    print(f"Captured {len(DAILY_FUND_SYMBOLS)} funds at {captured_at}")


def _capture_minute_bar_archive(client) -> None:
    end = datetime.now().date()
    start = end - timedelta(days=MINUTE_LOOKBACK_DAYS)
    for symbol in MINUTE_FUND_SYMBOLS:
        path = MINUTE_ARCHIVE_DIR / f"{symbol}.jsonl"
        existing = set()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        bar_at = rec.get("bar_at")
                        if bar_at:
                            existing.add(bar_at)
                    except json.JSONDecodeError:
                        continue
        bars = client.fund.candles(symbol, start=start.isoformat(), end=end.isoformat(), grain="1m")
        captured_at = datetime.now(timezone.utc).isoformat()
        new_count = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for bar in bars:
                bar_at = bar.get("bar_at")
                if bar_at is None or bar_at in existing:
                    continue
                f.write(json.dumps({"captured_at": captured_at, "symbol": symbol, **bar}, ensure_ascii=False) + "\n")
                existing.add(bar_at)
                new_count += 1
        print(f"{symbol}: +{new_count} new bars")


def _check_session_start_gap(client) -> None:
    for symbol in GAP_FUND_SYMBOLS:
        try:
            bars = client.fund.candles(symbol, start=CHECK_DATE, end=CHECK_DATE, grain="1m")
            if bars:
                print(f"{symbol}: {len(bars)} bars, {bars[0]['bar_at']} to {bars[-1]['bar_at']}")
            else:
                print(f"{symbol}: 0 bars returned")
        except Exception as exc:
            print(f"{symbol}: [error] {exc}")


def _inspect_ime_cdc_stats(client) -> None:
    for code in INSPECT_CONTRACTS:
        print(f"\n==> {code}")
        payload = client.market.ime_cdc_stats(code, days=180)
        pprint(payload)
        stats = payload.get("stats") if isinstance(payload, dict) else None
        if isinstance(stats, list) and stats:
            print(f"\n-- first row keys for {code}:")
            pprint(sorted(stats[0].keys()))
            print(f"-- row count: {len(stats)}")


if __name__ == "__main__":
    raise SystemExit(main())
