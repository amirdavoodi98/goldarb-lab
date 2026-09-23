"""Matching engines propose fills; they never mutate orders or portfolios."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from .engine import ZERO, floor_quantity
from .models import MatchResult, Order, OrderType, ProposedFill, Quote, Side


class MatchingEngine(Protocol):
    name: str

    def match_order(
        self,
        order: Order,
        *,
        quote: Quote | None,
        available_depth: Decimal | None,
        cash: Decimal,
        fee_rate: Decimal,
        current_position: Decimal,
        allow_short: bool,
    ) -> MatchResult: ...


class QuoteMatching:
    """Cross against best bid/ask (fallback last), respecting limit and depth."""

    name: str = "QuoteMatching"

    def match_order(
        self,
        order: Order,
        *,
        quote: Quote | None,
        available_depth: Decimal | None,
        cash: Decimal,
        fee_rate: Decimal,
        current_position: Decimal,
        allow_short: bool,
    ) -> MatchResult:
        remaining = order.remaining_quantity
        if remaining <= ZERO:
            return MatchResult(None, True)
        if quote is None:
            return MatchResult(None, False)

        raw = quote.ask if order.side == Side.BUY else quote.bid
        if raw is None or raw <= ZERO:
            raw = quote.last
        if raw is None or raw <= ZERO:
            return MatchResult(
                None,
                order.order_type == OrderType.MARKET,
                "price_unavailable",
            )

        if order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                return MatchResult(None, True, "limit_price_required")
            crosses = (
                raw <= order.limit_price
                if order.side == Side.BUY
                else raw >= order.limit_price
            )
            if not crosses:
                return MatchResult(None, False)

        fillable = remaining
        if available_depth is not None:
            fillable = min(fillable, max(available_depth, ZERO))
        if fillable <= ZERO:
            return MatchResult(None, order.order_type == OrderType.MARKET)

        if order.side == Side.BUY:
            unit_cost = raw * (Decimal(1) + fee_rate)
            affordable = floor_quantity(cash / unit_cost) if unit_cost > ZERO else ZERO
            fillable = min(fillable, affordable)
            if fillable <= ZERO:
                return MatchResult(None, True, "insufficient_cash")
        elif not allow_short:
            fillable = min(fillable, max(current_position, ZERO))
            if fillable <= ZERO:
                return MatchResult(None, True, "short_disabled")

        quantity = floor_quantity(fillable)
        if quantity <= ZERO:
            return MatchResult(None, order.order_type == OrderType.MARKET)
        terminal = order.order_type == OrderType.MARKET or quantity >= remaining
        return MatchResult(ProposedFill(quantity, raw), terminal)


class LastPriceMatching:
    """Last-trade matching via synthetic touch; optional alternative engine."""

    name: str = "LastPriceMatching"

    def match_order(
        self,
        order: Order,
        *,
        quote: Quote | None,
        available_depth: Decimal | None,
        cash: Decimal,
        fee_rate: Decimal,
        current_position: Decimal,
        allow_short: bool,
    ) -> MatchResult:
        del available_depth
        if quote is None or quote.last is None or quote.last <= ZERO:
            return MatchResult(None, order.order_type == OrderType.MARKET, "price_unavailable")
        synthetic = Quote(
            symbol=order.symbol,
            bid=quote.last,
            ask=quote.last,
            last=quote.last,
        )
        return QuoteMatching().match_order(
            order,
            quote=synthetic,
            available_depth=None,
            cash=cash,
            fee_rate=fee_rate,
            current_position=current_position,
            allow_short=allow_short,
        )
