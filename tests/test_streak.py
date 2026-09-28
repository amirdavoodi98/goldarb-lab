"""StreakStrategy behavior through the public backtest engine."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from goldarb import BacktestEngine, RunConfig, StreakStrategy
from goldarb.data import HistoricalDataProvider
from goldarb.execution import NoFee


def _run(closes: tuple[str, ...], **params: object):
    strategy = StreakStrategy(**params)  # type: ignore[arg-type]
    provider = HistoricalDataProvider.from_closes(
        closes,
        start=datetime(2026, 8, 29, 8, 30, tzinfo=UTC),
        step=timedelta(seconds=1),
    )
    return BacktestEngine().run(
        strategy,
        provider,
        RunConfig(strategy_name=strategy.name, initial_cash="1000"),
        fee=NoFee(),
    )


def test_streak_buys_upticks_and_sells_downticks():
    result = _run(
        ("100", "101", "102", "103", "110", "109", "108", "107"),
        quantity="1",
        length=3,
    )

    assert [signal.side.value for signal in result.signals] == ["BUY", "SELL"]
    assert [fill.price for fill in result.fills] == [Decimal("103"), Decimal("107")]
    assert result.portfolio.realized_pnl == Decimal("4")
    assert result.portfolio.positions[0].quantity == 0


def test_streak_does_not_add_to_an_open_long():
    result = _run(("100", "101", "102", "103", "104"), quantity="1", length=2)

    assert [signal.side.value for signal in result.signals] == ["BUY"]
    assert result.portfolio.positions[0].quantity == Decimal("1")


def test_streak_ignores_steps_smaller_than_min_step_pct():
    quiet = _run(("100", "100.5", "101"), quantity="1", length=2, min_step_pct="1")
    loud = _run(("100", "101", "102.01"), quantity="1", length=2, min_step_pct="1")

    assert quiet.signals == []
    assert [signal.side.value for signal in loud.signals] == ["BUY"]
    assert loud.fills[0].price == Decimal("102.01")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("quantity", "0"),
        ("length", 1),
        ("min_step_pct", "-0.1"),
    ),
)
def test_streak_rejects_bad_config(field, value):
    params = {"quantity": "1", "length": 3, "min_step_pct": "0", field: value}
    with pytest.raises(ValueError):
        StreakStrategy(**params)
