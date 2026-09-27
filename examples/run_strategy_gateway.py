#!/usr/bin/env python3
"""Run one registered Strategy through OrderGateway in two modes.

``backtest`` and ``live_paper_local`` both send orders through the local
adapter. This script does not call ``submit_buy`` and does not use the network.

``simulate_local.py``, ``simulate_remote.py``, and ``simulate_agah_broker.py``
are direct paper, not this path. ``run_premium_threshold`` is outside the
Strategy contract.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from goldarb import AppConfig, StrategyRunner
from goldarb.archive import write_symbol_bars
from goldarb.strategies import PriceMomentumStrategy

TEHRAN = ZoneInfo("Asia/Tehran")
WHEN = datetime(2026, 8, 29, 12, 30, tzinfo=TEHRAN)


class _Fund:
    """Two live prints so price momentum can submit once."""

    def __init__(self) -> None:
        self._prices = ("100", "110")
        self._index = 0

    def last_price(self, symbol: str) -> dict[str, str]:
        price = self._prices[min(self._index, len(self._prices) - 1)]
        self._index += 1
        return {"symbol": symbol, "last_price": price}

    def orderbook(self, symbol: str) -> dict[str, str]:
        del symbol
        return {}

    def candles(
        self,
        symbol: str,
        *,
        start: str,
        end: str,
        grain: str = "1s",
    ) -> list[dict[str, str]]:
        del symbol, start, end, grain
        return []


class _Client:
    def __init__(self) -> None:
        self.fund = _Fund()

    def close(self) -> None:
        return None


def _archive(directory: Path) -> None:
    origin = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    rows = [
        {"bar_at": origin.isoformat(), "close": "100"},
        {"bar_at": (origin + timedelta(seconds=1)).isoformat(), "close": "110"},
    ]
    write_symbol_bars(
        directory,
        {"طلا": rows},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )


def main() -> None:
    strategy = PriceMomentumStrategy(quantity="1", threshold_pct="0.5")
    with tempfile.TemporaryDirectory() as raw:
        archive = Path(raw)
        _archive(archive)
        backtest = (
            AppConfig.builder()
            .set_archive(
                archive,
                symbols=["طلا"],
                start="2026-08-29",
                end="2026-08-29",
                mode="backtest",
            )
            .set_strategy("price_momentum", quantity="1", threshold_pct="0.5")
            .set_fee("NoFee")
            .set_initial_cash("100000")
            .build()
        )
        back = StrategyRunner.from_config(backtest).run(strategy)
        live = (
            AppConfig.builder()
            .set_live(symbols=["طلا"], max_polls=2)
            .set_strategy("price_momentum", quantity="1", threshold_pct="0.5")
            .set_fee("NoFee")
            .set_initial_cash("100000")
            .build()
        )
        paper = (
            StrategyRunner.from_config(live)
            .set_client(_Client())
            .set_live_clock(sleep=lambda _seconds: None, now=lambda: WHEN)
            .run(strategy)
        )
    print(
        f"backtest orders={back.metrics.n_orders} fills={back.metrics.n_trades} "
        f"live_paper_local orders={paper.metrics.n_orders} fills={paper.metrics.n_trades}"
    )


if __name__ == "__main__":
    main()
