"""RemoteSimulator scenarios — server matches; client mirrors without local pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from goldarb.engine import SimulationLoop
from goldarb.execution import FixedSlippage, NoLatency, NoOpMarketIngress
from goldarb.simulation import OrderStatus, RemoteSimulator
from goldarb.simulation.inmemory_remote import InMemoryRemoteVenue
from goldarb.simulation.models import MarketSnapshot, Quote
from goldarb.strategy import Strategy, StrategyContext


class _Quiet(Strategy):
    name = "quiet"

    def on_market_data(self, ctx: StrategyContext) -> None:
        return None


def _venue(**kwargs) -> InMemoryRemoteVenue:
    venue = InMemoryRemoteVenue(**kwargs)
    venue.set_quote(
        Quote(
            symbol="طلا",
            bid=Decimal("99"),
            ask=Decimal("101"),
            last=Decimal("100"),
            bid_size=Decimal("10"),
            ask_size=Decimal("10"),
        )
    )
    return venue


def test_remote_order_submission_and_accepted():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    venue.set_quote(
        Quote(
            symbol="طلا",
            ask=Decimal("110"),
            bid=Decimal("100"),
            last=Decimal("105"),
            ask_size=Decimal("5"),
        )
    )
    order = remote.submit_order(
        account.id,
        symbol="طلا",
        side="BUY",
        quantity="2",
        order_type="LIMIT",
        limit_price="102",
        client_order_id="r1",
    )
    assert order.status == OrderStatus.ACCEPTED
    assert order.status == OrderStatus.OPEN
    assert remote.orders.get(order.id).status == OrderStatus.ACCEPTED


def test_remote_partial_and_full_fill():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    venue.set_quote(
        Quote(
            symbol="طلا",
            ask=Decimal("101"),
            bid=Decimal("99"),
            last=Decimal("100"),
            ask_size=Decimal("2"),
        )
    )
    order = remote.submit_order(
        account.id,
        symbol="طلا",
        side="BUY",
        quantity="5",
        order_type="LIMIT",
        limit_price="102",
        client_order_id="p1",
    )
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_quantity == Decimal("2.00000000")
    venue.set_quote(
        Quote(
            symbol="طلا",
            ask=Decimal("100"),
            bid=Decimal("99"),
            last=Decimal("100"),
            ask_size=Decimal("10"),
        )
    )
    venue.apply_market(
        MarketSnapshot(
            event_id="m2",
            timestamp=datetime(2026, 1, 1, 12, 1, tzinfo=UTC),
            quotes=(venue.quotes["طلا"],),
        )
    )
    remote.sync_account(account.id)
    order = remote.orders.get(order.id)
    assert order.status == OrderStatus.FILLED
    assert len(remote.list_fills(account.id)) == 2


def test_remote_rejection_insufficient_cash():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="0.0000001", fee_rate="0")
    order = remote.submit_order(
        account.id, symbol="طلا", side="BUY", quantity="10", client_order_id="poor"
    )
    assert order.status == OrderStatus.REJECTED
    assert order.rejection_code == "insufficient_cash"


def test_remote_cancellation_and_late_fill_race():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    venue.set_quote(
        Quote(symbol="طلا", ask=Decimal("110"), last=Decimal("110"), ask_size=Decimal("1"))
    )
    order = remote.submit_order(
        account.id,
        symbol="طلا",
        side="BUY",
        quantity="5",
        order_type="LIMIT",
        limit_price="102",
        client_order_id="race",
    )
    assert order.status == OrderStatus.ACCEPTED
    venue.set_quote(
        Quote(symbol="طلا", ask=Decimal("101"), last=Decimal("101"), ask_size=Decimal("2"))
    )
    cancelled = remote.cancel_order(account.id, order.id)
    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.filled_quantity == Decimal("2.00000000")
    assert len(remote.list_fills(account.id)) == 1


def test_duplicate_remote_fill_and_order_update_are_idempotent():
    venue = _venue(fee_rate=Decimal("0"), server_slippage=Decimal("1"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    order = remote.submit_order(
        account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="dup"
    )
    fills = remote.list_fills(account.id)
    assert len(fills) == 1
    fill = fills[0]
    assert remote.ingest_fill(fill) is False
    assert remote.ingest_order(order) is False
    assert len(remote.list_fills(account.id)) == 1
    assert remote.portfolio(account.id).fees_paid == venue.portfolio(account.id).fees_paid


def test_remote_fill_updates_portfolio_and_bakes_server_fee_slippage():
    venue = _venue(fee_rate=Decimal("0.01"), server_slippage=Decimal("2"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0.01")
    order = remote.submit_order(
        account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="fee"
    )
    assert order.status == OrderStatus.FILLED
    fill = remote.list_fills(account.id)[0]
    assert fill.raw_match_price == Decimal("101")
    assert fill.price == Decimal("103")
    assert fill.fee == Decimal("1.030000")
    port = remote.portfolio(account.id)
    assert port.fees_paid == fill.fee
    assert port.cash == Decimal("10000") - fill.price - fill.fee


def test_remote_feed_does_not_trigger_local_matching():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    venue.set_quote(
        Quote(symbol="طلا", ask=Decimal("110"), last=Decimal("110"), ask_size=Decimal("5"))
    )
    order = remote.submit_order(
        account.id,
        symbol="طلا",
        side="BUY",
        quantity="1",
        order_type="LIMIT",
        limit_price="102",
        client_order_id="nofeed",
    )
    assert order.status == OrderStatus.ACCEPTED
    snap = MarketSnapshot(
        event_id="local-feed",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        quotes=(
            Quote(symbol="طلا", ask=Decimal("100"), last=Decimal("100"), ask_size=Decimal("5")),
        ),
    )
    assert remote.feed(snap) is False
    remote.sync_account(account.id)
    assert remote.orders.get(order.id).status == OrderStatus.ACCEPTED
    assert remote.list_fills(account.id) == []


def test_noop_market_ingress_and_no_double_counting_in_loop():
    venue = _venue(fee_rate=Decimal("0"), server_slippage=Decimal("3"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    loop = SimulationLoop(
        broker=remote,
        account_id=account.id,
        strategy=_Quiet(),
        slippage=FixedSlippage("50"),
        latency=NoLatency(),
        execution=NoOpMarketIngress(),
    )
    snap = MarketSnapshot(
        event_id="tick",
        timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        quotes=(venue.quotes["طلا"],),
    )
    loop.process(snap)
    order = remote.submit_order(
        account.id, symbol="طلا", side="BUY", quantity="1", client_order_id="once"
    )
    fill = remote.list_fills(account.id)[0]
    assert order.status == OrderStatus.FILLED
    assert fill.price == Decimal("104")  # 101 + 3, not +50
    remote.sync_account(account.id)
    assert len(remote.list_fills(account.id)) == 1
    assert remote.portfolio(account.id).fees_paid == Decimal("0")


def test_deterministic_remote_event_ordering():
    venue = _venue(fee_rate=Decimal("0"))
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    for index in range(3):
        remote.submit_order(
            account.id,
            symbol="طلا",
            side="BUY",
            quantity="1",
            client_order_id=f"ord-{index}",
        )
    first_kinds = [item.split(":")[0] for item in venue.event_log if not item.startswith("account")]

    venue2 = _venue(fee_rate=Decimal("0"))
    remote2 = RemoteSimulator(venue2)
    account2 = remote2.create_account(initial_cash="10000", fee_rate="0")
    for index in range(3):
        remote2.submit_order(
            account2.id,
            symbol="طلا",
            side="BUY",
            quantity="1",
            client_order_id=f"ord-{index}",
        )
    second_kinds = [
        item.split(":")[0] for item in venue2.event_log if not item.startswith("account")
    ]
    assert first_kinds == second_kinds


def test_http_fake_remote_still_works():
    class FakeHttp:
        def __init__(self) -> None:
            self.calls: list = []

        def post_json(self, path: str, body: dict | None = None):
            self.calls.append(("POST", path, body))
            return {
                "id": "order-1",
                "account_id": "account-1",
                "client_order_id": body["client_order_id"],
                "symbol": body["symbol"],
                "side": body["side"],
                "order_type": body["order_type"],
                "quantity": body["quantity"],
                "filled_quantity": "1",
                "limit_price": body.get("limit_price"),
                "status": "FILLED",
                "submitted_at": "2026-08-26T09:00:00+00:00",
                "updated_at": "2026-08-26T09:00:00+00:00",
            }

        def get_json(self, path: str):
            if path.endswith("/fills/"):
                return {
                    "results": [
                        {
                            "id": "fill-1",
                            "order_id": "order-1",
                            "market_event_id": "m1",
                            "quantity": "1",
                            "price": "101",
                            "fee": "0",
                            "filled_at": "2026-08-26T09:00:00+00:00",
                        }
                    ]
                }
            if path.endswith("/orders/"):
                return {"results": []}
            raise AssertionError(path)

    http = FakeHttp()
    remote = RemoteSimulator(http)  # type: ignore[arg-type]
    order = remote.submit_order(
        "account-1",
        symbol="طلا",
        side="buy",
        quantity=1,
        client_order_id="client-1",
    )
    assert order.status == OrderStatus.FILLED
    assert len(remote.list_fills("account-1")) == 1
