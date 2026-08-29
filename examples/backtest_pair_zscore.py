"""Run PairZScoreStrategy on 1s ticks for the full gold-fund universe."""

from goldarb import BacktestEngine, PairZScoreStrategy, RunConfig
from goldarb.data import HistoricalDataProvider, cross_section_1s
from goldarb.execution import PercentFee
from goldarb.universe import GOLD_FUND_SYMBOLS


def _bars():
    n = 20
    tala = []
    zar = []
    for index in range(n):
        if index < 15:
            tala.append(0.0)
            zar.append(0.0)
        else:
            delta = float(index - 15)
            tala.append(5.0 + delta)
            zar.append(-5.0 - delta)
    return cross_section_1s(n, premiums={"طلا": tala, "زر": zar})


def main() -> None:
    bars = _bars()
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
        HistoricalDataProvider.from_cross_section(bars, event_prefix="1s"),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
            label="pair-zscore-1s",
        ),
        fee=PercentFee("0"),
    )
    first = next(HistoricalDataProvider.from_cross_section(bars).events())
    print(f"grain=1s symbols={len(first.quotes)} universe={len(GOLD_FUND_SYMBOLS)}")
    print(f"status={strategy.last_status} events={[item['type'] for item in strategy.events]}")
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity}"
    )
    for position in result.portfolio.positions:
        print(f"  {position.symbol} qty={position.quantity}")


if __name__ == "__main__":
    main()
