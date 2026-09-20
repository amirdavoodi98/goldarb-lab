"""PriceMomentumStrategy behavior through the public backtest engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from goldarb import BacktestEngine, PriceMomentumStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import NoFee


def test_price_momentum_buys_rise_and_sells_drop():
    strategy = PriceMomentumStrategy(quantity="1", threshold_pct="1")
    provider = HistoricalDataProvider.from_closes(
        ("100", "102", "99"),
        start=datetime(2026, 8, 29, 8, 30, tzinfo=UTC),
        step=timedelta(seconds=1),
    )
    result = BacktestEngine().run(
        strategy,
        provider,
        RunConfig(strategy_name=strategy.name, initial_cash="1000"),
        fee=NoFee(),
    )

    assert [signal.side.value for signal in result.signals] == ["BUY", "SELL"]
    assert [fill.price for fill in result.fills] == [Decimal("102"), Decimal("99")]
    assert result.portfolio.realized_pnl == Decimal("-3")
    assert result.portfolio.positions[0].quantity == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (("quantity", "0"), ("threshold_pct", "0")),
)
def test_price_momentum_rejects_non_positive_config(field, value):
    params = {"quantity": "1", "threshold_pct": "1", field: value}
    with pytest.raises(ValueError):
        PriceMomentumStrategy(**params)
