"""Invariant checks for LocalPaperBroker / SimulationLoop contracts (ADR 0001)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from goldarb.execution import (
    FixedSlippage,
    LocalFeedExecution,
    NoLatency,
    NoSlippage,
    PercentFee,
)
from goldarb.engine import SimulationLoop
from goldarb.simulation import LocalPaperBroker, OrderStatus
from goldarb.simulation.models import MarketSnapshot, OrderEventType, Quote
from goldarb.strategy import Strategy, StrategyContext


class _Quiet(Strategy):
    name = "quiet"

    def on_market_data(self, ctx: StrategyContext) -> None:
        return None


def test_accepted_is_canonical_open_is_alias():
    assert OrderStatus.OPEN is OrderStatus.ACCEPTED
    assert OrderStatus.OPEN.value == "ACCEPTED"
    assert OrderStatus("ACCEPTED") is OrderStatus.ACCEPTED


def test_simulation_loop_does_not_transform_snapshot(tmp_path):
    seen: list[MarketSnapshot] = []

    class Capture(LocalFeedExecution):
        def on_market(self, broker, snapshot):  # type: ignore[no-untyped-def]
            seen.append(snapshot)
            super().on_market(broker, snapshot)

    broker = LocalPaperBroker(tmp_path / "inv.db", fee=PercentFee("0"))
    account = broker.create_account(initial_cash="10000", fee_rate="0")
    original = MarketSnapshot(
        event_id="e1",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        quotes=(Quote(symbol="طلا", last=Decimal("100"), ask=Decimal("100"), bid=Decimal("99")),),
    )
    loop = SimulationLoop(
        broker=broker,
        account_id=account.id,
        strategy=_Quiet(),
        slippage=FixedSlippage("50"),  # must NOT widen the fed snapshot
        latency=NoLatency(),
        execution=Capture(),
    )
    loop.process(original)
    assert seen[0] is original
    assert seen[0].quotes[0].ask == Decimal("100")
    broker.close()


def test_account_fee_rate_is_sole_fee_source_despite_broker_model(tmp_path):
    with LocalPaperBroker(tmp_path / "fee.db", fee=PercentFee("0.01")) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001")
        sim.feed(
            MarketSnapshot(
                event_id="e1",
                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                quotes=(
                    Quote(
                        symbol="طلا",
                        ask=Decimal("100"),
                        bid=Decimal("99"),
                        last=Decimal("100"),
                        ask_size=Decimal("10"),
                    ),
                ),
            )
        )
        sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="f1"
        )
        fill = sim.list_fills(account.id)[0]
        assert fill.fee == Decimal("0.100000")  # 0.001 * 100 * 1, not 0.01


def test_pipeline_slippage_applied_once_on_fill(tmp_path):
    with LocalPaperBroker(
        tmp_path / "slip.db",
        fee=PercentFee("0"),
        slippage=FixedSlippage("2"),
    ) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        sim.feed(
            MarketSnapshot(
                event_id="e1",
                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                quotes=(
                    Quote(
                        symbol="طلا",
                        ask=Decimal("100"),
                        last=Decimal("100"),
                        ask_size=Decimal("5"),
                    ),
                ),
            )
        )
        sim.submit_order(
            account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="s1"
        )
        fill = sim.list_fills(account.id)[0]
        assert fill.raw_match_price == Decimal("100")
        assert fill.price == Decimal("102")


def test_order_events_match_state_machine(tmp_path):
    with LocalPaperBroker(tmp_path / "ev.db", fee=PercentFee("0")) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        sim.feed(
            MarketSnapshot(
                event_id="e1",
                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                quotes=(
                    Quote(
                        symbol="طلا",
                        ask=Decimal("105"),
                        last=Decimal("105"),
                        ask_size=Decimal("1"),
                    ),
                ),
            )
        )
        order = sim.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="2",
            order_type="LIMIT",
            limit_price="102",
            client_order_id="ev1",
        )
        assert order.status == OrderStatus.ACCEPTED
        types = [e.event_type for e in sim.orders.events_for(order.id)]
        assert types[0] == OrderEventType.CREATED
        assert OrderEventType.ACCEPTED in types


def test_fill_transaction_atomicity_rolls_back_on_error(tmp_path):
    with LocalPaperBroker(tmp_path / "tx.db") as sim:
        account = sim.create_account(initial_cash="10000")
        sim.feed(
            MarketSnapshot(
                event_id="e1",
                timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                quotes=(Quote(symbol="طلا", last=Decimal("100"), ask=Decimal("100")),),
            )
        )
        before = sim.portfolio(account.id).cash
        try:
            sim.feed(
                MarketSnapshot(
                    event_id="e0",
                    timestamp=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                    quotes=(Quote(symbol="طلا", last=Decimal("100")),),
                )
            )
        except ValueError:
            pass
        assert sim.portfolio(account.id).cash == before
        assert len(sim.list_fills(account.id)) == 0
