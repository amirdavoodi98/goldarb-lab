"""Run BubbleRankStrategy on 1s ticks for the full gold-fund universe."""

from goldarb import BacktestEngine, BubbleRankStrategy, RunConfig
from goldarb.data import HistoricalDataProvider, cross_section_1s
from goldarb.execution import PercentFee
from goldarb.universe import GOLD_FUND_SYMBOLS


def _bars():
    n = 12
    tala = [0.0] * 11 + [-2.5]
    zar = [0.0] * 11 + [2.5]
    return cross_section_1s(n, premiums={"طلا": tala, "زر": zar})


def main() -> None:
    bars = _bars()
    strategy = BubbleRankStrategy(capital_per_side="100000", min_samples=10, min_gap=1.0)
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(bars, event_prefix="1s"),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
            label="bubble-rank-1s",
        ),
        fee=PercentFee("0"),
    )
    first = next(HistoricalDataProvider.from_cross_section(bars).events())
    print(f"grain=1s symbols={len(first.quotes)} universe={len(GOLD_FUND_SYMBOLS)}")
    print(f"events={[item['type'] for item in strategy.events]}")
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity} realized={result.portfolio.realized_pnl}"
    )
    for position in result.portfolio.positions:
        print(f"  {position.symbol} qty={position.quantity}")


if __name__ == "__main__":
    main()
