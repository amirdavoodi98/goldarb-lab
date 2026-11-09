"""Run MaBandStrategy through BacktestEngine with no network access."""

from goldarb import BacktestEngine, MaBandStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee

PRICES = ("100", "100", "100", "97", "97", "103", "103", "96", "96", "104")


def main() -> None:
    result = BacktestEngine().run(
        MaBandStrategy(window=3, buy_band="0.02", sell_band="0.02", quantity="10"),
        HistoricalDataProvider.from_closes(PRICES),
        RunConfig(
            strategy_name="ma_band",
            strategy_version="1",
            initial_cash="10000",
            label="ma-band-backtest",
        ),
        fee=PercentFee("0.001"),
    )
    print(
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades}"
    )
    for signal in result.signals:
        print(
            f"  {signal.side.value:4} event={signal.event_id} extra={signal.extra}"
        )
    portfolio = result.portfolio
    print(
        f"cash={portfolio.cash} equity={portfolio.equity} "
        f"realized={portfolio.realized_pnl} fees={portfolio.fees_paid} "
        f"return={result.metrics.total_return} drawdown={result.metrics.max_drawdown}"
    )


if __name__ == "__main__":
    main()
