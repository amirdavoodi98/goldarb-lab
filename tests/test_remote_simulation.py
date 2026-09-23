from __future__ import annotations

from decimal import Decimal
from typing import Any

from goldarb.simulation import OrderStatus, RemoteSimulator


class FakeHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def post_json(self, path: str, body: dict[str, Any] | None = None) -> Any:
        self.calls.append(("POST", path, body))
        if path.endswith("/orders/"):
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
        raise AssertionError(path)

    def get_json(self, path: str) -> Any:
        self.calls.append(("GET", path, None))
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


def test_remote_submit_order_uses_typed_contract():
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
    assert order.quantity == Decimal(1)
    assert ("POST", "/api/v1/simulation/accounts/account-1/orders/", {
        "client_order_id": "client-1",
        "symbol": "طلا",
        "side": "BUY",
        "quantity": "1",
        "order_type": "MARKET",
    }) in http.calls
