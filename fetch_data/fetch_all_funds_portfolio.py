#!/usr/bin/env python3
"""
Fetch: اطلاعات پورتفولیوی صندوق‌های مختلف — asset composition (%) and
total issued units for every fund in app.gold_funds.GOLD_FUNDS.

NOTE: "issued units" here is each fund's TOTAL outstanding units
(near-daily, TSETMC-sourced) — not a specific investor's position.
This SDK/platform does not expose per-investor holdings.

Continues past individual fund failures (404 / stale / no Codal data
yet) instead of aborting the whole run — failures are collected and
reported at the end.
"""

import json
import pprint
import sys

from fetch_data.gold_funds import GOLD_FUNDS
try:
    from .goldarb_client import close_client, get_client
    from .goldarb_data_bundle import get_fund_holdings, get_fund_issued_units
except ImportError:
    from goldarb_client import close_client, get_client
    from goldarb_data_bundle import get_fund_holdings, get_fund_issued_units


def fetch_all_portfolios(client=None) -> dict:
    if client is None:
        client = get_client()
    results: dict = {}
    errors: dict = {}

    for name, ins_code in GOLD_FUNDS.items():
        try:
            holdings = get_fund_holdings(client, name)
            units = get_fund_issued_units(client, name)
            results[name] = {
                "ins_code": ins_code,
                "holdings": holdings,
                "issued_units": units,
            }
        except Exception as exc:  # noqa: BLE001 — one bad fund shouldn't stop the rest
            errors[name] = str(exc)

    return {"results": results, "errors": errors}


def main() -> None:
    try:
        data = fetch_all_portfolios()
    finally:
        close_client()

    for name, payload in data["results"].items():
        print(f"\n==> {name}")
        pprint.pprint(payload)

    if data["errors"]:
        print("\n" + "=" * 50)
        print(f"Failed for {len(data['errors'])} fund(s):")
        for name, err in data["errors"].items():
            print(f"  {name}: {err}")

    # Optional: dump everything to a JSON file for downstream use
    out_path = "all_funds_portfolio.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data["results"], f, ensure_ascii=False, indent=2)
    print(f"\nSaved {len(data['results'])} funds to {out_path}")

    if data["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
