"""Explicit order state machine — sole mutator of order status."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal

from .engine import ZERO
from .models import (
    WORKING_STATUSES,
    DomainError,
    Fill,
    Order,
    OrderEvent,
    OrderEventType,
    OrderStatus,
    OrderType,
    Side,
    TimeInForce,
    decimal_value,
)

_ALLOWED: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.REJECTED, OrderStatus.ACCEPTED, OrderStatus.CANCELLED}
    ),
    OrderStatus.ACCEPTED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.EXPIRED,
            OrderStatus.REJECTED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.PARTIALLY_FILLED: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.EXPIRED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.CANCEL_PENDING: frozenset(
        {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


@dataclass
class OrderManager:
    """Owns submit validation, idempotency keys, and all status transitions."""

    _orders: dict[str, Order]
    _by_client: dict[tuple[str, str], str]
    _events: list[OrderEvent]
    _fills: dict[str, list[Fill]]

    def __init__(self) -> None:
        self._orders = {}
        self._by_client = {}
        self._events = []
        self._fills = {}

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise KeyError(f"unknown order: {order_id}") from exc

    def list_for_account(self, account_id: str) -> list[Order]:
        rows = [order for order in self._orders.values() if order.account_id == account_id]
        return sorted(rows, key=lambda item: (item.submitted_at, item.id))

    def fills_for_account(self, account_id: str) -> list[Fill]:
        out: list[Fill] = []
        for order in self.list_for_account(account_id):
            out.extend(self._fills.get(order.id, []))
        return sorted(out, key=lambda item: (item.filled_at, item.id))

    def working_for_account(self, account_id: str) -> list[Order]:
        return [
            order
            for order in self.list_for_account(account_id)
            if order.status in WORKING_STATUSES
            or order.status == OrderStatus.CREATED
        ]

    def get_by_client(self, account_id: str, client_order_id: str) -> Order | None:
        order_id = self._by_client.get((account_id, client_order_id))
        return None if order_id is None else self.get(order_id)

    def create(
        self,
        *,
        account_id: str,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
        submitted_at: str,
        active_at: str | None = None,
        order_id: str | None = None,
    ) -> Order:
        client_id = client_order_id or str(uuid.uuid4())
        key = (account_id, client_id)
        existing = self._by_client.get(key)
        if existing is not None:
            return self.get(existing)

        side_value = Side(str(side).upper())
        type_value = OrderType(str(order_type).upper())
        tif = TimeInForce(str(time_in_force).upper())
        qty = decimal_value(quantity)
        limit = None if limit_price is None else decimal_value(limit_price)
        if qty <= ZERO:
            raise DomainError("quantity must be positive")
        if type_value == OrderType.LIMIT and (limit is None or limit <= ZERO):
            raise DomainError("positive limit_price is required for LIMIT orders")

        identifier = order_id or str(uuid.uuid4())
        order = Order(
            id=identifier,
            account_id=account_id,
            client_order_id=client_id,
            symbol=symbol.strip(),
            side=side_value,
            order_type=type_value,
            quantity=qty,
            filled_quantity=ZERO,
            limit_price=limit,
            status=OrderStatus.CREATED,
            submitted_at=submitted_at,
            updated_at=submitted_at,
            time_in_force=tif,
            created_at=submitted_at,
            active_at=active_at or submitted_at,
        )
        self._orders[identifier] = order
        self._by_client[key] = identifier
        self._fills[identifier] = []
        self._record(
            order.id,
            OrderEventType.CREATED,
            submitted_at,
            {"client_order_id": client_id, "symbol": order.symbol, "side": order.side.value},
        )
        return order

    def reject(self, order_id: str, *, code: str, at: str) -> Order:
        order = self.get(order_id)
        updated = self._transition(
            order,
            OrderStatus.REJECTED,
            at=at,
            rejection_code=code,
            closed_at=at,
        )
        self._record(order_id, OrderEventType.REJECTED, at, {"code": code})
        return updated

    def accept(self, order_id: str, *, at: str) -> Order:
        order = self.get(order_id)
        if order.status == OrderStatus.ACCEPTED:
            return order
        updated = self._transition(order, OrderStatus.ACCEPTED, at=at, accepted_at=at)
        self._record(order_id, OrderEventType.ACCEPTED, at, {})
        return updated

    def request_cancel(self, order_id: str, *, at: str) -> Order:
        order = self.get(order_id)
        if order.status in {OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.REJECTED, OrderStatus.EXPIRED}:
            return order
        if order.status == OrderStatus.CREATED:
            updated = self._transition(
                order,
                OrderStatus.CANCELLED,
                at=at,
                closed_at=at,
            )
            self._record(order_id, OrderEventType.CANCELLED, at, {})
            return updated
        if order.status == OrderStatus.CANCEL_PENDING:
            return order
        updated = self._transition(order, OrderStatus.CANCEL_PENDING, at=at)
        self._record(order_id, OrderEventType.CANCEL_REQUESTED, at, {})
        return updated

    def confirm_cancel(self, order_id: str, *, at: str) -> Order:
        order = self.get(order_id)
        if order.status == OrderStatus.CANCELLED:
            return order
        if order.status not in {
            OrderStatus.CANCEL_PENDING,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CREATED,
        }:
            raise DomainError(f"cannot cancel order in status {order.status.value}")
        updated = self._transition(order, OrderStatus.CANCELLED, at=at, closed_at=at)
        self._record(order_id, OrderEventType.CANCELLED, at, {})
        return updated

    def expire(self, order_id: str, *, at: str) -> Order:
        order = self.get(order_id)
        if order.is_terminal:
            return order
        updated = self._transition(order, OrderStatus.EXPIRED, at=at, closed_at=at)
        self._record(order_id, OrderEventType.EXPIRED, at, {})
        return updated

    def apply_fill(self, order_id: str, fill: Fill, *, terminal_without_fill: bool = False) -> Order:
        order = self.get(order_id)
        if order.status not in WORKING_STATUSES and order.status != OrderStatus.ACCEPTED:
            if order.status == OrderStatus.CANCEL_PENDING:
                pass
            elif order.status not in WORKING_STATUSES:
                raise DomainError(f"cannot fill order in status {order.status.value}")

        new_filled = order.filled_quantity + fill.quantity
        if new_filled > order.quantity:
            raise DomainError("fill would exceed order quantity")

        avg = _avg_fill_price(order.avg_fill_price, order.filled_quantity, fill.price, fill.quantity)
        if new_filled >= order.quantity:
            status = OrderStatus.FILLED
            closed_at = fill.filled_at
        elif order.status == OrderStatus.CANCEL_PENDING:
            status = OrderStatus.CANCEL_PENDING
            closed_at = None
        else:
            status = OrderStatus.PARTIALLY_FILLED
            closed_at = None

        updated = replace(
            order,
            filled_quantity=new_filled,
            status=status,
            avg_fill_price=avg,
            updated_at=fill.filled_at,
            closed_at=closed_at if status == OrderStatus.FILLED else order.closed_at,
        )
        self._assert_transition(order.status, status)
        self._orders[order_id] = updated
        self._fills.setdefault(order_id, []).append(fill)
        self._record(
            order_id,
            OrderEventType.FILL,
            fill.filled_at,
            {
                "fill_id": fill.id,
                "quantity": str(fill.quantity),
                "price": str(fill.price),
                "fee": str(fill.fee),
            },
        )
        del terminal_without_fill
        return updated

    def close_unfilled(
        self,
        order_id: str,
        *,
        at: str,
        rejection: str | None = None,
    ) -> Order:
        """Terminal close after a matching attempt with no remaining work (e.g. MARKET)."""
        order = self.get(order_id)
        if order.filled_quantity > ZERO:
            return self.confirm_cancel(order_id, at=at)
        if rejection:
            return self.reject(order_id, code=rejection, at=at)
        return self.confirm_cancel(order_id, at=at)

    def restore(self, order: Order, fills: list[Fill] | None = None) -> None:
        """Hydrate manager from persistence without emitting events."""
        self._orders[order.id] = order
        self._by_client[(order.account_id, order.client_order_id)] = order.id
        self._fills[order.id] = list(fills or [])

    def events_for(self, order_id: str) -> list[OrderEvent]:
        return [event for event in self._events if event.order_id == order_id]

    def _transition(
        self,
        order: Order,
        new_status: OrderStatus,
        *,
        at: str,
        rejection_code: str | None = None,
        accepted_at: str | None = None,
        closed_at: str | None = None,
    ) -> Order:
        self._assert_transition(order.status, new_status)
        updated = replace(
            order,
            status=new_status,
            updated_at=at,
            rejection_code=rejection_code if rejection_code is not None else order.rejection_code,
            accepted_at=accepted_at if accepted_at is not None else order.accepted_at,
            closed_at=closed_at if closed_at is not None else order.closed_at,
        )
        self._orders[order.id] = updated
        return updated

    def _assert_transition(self, current: OrderStatus, new_status: OrderStatus) -> None:
        if current == new_status and current in {
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCEL_PENDING,
            OrderStatus.ACCEPTED,
        }:
            return
        allowed = _ALLOWED.get(current, frozenset())
        if new_status not in allowed:
            raise DomainError(
                f"invalid order transition {current.value} → {new_status.value}"
            )

    def _record(
        self,
        order_id: str,
        event_type: OrderEventType,
        timestamp: str,
        payload: dict[str, str],
    ) -> None:
        self._events.append(
            OrderEvent(
                id=str(uuid.uuid4()),
                order_id=order_id,
                event_type=event_type,
                timestamp=timestamp,
                payload=payload,
            )
        )


def _avg_fill_price(
    previous_avg: Decimal | None,
    previous_qty: Decimal,
    fill_price: Decimal,
    fill_qty: Decimal,
) -> Decimal:
    if previous_qty <= ZERO or previous_avg is None:
        return fill_price
    total = previous_qty + fill_qty
    return ((previous_avg * previous_qty) + (fill_price * fill_qty)) / total
