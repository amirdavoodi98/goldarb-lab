from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

from goldarb.simulation import (
    LocalSimulator,
    MarketSnapshot,
    OrderStatus,
    Quote,
)


def snapshot(
    event_id: str,
    *,
    minute: int = 0,
    bid: str = "99",
    ask: str = "101",
    bid_size: str = "10",
    ask_size: str = "10",
) -> MarketSnapshot:
    return MarketSnapshot(
        event_id=event_id,
        timestamp=datetime(2026, 8, 26, 9, minute, tzinfo=UTC),
        quotes=(
            Quote(
                symbol="طلا",
                bid=Decimal(bid),
                ask=Decimal(ask),
                last=Decimal(100),
                bid_size=Decimal(bid_size),
                ask_size=Decimal(ask_size),
            ),
        ),
    )


def test_market_order_fee_portfolio_and_restart(tmp_path):
    path = tmp_path / "simulation.sqlite3"
    with LocalSimulator(path) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001", allow_short=False)
        sim.feed(snapshot("tick-1"))
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="2",
            client_order_id="buy-1",
        )
        assert order.status == OrderStatus.FILLED
        portfolio = sim.portfolio(account.id)
        assert portfolio.cash == Decimal("9797.798000")
        assert portfolio.fees_paid == Decimal("0.202000")
        assert portfolio.positions[0].quantity == Decimal("2.00000000")
        assert portfolio.positions[0].average_cost == Decimal(101)

    with LocalSimulator(path) as restored:
        portfolio = restored.portfolio(account.id)
        assert portfolio.cash == Decimal("9797.798000")
        assert len(restored.list_fills(account.id)) == 1


def test_storage_has_hot_path_indexes_and_normal_sync(tmp_path):
    path = tmp_path / "indexed.sqlite3"
    with LocalSimulator(path) as sim:
        sync_mode = sim._repo.connection.execute("PRAGMA synchronous").fetchone()[0]
        assert sync_mode == 1  # NORMAL

    with sqlite3.connect(path) as db:
        market_indexes = {row[1] for row in db.execute("PRAGMA index_list('market_events')")}
        equity_indexes = {row[1] for row in db.execute("PRAGMA index_list('equity_points')")}
    assert "sim_market_events_timestamp_idx" in market_indexes
    assert "sim_equity_points_history_idx" in equity_indexes


def test_limit_partial_fill_then_complete_and_idempotent_event(tmp_path):
    with LocalSimulator(tmp_path / "sim.db") as sim:
        account = sim.create_account(initial_cash="10000", allow_short=True)
        sim.feed(snapshot("tick-1", ask="105", ask_size="2"))
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="5",
            order_type="LIMIT",
            limit_price="102",
            client_order_id="limit-1",
        )
        assert order.status == OrderStatus.OPEN

        sim.feed(snapshot("tick-2", minute=1, ask="101", ask_size="2"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal("2.00000000")
        assert sim.feed(snapshot("tick-2", minute=1, ask="101", ask_size="2")) is False

        sim.feed(snapshot("tick-3", minute=2, ask="100", ask_size="3"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("5.00000000")
        assert len(sim.list_fills(account.id)) == 2


def test_short_policy_cancel_and_realized_pnl(tmp_path):
    with LocalSimulator(tmp_path / "sim.db") as sim:
        long_only = sim.create_account(initial_cash="10000", allow_short=False)
        shortable = sim.create_account(initial_cash="10000", allow_short=True)
        sim.feed(snapshot("tick-1", bid="100", ask="101"))

        rejected = sim.submit_order(long_only.id, symbol="طلا", side="SELL", quantity="1")
        assert rejected.status == OrderStatus.REJECTED

        sell = sim.submit_order(shortable.id, symbol="طلا", side="SELL", quantity="2")
        assert sell.status == OrderStatus.FILLED
        sim.feed(snapshot("tick-2", minute=1, bid="89", ask="90"))
        cover = sim.submit_order(shortable.id, symbol="طلا", side="BUY", quantity="2")
        assert cover.status == OrderStatus.FILLED
        portfolio = sim.portfolio(shortable.id)
        assert portfolio.positions[0].quantity == Decimal("0E-8")
        assert portfolio.realized_pnl == Decimal("20.00000000")

        pending = sim.submit_order(
            shortable.id,
            symbol="طلا",
            side="BUY",
            quantity="1",
            order_type="LIMIT",
            limit_price="80",
        )
        assert sim.cancel_order(shortable.id, pending.id).status == OrderStatus.CANCELLED


def test_snapshot_requires_monotonic_aware_time(tmp_path):
    with LocalSimulator(tmp_path / "sim.db") as sim:
        sim.create_account(initial_cash="100")
        sim.feed(snapshot("later", minute=2))
        earlier = snapshot("earlier", minute=1)
        try:
            sim.feed(earlier)
        except ValueError as exc:
            assert "monotonic" in str(exc)
        else:
            raise AssertionError("out-of-order snapshot was accepted")


def test_orders_share_depth_within_same_market_event(tmp_path):
    with LocalSimulator(tmp_path / "sim.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(snapshot("tick-1", ask_size="1"))
        first = sim.submit_order(account.id, symbol="طلا", side="BUY", quantity="1")
        second = sim.submit_order(account.id, symbol="طلا", side="BUY", quantity="1")
        assert first.status == OrderStatus.FILLED
        assert second.status == OrderStatus.CANCELLED
        assert second.filled_quantity == 0
