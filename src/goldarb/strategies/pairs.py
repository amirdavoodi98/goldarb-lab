"""Shared long/short pair helpers for bubble-rank and pair z-score."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from goldarb.data import snapshot_close
from goldarb.signals.stats import premium_from_row, to_float
from goldarb.simulation.models import MarketSnapshot, Quote, Side, decimal_value
from goldarb.strategy import StrategyContext

ZERO = Decimal(0)


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


def append_premiums(
    history: dict[str, list[float]],
    snapshot: MarketSnapshot,
) -> None:
    for quote in snapshot.quotes:
        premium = quote_premium(quote)
        if premium is None:
            continue
        history.setdefault(quote.symbol, []).append(premium)


def flatten_positions(ctx: StrategyContext, *, prefix: str) -> None:
    market = ctx.market
    event_id = "" if market is None else market.event_id
    for position in ctx.positions():
        quantity = position.quantity
        if quantity == ZERO:
            continue
        side = Side.SELL if quantity > ZERO else Side.BUY
        ctx.submit_order(
            symbol=position.symbol,
            side=side,
            quantity=abs(quantity),
            client_order_id=f"{prefix}:flatten:{event_id}:{position.symbol}",
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
    event_id = market.event_id
    ctx.submit_order(
        symbol=short_sym,
        side=Side.SELL,
        quantity=capital / short_px,
        client_order_id=f"{prefix}:short:{event_id}:{short_sym}",
    )
    ctx.submit_order(
        symbol=long_sym,
        side=Side.BUY,
        quantity=capital / long_px,
        client_order_id=f"{prefix}:long:{event_id}:{long_sym}",
    )
    return True


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
