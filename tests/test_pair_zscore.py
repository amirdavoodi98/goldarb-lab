"""Pair z-score math and BacktestEngine rotation."""

from __future__ import annotations

from datetime import date, timedelta

from goldarb import BacktestEngine, PairZScoreStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee
from goldarb.signals.pair_spread import compute_pair_spread_stats
from goldarb.simulation import LocalSimulator, Side


def _pair_bars(premiums: list[tuple[float, float]]):
    start = date(2026, 6, 1)
    bars = []
    for index, (prem_a, prem_b) in enumerate(premiums):
        bars.append(
            (
                start + timedelta(days=index),
                {
                    "طلا": {"close": 20000.0, "premium": prem_a},
                    "زر": {"close": 10000.0, "premium": prem_b},
                },
            )
        )
    return bars


def test_positive_z_longs_b_shorts_a():
    series = [0.0] * 15 + [10.0, 12.0, 14.0, 16.0, 18.0]
    stats = compute_pair_spread_stats(
        fund_a="طلا",
        fund_b="زر",
        series=series,
        premium_a=9.0,
        premium_b=-9.0,
        price_a=20000.0,
        price_b=10000.0,
        window_days=20,
        min_samples=10,
        z_threshold=1.5,
    )
    assert stats["status"] == "ok"
    assert stats["z_score"] is not None and stats["z_score"] >= 1.5
    signal = stats["pair_signal"]
    assert signal["active"] is True
    assert signal["long"] == "زر"
    assert signal["short"] == "طلا"


def test_insufficient_samples_no_trade(tmp_path):
    premiums = [(0.0, 0.0)] * 5
    strategy = PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=30,
        min_samples=10,
        z_threshold=2.0,
        capital_per_side="100000",
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(_pair_bars(premiums)),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / "zshort.db"),
        fee=PercentFee("0"),
    )
    assert strategy.last_status == "insufficient_samples"
    assert strategy.events == []
    assert result.orders == []


def test_opens_when_z_extreme(tmp_path):
    premiums = []
    for index in range(20):
        if index < 15:
            premiums.append((0.0, 0.0))
        else:
            delta = float(index - 15)
            premiums.append((5.0 + delta, -5.0 - delta))
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
        HistoricalDataProvider.from_cross_section(_pair_bars(premiums)),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / "zscore.db"),
        fee=PercentFee("0"),
    )
    assert strategy.last_status == "ok"
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    sides = {(order.symbol, order.side) for order in result.orders}
    assert ("زر", Side.BUY) in sides
    assert ("طلا", Side.SELL) in sides
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["زر"] > 0
    assert held["طلا"] < 0
