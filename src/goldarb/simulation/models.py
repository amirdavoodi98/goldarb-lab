"""Typed domain contracts for local/remote paper simulation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class DomainError(ValueError):
    """Invalid domain transition or invariant violation."""


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(StrEnum):
    DAY = "DAY"
    IOC = "IOC"
    FOK = "FOK"
    GTC = "GTC"


class OrderStatus(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    OPEN = "ACCEPTED"  # legacy alias for resting accepted orders
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class OrderEventType(StrEnum):
    CREATED = "CREATED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    FILL = "FILL"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


WORKING_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.ACCEPTED,
        OrderStatus.PARTIALLY_FILLED,
        OrderStatus.CANCEL_PENDING,
    }
)

TERMINAL_STATUSES: frozenset[OrderStatus] = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


@dataclass(frozen=True)
class Quote:
    symbol: str
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    premium: Decimal | None = None
    nav: Decimal | None = None

    def __post_init__(self) -> None:
        if not str(self.symbol).strip():
            raise DomainError("quote.symbol is required")


@dataclass(frozen=True)
class MarketSnapshot:
    event_id: str
    timestamp: datetime
    quotes: tuple[Quote, ...]

    def __post_init__(self) -> None:
        if not str(self.event_id).strip():
            raise DomainError("event_id is required")
        if self.timestamp.tzinfo is None:
            raise DomainError("snapshot timestamp must be timezone-aware")


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
    broker: str = ""

    def __post_init__(self) -> None:
        if self.initial_cash <= 0:
            raise DomainError("initial_cash must be positive")
        if self.fee_rate < 0 or self.fee_rate >= 1:
            raise DomainError("fee_rate must be in [0, 1)")
        if self.fees_paid < 0:
            raise DomainError("fees_paid must be non-negative")


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
    broker: str = ""
    time_in_force: TimeInForce = TimeInForce.DAY
    rejection_code: str | None = None
    avg_fill_price: Decimal | None = None
    created_at: str | None = None
    accepted_at: str | None = None
    closed_at: str | None = None
    active_at: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainError("order.quantity must be positive")
        if self.filled_quantity < 0:
            raise DomainError("filled_quantity must be non-negative")
        if self.filled_quantity > self.quantity:
            raise DomainError("filled_quantity cannot exceed quantity")
        if self.order_type == OrderType.LIMIT and (
            self.limit_price is None or self.limit_price <= 0
        ):
            raise DomainError("positive limit_price is required for LIMIT orders")
        if not str(self.symbol).strip():
            raise DomainError("order.symbol is required")

    @property
    def remaining_quantity(self) -> Decimal:
        return self.quantity - self.filled_quantity

    @property
    def is_working(self) -> bool:
        return self.status in WORKING_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


@dataclass(frozen=True)
class Fill:
    id: str
    order_id: str
    market_event_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    filled_at: str
    raw_match_price: Decimal | None = None
    market_timestamp: str | None = None
    execution_timestamp: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainError("fill.quantity must be positive")
        if self.price <= 0:
            raise DomainError("fill.price must be positive")
        if self.fee < 0:
            raise DomainError("fill.fee must be non-negative")
        if self.raw_match_price is not None and self.raw_match_price <= 0:
            raise DomainError("raw_match_price must be positive when set")


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
    """Derived trading-state view; ``cash`` mirrors Account ledger truth."""

    account_id: str
    cash: Decimal
    equity: Decimal
    fees_paid: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    positions: tuple[Position, ...]
    as_of: str | None


@dataclass(frozen=True)
class ProposedFill:
    quantity: Decimal
    raw_match_price: Decimal

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainError("proposed fill quantity must be positive")
        if self.raw_match_price <= 0:
            raise DomainError("raw_match_price must be positive")


@dataclass(frozen=True)
class MatchResult:
    """Matching proposal only — never mutates order/account state."""

    proposed: ProposedFill | None
    terminal: bool
    rejection: str | None = None

    @property
    def quantity(self) -> Decimal:
        return self.proposed.quantity if self.proposed else Decimal(0)

    @property
    def price(self) -> Decimal | None:
        """Backward-compatible alias for raw_match_price."""
        return None if self.proposed is None else self.proposed.raw_match_price

    @property
    def raw_match_price(self) -> Decimal | None:
        return None if self.proposed is None else self.proposed.raw_match_price


@dataclass(frozen=True)
class OrderEvent:
    id: str
    order_id: str
    event_type: OrderEventType
    timestamp: str
    payload: dict[str, str] = field(default_factory=dict)


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
