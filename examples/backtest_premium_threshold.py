#!/usr/bin/env python3
"""
Backtest Lab ``premium_threshold`` offline via the SDK.

Requires:
  export GOLDARB_BASE_URL=https://goldarb.ir
  export GOLDARB_TOKEN=...

Optional env:
  GOLDARB_SYMBOL=طلا
  GOLDARB_DAYS=90
  GOLDARB_GRAIN=daily          # daily | 1m
  GOLDARB_BUY_LTE=-2
  GOLDARB_SELL_GTE=2
"""

from __future__ import annotations

import os
from datetime import date, timedelta

from goldarb import LabClient
from goldarb.premium_threshold import run_premium_threshold


def _date_range(days: int) -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=max(1, days) - 1)
    return start.isoformat(), end.isoformat()


def main() -> None:
    symbol = os.environ.get("GOLDARB_SYMBOL", "طلا")
    days = int(os.environ.get("GOLDARB_DAYS", "90"))
    grain = os.environ.get("GOLDARB_GRAIN", "daily").strip().lower()
    buy_lte = float(os.environ.get("GOLDARB_BUY_LTE", "-2"))
    sell_gte = float(os.environ.get("GOLDARB_SELL_GTE", "2"))
    start, end = _date_range(days)

    with LabClient.from_env() as client:
        bars = client.fund.candles(symbol, start=start, end=end, grain=grain)

    result = run_premium_threshold(
        bars,
        buy_lte=buy_lte,
        sell_gte=sell_gte,
    )
    print(
        f"symbol={symbol} grain={grain} range={start}..{end} bars={result.n_bars}"
    )
    print(result.summary())
    for ev in result.events[:10]:
        print(
            f"  {ev.kind:11} {ev.bar_at} px={ev.price:.2f} "
            f"prem={ev.premium} qty={ev.qty:.4f}"
        )
    if len(result.events) > 10:
        print(f"  … {len(result.events) - 10} more events")


if __name__ == "__main__":
    main()
