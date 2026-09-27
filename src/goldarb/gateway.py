"""Order surface for strategies. Not a broker and not brokerage HTTP.

``OrderGateway`` is the only order API ``StrategyContext`` calls.
``LocalPaperOrderGateway`` and ``RemoteSimulatorOrderGateway`` adapt the
existing paper engines. ``create_account`` and ``equity_history`` stay on
those engines. ``RemoteSimulator.feed`` is not used here; remote matching
stays on the server.

``StrategyRunner._resolve_broker_and_execution`` is the mode-based builder:
``backtest`` and ``live_paper_local`` get the local adapter, and
``live_paper_remote`` gets the remote adapter. ``runtime.broker`` is still
only the phase-2 paper preset.

``live_broker`` is a separate, explicit mode. It does not use those paper
adapters. With no gateway registered it raises ``TransportNotConfigured``.
``RecordingOrderGateway`` records submit and cancel and later hands fills
to ``on_fill``. It does not open a brokerage connection.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import uuid4

from .simulation.models import (
    Account,
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
    TimeInForce,
    decimal_value,
)
from .simulation.paper_broker import LocalPaperBroker
from .simulation.remote import RemoteSimulator

ZERO = Decimal(0)


@runtime_checkable
class OrderGateway(Protocol):
    """Submit, cancel, and read positions and cash. No account lifecycle."""

    def submit(
        self,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
    ) -> Order: ...

    def cancel(self, order_id: str) -> Order: ...

    def positions(self) -> tuple[Position, ...]: ...

    def cash(self) -> Decimal: ...


class _PaperOrderGateway:
    """Shared account binding for the two paper adapters."""

    def __init__(self, broker: Any, account_id: str | None = None) -> None:
        self._broker = broker
        self._account_id = None if account_id is None else str(account_id)

    def bind_account(self, account_id: str) -> None:
        """Attach the paper account the engine just created."""
        bound = str(account_id)
        if self._account_id is not None and self._account_id != bound:
            raise RuntimeError("order gateway is already bound to another account")
        self._account_id = bound

    def _account(self) -> str:
        if not self._account_id:
            raise RuntimeError("order gateway account is not bound")
        return self._account_id

    def cancel(self, order_id: str) -> Order:
        return self._broker.cancel_order(self._account(), order_id)

    def positions(self) -> tuple[Position, ...]:
        return tuple(self._broker.portfolio(self._account()).positions)

    def cash(self) -> Decimal:
        return self._broker.get_account(self._account()).cash


class LocalPaperOrderGateway(_PaperOrderGateway):
    """``OrderGateway`` over ``LocalPaperBroker``. Does not feed the book."""

    def __init__(self, broker: LocalPaperBroker, account_id: str | None = None) -> None:
        super().__init__(broker, account_id)

    def submit(
        self,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
    ) -> Order:
        return self._broker.submit_order(
            self._account(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
            time_in_force=time_in_force,
        )


class RemoteSimulatorOrderGateway(_PaperOrderGateway):
    """``OrderGateway`` over ``RemoteSimulator``.

    Does not call ``feed`` and does not match locally. ``time_in_force`` is
    not sent: the remote paper venue has no such field, and this adapter
    does not add HTTP.
    """

    def __init__(self, broker: RemoteSimulator, account_id: str | None = None) -> None:
        super().__init__(broker, account_id)

    def submit(
        self,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
    ) -> Order:
        del time_in_force
        return self._broker.submit_order(
            self._account(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )


class TransportNotConfigured(RuntimeError):
    """``live_broker`` was selected and no OrderGateway is registered.

    ``runtime.broker`` (including ``agah`` and ``mofid``) is a paper preset.
    It does not register a transport and does not send an order.
    """

    def __init__(self, message: str = "transport not configured") -> None:
        super().__init__(message)


@dataclass(frozen=True)
class RecordedSubmit:
    """One ``OrderGateway.submit`` call, stored with the phase-5 arguments."""

    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType
    limit_price: Decimal | None
    client_order_id: str | None
    time_in_force: TimeInForce
    order: Order


class _RecordingLedger:
    """Account book for recorded orders. Not a matcher and not a client.

    ``submit`` on the gateway queues an accepted order. ``release_fills``
    applies a full fill afterwards. Cash and positions change only then.
    """

    def __init__(self) -> None:
        self._account: Account | None = None
        self._orders: dict[str, Order] = {}
        self._order_ids: list[str] = []
        self._fills: list[Fill] = []
        self._pending: list[str] = []
        self._lots: dict[str, tuple[Decimal, Decimal, Decimal]] = {}
        self._last: dict[str, Decimal] = {}
        self._as_of: datetime | None = None
        self._equity: list[dict[str, str]] = []

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
    ) -> Account:
        if self._account is not None:
            raise RuntimeError("recording ledger already has an account")
        cash = decimal_value(initial_cash)
        now = self._stamp()
        account = Account(
            id=uuid4().hex,
            label=str(label),
            status="ACTIVE",
            initial_cash=cash,
            cash=cash,
            fee_rate=decimal_value(fee_rate),
            allow_short=bool(allow_short),
            fees_paid=ZERO,
            created_at=now,
            updated_at=now,
        )
        self._account = account
        self._equity.append({"equity": str(cash), "timestamp": now})
        return account

    def get_account(self, account_id: str) -> Account:
        account = self._require(account_id)
        return account

    def bind_account(self, account_id: str) -> None:
        self._require(account_id)

    def bound_account(self) -> Account | None:
        return self._account

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
    ) -> Order:
        del account_id, symbol, side, quantity, order_type, limit_price, client_order_id
        raise RuntimeError("live_broker records orders only through OrderGateway.submit")

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        del account_id, order_id
        raise RuntimeError("live_broker cancels orders only through OrderGateway.cancel")

    def list_orders(self, account_id: str) -> list[Order]:
        self._require(account_id)
        return [self._orders[order_id] for order_id in self._order_ids]

    def list_fills(self, account_id: str) -> list[Fill]:
        self._require(account_id)
        return list(self._fills)

    def portfolio(self, account_id: str) -> Portfolio:
        account = self._require(account_id)
        positions: list[Position] = []
        unrealized = ZERO
        market_value = ZERO
        realized = ZERO
        for symbol, (quantity, average, lot_realized) in sorted(self._lots.items()):
            realized += lot_realized
            if quantity == ZERO:
                continue
            mark = self._last.get(symbol, average)
            upnl = (mark - average) * quantity
            value = mark * quantity
            unrealized += upnl
            market_value += value
            positions.append(
                Position(
                    symbol=symbol,
                    quantity=quantity,
                    average_cost=average,
                    realized_pnl=lot_realized,
                    mark_price=mark,
                    unrealized_pnl=upnl,
                    market_value=value,
                )
            )
        equity = account.cash + market_value
        return Portfolio(
            account_id=account.id,
            cash=account.cash,
            equity=equity,
            fees_paid=account.fees_paid,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            positions=tuple(positions),
            as_of=None if self._as_of is None else self._as_of.isoformat(),
        )

    def equity_history(self, account_id: str) -> list[dict[str, str]]:
        self._require(account_id)
        return list(self._equity)

    def note_market(self, snapshot: MarketSnapshot) -> None:
        """Remember last prices. This is not a match against the book."""
        self._as_of = snapshot.timestamp
        for quote in snapshot.quotes:
            if quote.last is None or quote.last <= ZERO:
                continue
            self._last[quote.symbol] = quote.last

    def record_submit(
        self,
        *,
        symbol: str,
        side: Side,
        quantity: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None,
        client_order_id: str | None,
        time_in_force: TimeInForce,
    ) -> Order:
        account = self._require_bound()
        now = self._stamp()
        order = Order(
            id=uuid4().hex,
            account_id=account.id,
            client_order_id=client_order_id or "",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            filled_quantity=ZERO,
            limit_price=limit_price,
            status=OrderStatus.ACCEPTED,
            submitted_at=now,
            updated_at=now,
            time_in_force=time_in_force,
            created_at=now,
            accepted_at=now,
        )
        self._orders[order.id] = order
        self._order_ids.append(order.id)
        self._pending.append(order.id)
        return order

    def record_cancel(self, order_id: str) -> Order:
        self._require_bound()
        order = self._orders.get(order_id)
        if order is None:
            raise KeyError(order_id)
        if order.status != OrderStatus.ACCEPTED:
            return order
        now = self._stamp()
        cancelled = replace(
            order,
            status=OrderStatus.CANCELLED,
            updated_at=now,
            closed_at=now,
        )
        self._orders[order_id] = cancelled
        self._pending = [item for item in self._pending if item != order_id]
        return cancelled

    def release_fills(self) -> None:
        """Apply queued fills. ``submit`` does not call this."""
        if self._account is None or not self._pending:
            return
        pending = list(self._pending)
        self._pending.clear()
        still_waiting: list[str] = []
        for order_id in pending:
            order = self._orders[order_id]
            if order.status != OrderStatus.ACCEPTED:
                continue
            price = self._fill_price(order)
            if price is None:
                still_waiting.append(order_id)
                continue
            if self._short_rejected(order):
                now = self._stamp()
                self._orders[order_id] = replace(
                    order,
                    status=OrderStatus.REJECTED,
                    rejection_code="short_not_allowed",
                    updated_at=now,
                    closed_at=now,
                )
                continue
            self._apply_fill(order, price)
        self._pending.extend(still_waiting)
        if self._account is not None:
            portfolio = self.portfolio(self._account.id)
            self._equity.append({"equity": str(portfolio.equity), "timestamp": self._stamp()})

    def _fill_price(self, order: Order) -> Decimal | None:
        last = self._last.get(order.symbol)
        if last is not None and last > ZERO:
            return last
        if order.limit_price is not None and order.limit_price > ZERO:
            return order.limit_price
        return None

    def _short_rejected(self, order: Order) -> bool:
        account = self._require_bound()
        if order.side is not Side.SELL or account.allow_short:
            return False
        held = self._lots.get(order.symbol, (ZERO, ZERO, ZERO))[0]
        return held - order.quantity < ZERO

    def _apply_fill(self, order: Order, price: Decimal) -> None:
        account = self._require_bound()
        now = self._stamp()
        notional = price * order.quantity
        if order.side is Side.BUY:
            cash = account.cash - notional
        else:
            cash = account.cash + notional
        self._account = replace(account, cash=cash, updated_at=now)
        self._apply_lot(order.symbol, order.side, order.quantity, price)
        filled = replace(
            order,
            status=OrderStatus.FILLED,
            filled_quantity=order.quantity,
            avg_fill_price=price,
            updated_at=now,
            closed_at=now,
        )
        self._orders[order.id] = filled
        self._fills.append(
            Fill(
                id=uuid4().hex,
                order_id=order.id,
                market_event_id="",
                quantity=order.quantity,
                price=price,
                fee=ZERO,
                filled_at=now,
                raw_match_price=price,
                market_timestamp=now,
                execution_timestamp=now,
            )
        )

    def _apply_lot(self, symbol: str, side: Side, quantity: Decimal, price: Decimal) -> None:
        held, average, realized = self._lots.get(symbol, (ZERO, ZERO, ZERO))
        signed = quantity if side is Side.BUY else -quantity
        new_qty = held + signed
        if held == ZERO or (held > ZERO and signed > ZERO) or (held < ZERO and signed < ZERO):
            new_average = (abs(held) * average + quantity * price) / abs(new_qty)
        elif new_qty == ZERO:
            realized = realized + (price - average) * held
            new_average = ZERO
        else:
            closing = min(abs(signed), abs(held))
            direction = Decimal(1) if held > ZERO else Decimal(-1)
            realized = realized + (price - average) * closing * direction
            crossed = (held > ZERO and new_qty < ZERO) or (held < ZERO and new_qty > ZERO)
            new_average = price if crossed else average
        self._lots[symbol] = (new_qty, new_average, realized)

    def _require_bound(self) -> Account:
        if self._account is None:
            raise RuntimeError("order gateway account is not bound")
        return self._account

    def _require(self, account_id: str) -> Account:
        account = self._require_bound()
        if account.id != str(account_id):
            raise KeyError(account_id)
        return account

    def _stamp(self) -> str:
        if self._as_of is not None:
            return self._as_of.isoformat()
        return datetime.now(UTC).isoformat()


class RecordingOrderGateway:
    """Record submit and cancel. Do not send them to a venue.

    ``submit`` returns an accepted order and does not fill it. The
    simulation loop calls ``release_fills`` after ``on_market_data``, and
    that is what reaches ``on_fill``. Fill price is the snapshot last the
    strategy already saw, not a brokerage match and not ``QuoteMatching``.
    There is no HTTP client. The class is not an Agah or Mofid preset.
    """

    def __init__(self) -> None:
        self._ledger = _RecordingLedger()
        self.submits: list[RecordedSubmit] = []
        self.cancels: list[str] = []

    @property
    def ledger(self) -> _RecordingLedger:
        """Account book the runner gives the engine. Not a paper matcher."""
        return self._ledger

    def bind_account(self, account_id: str) -> None:
        self._ledger.bind_account(account_id)

    def note_market(self, snapshot: MarketSnapshot) -> None:
        self._ledger.note_market(snapshot)

    def release_fills(self) -> None:
        self._ledger.release_fills()

    def submit(
        self,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
        time_in_force: TimeInForce | str = TimeInForce.DAY,
    ) -> Order:
        parsed_side = Side(str(side).upper())
        parsed_type = OrderType(str(order_type).upper())
        parsed_qty = decimal_value(quantity)
        parsed_limit = None if limit_price is None else decimal_value(limit_price)
        parsed_tif = TimeInForce(str(time_in_force).upper())
        order = self._ledger.record_submit(
            symbol=str(symbol),
            side=parsed_side,
            quantity=parsed_qty,
            order_type=parsed_type,
            limit_price=parsed_limit,
            client_order_id=None if client_order_id is None else str(client_order_id),
            time_in_force=parsed_tif,
        )
        self.submits.append(
            RecordedSubmit(
                symbol=str(symbol),
                side=parsed_side,
                quantity=parsed_qty,
                order_type=parsed_type,
                limit_price=parsed_limit,
                client_order_id=None if client_order_id is None else str(client_order_id),
                time_in_force=parsed_tif,
                order=order,
            )
        )
        return order

    def cancel(self, order_id: str) -> Order:
        order = self._ledger.record_cancel(str(order_id))
        self.cancels.append(str(order_id))
        return order

    def positions(self) -> tuple[Position, ...]:
        account = self._ledger.bound_account()
        if account is None:
            return ()
        return self._ledger.portfolio(account.id).positions

    def cash(self) -> Decimal:
        account = self._ledger.bound_account()
        if account is None:
            raise RuntimeError("order gateway account is not bound")
        return account.cash


def order_gateway_for(
    broker: Any,
    account_id: str | None = None,
) -> LocalPaperOrderGateway | RemoteSimulatorOrderGateway:
    """Wrap the paper engine the caller already selected.

    Mode selection (local vs remote) lives in
    ``StrategyRunner._resolve_broker_and_execution``. This helper only
    matches the object in hand.
    """
    if isinstance(broker, RemoteSimulator):
        return RemoteSimulatorOrderGateway(broker, account_id)
    if isinstance(broker, LocalPaperBroker):
        return LocalPaperOrderGateway(broker, account_id)
    raise TypeError(
        "OrderGateway transport must be LocalPaperBroker or RemoteSimulator, "
        f"not {type(broker).__name__}"
    )


__all__ = [
    "LocalPaperOrderGateway",
    "OrderGateway",
    "RecordedSubmit",
    "RecordingOrderGateway",
    "RemoteSimulatorOrderGateway",
    "TransportNotConfigured",
    "order_gateway_for",
]
