"""Long-only sign-of-bubble strategy.

Buy when NAV premium is negative (discount). Sell when it is positive.
Does nothing at zero or missing premium, and does not add to an open long.
"""

from __future__ import annotations

from decimal import Decimal

from goldarb.simulation.models import Side, decimal_value
from goldarb.strategy import Strategy, StrategyContext

ZERO = Decimal(0)


class BubbleSignStrategy(Strategy):
    name = "bubble_sign"
    version = "1"

    def __init__(self, *, quantity: Decimal | float | str = "1") -> None:
        size = decimal_value(quantity)
        if size <= ZERO:
            raise ValueError("quantity must be positive")
        self.quantity = size

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        for quote in snapshot.quotes:
            if quote.premium is None:
                continue
            held = ctx.held(quote.symbol)
            if quote.premium < ZERO and held <= ZERO:
                side = Side.BUY
            elif quote.premium > ZERO and held > ZERO:
                side = Side.SELL
            else:
                continue
            ctx.emit_signal(
                symbol=quote.symbol,
                side=side,
                extra={"premium": str(quote.premium)},
            )
            ctx.submit_order(
                symbol=quote.symbol,
                side=side,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=f"{self.name}:{snapshot.event_id}:{quote.symbol}:{side.value}",
            )
