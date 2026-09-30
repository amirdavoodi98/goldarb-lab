"""Shared long/short pair helpers for bubble-rank and pair z-score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any, Literal
from uuid import uuid4
from weakref import WeakKeyDictionary

from ..data import snapshot_close
from ..signals.stats import premium_from_row, to_float
from ..simulation.engine import QUANTITY_QUANTUM
from ..simulation.models import (
    Fill,
    MarketSnapshot,
    Order,
    OrderStatus,
    Quote,
    Side,
    decimal_value,
)
from ..strategy import StrategyContext

ZERO = Decimal(0)


def history_reset_requested(ctx: StrategyContext) -> bool:
    return str(ctx.config.get("reset_history", "")).lower() in {"1", "true", "yes"}


def dump_premium_points(
    series: Sequence[tuple[datetime, float]],
) -> list[list[Any]]:
    return [[stamp.isoformat(), value] for stamp, value in series]


def load_premium_points(raw: Any) -> list[tuple[datetime, float]]:
    if not isinstance(raw, list):
        raise ValueError("premium history must be a list")
    points: list[tuple[datetime, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("premium point must be [timestamp, value]")
        points.append((datetime.fromisoformat(str(item[0])), float(item[1])))
    return points


def _order_quantity(value: Decimal) -> Decimal:
    qty = value.quantize(QUANTITY_QUANTUM, rounding=ROUND_DOWN)
    return qty if qty > ZERO else ZERO


def quote_premium(quote: Quote) -> float | None:
    if quote.premium is not None:
        return to_float(quote.premium)
    return premium_from_row(
        {
            "premium": None,
            "close": quote.last,
            "nav": quote.nav,
        }
    )


def snapshot_premium(snapshot: MarketSnapshot, symbol: str) -> float | None:
    for quote in snapshot.quotes:
        if quote.symbol == symbol:
            return quote_premium(quote)
    return None


def premiums_on_snapshot(snapshot: MarketSnapshot) -> dict[str, float]:
    """Premiums for symbols actually quoted on this snapshot."""
    values: dict[str, float] = {}
    for quote in snapshot.quotes:
        premium = quote_premium(quote)
        if premium is None:
            continue
        values[quote.symbol] = premium
    return values


def window_values(
    samples: Sequence[tuple[datetime, float]],
    *,
    now: datetime,
    window: timedelta,
) -> list[float]:
    """Premiums whose timestamp falls in ``[now - window, now]``."""
    if window.total_seconds() <= 0:
        return [value for _, value in samples]
    cutoff = now - window
    return [value for stamp, value in samples if stamp >= cutoff]


def append_premiums(
    history: dict[str, list[tuple[datetime, float]]],
    snapshot: MarketSnapshot,
    *,
    window: timedelta | None = None,
) -> None:
    timestamp = snapshot.timestamp
    cutoff = None if window is None or window.total_seconds() <= 0 else timestamp - window
    for symbol, premium in premiums_on_snapshot(snapshot).items():
        series = history.setdefault(symbol, [])
        if series and timestamp <= series[-1][0]:
            if series[-1][0] == timestamp:
                series[-1] = (timestamp, premium)
            continue
        series.append((timestamp, premium))
        if cutoff is None:
            continue
        keep = 0
        for index, (stamp, _) in enumerate(series):
            if stamp >= cutoff:
                keep = index
                break
        else:
            series.clear()
            continue
        if keep:
            del series[:keep]


@dataclass
class PairIntent:
    """Two-leg order the strategy asked for, applied only after fills."""

    long_sym: str
    short_sym: str
    prefix: str
    long_order_id: str
    short_order_id: str
    event_type: str
    gap: float | None
    label_fa: str | None
    applied: bool = False
    failed: bool = False


_INTENTS: WeakKeyDictionary[StrategyContext, PairIntent] = WeakKeyDictionary()

_IN_FLIGHT = {
    OrderStatus.CREATED,
    OrderStatus.ACCEPTED,
    OrderStatus.PARTIALLY_FILLED,
    OrderStatus.CANCEL_PENDING,
}

_LEG_FAILED = {
    OrderStatus.REJECTED,
    OrderStatus.CANCELLED,
    OrderStatus.EXPIRED,
}

PairFillOutcome = Literal["opened", "failed"]


def current_pair_intent(ctx: StrategyContext) -> PairIntent | None:
    return _INTENTS.get(ctx)


def _order_by_id(ctx: StrategyContext, order_id: str) -> Order | None:
    for order in ctx.orders():
        if order.id == order_id:
            return order
    return None


def _in_flight(order: Order) -> bool:
    return order.status in _IN_FLIGHT


def pair_intent_pending(ctx: StrategyContext, target: tuple[str, str]) -> bool:
    """True while this pair is submitted and at least one leg can still fill."""
    intent = _INTENTS.get(ctx)
    if intent is None or intent.applied or intent.failed:
        return False
    if (intent.long_sym, intent.short_sym) != target:
        return False
    for order_id in (intent.long_order_id, intent.short_order_id):
        order = _order_by_id(ctx, order_id)
        if order is not None and _in_flight(order):
            return True
    return False


def _cancel_in_flight(ctx: StrategyContext, intent: PairIntent) -> None:
    for order_id in (intent.long_order_id, intent.short_order_id):
        order = _order_by_id(ctx, order_id)
        if order is not None and _in_flight(order):
            ctx.cancel_order(order.id)
    intent.failed = True


def _awaiting_fill(long_order: Order, short_order: Order) -> bool:
    if long_order.status == OrderStatus.FILLED and short_order.status == OrderStatus.FILLED:
        return True
    if _in_flight(long_order) or _in_flight(short_order):
        return True
    return long_order.filled_quantity > ZERO or short_order.filled_quantity > ZERO


def flatten_positions(ctx: StrategyContext, *, prefix: str) -> None:
    market = ctx.market
    event_id = "" if market is None else market.event_id
    for position in ctx.positions():
        quantity = position.quantity
        if quantity == ZERO:
            continue
        side = Side.SELL if quantity > ZERO else Side.BUY
        # Unique id: the same event may flatten twice (exit then failed re-entry).
        ctx.submit_order(
            symbol=position.symbol,
            side=side,
            quantity=abs(quantity),
            client_order_id=f"{prefix}:flatten:{event_id}:{position.symbol}:{uuid4().hex[:8]}",
        )


def open_pair(
    ctx: StrategyContext,
    long_sym: str,
    short_sym: str,
    *,
    capital_per_side: Decimal | float | str,
    prefix: str,
    event_type: str = "enter_pair",
    gap: float | None = None,
    label_fa: str | None = None,
) -> bool:
    """Submit both legs and record the intent. Fills update the pair in ``on_fill``.

    A same-tick status other than ``FILLED`` is not a failure and does not flatten.
    Returns False only when the orders were not submitted, or both legs are already
    terminal with no quantity filled.
    """
    market = ctx.market
    if market is None:
        return False
    long_px = snapshot_close(market, long_sym)
    short_px = snapshot_close(market, short_sym)
    if long_px is None or short_px is None or long_px <= ZERO or short_px <= ZERO:
        return False
    capital = decimal_value(capital_per_side)
    short_qty = _order_quantity(capital / short_px)
    long_qty = _order_quantity(capital / long_px)
    if short_qty <= ZERO or long_qty <= ZERO:
        return False
    target = (long_sym, short_sym)
    previous = _INTENTS.get(ctx)
    if previous is not None and not previous.applied and not previous.failed:
        if pair_intent_pending(ctx, target):
            return True
        if (previous.long_sym, previous.short_sym) != target:
            _cancel_in_flight(ctx, previous)
    event_id = market.event_id
    short_order = ctx.submit_order(
        symbol=short_sym,
        side=Side.SELL,
        quantity=short_qty,
        client_order_id=f"{prefix}:short:{event_id}:{short_sym}",
    )
    long_order = ctx.submit_order(
        symbol=long_sym,
        side=Side.BUY,
        quantity=long_qty,
        client_order_id=f"{prefix}:long:{event_id}:{long_sym}",
    )
    intent = PairIntent(
        long_sym=long_sym,
        short_sym=short_sym,
        prefix=prefix,
        long_order_id=long_order.id,
        short_order_id=short_order.id,
        event_type=event_type,
        gap=gap,
        label_fa=label_fa,
    )
    _INTENTS[ctx] = intent
    if not _awaiting_fill(long_order, short_order):
        intent.failed = True
        return False
    return True


def consume_pair_fill(ctx: StrategyContext, fill: Fill) -> PairFillOutcome | None:
    """Update a recorded pair from a fill. Flatten a filled leg if the other died."""
    intent = _INTENTS.get(ctx)
    if intent is None or intent.applied or intent.failed:
        return None
    if fill.order_id not in {intent.long_order_id, intent.short_order_id}:
        return None
    long_order = _order_by_id(ctx, intent.long_order_id)
    short_order = _order_by_id(ctx, intent.short_order_id)
    if long_order is None or short_order is None:
        return None
    if (
        long_order.status == OrderStatus.FILLED
        and short_order.status == OrderStatus.FILLED
    ):
        intent.applied = True
        return "opened"
    if long_order.status in _LEG_FAILED or short_order.status in _LEG_FAILED:
        filled = long_order.filled_quantity > ZERO or short_order.filled_quantity > ZERO
        intent.failed = True
        if filled:
            flatten_positions(ctx, prefix=intent.prefix)
        return "failed"
    return None


def pair_event(
    *,
    event_type: str,
    long_sym: str | None,
    short_sym: str | None,
    gap: float | None,
    label_fa: str | None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "long": long_sym,
        "short": short_sym,
        "gap": gap,
        "label_fa": label_fa,
    }
    if extra:
        payload.update(dict(extra))
    return payload
