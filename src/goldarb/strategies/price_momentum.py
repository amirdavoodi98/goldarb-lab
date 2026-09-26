"""Simple long-only strategy based on one-tick percentage price changes."""

from __future__ import annotations

from decimal import Decimal
from typing import Self

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
        self._validate()
        self._last_price: dict[str, Decimal] = {}

    def _validate(self) -> None:
        if self.quantity <= ZERO:
            raise ValueError("quantity must be positive")
        if self.threshold_pct <= ZERO:
            raise ValueError("threshold_pct must be positive")

    def set_quantity(self, quantity: Decimal | float | str) -> Self:
        self.quantity = decimal_value(quantity)
        self._validate()
        return self

    def set_threshold_pct(self, threshold_pct: Decimal | float | str) -> Self:
        self.threshold_pct = decimal_value(threshold_pct)
        self._validate()
        return self

    def configure(self, **params: object) -> Self:
        if "quantity" in params:
            self.set_quantity(params.pop("quantity"))  # type: ignore[arg-type]
        if "threshold_pct" in params:
            self.set_threshold_pct(params.pop("threshold_pct"))  # type: ignore[arg-type]
        if params:
            raise ValueError(f"unknown strategy param(s): {sorted(params)}")
        return self

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
