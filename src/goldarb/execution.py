"""Replaceable execution models: broker protocol, fee, slippage, latency.

``LocalSimulator`` remains the paper broker. Engines apply slippage and latency
to snapshots before ``feed()`` so default matching behavior is unchanged when
``NoSlippage`` and ``NoLatency`` are used.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from .simulation.engine import ZERO, fee_for
from .simulation.models import (
    Fill,
    MarketSnapshot,
    Order,
    OrderType,
    Portfolio,
    Quote,
    Side,
    decimal_value,
)


@runtime_checkable
class Broker(Protocol):
    """Order and portfolio surface shared by local and remote paper brokers."""

    def create_account(
        self,
        *,
        initial_cash: Decimal | float | str,
        label: str = "",
        fee_rate: Decimal | float | str = "0.0005",
        allow_short: bool = False,
    ) -> Any: ...

    def get_account(self, account_id: str) -> Any: ...

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
    ) -> Order: ...

    def cancel_order(self, account_id: str, order_id: str) -> Order: ...

    def list_orders(self, account_id: str) -> list[Order]: ...

    def list_fills(self, account_id: str) -> list[Fill]: ...

    def portfolio(self, account_id: str) -> Portfolio: ...

    def equity_history(self, account_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class PaperBroker(Broker, Protocol):
    """Broker that also accepts market snapshots for offline matching."""

    def feed(self, snapshot: MarketSnapshot) -> bool: ...

    def equity_history(self, account_id: str) -> list[dict[str, str]]: ...


class ExecutionDriver(Protocol):
    """Deliver market events according to the broker's matching ownership."""

    name: str

    def on_market(self, broker: Broker, snapshot: MarketSnapshot) -> None: ...


@dataclass(frozen=True)
class LocalFeedExecution:
    """Feed snapshots to an SDK-side paper matcher."""

    name: str = "LocalFeedExecution"

    def on_market(self, broker: Broker, snapshot: MarketSnapshot) -> None:
        if not isinstance(broker, PaperBroker):
            raise TypeError("local execution requires a PaperBroker with feed()")
        broker.feed(snapshot)


@dataclass(frozen=True)
class ServerSideExecution:
    """Server owns matching; client market events only drive the Strategy."""

    name: str = "ServerSideExecution"

    def on_market(self, broker: Broker, snapshot: MarketSnapshot) -> None:
        del broker, snapshot


class FeeModel(Protocol):
    name: str

    def rate(self) -> Decimal: ...

    def fee_for(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
        side: Side | None = None,
        order_type: OrderType | None = None,
        symbol: str | None = None,
    ) -> Decimal: ...

    def config(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class PercentFee:
    """Proportional fee; ``rate`` is wired into ``LocalSimulator`` account fee_rate."""

    fee_rate: Decimal | float | str = "0.0005"
    name: str = "PercentFee"

    def rate(self) -> Decimal:
        return decimal_value(self.fee_rate)

    def fee_for(
        self,
        *,
        quantity: Decimal,
        price: Decimal,
        side: Side | None = None,
        order_type: OrderType | None = None,
        symbol: str | None = None,
    ) -> Decimal:
        del side, order_type, symbol
        return fee_for(quantity, price, self.rate())

    def config(self) -> dict[str, str]:
        return {"fee_rate": str(self.rate())}


@dataclass(frozen=True)
class NoFee(PercentFee):
    fee_rate: Decimal | float | str = "0"
    name: str = "NoFee"


class SlippageModel(Protocol):
    name: str

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot: ...

    def config(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class NoSlippage:
    name: str = "NoSlippage"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        return snapshot

    def config(self) -> dict[str, str]:
        return {}


def _positive(value: Decimal | None) -> Decimal | None:
    if value is None or value <= ZERO:
        return None
    return value


def _slip_quote(
    quote: Quote,
    *,
    bid_delta: Decimal,
    ask_delta: Decimal,
) -> Quote:
    bid = quote.bid
    ask = quote.ask
    last = quote.last
    if bid is None and ask is None and last is not None and last > ZERO:
        bid = last
        ask = last
    slipped_bid = _positive(bid - bid_delta) if bid is not None else None
    slipped_ask = _positive(ask + ask_delta) if ask is not None else None
    return replace(quote, bid=slipped_bid, ask=slipped_ask)


def _map_quotes(snapshot: MarketSnapshot, mapper: Callable[[Quote], Quote]) -> MarketSnapshot:
    return replace(
        snapshot,
        quotes=tuple(mapper(quote) for quote in snapshot.quotes),
    )


@dataclass(frozen=True)
class FixedSlippage:
    """Widen the book by a fixed amount: BUY pays more, SELL receives less."""

    amount: Decimal | float | str
    name: str = "FixedSlippage"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        delta = decimal_value(self.amount)
        if delta < ZERO:
            raise ValueError("slippage amount must be non-negative")

        def mapper(quote: Quote) -> Quote:
            return _slip_quote(quote, bid_delta=delta, ask_delta=delta)

        return _map_quotes(snapshot, mapper)

    def config(self) -> dict[str, str]:
        return {"amount": str(decimal_value(self.amount))}


@dataclass(frozen=True)
class PercentSlippage:
    """Widen the book by a fraction of price (0.01 = 1%)."""

    fraction: Decimal | float | str
    name: str = "PercentSlippage"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        pct = decimal_value(self.fraction)
        if pct < ZERO:
            raise ValueError("slippage fraction must be non-negative")

        def mapper(quote: Quote) -> Quote:
            bid = quote.bid if quote.bid is not None else quote.last
            ask = quote.ask if quote.ask is not None else quote.last
            bid_delta = (bid or ZERO) * pct
            ask_delta = (ask or ZERO) * pct
            return _slip_quote(quote, bid_delta=bid_delta, ask_delta=ask_delta)

        return _map_quotes(snapshot, mapper)

    def config(self) -> dict[str, str]:
        return {"fraction": str(decimal_value(self.fraction))}


class LatencyModel(Protocol):
    name: str

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot: ...

    def delay(self) -> timedelta: ...

    def config(self) -> dict[str, str]: ...


@dataclass(frozen=True)
class NoLatency:
    name: str = "NoLatency"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        return snapshot

    def delay(self) -> timedelta:
        return timedelta(0)

    def config(self) -> dict[str, str]:
        return {}


@dataclass(frozen=True)
class FixedLatency:
    """Shift the execution clock forward by a fixed delay."""

    milliseconds: int
    name: str = "FixedLatency"

    def delay(self) -> timedelta:
        if self.milliseconds < 0:
            raise ValueError("latency milliseconds must be non-negative")
        return timedelta(milliseconds=self.milliseconds)

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        return replace(snapshot, timestamp=snapshot.timestamp + self.delay())

    def config(self) -> dict[str, str]:
        return {"milliseconds": str(self.milliseconds)}
