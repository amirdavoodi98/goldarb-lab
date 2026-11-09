from decimal import Decimal

from goldarb.simulation.models import Side
from goldarb.strategy import Strategy, StrategyContext

ZERO = Decimal(0)


class OddEvenStrategy(Strategy):
    name = "odd_even"
    version = "1"

    def __init__(self, *, quantity: str = "1", symbol: str = "طلا") -> None:
        self.quantity = quantity
        self.symbol = symbol

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        if snapshot is None:
            return
        even = ctx.clock.second % 2 == 0
        for quote in snapshot.quotes:
            if quote.symbol != self.symbol or quote.last is None:
                continue
            held = ctx.held(quote.symbol)
            if even and held <= ZERO:
                side = Side.BUY
            elif (not even) and held > ZERO:
                side = Side.SELL
            else:
                continue
            ctx.emit_signal(symbol=quote.symbol, side=side, extra={"price": str(quote.last)})
            ctx.submit_order(
                symbol=quote.symbol,
                side=side,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=f"{self.name}:{snapshot.event_id}:{quote.symbol}:{side.value}",
            )
