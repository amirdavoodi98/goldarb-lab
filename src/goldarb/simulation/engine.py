"""Quantity rounding, fill fees, and position accounting.

Quote matching lives in ``matching.QuoteMatching``. This module only
supplies the shared numeric helpers those collaborators call.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from .models import Side

ZERO = Decimal(0)
QUANTITY_QUANTUM = Decimal("0.00000001")
MONEY_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class PositionResult:
    quantity: Decimal
    average_cost: Decimal
    realized_delta: Decimal


def floor_quantity(value: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    return value.quantize(QUANTITY_QUANTUM, rounding=ROUND_DOWN)


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
