#!/usr/bin/env python3
"""
check_session_start_gap.py — diagnostic: confirm whether the observed
08:30 UTC bar-start gap (vs. the stated 09:00 Tehran / 05:30 UTC session
open) is systemic across all 5 target funds, or specific to one.

Run once, on a closed trading day, to get clean evidence for the
platform-team backend request (Chunk 7).
"""

from .goldarb_client import get_client, close_client
from .goldarb_data_bundle import get_fund_candles_1m

FUND_SYMBOLS = ("عیار", "طلا", "کهربا", "مثقال", "آتش")
CHECK_DATE = "2026-08-08"  # adjust to a known-closed trading day


def main() -> None:
    client = get_client()
    try:
        for symbol in FUND_SYMBOLS:
            try:
                bars = get_fund_candles_1m(client, symbol, start=CHECK_DATE, end=CHECK_DATE)
                if bars:
                    print(f"{symbol}: {len(bars)} bars, {bars[0]['bar_at']} to {bars[-1]['bar_at']}")
                else:
                    print(f"{symbol}: 0 bars returned")
            except Exception as exc:
                print(f"{symbol}: [error] {exc}")
    finally:
        close_client()


if __name__ == "__main__":
    main()