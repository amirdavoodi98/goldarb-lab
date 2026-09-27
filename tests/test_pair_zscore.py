"""Pair z-score math and 1s BacktestEngine rotation over the full universe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldarb import BacktestEngine, PairZScoreStrategy, RunConfig
from goldarb.data import HistoricalDataProvider, cross_section_1s
from goldarb.execution import FixedLatency, PercentFee
from goldarb.signals.pair_spread import compute_pair_spread_stats
from goldarb.simulation import LocalSimulator, MarketSnapshot, OrderStatus, Quote, Side
from goldarb.universe import GOLD_FUND_SYMBOLS


def _pair_bars(premiums: list[tuple[float, float]]):
    tala = [prem_a for prem_a, _ in premiums]
    zar = [prem_b for _, prem_b in premiums]
    return cross_section_1s(len(premiums), premiums={"طلا": tala, "زر": zar})


def _run(strategy, bars, tmp_path, name):
    return BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_cross_section(bars),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / name),
        fee=PercentFee("0"),
    )


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
    bars = _pair_bars(premiums)
    snapshots = list(HistoricalDataProvider.from_cross_section(bars).events())
    assert all(
        {quote.symbol for quote in snapshot.quotes} == set(GOLD_FUND_SYMBOLS)
        for snapshot in snapshots
    )
    strategy = PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=30,
        min_samples=10,
        z_threshold=2.0,
        capital_per_side="100000",
    )
    result = _run(strategy, bars, tmp_path, "zshort.db")
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
    bars = _pair_bars(premiums)
    snapshots = list(HistoricalDataProvider.from_cross_section(bars).events())
    assert (snapshots[1].timestamp - snapshots[0].timestamp) == timedelta(seconds=1)
    assert {quote.symbol for quote in snapshots[0].quotes} == set(GOLD_FUND_SYMBOLS)
    strategy = PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=20,
        min_samples=10,
        z_threshold=1.5,
        capital_per_side="100000",
    )
    result = _run(strategy, bars, tmp_path, "zscore.db")
    assert strategy.last_status == "ok"
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    sides = {(order.symbol, order.side) for order in result.orders}
    assert ("زر", Side.BUY) in sides
    assert ("طلا", Side.SELL) in sides
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["زر"] > 0
    assert held["طلا"] < 0


def test_spread_uses_same_snapshot_not_index_zip(tmp_path):
    tala = [0.0] * 10 + [20.0] * 10 + [0.0]
    zar = [0.0] * 21
    bars = cross_section_1s(21, premiums={"طلا": tala, "زر": zar})
    for index in range(10, 20):
        del bars[index][1]["زر"]
    strategy = PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=30,
        min_samples=10,
        z_threshold=1.5,
        capital_per_side="100000",
    )
    result = _run(strategy, bars, tmp_path, "align.db")
    assert strategy._spread_series() == [0.0] * 11
    assert strategy.events == []
    assert result.orders == []


def _zscore_snapshots(premiums: list[tuple[float, float]]) -> list[MarketSnapshot]:
    origin = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    snapshots: list[MarketSnapshot] = []
    for index, (prem_a, prem_b) in enumerate(premiums):
        timestamp = origin + timedelta(seconds=index)
        snapshots.append(
            MarketSnapshot(
                event_id=f"z:{index}",
                timestamp=timestamp,
                quotes=(
                    Quote(symbol="طلا", last=Decimal("20000"), premium=Decimal(str(prem_a))),
                    Quote(symbol="زر", last=Decimal("10000"), premium=Decimal(str(prem_b))),
                ),
            )
        )
    return snapshots


def _hot_spreads() -> list[tuple[float, float]]:
    premiums = [(0.0, 0.0)] * 15
    for index in range(12):
        delta = float(index)
        premiums.append((5.0 + delta, -5.0 - delta))
    return premiums


def _run_zscore(strategy, snapshots, tmp_path, name, *, latency_ms: int):
    return BacktestEngine().run(
        strategy,
        HistoricalDataProvider(snapshots),
        RunConfig(
            strategy_name="pair_zscore",
            initial_cash="1000000",
            allow_short=True,
        ),
        simulator=LocalSimulator(tmp_path / name),
        fee=PercentFee("0"),
        latency=FixedLatency(latency_ms),
    )


def _zscore():
    return PairZScoreStrategy(
        fund_a="طلا",
        fund_b="زر",
        window_days=20,
        min_samples=10,
        z_threshold=1.5,
        capital_per_side="100000",
    )


def test_open_pair_fills_on_a_later_tick_when_latency_is_set(tmp_path):
    strategy = _zscore()
    result = _run_zscore(
        strategy,
        _zscore_snapshots(_hot_spreads()),
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
    assert held["زر"] > 0
    assert held["طلا"] < 0


def test_open_pair_fills_both_legs_with_zero_latency(tmp_path):
    strategy = _zscore()
    result = _run_zscore(
        strategy,
        _zscore_snapshots(_hot_spreads()),
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
    assert held["زر"] > 0
    assert held["طلا"] < 0
