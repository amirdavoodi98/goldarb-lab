"""Iran cash-market session helpers for the local MA-band simulator."""

from __future__ import annotations

from decimal import Decimal

from goldarb.session import (
    SESSION_CLOSE,
    SESSION_OPEN,
    TEHRAN,
    filter_session_snapshots,
    in_iran_session,
    is_iran_trading_day,
    session_bounds,
    snapshot_from_live,
)
from goldarb.strategies.ma_band import MaBandTick

__all__ = [
    "SESSION_CLOSE",
    "SESSION_OPEN",
    "TEHRAN",
    "filter_session_snapshots",
    "format_tick",
    "in_iran_session",
    "is_iran_trading_day",
    "session_bounds",
    "snapshot_from_live",
    "tick_record",
]


def format_tick(
    tick: MaBandTick,
    *,
    symbol: str,
    buy_band: Decimal,
    sell_band: Decimal,
) -> str:
    local = tick.timestamp.astimezone(TEHRAN).strftime("%H:%M:%S")
    sma_text = f"{tick.sma:.4f}" if tick.sma is not None else "warmup"
    if tick.sma and tick.sma > 0:
        vs_sma = (tick.close / tick.sma - 1) * Decimal(100)
        vs_text = f"{vs_sma:+.4f}%"
    else:
        vs_text = "n/a"
    held = "long" if tick.held > 0 else "flat"
    buy_pct = f"{float(buy_band) * 100:.2f}"
    sell_pct = f"{float(sell_band) * 100:.2f}"
    line = (
        f"{local}  {symbol}  close={tick.close}  sma={sma_text}  "
        f"vs_sma={vs_text}  band=-{buy_pct}%/+{sell_pct}%  {held}"
    )
    if tick.signal is not None:
        return f"SIGNAL {tick.signal.side.value}  {line}"
    return line


def tick_record(tick: MaBandTick, *, symbol: str) -> dict[str, str]:
    return {
        "event_id": tick.event_id,
        "timestamp": tick.timestamp.isoformat(),
        "symbol": symbol,
        "close": str(tick.close),
        "sma": "" if tick.sma is None else str(tick.sma),
        "held": str(tick.held),
        "raw_side": "" if tick.raw_side is None else tick.raw_side.value,
        "signal": "" if tick.signal is None else tick.signal.side.value,
    }
