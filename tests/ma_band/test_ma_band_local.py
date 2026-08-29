"""Offline MA-band strategy tests against LocalSimulator."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from ma_band import (
    ma_band_side,
    run_ma_band,
    snapshots_from_bars,
    snapshots_from_closes,
)

from goldarb.simulation import LocalSimulator, OrderStatus, Side

ARCHIVE = Path(__file__).resolve().parents[2] / "archive" / "fund_bars_1m" / "طلا.jsonl"

# window=3, band=2%:
# t0-t2 warmup at 100
# t3 close 97 < SMA 99 * 0.98 → BUY @ 97
# t5 close 103 > SMA 99 * 1.02 → SELL @ 103
ROUND_TRIP = ("100", "100", "100", "97", "97", "103")


def test_signal_thresholds():
    sma = Decimal("100")
    band = {"buy_band": Decimal("0.02"), "sell_band": Decimal("0.02")}
    assert ma_band_side(Decimal("97"), sma, **band) == Side.BUY
    assert ma_band_side(Decimal("103"), sma, **band) == Side.SELL
    assert ma_band_side(Decimal("100"), sma, **band) is None


def test_round_trip_fills_portfolio_and_pnl(tmp_path):
    snapshots = snapshots_from_closes(ROUND_TRIP)
    with LocalSimulator(tmp_path / "ma.db") as sim:
        account = sim.create_account(
            initial_cash="10000",
            fee_rate="0",
            allow_short=False,
            label="ma-band-round-trip",
        )
        result = run_ma_band(snapshots, simulator=sim, account_id=account.id)

    assert [signal.side for signal in result.signals] == [Side.BUY, Side.SELL]
    assert [order.status for order in result.orders] == [OrderStatus.FILLED, OrderStatus.FILLED]
    assert [fill.price for fill in result.fills] == [Decimal("97"), Decimal("103")]
    assert [fill.quantity for fill in result.fills] == [Decimal("10"), Decimal("10")]
    assert result.portfolio.cash == Decimal("10060")
    assert result.portfolio.realized_pnl == Decimal("60")
    assert result.portfolio.fees_paid == Decimal("0")
    assert result.portfolio.equity == Decimal("10060")
    held = next((p.quantity for p in result.portfolio.positions if p.symbol == "طلا"), Decimal(0))
    assert held == 0
    assert len(sim_equity_if_closed(tmp_path / "ma.db", account.id)) == len(ROUND_TRIP)


def sim_equity_if_closed(path: Path, account_id: str) -> list:
    with LocalSimulator(path) as restored:
        return restored.equity_history(account_id)


def test_no_trade_inside_band(tmp_path):
    snapshots = snapshots_from_closes(("100", "100.5", "100.2", "99.8"))
    with LocalSimulator(tmp_path / "flat.db") as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        result = run_ma_band(snapshots, simulator=sim, account_id=account.id)
    assert result.signals == []
    assert result.orders == []
    assert result.portfolio.cash == Decimal("10000")
    assert result.portfolio.equity == Decimal("10000")


def test_long_only_skips_sell_while_flat(tmp_path):
    snapshots = snapshots_from_closes(("100", "110", "120"))
    with LocalSimulator(tmp_path / "long-only.db") as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0", allow_short=False)
        result = run_ma_band(
            snapshots,
            simulator=sim,
            account_id=account.id,
            window=2,
        )
    assert result.signals == []
    assert result.orders == []


def test_fees_are_taken_from_cash(tmp_path):
    snapshots = snapshots_from_closes(ROUND_TRIP)
    with LocalSimulator(tmp_path / "fees.db") as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001", allow_short=False)
        result = run_ma_band(snapshots, simulator=sim, account_id=account.id)
    assert result.portfolio.fees_paid == Decimal("2.000000")
    assert result.portfolio.cash == Decimal("10058.000000")
    assert result.portfolio.realized_pnl == Decimal("60")


def test_replay_is_idempotent(tmp_path):
    snapshots = snapshots_from_closes(ROUND_TRIP)
    path = tmp_path / "replay.db"
    with LocalSimulator(path) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        first = run_ma_band(snapshots, simulator=sim, account_id=account.id)
        second = run_ma_band(snapshots, simulator=sim, account_id=account.id)
    assert [order.id for order in first.orders] == [order.id for order in second.orders]
    assert len(second.fills) == 2
    assert second.portfolio.cash == Decimal("10060")


def test_restart_keeps_account_and_can_finish_round_trip(tmp_path):
    snapshots = snapshots_from_closes(ROUND_TRIP)
    path = tmp_path / "restart.db"
    with LocalSimulator(path) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0", allow_short=False)
        run_ma_band(snapshots[:4], simulator=sim, account_id=account.id)
        mid = sim.portfolio(account.id)
        assert mid.positions[0].quantity == Decimal("10")
        account_id = account.id

    with LocalSimulator(path) as sim:
        restored = sim.portfolio(account_id)
        assert restored.positions[0].quantity == Decimal("10")
        replay = run_ma_band(snapshots, simulator=sim, account_id=account_id)

    assert replay.portfolio.cash == Decimal("10060")
    assert replay.portfolio.realized_pnl == Decimal("60")
    assert len(replay.fills) == 2
    held = next((p.quantity for p in replay.portfolio.positions if p.symbol == "طلا"), Decimal(0))
    assert held == 0


@pytest.mark.skipif(not ARCHIVE.exists(), reason="local طلا 1m archive is missing")
def test_archive_bars_drive_local_simulator(tmp_path):
    bars: list[dict] = []
    with ARCHIVE.open(encoding="utf-8") as handle:
        for line in handle:
            bars.append(json.loads(line))
            if len(bars) >= 180:
                break
    snapshots = snapshots_from_bars(bars)
    assert len(snapshots) >= 180
    with LocalSimulator(tmp_path / "archive.db") as sim:
        account = sim.create_account(
            initial_cash="1000000000",
            fee_rate="0.0005",
            allow_short=False,
            label="ma-band-archive",
        )
        result = run_ma_band(
            snapshots,
            simulator=sim,
            account_id=account.id,
            window=10,
            buy_band="0.002",
            sell_band="0.002",
            quantity="1",
        )
        history = sim.equity_history(account.id)

    assert result.portfolio.equity > 0
    assert result.portfolio.cash > 0
    assert result.portfolio.fees_paid >= 0
    assert len(history) == len(snapshots)
    assert all(order.status in OrderStatus for order in result.orders)
    cash = result.portfolio.cash
    market_value = sum((p.market_value for p in result.portfolio.positions), Decimal(0))
    assert result.portfolio.equity == cash + market_value
