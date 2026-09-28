"""Long-only strategy that follows a run of consecutive price moves.

Buy after ``length`` strict upticks while flat. Sell after ``length`` strict
downticks while long. A flat or opposite tick breaks the run.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal

from ..simulation.models import Side, decimal_value
from ..strategy import Strategy, StrategyContext

ZERO = Decimal(0)
HUNDRED = Decimal(100)


class StreakStrategy(Strategy):
    """Trade only when the last ``length`` steps all point the same way."""

    name = "streak"
    version = "1"

    def __init__(
        self,
        *,
        quantity: Decimal | float | str = "1",
        length: int | str = 3,
        min_step_pct: Decimal | float | str = "0",
    ) -> None:
        self.quantity = decimal_value(quantity)
        self.length = int(length)
        self.min_step_pct = decimal_value(min_step_pct)
        self._validate()
        self._prices: dict[str, deque[Decimal]] = {}

    def _validate(self) -> None:
        if self.quantity <= ZERO:
            raise ValueError("quantity must be positive")
        if self.length < 2:
            raise ValueError("length must be at least 2")
        if self.min_step_pct < ZERO:
            raise ValueError("min_step_pct must be non-negative")

    def on_start(self, ctx: StrategyContext) -> None:
        del ctx
        self._prices.clear()

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        for quote in snapshot.quotes:
            price = quote.last
            if price is None or price <= ZERO:
                self._prices.pop(quote.symbol, None)
                continue
            window = self._prices.get(quote.symbol)
            if window is None or window.maxlen != self.length + 1:
                window = deque(maxlen=self.length + 1)
                self._prices[quote.symbol] = window
            window.append(price)
            side = _streak_side(window, self.min_step_pct)
            held = ctx.held(quote.symbol)
            if side == Side.BUY and held <= ZERO:
                pass
            elif side == Side.SELL and held > ZERO:
                pass
            else:
                continue
            ctx.emit_signal(
                symbol=quote.symbol,
                side=side,
                extra={
                    "length": str(self.length),
                    "price": str(price),
                },
            )
            ctx.submit_order(
                symbol=quote.symbol,
                side=side,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=(
                    f"{self.name}:{snapshot.event_id}:{quote.symbol}:{side.value}"
                ),
            )


def _streak_side(prices: deque[Decimal], min_step_pct: Decimal) -> Side | None:
    """Return BUY or SELL when every step in the window shares one direction."""
    if len(prices) < 2 or prices.maxlen is None or len(prices) < prices.maxlen:
        return None
    ups = 0
    downs = 0
    steps = 0
    previous: Decimal | None = None
    for price in prices:
        if previous is not None:
            steps += 1
            if previous <= ZERO:
                return None
            change_pct = ((price - previous) / previous) * HUNDRED
            if change_pct > ZERO and change_pct >= min_step_pct:
                ups += 1
            elif change_pct < ZERO and -change_pct >= min_step_pct:
                downs += 1
        previous = price
    if steps == 0:
        return None
    if ups == steps:
        return Side.BUY
    if downs == steps:
        return Side.SELL
    return None
