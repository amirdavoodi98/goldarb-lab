"""Simple long-only strategy based on one-tick percentage price changes."""

from __future__ import annotations

from decimal import Decimal

from ..simulation.models import Side, decimal_value
from ..strategy import Strategy, StrategyContext

ZERO = Decimal(0)
HUNDRED = Decimal(100)


class PriceMomentumStrategy(Strategy):
    """Buy on an upward move and exit the long on a downward move."""

    name = "price_momentum"
    version = "1"

    def __init__(
        self,
        *,
        quantity: Decimal | float | str = "1",
        threshold_pct: Decimal | float | str = "0.1",
    ) -> None:
        self.quantity = decimal_value(quantity)
        self.threshold_pct = decimal_value(threshold_pct)
        if self.quantity <= ZERO:
            raise ValueError("quantity must be positive")
        if self.threshold_pct <= ZERO:
            raise ValueError("threshold_pct must be positive")
        self._last_price: dict[str, Decimal] = {}

    def on_start(self, ctx: StrategyContext) -> None:
        del ctx
        self._last_price.clear()

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        for quote in snapshot.quotes:
            price = quote.last
            if price is None or price <= ZERO:
                continue
            previous = self._last_price.get(quote.symbol)
            self._last_price[quote.symbol] = price
            if previous is None or previous <= ZERO:
                continue
            change_pct = ((price - previous) / previous) * HUNDRED
            held = ctx.held(quote.symbol)
            if change_pct >= self.threshold_pct and held <= ZERO:
                side = Side.BUY
            elif change_pct <= -self.threshold_pct and held > ZERO:
                side = Side.SELL
            else:
                continue
            ctx.emit_signal(
                symbol=quote.symbol,
                side=side,
                extra={
                    "change_pct": str(change_pct),
                    "previous_price": str(previous),
                    "price": str(price),
                },
            )
            ctx.submit_order(
                symbol=quote.symbol,
                side=side,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=(f"{self.name}:{snapshot.event_id}:{quote.symbol}:{side.value}"),
            )
