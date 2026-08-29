"""Run BubbleRankStrategy through BacktestEngine with no network access."""

from datetime import date, timedelta

from goldarb import BacktestEngine, BubbleRankStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee


def _bars() -> list:
    start = date(2026, 1, 1)
    rows = []
    for index in range(12):
        if index < 11:
            prem_a, prem_b = 0.0, 0.0
        else:
            prem_a, prem_b = -2.5, 2.5
        rows.append(
            (
                start + timedelta(days=index),
                {
                    "طلا": {"close": 20000.0, "premium": prem_a},
                    "زر": {"close": 10000.0, "premium": prem_b},
                },
            )
        )
    return rows


def main() -> None:
    strategy = BubbleRankStrategy(capital_per_side="100000", min_samples=10, min_gap=1.0)
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(_bars()),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
            label="bubble-rank-backtest",
        ),
        fee=PercentFee("0"),
    )
    print(f"events={[item['type'] for item in strategy.events]}")
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity} realized={result.portfolio.realized_pnl}"
    )
    for position in result.portfolio.positions:
        print(f"  {position.symbol} qty={position.quantity}")


if __name__ == "__main__":
    main()
