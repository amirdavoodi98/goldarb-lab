"""Environment-agnostic Strategy contract.

A Strategy talks only to ``StrategyContext``. Engines feed market data into a
``PaperBroker`` (typically ``LocalSimulator``) and then call the strategy.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .simulation.models import (
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
)

_OPEN = (OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)


@dataclass(frozen=True)
class Signal:
    event_id: str
    timestamp: datetime
    symbol: str
    side: Side
    extra: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class EngineLog:
    kind: str
    timestamp: datetime
    payload: dict[str, str] = field(default_factory=dict)


class StrategyContext:
    """Read portfolio / orders and submit trades without knowing the engine."""

    def __init__(
        self,
        broker: Any,
        account_id: str,
        *,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self._broker = broker
        self.account_id = account_id
        self.config: dict[str, Any] = dict(config or {})
        self._market: MarketSnapshot | None = None
        self._clock: datetime | None = None
        self._portfolio_cache: Portfolio | None = None
        self.signals: list[Signal] = []
        self.log: list[EngineLog] = []

    @property
    def market(self) -> MarketSnapshot | None:
        return self._market

    @property
    def clock(self) -> datetime:
        if self._clock is not None:
            return self._clock
        raise RuntimeError("strategy clock is not set")

    def set_market(self, snapshot: MarketSnapshot) -> None:
        self._market = snapshot
        self._clock = snapshot.timestamp
        self._portfolio_cache = None

    def portfolio(self) -> Portfolio:
        if self._portfolio_cache is None:
            self._portfolio_cache = self._broker.portfolio(self.account_id)
        return self._portfolio_cache

    def positions(self) -> tuple[Position, ...]:
        return self.portfolio().positions

    def held(self, symbol: str) -> Decimal:
        for position in self.positions():
            if position.symbol == symbol:
                return position.quantity
        return Decimal(0)

    def orders(self) -> list[Order]:
        return self._broker.list_orders(self.account_id)

    def open_orders(self) -> list[Order]:
        return [order for order in self.orders() if order.status in _OPEN]

    def fills(self) -> list[Fill]:
        return self._broker.list_fills(self.account_id)

    def submit_order(
        self,
        *,
        symbol: str,
        side: Side | str,
        quantity: Decimal | float | str,
        order_type: OrderType | str = OrderType.MARKET,
        limit_price: Decimal | float | str | None = None,
        client_order_id: str | None = None,
    ) -> Order:
        order = self._broker.submit_order(
            self.account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
            client_order_id=client_order_id,
        )
        self._portfolio_cache = None
        self.record(
            "order",
            {
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side.value,
                "status": order.status.value,
                "quantity": str(order.quantity),
            },
        )
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._broker.cancel_order(self.account_id, order_id)
        self._portfolio_cache = None
        self.record("cancel", {"order_id": order.id, "status": order.status.value})
        return order

    def emit_signal(
        self,
        *,
        symbol: str,
        side: Side | str,
        extra: Mapping[str, str] | None = None,
    ) -> Signal:
        market = self._market
        signal = Signal(
            event_id="" if market is None else market.event_id,
            timestamp=self.clock,
            symbol=symbol,
            side=Side(str(side).upper()),
            extra=dict(extra or {}),
        )
        self.signals.append(signal)
        payload = {
            "symbol": signal.symbol,
            "side": signal.side.value,
            "event_id": signal.event_id,
        }
        payload.update(signal.extra)
        self.record("signal", payload)
        return signal

    def record(self, kind: str, payload: Mapping[str, str] | None = None) -> EngineLog:
        stamp = self._clock
        if stamp is None:
            from datetime import UTC

            stamp = datetime.now(UTC)
        event = EngineLog(kind=kind, timestamp=stamp, payload=dict(payload or {}))
        self.log.append(event)
        return event

    def status(self) -> dict[str, Any]:
        portfolio = self.portfolio()
        return {
            "cash": portfolio.cash,
            "equity": portfolio.equity,
            "fees_paid": portfolio.fees_paid,
            "realized_pnl": portfolio.realized_pnl,
            "unrealized_pnl": portfolio.unrealized_pnl,
            "open_orders": len(self.open_orders()),
            "positions": {item.symbol: str(item.quantity) for item in portfolio.positions},
            "signals": len(self.signals),
        }


class Strategy:
    """Override ``on_market_data``. Other hooks are optional."""

    name: str = "strategy"
    version: str = "0"

    def on_start(self, ctx: StrategyContext) -> None:
        return None

    def on_market_data(self, ctx: StrategyContext) -> None:
        raise NotImplementedError

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        del ctx, fill
        return None

    def on_stop(self, ctx: StrategyContext) -> None:
        del ctx
        return None
