"""Deterministic order matching and position accounting."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from .models import OrderType, Quote, Side

ZERO = Decimal(0)
QUANTITY_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class MatchResult:
    quantity: Decimal
    price: Decimal | None
    terminal: bool
    rejection: str | None = None


@dataclass(frozen=True)
class PositionResult:
    quantity: Decimal
    average_cost: Decimal
    realized_delta: Decimal


def floor_quantity(value: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_DOWN)


# Backward-compatible private alias.
_floor_quantity = floor_quantity


def match_order(
    *,
    side: Side,
    order_type: OrderType,
    remaining: Decimal,
    limit_price: Decimal | None,
    quote: Quote | None,
    available_depth: Decimal | None,
    cash: Decimal,
    fee_rate: Decimal,
    current_position: Decimal,
    allow_short: bool,
) -> MatchResult:
    """Match one order against one quote without mutating persistence state."""
    if remaining <= ZERO:
        return MatchResult(ZERO, None, True)
    if quote is None:
        return MatchResult(ZERO, None, False)

    price = quote.ask if side == Side.BUY else quote.bid
    if price is None or price <= ZERO:
        price = quote.last
    if price is None or price <= ZERO:
        return MatchResult(ZERO, None, order_type == OrderType.MARKET, "price_unavailable")

    if order_type == OrderType.LIMIT:
        if limit_price is None:
            return MatchResult(ZERO, None, True, "limit_price_required")
        crosses = price <= limit_price if side == Side.BUY else price >= limit_price
        if not crosses:
            return MatchResult(ZERO, price, False)

    fillable = remaining
    if available_depth is not None:
        fillable = min(fillable, max(available_depth, ZERO))
    if fillable <= ZERO:
        return MatchResult(ZERO, price, order_type == OrderType.MARKET)

    if side == Side.BUY:
        unit_cost = price * (Decimal(1) + fee_rate)
        affordable = _floor_quantity(cash / unit_cost) if unit_cost > ZERO else ZERO
        fillable = min(fillable, affordable)
        if fillable <= ZERO:
            return MatchResult(ZERO, price, True, "insufficient_cash")
    elif not allow_short:
        fillable = min(fillable, max(current_position, ZERO))
        if fillable <= ZERO:
            return MatchResult(ZERO, price, True, "short_disabled")

    quantity = _floor_quantity(fillable)
    terminal = order_type == OrderType.MARKET or quantity >= remaining
    return MatchResult(quantity, price, terminal)


def apply_position_fill(
    *,
    current_quantity: Decimal,
    average_cost: Decimal,
    side: Side,
    fill_quantity: Decimal,
    fill_price: Decimal,
) -> PositionResult:
    """Apply a signed fill and return quantity, cost basis, and realized P&L."""
    delta = fill_quantity if side == Side.BUY else -fill_quantity
    new_quantity = current_quantity + delta
    if fill_quantity <= ZERO:
        return PositionResult(current_quantity, average_cost, ZERO)

    same_direction = (
        current_quantity == ZERO
        or (current_quantity > ZERO and delta > ZERO)
        or (current_quantity < ZERO and delta < ZERO)
    )
    if same_direction:
        old_abs = abs(current_quantity)
        new_abs = abs(new_quantity)
        new_average = (
            ((old_abs * average_cost) + (abs(delta) * fill_price)) / new_abs
            if new_abs > ZERO
            else ZERO
        )
        return PositionResult(new_quantity, new_average, ZERO)

    closing = min(abs(current_quantity), abs(delta))
    direction = Decimal(1) if current_quantity > ZERO else Decimal(-1)
    realized = closing * (fill_price - average_cost) * direction
    if new_quantity == ZERO:
        new_average = ZERO
    elif (new_quantity > ZERO) != (current_quantity > ZERO):
        new_average = fill_price
    else:
        new_average = average_cost
    return PositionResult(new_quantity, new_average, realized)


def fee_for(quantity: Decimal, price: Decimal, fee_rate: Decimal) -> Decimal:
    return (quantity * price * fee_rate).quantize(MONEY_QUANTUM)
