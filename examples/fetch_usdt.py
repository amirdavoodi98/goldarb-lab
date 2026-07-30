#!/usr/bin/env python3
"""Example: fetch USDT/IRR 1m bars + live tip (toman) via LabClient."""

from goldarb import LabClient


def main() -> None:
    with LabClient.from_env() as client:
        bars = client.market.usdt(start="2026-07-28", end="2026-07-29")
        tip = client.market.usdt_live()
        print(f"usdt_1m bars={len(bars)}")
        if bars:
            print("first=", bars[0])
            print("last =", bars[-1])
        print(
            "live last_irr=",
            tip.get("last_irr"),
            "unit=",
            tip.get("unit"),
            "source=",
            tip.get("source"),
            "status=",
            tip.get("status"),
        )


if __name__ == "__main__":
    main()
