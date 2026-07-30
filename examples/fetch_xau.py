#!/usr/bin/env python3
"""Example: fetch XAU 1m bars via LabClient."""

from goldarb import LabClient


def main() -> None:
    with LabClient.from_env() as client:
        bars = client.market.xau(
            start="2026-07-01",
            end="2026-07-02",
            grain="1m",
        )
        print(f"xau_bars={len(bars)}")
        if bars:
            print(bars[0])


if __name__ == "__main__":
    main()
