"""Long-only moving-average band strategy for ``LocalSimulator``.

The simulator stays a paper broker. This module owns the signal, injects
snapshots, and submits MARKET orders with stable ``client_order_id`` values.

Rules:
- Ignore signals until ``window`` closes are available.
- BUY when close < SMA * (1 - buy_band) and the account is flat.
- SELL when close > SMA * (1 + sell_band) and the account is long.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from goldarb.simulation import (
    Fill,
    LocalSimulator,
    MarketSnapshot,
    Order,
    Portfolio,
    Quote,
    Side,
)
from goldarb.simulation.models import decimal_value

ONE = Decimal(1)
ZERO = Decimal(0)


@dataclass(frozen=True)
class MaBandSignal:
    event_id: str
    timestamp: datetime
    close: Decimal
    sma: Decimal
    side: Side


@dataclass
class MaBandResult:
    account_id: str
    portfolio: Portfolio
    signals: list[MaBandSignal] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)


@dataclass(frozen=True)
class MaBandTick:
    event_id: str
    timestamp: datetime
    close: Decimal
    sma: Decimal | None
    held: Decimal
    raw_side: Side | None
    signal: MaBandSignal | None


def snapshot_close(snapshot: MarketSnapshot, symbol: str) -> Decimal | None:
    """Prefer last; otherwise midpoint, then a single-sided quote."""
    for quote in snapshot.quotes:
        if quote.symbol != symbol:
            continue
        if quote.last is not None and quote.last > ZERO:
            return quote.last
        if (
            quote.bid is not None
            and quote.ask is not None
            and quote.bid > ZERO
            and quote.ask > ZERO
        ):
            return (quote.bid + quote.ask) / Decimal(2)
        if quote.bid is not None and quote.bid > ZERO:
            return quote.bid
        if quote.ask is not None and quote.ask > ZERO:
            return quote.ask
    return None


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


def snapshots_from_closes(
    closes: Sequence[Decimal | float | str],
    *,
    symbol: str = "طلا",
    start: datetime | None = None,
    step: timedelta = timedelta(minutes=1),
) -> list[MarketSnapshot]:
    """Build last-only snapshots from a close series (no order-book depth)."""
    origin = start or datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    snapshots: list[MarketSnapshot] = []
    for index, raw in enumerate(closes):
        close = decimal_value(raw)
        timestamp = origin + step * index
        snapshots.append(
            MarketSnapshot(
                event_id=f"ma-band:{symbol}:{timestamp.isoformat()}",
                timestamp=timestamp,
                quotes=(Quote(symbol=symbol, last=close),),
            )
        )
    return snapshots


def snapshots_from_bars(
    bars: Sequence[dict[str, Any]],
    *,
    symbol: str = "طلا",
) -> list[MarketSnapshot]:
    """Convert archive/API bar dicts into timezone-aware snapshots."""
    snapshots: list[MarketSnapshot] = []
    for row in bars:
        close = _bar_close(row)
        timestamp = _bar_timestamp(row)
        if close is None or timestamp is None:
            continue
        snapshots.append(
            MarketSnapshot(
                event_id=f"ma-band:{symbol}:{timestamp.isoformat()}",
                timestamp=timestamp,
                quotes=(Quote(symbol=symbol, last=close),),
            )
        )
    return snapshots


class MaBandEngine:
    """Incremental MA-band trader; call ``on_snapshot`` as live bars arrive."""

    def __init__(
        self,
        *,
        simulator: LocalSimulator,
        account_id: str,
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
        self.simulator = simulator
        self.account_id = account_id
        self.symbol = symbol
        self.window = window
        self.buy_band = buy
        self.sell_band = sell
        self.quantity = size
        self.closes: deque[Decimal] = deque(maxlen=window)
        self.signals: list[MaBandSignal] = []

    def on_snapshot(self, snapshot: MarketSnapshot) -> MaBandTick | None:
        self.simulator.feed(snapshot)
        close = snapshot_close(snapshot, self.symbol)
        if close is None:
            return None
        self.closes.append(close)
        sma = (
            sum(self.closes, ZERO) / Decimal(self.window)
            if len(self.closes) >= self.window
            else None
        )
        held = _held_quantity(self.simulator, self.account_id, self.symbol)
        raw_side = (
            ma_band_side(close, sma, buy_band=self.buy_band, sell_band=self.sell_band)
            if sma is not None
            else None
        )
        signal: MaBandSignal | None = None
        if raw_side == Side.BUY and held > ZERO:
            raw_side_for_trade = None
        elif raw_side == Side.SELL and held <= ZERO:
            raw_side_for_trade = None
        else:
            raw_side_for_trade = raw_side
        if raw_side_for_trade is not None and sma is not None:
            signal = MaBandSignal(
                event_id=snapshot.event_id,
                timestamp=snapshot.timestamp,
                close=close,
                sma=sma,
                side=raw_side_for_trade,
            )
            self.signals.append(signal)
            self.simulator.submit_order(
                self.account_id,
                symbol=self.symbol,
                side=raw_side_for_trade,
                quantity=self.quantity,
                order_type="MARKET",
                client_order_id=(
                    f"ma-band:{snapshot.event_id}:{self.symbol}:{raw_side_for_trade.value}"
                ),
            )
        return MaBandTick(
            event_id=snapshot.event_id,
            timestamp=snapshot.timestamp,
            close=close,
            sma=sma,
            held=held,
            raw_side=raw_side,
            signal=signal,
        )

    def result(self) -> MaBandResult:
        return MaBandResult(
            account_id=self.account_id,
            portfolio=self.simulator.portfolio(self.account_id),
            signals=self.signals,
            orders=self.simulator.list_orders(self.account_id),
            fills=self.simulator.list_fills(self.account_id),
        )


def run_ma_band(
    snapshots: Sequence[MarketSnapshot],
    *,
    simulator: LocalSimulator,
    account_id: str,
    symbol: str = "طلا",
    window: int = 3,
    buy_band: Decimal | float | str = "0.02",
    sell_band: Decimal | float | str = "0.02",
    quantity: Decimal | float | str = "10",
) -> MaBandResult:
    """Replay snapshots through ``LocalSimulator`` and trade the MA band."""
    engine = MaBandEngine(
        simulator=simulator,
        account_id=account_id,
        symbol=symbol,
        window=window,
        buy_band=buy_band,
        sell_band=sell_band,
        quantity=quantity,
    )
    for snapshot in snapshots:
        engine.on_snapshot(snapshot)
    return engine.result()


def _held_quantity(simulator: LocalSimulator, account_id: str, symbol: str) -> Decimal:
    for position in simulator.portfolio(account_id).positions:
        if position.symbol == symbol:
            return position.quantity
    return ZERO


def _bar_close(row: dict[str, Any]) -> Decimal | None:
    for key in ("close", "close_price"):
        value = row.get(key)
        if value is None:
            continue
        close = decimal_value(value)
        if close > ZERO:
            return close
    return None


def _bar_timestamp(row: dict[str, Any]) -> datetime | None:
    raw = row.get("bar_at") or row.get("date")
    if not raw:
        return None
    timestamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp
