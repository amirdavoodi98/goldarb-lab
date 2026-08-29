"""Run PairZScoreStrategy through BacktestEngine with no network access."""

from datetime import date, timedelta

from goldarb import BacktestEngine, PairZScoreStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee


def _bars() -> list:
    start = date(2026, 6, 1)
    rows = []
    for index in range(20):
        if index < 15:
            prem_a, prem_b = 0.0, 0.0
        else:
            delta = float(index - 15)
            prem_a, prem_b = 5.0 + delta, -5.0 - delta
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
    strategy = PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=20,
        min_samples=10,
        z_threshold=1.5,
        capital_per_side="100000",
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(_bars()),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
            label="pair-zscore-backtest",
        ),
        fee=PercentFee("0"),
    )
    print(f"status={strategy.last_status} events={[item['type'] for item in strategy.events]}")
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity}"
    )
    for position in result.portfolio.positions:
        print(f"  {position.symbol} qty={position.quantity}")


if __name__ == "__main__":
    main()
