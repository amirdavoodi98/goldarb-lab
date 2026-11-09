from decimal import Decimal

from goldarb import AppConfig, StrategyRunner
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


def main() -> None:
    config = AppConfig.from_file("examples/runtime.odd_even.yaml")
    strategy = OddEvenStrategy(**config.strategy.params)
    result = StrategyRunner.from_config(config=config).run(strategy=strategy)

    print(
        f"mode={config.runtime.mode} "
        f"signals={result.metrics.n_signals} "
        f"orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity} "
        f"pnl={result.metrics.total_pnl}"
    )
    for signal in result.signals[:8]:
        print(f"  {signal.timestamp} {signal.side.value} {signal.symbol} {signal.extra}")


if __name__ == "__main__":
    main()
