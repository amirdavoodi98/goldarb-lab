#!/usr/bin/env python3
"""Run every fetch flow in this package with one authenticated client."""

from __future__ import annotations

from pprint import pprint

from .goldarb_client import close_client, get_client
from .goldarb_data_bundle import (
    get_fund_holdings,
    get_fund_issued_units,
    get_gold_bar_live,
    get_gold_coin_live,
    get_usdt_live,
    get_xau_xag_live,
)


def main() -> int:
    client = get_client()
    try:
        results = {
            "xau_xag_live": get_xau_xag_live(client),
            "usdt_live": get_usdt_live(client),
            "gold_coin_live": get_gold_coin_live(client),
            "gold_bar_live": get_gold_bar_live(client),
            "fund_holdings": {"طلا": get_fund_holdings(client, "طلا")},
            "fund_issued_units": {"طلا": get_fund_issued_units(client, "طلا")},
        }

        for key, value in results.items():
            print(f"\n==> {key}")
            pprint(value)

        print("\nAll fetch flows completed successfully.")
        return 0
    finally:
        close_client()


if __name__ == "__main__":
    raise SystemExit(main())

