"""Paper-simulator broker objects.

V1 still matches through the local or remote paper engine. ``AgahBroker`` and
``MofidBroker`` only differ by identity; both use ``fee_rate="0.0005"`` and
``allow_short=False``. This registry is the lab simulator destination, not a
live brokerage client.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from .models import Account, Order, OrderType, Position, Side

FEE_RATE = Decimal("0.0005")


def resolve_broker(broker: Broker | str | None) -> Broker | None:
    """Return a broker instance, or None when no code was provided."""
    if broker is None:
        return None
    if isinstance(broker, Broker):
        return broker
    text = broker.strip()
    if not text:
        return None
    return get_broker(text)


def terms_for_fill(
    *,
    account_fee_rate: Decimal,
    account_allow_short: bool,
    account_broker: str,
    order_broker: str,
) -> tuple[Decimal, bool]:
    """Fee rate and short permission used to match one order.

    No destination broker keeps the account values. A destination that differs
    from the account broker supplies its own fee and short permission. The
    same broker keeps the account fee so an explicit ``fee_rate`` override
    still applies to that account.
    """
    destination = (order_broker or account_broker or "").strip().lower()
    configured = (account_broker or "").strip().lower()
    if not destination or destination == configured:
        return account_fee_rate, account_allow_short
    broker = get_broker(destination)
    return broker.fee_rate, broker.allow_short


class Broker(ABC):
    """Destination broker for paper orders."""

    code: str
    display_name: str
    fee_rate: Decimal
    allow_short: bool

    def __init__(self) -> None:
        self._simulator: Any = None

    def attach(self, simulator: Any) -> None:
        """Bind this broker to the simulator that stores paper state."""
        self._simulator = simulator

    def _bound(self) -> Any:
        if self._simulator is None:
            name = self.code or type(self).__name__
            raise RuntimeError(f"broker {name} is not bound to a simulator")
        return self._simulator

    @abstractmethod
    def submit_buy(
        self,
        account: Account,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit a buy to this broker."""

    @abstractmethod
    def submit_sell(
        self,
        account: Account,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        """Submit a sell to this broker."""

    @abstractmethod
    def cancel_order(self, order: Order) -> Order:
        """Cancel one order previously sent to this broker."""

    @abstractmethod
    def list_orders(self, account: Account) -> list[Order]:
        """List paper orders for the account."""

    @abstractmethod
    def list_holdings(self, account: Account) -> list[Position]:
        """List paper positions (assets) for the account."""

    @abstractmethod
    def get_cash(self, account: Account) -> Decimal:
        """Return the account cash balance."""


class PaperBroker(Broker):
    """Shared paper implementation used by the v1 brokerage wrappers."""

    code = ""
    display_name = ""
    fee_rate = FEE_RATE
    allow_short = False

    def submit_buy(
        self,
        account: Account,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        return self._submit(
            account,
            side=Side.BUY,
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )

    def submit_sell(
        self,
        account: Account,
        *,
        symbol: str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        return self._submit(
            account,
            side=Side.SELL,
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )

    def cancel_order(self, order: Order) -> Order:
        return self._bound().cancel_order(order.account_id, order.id)

    def list_orders(self, account: Account) -> list[Order]:
        return self._bound().list_orders(account.id)

    def list_holdings(self, account: Account) -> list[Position]:
        portfolio = self._bound().portfolio(account.id)
        return list(portfolio.positions)

    def get_cash(self, account: Account) -> Decimal:
        return self._bound().get_account(account.id).cash

    def _submit(
        self,
        account: Account,
        *,
        side: Side,
        symbol: str,
        quantity: Decimal | float | str,
        order_type: OrderType | str,
        limit_price: Decimal | float | str | None,
        client_order_id: str | None,
    ) -> Order:
        return self._bound().submit_order(
            account.id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
            broker=self,
        )


class AgahBroker(PaperBroker):
    """Agah (آگاه) paper destination."""

    code = "agah"
    display_name = "آگاه"
    fee_rate = FEE_RATE
    allow_short = False


class MofidBroker(PaperBroker):
    """Mofid (مفید) paper destination."""

    code = "mofid"
    display_name = "مفید"
    fee_rate = FEE_RATE
    allow_short = False


_REGISTRY: dict[str, type[PaperBroker]] = {
    AgahBroker.code: AgahBroker,
    MofidBroker.code: MofidBroker,
}


def get_broker(code: str) -> Broker:
    """Return the destination broker for ``agah`` or ``mofid``.

    Unknown codes raise ``ValueError``.
    """
    key = code.strip().lower()
    try:
        broker_cls = _REGISTRY[key]
    except KeyError as exc:
        raise ValueError(f"unknown broker: {code}") from exc
    return broker_cls()
