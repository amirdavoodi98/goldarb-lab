"""Translate a strategy order into the paper order a venue will accept.

Strategies keep sending raw ``MARKET`` size. ``StrategyContext.submit_order``
runs an ``ExecutionPolicy`` before ``LocalPaperBroker``. ``QuoteMatching``
then matches that translated order. Slippage stays on
``SlippageModel.adjust_fill_price``.

Parameters live on ``AppConfig.execution_policy``. This module does not
encode a brokerage tick table, lot size, or protocol code. ``NoOp`` is the
default and leaves the order unchanged. ``live_paper_remote`` must stay on
``NoOp`` until the paper server applies the same policy; a local rewrite
would not match the server.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, Decimal
from typing import Any, Mapping, Protocol, Self

from .simulation.engine import QUANTITY_QUANTUM
from .simulation.models import OrderType, Quote, Side, TimeInForce, decimal_value

_QUOTE_FILL_MODES = frozenset({"last", "book"})
_POLICY_PARAMS = frozenset(
    {
        "quantity_quantum",
        "price_tick",
        "min_quantity",
        "market_offset",
        "time_in_force",
    }
)

REMOTE_POLICY_ERROR = (
    "live_paper_remote refuses a non-NoOp ExecutionPolicy; "
    "local translation would not match the paper server. "
    "Use NoOp until the server applies the same policy."
)


def _quote_fill_mode(quote_fill: str) -> str:
    mode = str(quote_fill or "last").strip().lower()
    if mode not in _QUOTE_FILL_MODES:
        raise ValueError("data.quote_fill must be 'last' or 'book'")
    return mode


def _floor_quantum(value: Decimal, quantum: Decimal) -> Decimal:
    units = (value / quantum).to_integral_value(rounding=ROUND_DOWN)
    return units * quantum


def _snap_to_tick(price: Decimal, tick: Decimal, *, side: Side) -> Decimal:
    """Keep the limit at least as aggressive as ``price`` on the tick grid.

    BUY rounds away from zero (ceiling). SELL rounds toward zero (floor).
    A MARKET converted at the touch still crosses ``QuoteMatching``.
    """
    units = price / tick
    rounding = ROUND_CEILING if side == Side.BUY else ROUND_FLOOR
    return units.to_integral_value(rounding=rounding) * tick


def _required_positive(params: Mapping[str, Any], name: str, *, default: Decimal | None) -> Decimal:
    if name not in params:
        if default is None:
            raise ValueError(f"execution policy param {name} is required")
        return default
    number = decimal_value(params[name])
    if number <= 0:
        raise ValueError(f"execution policy param {name} must be positive")
    return number


def _optional_positive(params: Mapping[str, Any], name: str) -> Decimal | None:
    if name not in params or params[name] is None or params[name] == "":
        return None
    number = decimal_value(params[name])
    if number <= 0:
        raise ValueError(f"execution policy param {name} must be positive")
    return number


def _non_negative(params: Mapping[str, Any], name: str, *, default: Decimal) -> Decimal:
    if name not in params:
        return default
    number = decimal_value(params[name])
    if number < 0:
        raise ValueError(f"execution policy param {name} must be non-negative")
    return number


@dataclass(frozen=True)
class RawOrder:
    """Order intent as the strategy submitted it."""

    symbol: str
    side: Side
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.DAY

    def __post_init__(self) -> None:
        if not str(self.symbol).strip():
            raise ValueError("order symbol is required")
        object.__setattr__(self, "side", Side(str(self.side).upper()))
        object.__setattr__(self, "order_type", OrderType(str(self.order_type).upper()))
        object.__setattr__(
            self,
            "time_in_force",
            TimeInForce(str(self.time_in_force).upper()),
        )
        quantity = decimal_value(self.quantity)
        if quantity <= 0:
            raise ValueError("order quantity must be positive")
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(
            self,
            "limit_price",
            None if self.limit_price is None else decimal_value(self.limit_price),
        )


@dataclass(frozen=True)
class PaperOrder:
    """Venue order fields written onto the existing paper ``Order``."""

    order_type: OrderType
    limit_price: Decimal | None
    quantity: Decimal
    time_in_force: TimeInForce


class ExecutionPolicy(Protocol):
    """One translation from a raw strategy order to a paper order."""

    name: str

    def translate(
        self,
        order: RawOrder,
        *,
        quote: Quote | None,
        quote_fill: str,
    ) -> PaperOrder: ...


@dataclass(frozen=True)
class NoOpExecutionPolicy:
    """Pass the strategy order through. Default, and the only remote policy."""

    name: str = "NoOp"

    def translate(
        self,
        order: RawOrder,
        *,
        quote: Quote | None,
        quote_fill: str,
    ) -> PaperOrder:
        del quote, quote_fill
        return PaperOrder(
            order_type=order.order_type,
            limit_price=order.limit_price,
            quantity=order.quantity,
            time_in_force=order.time_in_force,
        )


@dataclass(frozen=True)
class OffsetLimitPolicy:
    """Round size, snap price, and turn ``MARKET`` into an offset ``LIMIT``.

    ``quantity_quantum`` defaults to the paper simulator's ``QUANTITY_QUANTUM``.
    ``price_tick``, ``min_quantity``, and ``market_offset`` come from config.
    There is no exchange default for those three.

    ``MARKET`` reference price:

    - ``quote_fill=last``: ``last``
    - ``quote_fill=book``: ``ask`` for BUY, ``bid`` for SELL

    BUY limit is ``reference + market_offset`` (ceiling to ``price_tick``).
    SELL limit is ``reference - market_offset`` (floor to ``price_tick``).
    ``QuoteMatching`` still fills at the touch when that limit crosses.
    """

    quantity_quantum: Decimal = QUANTITY_QUANTUM
    price_tick: Decimal | None = None
    min_quantity: Decimal | None = None
    market_offset: Decimal = Decimal(0)
    time_in_force: TimeInForce = TimeInForce.DAY
    name: str = "OffsetLimit"

    def __post_init__(self) -> None:
        if self.quantity_quantum <= 0:
            raise ValueError("quantity_quantum must be positive")
        if self.price_tick is not None and self.price_tick <= 0:
            raise ValueError("price_tick must be positive")
        if self.min_quantity is not None and self.min_quantity <= 0:
            raise ValueError("min_quantity must be positive")
        if self.market_offset < 0:
            raise ValueError("market_offset must be non-negative")

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> Self:
        unknown = sorted(set(params) - _POLICY_PARAMS)
        if unknown:
            raise ValueError(
                "unknown execution policy params: " + ", ".join(unknown)
            )
        tif = TimeInForce(str(params.get("time_in_force", TimeInForce.DAY)).upper())
        return cls(
            quantity_quantum=_required_positive(
                params, "quantity_quantum", default=QUANTITY_QUANTUM
            ),
            price_tick=_optional_positive(params, "price_tick"),
            min_quantity=_optional_positive(params, "min_quantity"),
            market_offset=_non_negative(params, "market_offset", default=Decimal(0)),
            time_in_force=tif,
        )

    def translate(
        self,
        order: RawOrder,
        *,
        quote: Quote | None,
        quote_fill: str,
    ) -> PaperOrder:
        mode = _quote_fill_mode(quote_fill)
        quantity = self._round_quantity(order.quantity)
        if order.order_type == OrderType.MARKET:
            reference = self._reference_price(side=order.side, quote=quote, quote_fill=mode)
            limit = self._offset_limit(reference, side=order.side)
            order_type = OrderType.LIMIT
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None or order.limit_price <= 0:
                raise ValueError("positive limit_price is required for LIMIT orders")
            limit = order.limit_price
            if self.price_tick is not None:
                limit = _snap_to_tick(limit, self.price_tick, side=order.side)
            if limit <= 0:
                raise ValueError("execution policy limit price must be positive")
            order_type = OrderType.LIMIT
        else:
            raise ValueError(f"unsupported order type: {order.order_type}")
        return PaperOrder(
            order_type=order_type,
            limit_price=limit,
            quantity=quantity,
            time_in_force=self.time_in_force,
        )

    def _round_quantity(self, quantity: Decimal) -> Decimal:
        rounded = _floor_quantum(quantity, self.quantity_quantum)
        if rounded <= 0:
            raise ValueError("execution policy rounded quantity to zero")
        if self.min_quantity is not None and rounded < self.min_quantity:
            raise ValueError(
                "execution policy quantity is below min_quantity: "
                f"{rounded} < {self.min_quantity}"
            )
        return rounded

    def _reference_price(self, *, side: Side, quote: Quote | None, quote_fill: str) -> Decimal:
        if quote is None:
            raise ValueError("execution policy needs a quote to price a MARKET order")
        if quote_fill == "last":
            if quote.last is None or quote.last <= 0:
                raise ValueError("quote_fill=last needs a positive last price")
            return quote.last
        touch = quote.ask if side == Side.BUY else quote.bid
        side_name = "ask" if side == Side.BUY else "bid"
        if touch is None or touch <= 0:
            raise ValueError(f"quote_fill=book needs a positive {side_name}")
        return touch

    def _offset_limit(self, reference: Decimal, *, side: Side) -> Decimal:
        if side == Side.BUY:
            raw = reference + self.market_offset
        else:
            raw = reference - self.market_offset
        if self.price_tick is not None:
            raw = _snap_to_tick(raw, self.price_tick, side=side)
        if raw <= 0:
            raise ValueError("execution policy limit price must be positive")
        return raw


def policy_is_noop(policy: ExecutionPolicy) -> bool:
    """True only for the passthrough policy remote paper is allowed to use."""
    return isinstance(policy, NoOpExecutionPolicy)


__all__ = [
    "REMOTE_POLICY_ERROR",
    "ExecutionPolicy",
    "NoOpExecutionPolicy",
    "OffsetLimitPolicy",
    "PaperOrder",
    "RawOrder",
    "policy_is_noop",
]
