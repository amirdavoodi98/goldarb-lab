"""Authenticated remote adapter for the platform simulation API."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from .._http import LabHttp
from .models import (
    Account,
    Fill,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
    decimal_value,
)


class RemoteSimulator:
    """Run paper orders on the main server while strategy code stays client-side."""

    def __init__(self, http: LabHttp) -> None:
        self._http = http

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
    ) -> Account:
        payload = self._http.post_json(
            "/api/v1/simulation/accounts/",
            {
                "initial_cash": str(decimal_value(initial_cash)),
                "label": label,
                "fee_rate": str(decimal_value(fee_rate)),
                "allow_short": allow_short,
            },
        )
        return _account(payload)

    def get_account(self, account_id: str) -> Account:
        return _account(
            self._http.get_json(f"/api/v1/simulation/accounts/{account_id}/")
        )

    def list_accounts(self) -> list[Account]:
        payload = self._http.get_json("/api/v1/simulation/accounts/")
        return [_account(item) for item in payload.get("results", [])]

    def stop_account(self, account_id: str) -> Account:
        return _account(
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
    ) -> Order:
        body: dict[str, Any] = {
            "client_order_id": client_order_id or str(uuid.uuid4()),
            "symbol": symbol,
            "side": Side(str(side).upper()).value,
            "quantity": str(decimal_value(quantity)),
            "order_type": OrderType(str(order_type).upper()).value,
        }
        if limit_price is not None:
            body["limit_price"] = str(decimal_value(limit_price))
        return _order(
            self._http.post_json(
                f"/api/v1/simulation/accounts/{account_id}/orders/", body
            )
        )

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        return _order(
            self._http.post_json(
                f"/api/v1/simulation/accounts/{account_id}/orders/{order_id}/cancel/"
            )
        )

    def list_orders(self, account_id: str) -> list[Order]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/orders/"
        )
        return [_order(item) for item in payload.get("results", [])]

    def list_fills(self, account_id: str) -> list[Fill]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/fills/"
        )
        return [_fill(item) for item in payload.get("results", [])]

    def portfolio(self, account_id: str) -> Portfolio:
        return _portfolio(
            self._http.get_json(
                f"/api/v1/simulation/accounts/{account_id}/portfolio/"
            )
        )

    def equity_history(self, account_id: str) -> list[dict[str, Any]]:
        payload = self._http.get_json(
            f"/api/v1/simulation/accounts/{account_id}/equity/"
        )
        return list(payload.get("results", []))


def _account(item: dict[str, Any]) -> Account:
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
    )


def _order(item: dict[str, Any]) -> Order:
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
        status=OrderStatus(item["status"]),
        submitted_at=str(item["submitted_at"]),
        updated_at=str(item["updated_at"]),
    )


def _fill(item: dict[str, Any]) -> Fill:
    return Fill(
        id=str(item["id"]),
        order_id=str(item["order_id"]),
        market_event_id=str(item["market_event_id"]),
        quantity=decimal_value(item["quantity"]),
        price=decimal_value(item["price"]),
        fee=decimal_value(item["fee"]),
        filled_at=str(item["filled_at"]),
    )


def _portfolio(item: dict[str, Any]) -> Portfolio:
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
