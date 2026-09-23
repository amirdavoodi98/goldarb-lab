"""LocalPaperBroker / OrderManager / QuoteMatching integration scenarios."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from goldarb.execution import FixedLatency, FixedSlippage, NoFee, PercentFee
from goldarb.simulation import (
    DomainError,
    LocalPaperBroker,
    LocalSimulator,
    MarketSnapshot,
    OrderStatus,
    Quote,
)
from goldarb.simulation.matching import QuoteMatching
from goldarb.simulation.models import Order, OrderType, ProposedFill, Side
from goldarb.simulation.order_manager import OrderManager
from goldarb.simulation.pipeline import ExecutionPipeline
from goldarb.simulation.portfolio_service import LedgerState, PortfolioService


def snap(
    event_id: str,
    *,
    minute: int = 0,
    second: int = 0,
    bid: str = "99",
    ask: str = "101",
    bid_size: str = "10",
    ask_size: str = "10",
    last: str = "100",
) -> MarketSnapshot:
    return MarketSnapshot(
        event_id=event_id,
        timestamp=datetime(2026, 8, 26, 9, minute, second, tzinfo=UTC),
        quotes=(
            Quote(
                symbol="طلا",
                bid=Decimal(bid),
                ask=Decimal(ask),
                last=Decimal(last),
                bid_size=Decimal(bid_size),
                ask_size=Decimal(ask_size),
            ),
        ),
    )


def test_market_order_full_fill(tmp_path):
    with LocalPaperBroker(tmp_path / "a.db", fee=PercentFee("0.001")) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001")
        sim.feed(snap("t1"))
        order = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="2", client_order_id="c1"
        )
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("2.00000000")
        fills = sim.list_fills(account.id)
        assert len(fills) == 1
        assert fills[0].raw_match_price == Decimal("101")
        assert fills[0].price == Decimal("101")


def test_limit_order_rests_then_fills(tmp_path):
    with LocalSimulator(tmp_path / "b.db") as sim:
        account = sim.create_account(initial_cash="10000", allow_short=True)
        sim.feed(snap("t1", ask="105", ask_size="2"))
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="5",
            order_type="LIMIT",
            limit_price="102",
            client_order_id="limit-1",
        )
        assert order.status == OrderStatus.ACCEPTED
        assert order.status == OrderStatus.OPEN  # legacy alias
        sim.feed(snap("t2", minute=1, ask="101", ask_size="2"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.PARTIALLY_FILLED
        assert order.filled_quantity == Decimal("2.00000000")


def test_partial_and_multiple_fills(tmp_path):
    with LocalPaperBroker(tmp_path / "c.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(snap("t1", ask="101", ask_size="2"))
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="5",
            order_type="LIMIT",
            limit_price="102",
            client_order_id="m1",
        )
        assert order.status == OrderStatus.PARTIALLY_FILLED
        sim.feed(snap("t2", minute=1, ask="100", ask_size="3"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.FILLED
        assert len(sim.list_fills(account.id)) == 2
        assert order.avg_fill_price is not None


def test_insufficient_cash_rejects_market(tmp_path):
    with LocalPaperBroker(tmp_path / "d.db", fee=NoFee()) as sim:
        # Below one quantity quantum at ask=101 → zero fillable size.
        account = sim.create_account(initial_cash="0.0000001", fee_rate="0")
        sim.feed(snap("t1", ask="101", ask_size="10"))
        order = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="10", client_order_id="poor"
        )
        assert order.status == OrderStatus.REJECTED
        assert order.rejection_code == "insufficient_cash"
        assert order.filled_quantity == Decimal("0")


def test_cancel_and_cancel_race_late_fill(tmp_path):
    with LocalPaperBroker(tmp_path / "e.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(snap("t1", ask="105", ask_size="1"))
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="5",
            order_type="LIMIT",
            limit_price="102",
            client_order_id="race",
        )
        assert order.status == OrderStatus.ACCEPTED
        pending = sim.cancel_order(account.id, order.id, confirm=False)
        assert pending.status == OrderStatus.CANCEL_PENDING
        # Late fill while cancel pending
        sim.feed(snap("t2", minute=1, ask="101", ask_size="2"))
        order = sim.get_order(account.id, order.id)
        assert order.filled_quantity == Decimal("2.00000000")
        # Remainder cancelled on same feed after match attempt
        assert order.status in {OrderStatus.CANCELLED, OrderStatus.PARTIALLY_FILLED, OrderStatus.CANCEL_PENDING}
        if order.status == OrderStatus.CANCEL_PENDING:
            sim.feed(snap("t3", minute=2, ask="110", ask_size="1"))
            order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.CANCELLED
        assert order.filled_quantity == Decimal("2.00000000")


def test_idempotent_submit(tmp_path):
    with LocalPaperBroker(tmp_path / "f.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(snap("t1"))
        first = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="same"
        )
        second = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="same"
        )
        assert first.id == second.id
        assert len(sim.list_orders(account.id)) == 1


def test_submit_latency_delays_activation(tmp_path):
    with LocalPaperBroker(
        tmp_path / "g.db",
        latency=FixedLatency(milliseconds=60_000),
        fee=NoFee(),
    ) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        sim.feed(snap("t1", ask="101"))
        order = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="late"
        )
        assert order.status == OrderStatus.CREATED
        # Still within latency window
        sim.feed(snap("t2", minute=0, second=30, ask="102"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.CREATED
        assert len(sim.list_fills(account.id)) == 0
        # Past active_at
        sim.feed(snap("t3", minute=1, second=1, ask="103"))
        order = sim.get_order(account.id, order.id)
        assert order.status == OrderStatus.FILLED
        assert sim.list_fills(account.id)[0].raw_match_price == Decimal("103")


def test_slippage_and_fee_on_fill_price(tmp_path):
    with LocalPaperBroker(
        tmp_path / "h.db",
        fee=PercentFee("0.01"),
        slippage=FixedSlippage("1"),
    ) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.01")
        sim.feed(snap("t1", ask="100", ask_size="5"))
        order = sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="slip"
        )
        assert order.status == OrderStatus.FILLED
        fill = sim.list_fills(account.id)[0]
        assert fill.raw_match_price == Decimal("100")
        assert fill.price == Decimal("101")
        assert fill.fee == Decimal("1.010000")  # 1% of 101


def test_portfolio_update_and_restart(tmp_path):
    path = tmp_path / "i.db"
    with LocalPaperBroker(path, fee=PercentFee("0.001")) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001")
        sim.feed(snap("t1"))
        sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="2", client_order_id="p1"
        )
        portfolio = sim.portfolio(account.id)
        cash = portfolio.cash
        assert portfolio.positions[0].quantity == Decimal("2.00000000")

    with LocalPaperBroker(path) as restored:
        assert restored.portfolio(account.id).cash == cash
        assert len(restored.list_fills(account.id)) == 1


def test_transaction_rollback_on_error(tmp_path):
    with LocalPaperBroker(tmp_path / "j.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(snap("t1"))
        with pytest.raises(ValueError):
            sim.feed(
                MarketSnapshot(
                    event_id="bad",
                    timestamp=datetime(2026, 8, 26, 8, 0, tzinfo=UTC),  # non-monotonic
                    quotes=snap("x").quotes,
                )
            )
        assert sim.portfolio(account.id).cash == Decimal("10000")


def test_order_manager_invalid_transition():
    manager = OrderManager()
    order = manager.create(
        account_id="a",
        symbol="طلا",
        side=Side.BUY,
        quantity="1",
        submitted_at="2026-01-01T00:00:00+00:00",
    )
    manager.accept(order.id, at="2026-01-01T00:00:01+00:00")
    manager.confirm_cancel(order.id, at="2026-01-01T00:00:02+00:00")
    with pytest.raises(DomainError):
        manager.accept(order.id, at="2026-01-01T00:00:03+00:00")


def test_pipeline_unit_match_slip_fee():
    matching = QuoteMatching()
    pipeline = ExecutionPipeline(
        matching,
        slippage=FixedSlippage("2"),
        fee=PercentFee("0"),
    )
    order = Order(
        id="o1",
        account_id="a",
        client_order_id="c",
        symbol="طلا",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        filled_quantity=Decimal("0"),
        limit_price=None,
        status=OrderStatus.ACCEPTED,
        submitted_at="t",
        updated_at="t",
    )
    quote = Quote(symbol="طلا", ask=Decimal("100"), bid=Decimal("99"), last=Decimal("100"), ask_size=Decimal("5"))
    result = pipeline.run(
        order,
        quote=quote,
        available_depth=Decimal("5"),
        ledger=LedgerState(cash=Decimal("10000"), fees_paid=Decimal("0"), positions={}),
        allow_short=False,
        market_event_id="e1",
        market_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert result.fills[0].fill.raw_match_price == Decimal("100")
    assert result.fills[0].fill.price == Decimal("102")


def test_deterministic_backtest_replay(tmp_path):
    def run_once(path):
        with LocalPaperBroker(path, fee=NoFee()) as sim:
            account = sim.create_account(initial_cash="10000", fee_rate="0", account_id="fixed")
            sim.feed(snap("t1", ask="101", ask_size="3"))
            sim.submit_order(
                account.id,
                symbol="طلا",
                side="BUY",
                quantity="2",
                client_order_id="d1",
            )
            sim.feed(snap("t2", minute=1, bid="98", bid_size="2"))
            sim.submit_order(
                account.id,
                symbol="طلا",
                side="SELL",
                quantity="2",
                client_order_id="d2",
            )
            return sim.portfolio(account.id).cash, [f.price for f in sim.list_fills(account.id)]

    first = run_once(tmp_path / "d1.db")
    second = run_once(tmp_path / "d2.db")
    assert first == second
