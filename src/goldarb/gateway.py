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
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from .simulation.models import (
    Order,
    OrderType,
    Position,
    Side,
    TimeInForce,
)
from .simulation.paper_broker import LocalPaperBroker
from .simulation.remote import RemoteSimulator


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
    "RemoteSimulatorOrderGateway",
    "order_gateway_for",
]
