#!/usr/bin/env python3
"""Example: fetch 1s طلا candles (auto-chunked, one calendar day per request)."""

from datetime import date, timedelta

from goldarb import LabClient


def main() -> None:
    end = date.today()
    start = end - timedelta(days=3)
    with LabClient.from_env() as client:
        bars = client.fund.candles(
            "طلا",
            start=start,
            end=end,
            grain="1s",
        )
        print(f"range={start}..{end} bars={len(bars)}")
        if bars:
            print(bars[0])
            print(bars[-1])


if __name__ == "__main__":
    main()
