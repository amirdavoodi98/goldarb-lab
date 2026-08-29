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


def test_does_not_leave_long_only_when_short_disabled(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-2.5, 2.5)]
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
            allow_short=False,
        ),
        simulator=LocalSimulator(tmp_path / "noshort.db"),
        fee=PercentFee("0"),
    )
    assert strategy.events == []
    assert strategy._current_pair is None
    for position in result.portfolio.positions:
        assert position.quantity == 0


def test_ignores_stale_premium_when_symbol_absent(tmp_path):
    start = date(2026, 1, 1)
    bars = []
    for index in range(12):
        row = {
            "طلا": {"close": 20000.0, "premium": 0.0},
            "زر": {"close": 10000.0, "premium": 0.0},
        }
        if index < 11:
            row["گوهر"] = {"close": 15000.0, "premium": 0.0 if index < 10 else -10.0}
        bars.append((start + timedelta(days=index), row))
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
    )
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(bars),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / "stale.db"),
        fee=PercentFee("0"),
    )
    assert any(
        item["type"] == "enter_pair" and item["long"] == "گوهر" for item in strategy.events
    )
    assert any(item["type"] == "exit_pair" for item in strategy.events)
    best = (strategy.last_ranking or {}).get("best_pair")
    assert best is None or best.get("active") is False or best.get("long") != "گوهر"
    for position in result.portfolio.positions:
        assert position.quantity == 0


def test_rotates_when_cheap_and_rich_swap(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0), (3.0, -3.0)]
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
        simulator=LocalSimulator(tmp_path / "swap.db"),
        fee=PercentFee("0"),
    )
    types = [item["type"] for item in strategy.events]
    assert "enter_pair" in types
    assert "rebalance_pair" in types
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["زر"] > 0
    assert held["طلا"] < 0
