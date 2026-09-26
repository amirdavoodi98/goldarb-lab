#!/usr/bin/env python3
"""Realtime live-paper sample with strategy + runner setters.

Shows:
  1. Strategy setters / ``configure`` for direct params
  2. ``StrategyRunner.set_broker`` for an explicit LocalPaperBroker
  3. One ``StrategyRunner`` path (same as backtest; only ``runtime.mode`` / data differ)

Requires GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD.

Smoke (~20 funds, 30 polls)::

    .venv/bin/python examples/run_realtime_momentum.py

Until session close::

    .venv/bin/python examples/run_realtime_momentum.py --until-close
"""

from __future__ import annotations

import argparse

from goldarb import (
    AppConfig,
    GOLD_FUND_SYMBOLS,
    PriceMomentumStrategy,
    StrategyRunner,
)
from goldarb.simulation import LocalSimulator


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated funds (default: first 20 GOLD_FUND_SYMBOLS)",
    )
    parser.add_argument("--min-funds", type=int, default=20)
    parser.add_argument("--max-polls", type=int, default=30)
    parser.add_argument(
        "--until-close",
        action="store_true",
        help="Ignore max_polls; run until session.end",
    )
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--quantity", default="1")
    parser.add_argument("--threshold-pct", default="0.1")
    args = parser.parse_args()

    if args.symbols:
        symbols = tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    else:
        symbols = GOLD_FUND_SYMBOLS[: max(args.min_funds, 20)]
    if len(symbols) < args.min_funds:
        raise SystemExit(f"need at least {args.min_funds} symbols, got {len(symbols)}")

    # 1) Strategy setters — config goes onto the strategy instance directly
    strategy = (
        PriceMomentumStrategy()
        .set_quantity(args.quantity)
        .set_threshold_pct(args.threshold_pct)
    )
    # equivalent: strategy.configure(quantity=args.quantity, threshold_pct=args.threshold_pct)

    # Same runner as backtest; only mode + live data change
    builder = (
        AppConfig.builder()
        .set_live(
            symbols=symbols,
            max_polls=None if args.until_close else args.max_polls,
            poll_seconds=args.poll_seconds,
        )
        .set_initial_cash("1000000000")
        .set_database(":memory:")
        .set_label("realtime_price_momentum")
        .set_fee("PercentFee", fee_rate="0.0005")
        .set_slippage("NoSlippage")
        .set_latency("NoLatency")
    )
    config = builder.build()

    # 2) Runner broker setter — explicit local paper matcher
    broker = LocalSimulator(":memory:")

    result = (
        StrategyRunner.from_config(config)
        .set_broker(broker)
        .set_strategy(strategy)
        .run()
    )
    print(
        f"strategy={result.config.strategy_name} mode={config.runtime.mode} "
        f"symbols={len(symbols)} events={len(result.equity_history)} "
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} equity={result.portfolio.equity}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
