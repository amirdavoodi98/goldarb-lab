"""Bubble-rank math and BacktestEngine pair rotation."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from goldarb import BacktestEngine, BubbleRankStrategy, RunConfig
from goldarb.data import HistoricalDataProvider
from goldarb.execution import PercentFee
from goldarb.signals.bubble_rank import compute_rankings, compute_symbol_score
from goldarb.simulation import LocalSimulator, Side


def _pair_bars(premiums: list[tuple[float, float]]):
    start = date(2026, 1, 1)
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


def test_score_is_avg_minus_current():
    series = [0.0] * 10 + [-2.0]
    payload = compute_symbol_score(series, min_samples=10)
    assert payload["status"] == "ok"
    assert payload["current"] == -2.0
    assert payload["score"] == payload["avg20"] - payload["current"]
    assert payload["score"] > 0


def test_best_pair_active_when_gap_met():
    by_symbol = {
        "طلا": [0.0] * 11 + [-2.5],
        "زر": [0.0] * 11 + [2.5],
        "گوهر": [0.1] * 5,
    }
    payload = compute_rankings(by_symbol, min_gap=1.0)
    assert payload["best_pair"]["active"] is True
    assert payload["best_pair"]["long"] == "طلا"
    assert payload["best_pair"]["short"] == "زر"


def test_opens_pair_when_gap_active(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-2.5, 2.5)]
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
        window_days=20,
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(_pair_bars(premiums)),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / "bubble.db"),
        fee=PercentFee("0"),
    )
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    sides = {(order.symbol, order.side) for order in result.orders}
    assert ("طلا", Side.BUY) in sides
    assert ("زر", Side.SELL) in sides
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["طلا"] > 0
    assert held["زر"] < 0


def test_flattens_when_signal_goes_inactive(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0), (0.0, 0.0)]
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(_pair_bars(premiums)),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / "flat.db"),
        fee=PercentFee("0"),
    )
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    assert any(item["type"] == "exit_pair" for item in strategy.events)
    assert len(result.orders) >= 4
    for position in result.portfolio.positions:
        assert position.quantity == 0
    assert result.portfolio.realized_pnl == Decimal("0")
