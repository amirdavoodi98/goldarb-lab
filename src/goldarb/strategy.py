"""Environment-agnostic Strategy contract.

A Strategy talks only to ``StrategyContext``. Order submit and cancel go
through ``OrderGateway``. Engines still feed market data into the paper
broker and keep ``create_account`` / ``equity_history`` there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Self

from .execution_policy import (
    REMOTE_POLICY_ERROR,
    ExecutionPolicy,
    NoOpExecutionPolicy,
    RawOrder,
    policy_is_noop,
)
from .gateway import (
    OrderGateway,
    RemoteSimulatorOrderGateway,
    order_gateway_for,
)
from .simulation.models import (
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Quote,
    Side,
)
from .simulation.remote import RemoteSimulator

_OPEN = (
    OrderStatus.OPEN,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_PENDING,
)


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
        execution_policy: ExecutionPolicy | None = None,
        quote_fill: str = "last",
        gateway: OrderGateway | None = None,
    ) -> None:
        self._broker = broker
        self.account_id = account_id
        self.config: dict[str, Any] = dict(config or {})
        self._policy: ExecutionPolicy = execution_policy or NoOpExecutionPolicy()
        self._quote_fill = quote_fill
        self._gateway = gateway
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

    def _quote_for(self, symbol: str) -> Quote | None:
        market = self._market
        if market is None:
            return None
        for quote in market.quotes:
            if quote.symbol == symbol:
                return quote
        return None

    @property
    def order_gateway(self) -> OrderGateway | None:
        """Gateway bound for this run. None until one is injected or used."""
        return self._gateway

    def _order_gateway(self) -> OrderGateway:
        """Gateway injected by ``StrategyRunner``, or a wrap of this paper broker."""
        if self._gateway is None:
            self._gateway = order_gateway_for(self._broker, self.account_id)
        return self._gateway

    def _remote_paper(self) -> bool:
        return isinstance(self._broker, RemoteSimulator) or isinstance(
            self._gateway, RemoteSimulatorOrderGateway
        )

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
        # NoOp keeps the gateway call unchanged, including remote paper.
        # A real policy rewrites type, limit, size, and time_in_force first.
        gateway = self._order_gateway()
        if policy_is_noop(self._policy):
            order = gateway.submit(
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                limit_price=limit_price,
                client_order_id=client_order_id,
            )
        else:
            if self._remote_paper():
                raise ValueError(REMOTE_POLICY_ERROR)
            paper = self._policy.translate(
                RawOrder(
                    symbol=symbol,
                    side=Side(str(side).upper()),
                    quantity=Decimal(str(quantity)),
                    order_type=OrderType(str(order_type).upper()),
                    limit_price=None if limit_price is None else Decimal(str(limit_price)),
                ),
                quote=self._quote_for(symbol),
                quote_fill=self._quote_fill,
            )
            order = gateway.submit(
                symbol=symbol,
                side=side,
                quantity=paper.quantity,
                order_type=paper.order_type,
                limit_price=paper.limit_price,
                client_order_id=client_order_id,
                time_in_force=paper.time_in_force,
            )
        self._portfolio_cache = None
        limit = "" if order.limit_price is None else format(order.limit_price, "f")
        self.record(
            "order",
            {
                "order_id": order.id,
                "symbol": order.symbol,
                "side": order.side.value,
                "status": order.status.value,
                "quantity": str(order.quantity),
                "gateway": type(gateway).__name__,
                "order_type": order.order_type.value,
                "limit_price": limit,
                "filled_quantity": format(order.filled_quantity, "f"),
            },
        )
        return order

    def cancel_order(self, order_id: str) -> Order:
        order = self._order_gateway().cancel(order_id)
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

    def configure(self, **params: Any) -> Self:
        """Apply keyword params onto known attributes (chainable).

        Unknown keys raise ``ValueError``. Subclasses may override for
        typed coercion; the default assigns attributes that already exist.
        """
        for key, value in params.items():
            if key.startswith("_") or not hasattr(self, key):
                raise ValueError(f"unknown strategy param: {key!r}")
            setattr(self, key, value)
        return self

    def export_state(self) -> dict[str, Any]:
        """Signal memory for another process. Default is empty."""
        return {}

    def load_state(self, state: Mapping[str, Any]) -> None:
        """Restore memory from ``export_state``. Default ignores the payload."""
        del state

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
