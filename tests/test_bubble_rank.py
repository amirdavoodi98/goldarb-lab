"""Bubble-rank math and 1s BacktestEngine pair rotation over the full universe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldarb import BacktestEngine, BubbleRankStrategy, RunConfig
from goldarb.data import HistoricalDataProvider, cross_section_1s
from goldarb.execution import FixedLatency, PercentFee
from goldarb.signals.bubble_rank import compute_rankings, compute_symbol_score
from goldarb.simulation import LocalSimulator, MarketSnapshot, OrderStatus, Quote, Side
from goldarb.universe import GOLD_FUND_SYMBOLS


def _pair_bars(premiums: list[tuple[float, float]]):
    tala = [prem_a for prem_a, _ in premiums]
    zar = [prem_b for _, prem_b in premiums]
    return cross_section_1s(len(premiums), premiums={"طلا": tala, "زر": zar})


def _run(strategy, bars, tmp_path, name, *, allow_short=True):
    return BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(bars),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=allow_short,
        ),
        simulator=LocalSimulator(tmp_path / name),
        fee=PercentFee("0"),
    )


def _assert_1s_universe(bars):
    snapshots = list(HistoricalDataProvider.from_cross_section(bars).events())
    assert snapshots
    for previous, current in zip(snapshots, snapshots[1:]):
        assert (current.timestamp - previous.timestamp) == timedelta(seconds=1)
    for snapshot in snapshots:
        assert {quote.symbol for quote in snapshot.quotes} == set(GOLD_FUND_SYMBOLS)


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
    bars = _pair_bars(premiums)
    _assert_1s_universe(bars)
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
        window_days=20,
    )
    result = _run(strategy, bars, tmp_path, "bubble.db")
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
    result = _run(strategy, _pair_bars(premiums), tmp_path, "flat.db")
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
    result = _run(
        strategy,
        _pair_bars(premiums),
        tmp_path,
        "noshort.db",
        allow_short=False,
    )
    assert strategy.events == []
    assert strategy._current_pair is None
    for position in result.portfolio.positions:
        assert position.quantity == 0


def test_ignores_stale_premium_when_symbol_absent(tmp_path):
    bars = cross_section_1s(
        12,
        premiums={
            "طلا": [0.0] * 12,
            "زر": [0.0] * 12,
            "گوهر": [0.0] * 10 + [-10.0],
        },
    )
    del bars[-1][1]["گوهر"]
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
    )
    result = _run(strategy, bars, tmp_path, "stale.db")
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
    result = _run(strategy, _pair_bars(premiums), tmp_path, "swap.db")
    types = [item["type"] for item in strategy.events]
    assert "enter_pair" in types
    assert "rebalance_pair" in types
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["زر"] > 0
    assert held["طلا"] < 0


def test_calendar_window_drops_old_1s_ticks(tmp_path):
    start = datetime(2026, 1, 1, 8, 30, tzinfo=UTC)
    early = cross_section_1s(
        12,
        start=start,
        premiums={"طلا": [0.0] * 11 + [-3.0], "زر": [0.0] * 11 + [3.0]},
    )
    later = cross_section_1s(
        5,
        start=start + timedelta(days=21),
        premiums={"طلا": [-3.0] * 5, "زر": [3.0] * 5},
    )
    strategy = BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
        window_days=20,
    )
    result = _run(strategy, early + later, tmp_path, "window.db")
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    assert any(item["type"] == "exit_pair" for item in strategy.events)
    for position in result.portfolio.positions:
        assert position.quantity == 0
    assert strategy.last_ranking is not None
    for row in strategy.last_ranking["rankings"]:
        assert row["sample_count"] <= 5


def _ranked_snapshots(
    premiums: list[tuple[float, float]],
    *,
    blank_short_from: int | None = None,
) -> list[MarketSnapshot]:
    origin = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    snapshots: list[MarketSnapshot] = []
    for index, (prem_long, prem_short) in enumerate(premiums):
        short_last = (
            None
            if blank_short_from is not None and index >= blank_short_from
            else Decimal("12000")
        )
        timestamp = origin + timedelta(seconds=index)
        snapshots.append(
            MarketSnapshot(
                event_id=f"bubble:{index}",
                timestamp=timestamp,
                quotes=(
                    Quote(
                        symbol="طلا",
                        last=Decimal("10000"),
                        premium=Decimal(str(prem_long)),
                    ),
                    Quote(
                        symbol="زر",
                        last=short_last,
                        premium=Decimal(str(prem_short)),
                    ),
                ),
            )
        )
    return snapshots


def _run_ranked(strategy, snapshots, tmp_path, name, *, latency_ms=0, on_event=None):
    return BacktestEngine().run(
        strategy,
        HistoricalDataProvider(snapshots),
        RunConfig(
            strategy_name="bubble_rank",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / name),
        fee=PercentFee("0"),
        latency=FixedLatency(latency_ms),
        on_event=on_event,
    )


def _bubble():
    return BubbleRankStrategy(
        capital_per_side="100000",
        min_samples=10,
        min_gap=1.0,
        window_days=20,
    )


def test_open_pair_fills_on_a_later_tick_when_latency_is_set(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0)] * 8
    strategy = _bubble()
    result = _run_ranked(
        strategy,
        _ranked_snapshots(premiums),
        tmp_path,
        "latency.db",
        latency_ms=2500,
    )
    assert [item["type"] for item in strategy.events] == ["enter_pair"]
    assert len(result.orders) == 2
    assert all(order.status == OrderStatus.FILLED for order in result.orders)
    assert not any("flatten" in order.client_order_id for order in result.orders)
    buy = next(order for order in result.orders if order.side == Side.BUY)
    buy_fill = next(fill for fill in result.fills if fill.order_id == buy.id)
    assert buy_fill.filled_at > buy.submitted_at
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["طلا"] > 0
    assert held["زر"] < 0
    assert strategy._current_pair == ("طلا", "زر")


def test_open_pair_fills_both_legs_with_zero_latency(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0)] * 8
    strategy = _bubble()
    result = _run_ranked(
        strategy,
        _ranked_snapshots(premiums),
        tmp_path,
        "instant.db",
        latency_ms=0,
    )
    assert [item["type"] for item in strategy.events] == ["enter_pair"]
    assert len(result.orders) == 2
    assert all(order.status == OrderStatus.FILLED for order in result.orders)
    buy = next(order for order in result.orders if order.side == Side.BUY)
    buy_fill = next(fill for fill in result.fills if fill.order_id == buy.id)
    assert buy_fill.filled_at == buy.submitted_at
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["طلا"] > 0
    assert held["زر"] < 0


def test_price_unavailable_second_leg_closes_the_filled_leg(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0)] + [(0.0, 0.0)] * 10
    strategy = _bubble()
    result = _run_ranked(
        strategy,
        _ranked_snapshots(premiums, blank_short_from=12),
        tmp_path,
        "unpriced.db",
        latency_ms=2500,
    )
    short = next(
        order
        for order in result.orders
        if order.symbol == "زر"
        and order.side == Side.SELL
        and "flatten" not in order.client_order_id
    )
    assert short.status == OrderStatus.REJECTED
    assert short.rejection_code == "price_unavailable"
    assert any(
        order.symbol == "طلا" and order.side == Side.BUY and order.status == OrderStatus.FILLED
        for order in result.orders
    )
    flats = [order for order in result.orders if "flatten" in order.client_order_id]
    assert len(flats) == 1
    assert flats[0].symbol == "طلا"
    assert flats[0].status == OrderStatus.FILLED
    assert strategy.events == []
    assert strategy._current_pair is None
    for position in result.portfolio.positions:
        assert position.quantity == 0


def test_cancelled_second_leg_closes_the_filled_leg(tmp_path):
    premiums = [(0.0, 0.0)] * 11 + [(-3.0, 3.0)] + [(0.0, 0.0)] * 10

    def _cancel_resting_short(kind, ctx):
        if kind != "tick":
            return
        for order in ctx.orders():
            if (
                order.symbol == "زر"
                and order.side == Side.SELL
                and order.status == OrderStatus.CREATED
            ):
                ctx.cancel_order(order.id)

    strategy = _bubble()
    result = _run_ranked(
        strategy,
        _ranked_snapshots(premiums),
        tmp_path,
        "cancel.db",
        latency_ms=2500,
        on_event=_cancel_resting_short,
    )
    short = next(
        order
        for order in result.orders
        if order.symbol == "زر"
        and order.side == Side.SELL
        and "flatten" not in order.client_order_id
    )
    assert short.status == OrderStatus.CANCELLED
    flats = [order for order in result.orders if "flatten" in order.client_order_id]
    assert len(flats) == 1
    assert flats[0].symbol == "طلا"
    assert flats[0].status == OrderStatus.FILLED
    assert strategy.events == []
    assert strategy._current_pair is None
    for position in result.portfolio.positions:
        assert position.quantity == 0
