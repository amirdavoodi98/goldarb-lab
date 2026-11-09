#!/usr/bin/env python3
"""Example: pull the main series a strategy notebook typically needs."""

from goldarb import LabClient


def main() -> None:
    with LabClient.from_env() as c:
        symbols = c.fund.symbols()
        print(f"universe={len(symbols)}")

        tala = c.fund.candles("طلا", start="2026-07-28", end="2026-07-29", grain="1m")
        flow = c.fund.flow("طلا", days=30)
        stats = c.fund.premium_stats("طلا", window=90)
        spreads = c.fund.spreads(window=90)
        xau = c.market.xau(start="2026-07-28", end="2026-07-29", grain="1m")
        usdt = c.market.usdt(days=2)
        gold = c.market.gold_daily(days=30)
        snap = c.market.live_snapshot(include=("refs", "funds", "orderbook"))

        print(f"tala_1m={len(tala)} flow={len(flow)} xau={len(xau)} usdt={len(usdt)}")
        print(f"gold_daily={len(gold)} premium_stats_keys={sorted(stats)[:8]}")
        print(f"spreads_keys={sorted(spreads)[:8]}")
        print(f"snapshot_keys={sorted(snap)}")


if __name__ == "__main__":
    main()
