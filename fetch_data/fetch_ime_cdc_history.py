#!/usr/bin/env python3
"""
One-shot full dump of daily history for IME CDC contracts (GoldBar,
GoldCoin, SilverBar) — a single snapshot export, not an archive. For
the growing, cumulative archive, see collect_data.py instead; this
script overwrites its output files each run rather than appending.

Only 5 of the originally-requested fields are real and available from
this endpoint: contract_code, trade_date, last_price, settlement_price
(mapped from today_settlement_price), trades_volume.

NOT available from this endpoint (kept as None for schema consistency):
  - bar_at            -> no intraday data exists; this endpoint is daily-only
  - best_bid/best_ask -> only in ime_cdc_live() (current snapshot, no history)
  - price_unit/currency, contract_multiplier, underlying_quantity, purity
                      -> static contract metadata, not returned here
  - source/published_at -> present on ime_cdc_live() but not this endpoint

Depth: HARD-CAPPED at 180 days by the platform, regardless of what you
request (see market.py `ime_cdc_stats` docstring: "Platform clamps days
to 1…180"). Requesting more than 180 does not get you more than 180 —
it's silently clamped server-side, so MAX_DAYS is set to 180 here to
avoid implying otherwise.
"""

import csv
import json

try:
    from .goldarb_client import close_client, get_client
except ImportError:
    from goldarb_client import close_client, get_client

CONTRACTS = ("GoldBar", "GoldCoin", "SilverBar")
MAX_DAYS = 180  # platform hard cap — requesting more does nothing

FIELDS = [
    "contract_code",
    "trade_date",
    "bar_at",
    "last_price",
    "settlement_price",
    "best_bid",
    "best_ask",
    "trades_volume",
    "price_unit",
    "currency",
    "contract_multiplier",
    "underlying_quantity",
    "purity",
    "source",
    "published_at",
]


def fetch_contract_history(client, code: str) -> list[dict]:
    payload = client.market.ime_cdc_stats(code, days=MAX_DAYS)
    contract_code = payload.get("contract_code", code)
    rows = payload.get("stats") or []

    records = []
    for row in rows:
        records.append({
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
        })
    return records


def main() -> None:
    client = get_client()
    all_records: list[dict] = []
    try:
        for code in CONTRACTS:
            records = fetch_contract_history(client, code)
            print(f"{code}: {len(records)} daily rows")
            all_records.extend(records)
    finally:
        close_client()

    with open("ime_cdc_history.jsonl", "w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with open("ime_cdc_history.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_records)

    print(f"\nSaved {len(all_records)} total rows to ime_cdc_history.jsonl / .csv")


if __name__ == "__main__":
    main()