#!/usr/bin/env python3
"""Example: fetch 1m طلا candles via LabClient."""

from goldarb import LabClient


def main() -> None:
    with LabClient.from_env() as client:
        bars = client.fund.candles(
            "طلا",
            start="2026-07-01",
            end="2026-07-02",
            grain="1m",
        )
        print(f"bars={len(bars)}")
        if bars:
            print(bars[0])
            print(bars[-1])


if __name__ == "__main__":
    main()
