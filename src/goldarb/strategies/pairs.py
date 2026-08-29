"""Shared long/short pair helpers for bubble-rank and pair z-score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from typing import Any
from uuid import uuid4

from goldarb.data import snapshot_close
from goldarb.signals.stats import premium_from_row, to_float
from goldarb.simulation.engine import QUANTITY_QUANTUM
from goldarb.simulation.models import (
    MarketSnapshot,
    OrderStatus,
    Quote,
    Side,
    decimal_value,
)
from goldarb.strategy import StrategyContext

ZERO = Decimal(0)


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
) -> bool:
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
    if (
        short_order.status == OrderStatus.FILLED
        and long_order.status == OrderStatus.FILLED
    ):
        return True
    flatten_positions(ctx, prefix=prefix)
    return False


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
