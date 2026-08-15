#!/usr/bin/env python3
"""
Diagnostic: dump the RAW ime_cdc_stats() payload for GoldBar, GoldCoin,
SilverBar so we can see the actual field set before building a fixed
schema/export around it.

days=180 is the platform's documented max lookback for this endpoint.
"""

import pprint

try:
    from .goldarb_client import close_client, get_client
except ImportError:
    from goldarb_client import close_client, get_client

CONTRACTS = ("GoldBar", "GoldCoin", "SilverBar")


def main() -> None:
    client = get_client()
    try:
        for code in CONTRACTS:
            print(f"\n==> {code}")
            payload = client.market.ime_cdc_stats(code, days=180)
            pprint.pprint(payload)

            stats = payload.get("stats") if isinstance(payload, dict) else None
            if isinstance(stats, list) and stats:
                print(f"\n-- first row keys for {code}:")
                pprint.pprint(sorted(stats[0].keys()))
                print(f"-- row count: {len(stats)}")
    finally:
        close_client()


if __name__ == "__main__":
    main()
