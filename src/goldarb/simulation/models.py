"""Typed contracts shared by local and remote paper simulators."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None


@dataclass(frozen=True)
class MarketSnapshot:
    event_id: str
    timestamp: datetime
    quotes: tuple[Quote, ...]


@dataclass(frozen=True)
class Account:
    id: str
    label: str
    status: str
    initial_cash: Decimal
    cash: Decimal
    fee_rate: Decimal
    allow_short: bool
    fees_paid: Decimal
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Order:
    id: str
    account_id: str
    client_order_id: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    filled_quantity: Decimal
    limit_price: Decimal | None
    status: OrderStatus
    submitted_at: str
    updated_at: str


@dataclass(frozen=True)
class Fill:
    id: str
    order_id: str
    market_event_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_at: str


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: Decimal
    average_cost: Decimal
    realized_pnl: Decimal
    mark_price: Decimal | None
    unrealized_pnl: Decimal
    market_value: Decimal


@dataclass(frozen=True)
class Portfolio:
    account_id: str
    cash: Decimal
    equity: Decimal
    fees_paid: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    positions: tuple[Position, ...]
    as_of: str | None


def decimal_value(value: Decimal | float | str) -> Decimal:
    """Parse public numeric input without inheriting binary-float artifacts."""
    return Decimal(str(value))


def jsonable(value: Any) -> Any:
    """Convert SDK records to canonical JSON-compatible values."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value
