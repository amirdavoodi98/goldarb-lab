#!/usr/bin/env python3
"""Try a strategy end-to-end on LocalPaperBroker (no API, no archive).

Runs PriceMomentumStrategy on a short synthetic price series so you can see
signals, orders, fills, and portfolio after one offline backtest.

    .venv/bin/python examples/try_strategy_paper_broker.py

Optional flags:

    .venv/bin/python examples/try_strategy_paper_broker.py --slippage 1 --fee 0.001
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from goldarb import BacktestEngine, PriceMomentumStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import FixedSlippage, NoSlippage, PercentFee
from goldarb.simulation import LocalSimulator

# Synthetic last prices (Tehran session-style ticks are not required here).
# +2% then -2% should produce BUY then SELL with threshold_pct=0.5.
PRICES = (
    "100",
    "100",
    "102",  # +2% → BUY
    "102",
    "99.9",  # ~-2% → SELL
    "100",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quantity", default="10", help="Order size")
    parser.add_argument("--threshold-pct", default="0.5", help="Move %% to trigger")
    parser.add_argument("--fee", default="0.001", help="Percent fee rate")
    parser.add_argument(
        "--slippage",
        default="0",
        help="Fixed slippage amount on fill price (0 = none)",
    )
    parser.add_argument(
        "--db",
        default=":memory:",
        help="SQLite path for LocalPaperBroker (default: memory)",
    )
    args = parser.parse_args()

    slip = Decimal(str(args.slippage))
    slippage = NoSlippage() if slip == 0 else FixedSlippage(slip)
    fee = PercentFee(args.fee)

    strategy = PriceMomentumStrategy(
        quantity=args.quantity,
        threshold_pct=args.threshold_pct,
    )
    provider = HistoricalDataProvider.from_closes(PRICES, symbol="طلا")

    with LocalSimulator(
        args.db,
        fee=fee,
        slippage=slippage,
    ) as simulator:
        result = BacktestEngine().run(
            strategy,
            provider,
            RunConfig(
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                initial_cash="1000000",
                label="try-strategy-paper-broker",
                database=None if args.db == ":memory:" else args.db,
            ),
            simulator=simulator,
            fee=fee,
            slippage=slippage,
        )

    print("=== run ===")
    print(
        f"strategy={strategy.name}  signals={result.metrics.n_signals}  "
        f"orders={result.metrics.n_orders}  fills={result.metrics.n_trades}  "
        f"fill_rate={result.metrics.fill_rate}"
    )
    print(
        f"cash={result.portfolio.cash}  equity={result.portfolio.equity}  "
        f"fees={result.portfolio.fees_paid}  "
        f"realized={result.portfolio.realized_pnl}  "
        f"return={result.metrics.total_return}"
    )

    print("\n=== signals ===")
    for signal in result.signals:
        print(
            f"  {signal.side.value:4}  {signal.symbol}  "
            f"extra={dict(signal.extra)}"
        )

    print("\n=== orders ===")
    for order in result.orders:
        print(
            f"  {order.status.value:16}  {order.side.value:4}  "
            f"qty={order.quantity}  filled={order.filled_quantity}  "
            f"avg={order.avg_fill_price}  id={order.id[:8]}…"
        )

    print("\n=== fills ===")
    for fill in result.fills:
        raw = fill.raw_match_price if fill.raw_match_price is not None else fill.price
        print(
            f"  qty={fill.quantity}  raw={raw}  price={fill.price}  "
            f"fee={fill.fee}  at={fill.filled_at}"
        )

    print("\n=== positions ===")
    if not result.portfolio.positions:
        print("  (flat)")
    for pos in result.portfolio.positions:
        print(
            f"  {pos.symbol}  qty={pos.quantity}  avg_cost={pos.average_cost}  "
            f"unrealized={pos.unrealized_pnl}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
