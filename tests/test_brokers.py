"""Broker wrappers for the lab paper simulator."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from goldarb.simulation import (
    AgahBroker,
    Broker,
    LocalSimulator,
    MarketSnapshot,
    MofidBroker,
    OrderStatus,
    PaperBroker,
    Quote,
    get_broker,
)
from goldarb.simulation.brokers import terms_for_fill
from goldarb.simulation.remote import RemoteSimulator
from goldarb.simulation.storage import SCHEMA_VERSION


def snapshot(event_id: str, *, minute: int = 0, ask: str = "101") -> MarketSnapshot:
    return MarketSnapshot(
        event_id=event_id,
        timestamp=datetime(2026, 8, 26, 9, minute, tzinfo=UTC),
        quotes=(
            Quote(
                symbol="طلا",
                bid=Decimal(100),
                ask=Decimal(ask),
                last=Decimal(100),
                bid_size=Decimal(10),
                ask_size=Decimal(10),
            ),
        ),
    )


def test_broker_abc_and_registry():
    assert Broker.__abstractmethods__ == {
        "cancel_order",
        "get_cash",
        "list_holdings",
        "list_orders",
        "submit_buy",
        "submit_sell",
    }
    with pytest.raises(TypeError):
        Broker()  # type: ignore[abstract]
    assert issubclass(PaperBroker, Broker)
    assert issubclass(AgahBroker, PaperBroker)
    assert issubclass(MofidBroker, PaperBroker)

    agah = get_broker("agah")
    mofid = get_broker(" MOFID ")
    assert isinstance(agah, AgahBroker)
    assert isinstance(mofid, MofidBroker)
    assert agah.code == "agah"
    assert mofid.code == "mofid"
    assert agah.display_name == "آگاه"
    assert mofid.display_name == "مفید"
    assert agah.fee_rate == Decimal("0.0005")
    assert mofid.fee_rate == Decimal("0.0005")
    assert agah.allow_short is False
    assert mofid.allow_short is False
    assert get_broker("agah") is not agah
    with pytest.raises(ValueError, match="unknown broker"):
        get_broker("dana")


def test_unbound_broker_cannot_trade():
    broker = get_broker("agah")
    with pytest.raises(RuntimeError, match="not bound"):
        broker.get_cash(account=None)  # type: ignore[arg-type]


def test_terms_follow_the_destination_broker():
    same = terms_for_fill(
        account_fee_rate=Decimal("0.001"),
        account_allow_short=True,
        account_broker="agah",
        order_broker="agah",
    )
    other = terms_for_fill(
        account_fee_rate=Decimal("0.001"),
        account_allow_short=True,
        account_broker="agah",
        order_broker="mofid",
    )
    assert same == (Decimal("0.001"), True)
    assert other == (Decimal("0.0005"), False)


def test_local_broker_buy_sell_cancel_holdings_and_cash(tmp_path):
    path = tmp_path / "brokers.sqlite3"
    broker = get_broker("agah")
    with LocalSimulator(path, broker=broker) as sim:
        account = sim.create_account(initial_cash="10000", label="agah book")
        assert account.broker == "agah"
        assert account.fee_rate == Decimal("0.0005")
        assert account.allow_short is False
        sim.feed(snapshot("tick-1"))

        bought = broker.submit_buy(
            account, symbol="طلا", quantity="2", client_order_id="buy-1"
        )
        assert bought.status == OrderStatus.FILLED
        assert bought.broker == "agah"
        assert broker.get_cash(account) == Decimal("9797.899000")
        holdings = broker.list_holdings(account)
        assert len(holdings) == 1
        assert holdings[0].symbol == "طلا"
        assert holdings[0].quantity == Decimal("2")

        sold = broker.submit_sell(
            account, symbol="طلا", quantity="1", client_order_id="sell-1"
        )
        assert sold.status == OrderStatus.FILLED
        assert sold.broker == "agah"
        assert broker.list_holdings(account)[0].quantity == Decimal("1")

        resting = broker.submit_buy(
            account,
            symbol="طلا",
            quantity="1",
            order_type="LIMIT",
            limit_price="90",
            client_order_id="rest-1",
        )
        assert resting.status == OrderStatus.ACCEPTED
        cancelled = broker.cancel_order(resting)
        assert cancelled.status == OrderStatus.CANCELLED
        assert cancelled.broker == "agah"
        orders = broker.list_orders(account)
        assert [order.broker for order in orders] == ["agah", "agah", "agah"]
        resting_row = next(order for order in orders if order.client_order_id == "rest-1")
        assert resting_row.status == OrderStatus.CANCELLED

    with LocalSimulator(path) as restored:
        reloaded = restored.get_account(account.id)
        assert reloaded.broker == "agah"
        assert restored.list_orders(account.id)[0].broker == "agah"
        version = restored._repo.connection.execute(
            "SELECT version FROM schema_meta"
        ).fetchone()["version"]
        assert version == SCHEMA_VERSION == 3


def test_explicit_fee_overrides_broker_but_other_broker_does_not(tmp_path):
    broker = get_broker("agah")
    with LocalSimulator(tmp_path / "fees.sqlite3", broker=broker) as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0.001")
        assert account.fee_rate == Decimal("0.001")
        assert account.allow_short is False
        sim.feed(snapshot("tick-1"))
        own = broker.submit_buy(account, symbol="طلا", quantity="2")
        assert own.broker == "agah"
        assert broker.get_cash(account) == Decimal("9797.798000")

        mofid = get_broker("mofid")
        mofid.attach(sim)
        shortable = sim.create_account(initial_cash="10000", allow_short=True)
        blocked = mofid.submit_sell(shortable, symbol="طلا", quantity="1")
        assert blocked.broker == "mofid"
        assert blocked.status == OrderStatus.REJECTED
        assert blocked.rejection_code == "short_disabled"


def test_schema_v1_upgrades_with_empty_broker_code(tmp_path):
    path = tmp_path / "legacy-v1.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER NOT NULL);
        INSERT INTO schema_meta(version) VALUES (1);
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            status TEXT NOT NULL,
            initial_cash TEXT NOT NULL,
            cash TEXT NOT NULL,
            fee_rate TEXT NOT NULL,
            allow_short INTEGER NOT NULL,
            fees_paid TEXT NOT NULL,
            last_market_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO accounts(
            id, label, status, initial_cash, cash, fee_rate,
            allow_short, fees_paid, created_at, updated_at
        ) VALUES (
            'acct-1', '', 'ACTIVE', '10', '10', '0.0005', 0, '0', 't', 't'
        );
        CREATE TABLE orders (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            client_order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity TEXT NOT NULL,
            filled_quantity TEXT NOT NULL,
            limit_price TEXT,
            status TEXT NOT NULL,
            rejection_code TEXT,
            submitted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, client_order_id)
        );
        INSERT INTO orders(
            id, account_id, client_order_id, symbol, side, order_type,
            quantity, filled_quantity, limit_price, status, submitted_at, updated_at
        ) VALUES (
            'order-1', 'acct-1', 'client-1', 'طلا', 'BUY', 'LIMIT',
            '1', '0', '90', 'OPEN', 't', 't'
        );
        CREATE TABLE fills (
            id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            market_event_id TEXT NOT NULL,
            quantity TEXT NOT NULL,
            price TEXT NOT NULL,
            fee TEXT NOT NULL,
            filled_at TEXT NOT NULL,
            UNIQUE(order_id, market_event_id)
        );
        """
    )
    connection.close()

    with LocalSimulator(path) as sim:
        account = sim.get_account("acct-1")
        assert account.broker == ""
        assert account.cash == Decimal(10)
        order = sim.list_orders("acct-1")[0]
        assert order.broker == ""
        assert order.status == OrderStatus.ACCEPTED
        version = sim._repo.connection.execute(
            "SELECT version FROM schema_meta"
        ).fetchone()["version"]
        assert version == 3


def test_schema_v2_upgrades_with_empty_broker_code(tmp_path):
    path = tmp_path / "legacy-v2.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE schema_meta (version INTEGER NOT NULL);
        INSERT INTO schema_meta(version) VALUES (2);
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            label TEXT NOT NULL,
            status TEXT NOT NULL,
            initial_cash TEXT NOT NULL,
            cash TEXT NOT NULL,
            fee_rate TEXT NOT NULL,
            allow_short INTEGER NOT NULL,
            fees_paid TEXT NOT NULL,
            last_market_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO accounts(
            id, label, status, initial_cash, cash, fee_rate,
            allow_short, fees_paid, created_at, updated_at
        ) VALUES (
            'acct-2', 'book', 'ACTIVE', '25', '25', '0.0005', 0, '0', 't', 't'
        );
        CREATE TABLE orders (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            client_order_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT NOT NULL,
            quantity TEXT NOT NULL,
            filled_quantity TEXT NOT NULL,
            limit_price TEXT,
            status TEXT NOT NULL,
            rejection_code TEXT,
            time_in_force TEXT NOT NULL DEFAULT 'DAY',
            avg_fill_price TEXT,
            submitted_at TEXT NOT NULL,
            created_at TEXT,
            accepted_at TEXT,
            closed_at TEXT,
            active_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(account_id, client_order_id)
        );
        INSERT INTO orders(
            id, account_id, client_order_id, symbol, side, order_type,
            quantity, filled_quantity, limit_price, status, time_in_force, submitted_at,
            created_at, active_at, updated_at
        ) VALUES (
            'order-2', 'acct-2', 'client-2', 'طلا', 'BUY', 'LIMIT',
            '1', '0', '90', 'ACCEPTED', 'DAY', 't', 't', 't', 't'
        );
        """
    )
    connection.close()

    with LocalSimulator(path) as sim:
        assert sim.get_account("acct-2").broker == ""
        assert sim.list_orders("acct-2")[0].broker == ""


class _RemoteHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def post_json(self, path: str, body: dict | None = None) -> dict:
        self.calls.append(("POST", path, body))
        if path.endswith("/cancel/"):
            payload = _order_body(
                {
                    "broker": "mofid",
                    "client_order_id": "buy-1",
                    "symbol": "طلا",
                    "side": "BUY",
                    "order_type": "LIMIT",
                    "quantity": "1",
                    "limit_price": "90",
                }
            )
            payload["status"] = "CANCELLED"
            return payload
        assert body is not None
        if path.endswith("/accounts/"):
            return _account_body(body)
        return _order_body(body)

    def get_json(self, path: str) -> dict:
        self.calls.append(("GET", path, None))
        if path.endswith("/orders/"):
            return {"results": []}
        if path.endswith("/fills/"):
            return {"results": []}
        if path.endswith("/portfolio/"):
            return {
                "account_id": "account-1",
                "cash": "10000",
                "equity": "10000",
                "fees_paid": "0",
                "realized_pnl": "0",
                "unrealized_pnl": "0",
                "positions": [
                    {
                        "symbol": "طلا",
                        "quantity": "1",
                        "average_cost": "101",
                        "realized_pnl": "0",
                        "mark_price": "100",
                        "unrealized_pnl": "-1",
                        "market_value": "100",
                    }
                ],
                "as_of": None,
            }
        return _account_body(
            {
                "initial_cash": "10000",
                "label": "remote",
                "fee_rate": "0.0005",
                "allow_short": False,
                "broker": "mofid",
            }
        )


def _account_body(body: dict) -> dict:
    return {
        "id": "account-1",
        "label": body.get("label") or "",
        "status": "ACTIVE",
        "initial_cash": body["initial_cash"],
        "cash": body["initial_cash"],
        "fee_rate": body["fee_rate"],
        "allow_short": body["allow_short"],
        "broker": body.get("broker") or "",
        "fees_paid": "0",
        "created_at": "2026-08-26T09:00:00+00:00",
        "updated_at": "2026-08-26T09:00:00+00:00",
    }


def _order_body(body: dict) -> dict:
    return {
        "id": "order-1",
        "account_id": "account-1",
        "client_order_id": body["client_order_id"],
        "symbol": body["symbol"],
        "side": body["side"],
        "order_type": body["order_type"],
        "quantity": body["quantity"],
        "filled_quantity": "0",
        "limit_price": body.get("limit_price"),
        "status": "OPEN",
        "broker": body.get("broker") or "",
        "submitted_at": "2026-08-26T09:00:00+00:00",
        "updated_at": "2026-08-26T09:00:00+00:00",
    }


def test_remote_client_sends_configured_broker():
    http = _RemoteHttp()
    broker = get_broker("mofid")
    remote = RemoteSimulator(http, broker=broker)  # type: ignore[arg-type]
    account = remote.create_account(initial_cash="10000", label="remote")
    assert account.broker == "mofid"
    assert account.fee_rate == Decimal("0.0005")
    assert account.allow_short is False
    order = broker.submit_buy(
        account,
        symbol="طلا",
        quantity="1",
        order_type="LIMIT",
        limit_price="90",
        client_order_id="buy-1",
    )
    assert order.broker == "mofid"
    listed = broker.list_orders(account)
    assert [item.id for item in listed] == [order.id]
    assert listed[0].broker == "mofid"
    assert broker.list_holdings(account)[0].symbol == "طلا"
    assert broker.get_cash(account) == Decimal(10000)
    assert broker.cancel_order(order).status == OrderStatus.CANCELLED
    posted = [call for call in http.calls if call[0] == "POST"]
    assert posted[0][2]["broker"] == "mofid"  # type: ignore[index]
    assert posted[0][2]["fee_rate"] == "0.0005"  # type: ignore[index]
    assert posted[0][2]["allow_short"] is False  # type: ignore[index]
    assert posted[1][2]["broker"] == "mofid"  # type: ignore[index]
