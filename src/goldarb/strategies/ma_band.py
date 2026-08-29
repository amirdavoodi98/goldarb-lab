"""Long-only moving-average band strategy.

Rules:
- Ignore signals until ``window`` closes are available.
- BUY when close < SMA * (1 - buy_band) and the account is flat.
- SELL when close > SMA * (1 + sell_band) and the account is long.

The strategy never feeds the broker; engines inject market data.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from goldarb.data import snapshot_close
from goldarb.simulation.models import Side, decimal_value
from goldarb.strategy import Strategy, StrategyContext

ONE = Decimal(1)
ZERO = Decimal(0)


@dataclass(frozen=True)
class MaBandSignal:
    event_id: str
    timestamp: datetime
    close: Decimal
    sma: Decimal
    side: Side


@dataclass(frozen=True)
class MaBandTick:
    event_id: str
    timestamp: datetime
    close: Decimal
    sma: Decimal | None
    held: Decimal
    raw_side: Side | None
    signal: MaBandSignal | None


def ma_band_side(
    close: Decimal,
    sma: Decimal,
    *,
    buy_band: Decimal,
    sell_band: Decimal,
) -> Side | None:
    if sma <= ZERO:
        return None
    if close < sma * (ONE - buy_band):
        return Side.BUY
    if close > sma * (ONE + sell_band):
        return Side.SELL
    return None


class MaBandStrategy(Strategy):
    name = "ma_band"
    version = "1"

    def __init__(
        self,
        *,
        symbol: str = "طلا",
        window: int = 3,
        buy_band: Decimal | float | str = "0.02",
        sell_band: Decimal | float | str = "0.02",
        quantity: Decimal | float | str = "10",
    ) -> None:
        if window < 1:
            raise ValueError("window must be at least 1")
        buy = decimal_value(buy_band)
        sell = decimal_value(sell_band)
        size = decimal_value(quantity)
        if buy < ZERO or sell < ZERO:
            raise ValueError("bands must be non-negative")
        if size <= ZERO:
            raise ValueError("quantity must be positive")
        self.symbol = symbol
        self.window = window
        self.buy_band = buy
        self.sell_band = sell
        self.quantity = size
        self.closes: deque[Decimal] = deque(maxlen=window)
        self.signals: list[MaBandSignal] = []
        self.last_tick: MaBandTick | None = None

    def on_market_data(self, ctx: StrategyContext) -> None:
        snapshot = ctx.market
        self.last_tick = None
        if snapshot is None:
            return
        close = snapshot_close(snapshot, self.symbol)
        if close is None:
            return
        self.closes.append(close)
        sma = (
            sum(self.closes, ZERO) / Decimal(self.window)
            if len(self.closes) >= self.window
            else None
        )
        held = ctx.held(self.symbol)
        raw_side = (
            ma_band_side(close, sma, buy_band=self.buy_band, sell_band=self.sell_band)
            if sma is not None
            else None
        )
        if raw_side == Side.BUY and held > ZERO:
            tradable = None
        elif raw_side == Side.SELL and held <= ZERO:
            tradable = None
        else:
            tradable = raw_side
        signal: MaBandSignal | None = None
        if tradable is not None and sma is not None:
            signal = MaBandSignal(
                event_id=snapshot.event_id,
                timestamp=snapshot.timestamp,
                close=close,
                sma=sma,
                side=tradable,
            )
            self.signals.append(signal)
            ctx.emit_signal(
                symbol=self.symbol,
                side=tradable,
                extra={"close": str(close), "sma": str(sma)},
            )
            ctx.submit_order(
                symbol=self.symbol,
                side=tradable,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=(
                    f"ma-band:{snapshot.event_id}:{self.symbol}:{tradable.value}"
                ),
            )
        self.last_tick = MaBandTick(
            event_id=snapshot.event_id,
            timestamp=snapshot.timestamp,
            close=close,
            sma=sma,
            held=held,
            raw_side=raw_side,
            signal=signal,
        )
