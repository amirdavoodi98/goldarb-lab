"""Remote venue protocol — server owns matching; client only mirrors state."""

from __future__ import annotations

from typing import Any, Protocol

from .models import Account, Fill, Order, OrderType, Portfolio, Side


class RemoteVenue(Protocol):
    """Transport to a remote paper/live matching venue."""

    def create_account(
        self,
        *,
        initial_cash: Any,
        label: str = "",
        fee_rate: Any = "0.0005",
        allow_short: bool = False,
        broker: str | None = None,
    ) -> Account: ...

    def get_account(self, account_id: str) -> Account: ...

    def submit_order(
        self,
        account_id: str,
        *,
        symbol: str,
        side: Side | str,
        quantity: Any,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Any | None = None,
        client_order_id: str | None = None,
        broker: str | None = None,
    ) -> Order: ...

    def cancel_order(self, account_id: str, order_id: str) -> Order: ...

    def list_orders(self, account_id: str) -> list[Order]: ...

    def list_fills(self, account_id: str) -> list[Fill]: ...

    def portfolio(self, account_id: str) -> Portfolio: ...

    def equity_history(self, account_id: str) -> list[dict[str, Any]]: ...
