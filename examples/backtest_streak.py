"""Run StreakStrategy through BacktestEngine with no network access.

Three rising closes buy. Three falling closes sell.

    .venv/bin/python examples/backtest_streak.py
"""

from goldarb import BacktestEngine, RunConfig, StreakStrategy
from goldarb.data import HistoricalDataProvider
from goldarb.execution import NoFee

# 100→101→102→103 is three upticks (buy at 103).
# 110→109→108→107 is three downticks (sell at 107).
PRICES = ("100", "101", "102", "103", "110", "109", "108", "107")


def main() -> None:
    result = BacktestEngine().run(
        StreakStrategy(quantity="1", length=3),
        HistoricalDataProvider.from_closes(PRICES),
        RunConfig(
            strategy_name="streak",
            strategy_version="1",
            initial_cash="1000",
            label="streak-backtest",
        ),
        fee=NoFee(),
    )
    print(
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades}"
    )
    for signal in result.signals:
        print(f"  {signal.side.value:4} price={signal.extra['price']}")
    portfolio = result.portfolio
    print(
        f"cash={portfolio.cash} equity={portfolio.equity} "
        f"realized={portfolio.realized_pnl} fees={portfolio.fees_paid}"
    )


if __name__ == "__main__":
    main()
