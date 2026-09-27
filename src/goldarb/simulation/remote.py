"""Remote paper broker: server matches; client mirrors orders/fills without local matching."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from .._http import LabHttp
from .brokers import Broker, resolve_broker
from .models import (
    Account,
    Fill,
    Order,
    OrderEvent,
    OrderEventType,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
    TimeInForce,
    decimal_value,
)
from .order_manager import OrderManager
from .remote_venue import RemoteVenue


class HttpRemoteVenue:
    """Adapter over the Lab HTTP simulation API."""

    def __init__(self, http: LabHttp) -> None:
        self._http = http

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
        broker: str | None = None,
    ) -> Account:
        body: dict[str, Any] = {
            "initial_cash": str(decimal_value(initial_cash)),
            "label": label,
            "fee_rate": str(decimal_value(fee_rate)),
            "allow_short": allow_short,
        }
        if broker:
            body["broker"] = broker
        payload = self._http.post_json("/api/v1/simulation/accounts/", body)
        return account_from_payload(payload)

    def get_account(self, account_id: str) -> Account:
        return account_from_payload(
            self._http.get_json(f"/api/v1/simulation/accounts/{account_id}/")
        )

    def list_accounts(self) -> list[Account]:
        payload = self._http.get_json("/api/v1/simulation/accounts/")
        return [account_from_payload(item) for item in payload.get("results", [])]

    def stop_account(self, account_id: str) -> Account:
        return account_from_payload(
            self._http.delete_json(f"/api/v1/simulation/accounts/{account_id}/")
        )

    def submit_order(
        self,
        account_id: str,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        broker: str | None = None,
    ) -> Order:
        body: dict[str, Any] = {
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "symbol": symbol,
            "side": Side(str(side).upper()).value,
            "quantity": str(decimal_value(quantity)),
            "order_type": OrderType(str(order_type).upper()).value,
        }
        if broker:
            body["broker"] = broker
        if limit_price is not None:
            body["limit_price"] = str(decimal_value(limit_price))
        return order_from_payload(
            self._http.post_json(
                f"/api/v1/simulation/accounts/{account_id}/orders/", body
            )
        )

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        return order_from_payload(
            self._http.post_json(
                f"/api/v1/simulation/accounts/{account_id}/orders/{order_id}/cancel/"
            )
        )

    def list_orders(self, account_id: str) -> list[Order]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/orders/"
        )
        return [order_from_payload(item) for item in payload.get("results", [])]

    def list_fills(self, account_id: str) -> list[Fill]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/fills/"
        )
        return [fill_from_payload(item) for item in payload.get("results", [])]

    def portfolio(self, account_id: str) -> Portfolio:
        return portfolio_from_payload(
            self._http.get_json(
                f"/api/v1/simulation/accounts/{account_id}/portfolio/"
            )
        )

    def equity_history(self, account_id: str) -> list[dict[str, Any]]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/equity/"
        )
        return list(payload.get("results", []))


class RemoteSimulator:
    """Broker facade for remote matching — never runs local MatchingEngine."""

    def __init__(
        self,
        venue: RemoteVenue | LabHttp | Any,
        broker: Broker | str | None = None,
    ) -> None:
        if isinstance(venue, HttpRemoteVenue):
            self._venue: RemoteVenue = venue
        elif isinstance(venue, LabHttp) or (
            hasattr(venue, "post_json") and hasattr(venue, "get_json")
        ):
            self._venue = HttpRemoteVenue(venue)  # type: ignore[arg-type]
        else:
            self._venue = venue  # type: ignore[assignment]
        self.broker: Broker | None = None
        if broker is not None:
            self.bind(broker)
        self.orders = OrderManager()
        self._seen_fill_ids: set[str] = set()
        self._seen_order_versions: set[tuple[str, str, str, str]] = set()
        self._ingest_log: list[str] = []

    @property
    def venue(self) -> RemoteVenue:
        return self._venue

    def bind(self, broker: Broker | str) -> Broker:
        """Use this broker as the destination for accounts created afterwards."""
        resolved = resolve_broker(broker)
        if resolved is None:
            raise ValueError("unknown broker: ")
        self.broker = resolved
        resolved.attach(self)
        return resolved

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str | None = None,
        allow_short: bool | None = None,
        broker: Broker | str | None = None,
    ) -> Account:
        chosen = resolve_broker(broker)
        if chosen is None:
            chosen = self.broker
        if fee_rate is None and chosen is not None:
            fee = chosen.fee_rate
        elif fee_rate is None:
            fee = decimal_value("0.0005")
        else:
            fee = decimal_value(fee_rate)
        short = (
            chosen.allow_short
            if chosen is not None and allow_short is None
            else bool(allow_short)
        )
        extra: dict[str, Any] = {}
        if chosen is not None:
            extra["broker"] = chosen.code
        return self._venue.create_account(
            initial_cash=initial_cash,
            label=label,
            fee_rate=fee,
            allow_short=short,
            **extra,
        )

    def get_account(self, account_id: str) -> Account:
        return self._venue.get_account(account_id)

    def list_accounts(self) -> list[Account]:
        list_fn = getattr(self._venue, "list_accounts", None)
        if list_fn is None:
            raise AttributeError("venue does not support list_accounts")
        return list_fn()

    def stop_account(self, account_id: str) -> Account:
        stop_fn = getattr(self._venue, "stop_account", None)
        if stop_fn is None:
            raise AttributeError("venue does not support stop_account")
        return stop_fn(account_id)

    def submit_order(
        self,
        account_id: str,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        broker: Broker | str | None = None,
    ) -> Order:
        destination = resolve_broker(broker)
        extra: dict[str, Any] = {}
        if destination is not None:
            extra["broker"] = destination.code
        remote = self._venue.submit_order(
            account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
            **extra,
        )
        self.ingest_order(remote)
        self.sync_fills(account_id)
        return self.orders.get(remote.id)

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        remote = self._venue.cancel_order(account_id, order_id)
        self.ingest_order(remote)
        self.sync_fills(account_id)
        return self.orders.get(remote.id)

    def list_orders(self, account_id: str) -> list[Order]:
        remotes = self._venue.list_orders(account_id)
        for order in remotes:
            self.ingest_order(order)
        return self.orders.list_for_account(account_id)

    def list_fills(self, account_id: str) -> list[Fill]:
        self.sync_fills(account_id)
        return self.orders.fills_for_account(account_id)

    def portfolio(self, account_id: str) -> Portfolio:
        # Source of truth is the remote venue (fees/slippage already applied server-side).
        return self._venue.portfolio(account_id)

    def equity_history(self, account_id: str) -> list[dict[str, Any]]:
        return self._venue.equity_history(account_id)

    def feed(self, snapshot: Any) -> bool:
        """Remote venues do not match on local market feed."""
        del snapshot
        return False

    def sync_fills(self, account_id: str) -> list[Fill]:
        """Pull fills from the venue and ingest new ones idempotently."""
        fresh: list[Fill] = []
        for fill in self._venue.list_fills(account_id):
            if self.ingest_fill(fill):
                fresh.append(fill)
        return fresh

    def ingest_order(self, order: Order) -> bool:
        """Mirror a remote order snapshot. Returns False if duplicate noop."""
        version = (
            order.id,
            order.status.value,
            str(order.filled_quantity),
            order.updated_at,
        )
        if version in self._seen_order_versions:
            return False
        self._seen_order_versions.add(version)
        existing = self.orders._orders.get(order.id)
        fills = list(self.orders._fills.get(order.id, []))
        self.orders.restore(order, fills)
        if existing is None:
            self._record_mirror_event(order, OrderEventType.CREATED)
            if order.status == OrderStatus.ACCEPTED:
                self._record_mirror_event(order, OrderEventType.ACCEPTED)
            elif order.status == OrderStatus.REJECTED:
                self._record_mirror_event(order, OrderEventType.REJECTED)
            elif order.status == OrderStatus.CANCELLED:
                self._record_mirror_event(order, OrderEventType.CANCELLED)
            elif order.status == OrderStatus.FILLED:
                self._record_mirror_event(order, OrderEventType.ACCEPTED)
        elif existing.status != order.status:
            event_type = {
                OrderStatus.ACCEPTED: OrderEventType.ACCEPTED,
                OrderStatus.REJECTED: OrderEventType.REJECTED,
                OrderStatus.CANCELLED: OrderEventType.CANCELLED,
                OrderStatus.EXPIRED: OrderEventType.EXPIRED,
                OrderStatus.CANCEL_PENDING: OrderEventType.CANCEL_REQUESTED,
                OrderStatus.FILLED: OrderEventType.FILL,
                OrderStatus.PARTIALLY_FILLED: OrderEventType.FILL,
            }.get(order.status)
            if event_type is not None:
                self._record_mirror_event(order, event_type)
        self._ingest_log.append(f"order:{order.id}:{order.status.value}")
        return True

    def ingest_fill(self, fill: Fill) -> bool:
        """Record a remote fill idempotently without local re-pricing or re-matching."""
        if fill.id in self._seen_fill_ids:
            return False
        self._seen_fill_ids.add(fill.id)
        bucket = self.orders._fills.setdefault(fill.order_id, [])
        if any(item.id == fill.id for item in bucket):
            return False
        bucket.append(fill)
        self._ingest_log.append(f"fill:{fill.id}")
        return True

    def sync_account(self, account_id: str) -> None:
        for order in self._venue.list_orders(account_id):
            self.ingest_order(order)
        self.sync_fills(account_id)

    def _record_mirror_event(self, order: Order, event_type: OrderEventType) -> None:
        self.orders._events.append(
            OrderEvent(
                id=str(uuid.uuid4()),
                order_id=order.id,
                event_type=event_type,
                timestamp=order.updated_at,
                payload={"source": "remote"},
            )
        )


def account_from_payload(item: dict[str, Any]) -> Account:
    return Account(
        id=str(item["id"]),
        label=str(item.get("label") or ""),
        status=str(item["status"]),
        initial_cash=decimal_value(item["initial_cash"]),
        cash=decimal_value(item["cash"]),
        fee_rate=decimal_value(item["fee_rate"]),
        allow_short=bool(item["allow_short"]),
        fees_paid=decimal_value(item["fees_paid"]),
        created_at=str(item["created_at"]),
        updated_at=str(item["updated_at"]),
        broker=str(item.get("broker") or item.get("broker_code") or ""),
    )


def order_from_payload(item: dict[str, Any]) -> Order:
    status_raw = str(item["status"])
    status = (
        OrderStatus.ACCEPTED if status_raw == "OPEN" else OrderStatus(status_raw)
    )
    return Order(
        id=str(item["id"]),
        account_id=str(item["account_id"]),
        client_order_id=str(item["client_order_id"]),
        symbol=str(item["symbol"]),
        side=Side(item["side"]),
        order_type=OrderType(item["order_type"]),
        quantity=decimal_value(item["quantity"]),
        filled_quantity=decimal_value(item["filled_quantity"]),
        limit_price=(
            None
            if item.get("limit_price") is None
            else decimal_value(item["limit_price"])
        ),
        status=status,
        submitted_at=str(item["submitted_at"]),
        updated_at=str(item["updated_at"]),
        broker=str(item.get("broker") or item.get("broker_code") or ""),
        time_in_force=TimeInForce(str(item.get("time_in_force") or "DAY")),
        rejection_code=item.get("rejection_code"),
        avg_fill_price=(
            None
            if item.get("avg_fill_price") is None
            else decimal_value(item["avg_fill_price"])
        ),
        created_at=item.get("created_at") or str(item["submitted_at"]),
        accepted_at=item.get("accepted_at"),
        closed_at=item.get("closed_at"),
        active_at=item.get("active_at") or str(item["submitted_at"]),
    )


def fill_from_payload(item: dict[str, Any]) -> Fill:
    return Fill(
        id=str(item["id"]),
        order_id=str(item["order_id"]),
        market_event_id=str(item["market_event_id"]),
        quantity=decimal_value(item["quantity"]),
        price=decimal_value(item["price"]),
        fee=decimal_value(item["fee"]),
        filled_at=str(item["filled_at"]),
        raw_match_price=(
            None
            if item.get("raw_match_price") is None
            else decimal_value(item["raw_match_price"])
        ),
        market_timestamp=item.get("market_timestamp"),
        execution_timestamp=item.get("execution_timestamp"),
    )


def portfolio_from_payload(item: dict[str, Any]) -> Portfolio:
    positions = tuple(
        Position(
            symbol=str(row["symbol"]),
            quantity=decimal_value(row["quantity"]),
            average_cost=decimal_value(row["average_cost"]),
            realized_pnl=decimal_value(row["realized_pnl"]),
            mark_price=(
                None
                if row.get("mark_price") is None
                else decimal_value(row["mark_price"])
            ),
            unrealized_pnl=decimal_value(row["unrealized_pnl"]),
            market_value=decimal_value(row["market_value"]),
        )
        for row in item.get("positions", [])
    )
    return Portfolio(
        account_id=str(item["account_id"]),
        cash=decimal_value(item["cash"]),
        equity=decimal_value(item["equity"]),
        fees_paid=decimal_value(item["fees_paid"]),
        realized_pnl=decimal_value(item["realized_pnl"]),
        unrealized_pnl=decimal_value(item["unrealized_pnl"]),
        positions=positions,
        as_of=item.get("as_of"),
    )
