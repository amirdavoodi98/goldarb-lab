"""Iran cash-market session helpers for the local MA-band simulator."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from ma_band import MaBandTick

from goldarb.simulation import MarketSnapshot, Quote
from goldarb.simulation.models import decimal_value

TEHRAN = ZoneInfo("Asia/Tehran")
SESSION_OPEN = time(12, 0)
SESSION_CLOSE = time(17, 0)
ZERO = Decimal(0)


def session_bounds(day: date | None = None) -> tuple[datetime, datetime]:
    """Return [12:00, 17:00] Asia/Tehran for ``day`` (default: today in Tehran)."""
    local_day = day or datetime.now(TEHRAN).date()
    start = datetime.combine(local_day, SESSION_OPEN, tzinfo=TEHRAN)
    end = datetime.combine(local_day, SESSION_CLOSE, tzinfo=TEHRAN)
    return start, end


def in_iran_session(timestamp: datetime, *, day: date | None = None) -> bool:
    """True when ``timestamp`` falls in 12:00–17:00 Iran time, inclusive of 17:00."""
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    local = timestamp.astimezone(TEHRAN)
    if day is not None and local.date() != day:
        return False
    start, end = session_bounds(local.date())
    return start <= local <= end


def filter_session_snapshots(
    snapshots: Sequence[MarketSnapshot],
    *,
    day: date | None = None,
) -> list[MarketSnapshot]:
    return [item for item in snapshots if in_iran_session(item.timestamp, day=day)]


def snapshot_from_live(
    *,
    symbol: str,
    last_price: dict[str, Any],
    orderbook: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> MarketSnapshot | None:
    """Build a snapshot from last-price (+ optional best bid/ask)."""
    clock = now or datetime.now(TEHRAN)
    timestamp = _live_timestamp(last_price, orderbook, clock)
    stale = str(last_price.get("status") or "") == "stale"
    last = None if stale else _positive_decimal(
        last_price.get("last_price")
        or last_price.get("display_price")
        or last_price.get("close_price")
        or last_price.get("close")
    )
    book = orderbook or {}
    bid = _positive_decimal(book.get("best_bid"))
    ask = _positive_decimal(book.get("best_ask"))
    buy = book.get("buy_orders") or []
    sell = book.get("sell_orders") or []
    bid_size = _positive_decimal(buy[0].get("volume") if buy else None)
    ask_size = _positive_decimal(sell[0].get("volume") if sell else None)
    if last is None and bid is not None and ask is not None:
        last = (bid + ask) / Decimal(2)
    if last is None and bid is None and ask is None:
        return None
    if timestamp < clock and (clock - timestamp).total_seconds() > 60:
        timestamp = clock
    return MarketSnapshot(
        event_id=f"live:{symbol}:{last}:{bid}:{ask}",
        timestamp=timestamp,
        quotes=(
            Quote(
                symbol=symbol,
                last=last,
                bid=bid,
                ask=ask,
                bid_size=bid_size,
                ask_size=ask_size,
            ),
        ),
    )


def format_tick(
    tick: MaBandTick,
    *,
    symbol: str,
    buy_band: Decimal,
    sell_band: Decimal,
) -> str:
    local = tick.timestamp.astimezone(TEHRAN).strftime("%H:%M:%S")
    sma_text = f"{tick.sma:.4f}" if tick.sma is not None else "warmup"
    if tick.sma and tick.sma > ZERO:
        vs_sma = (tick.close / tick.sma - 1) * Decimal(100)
        vs_text = f"{vs_sma:+.4f}%"
    else:
        vs_text = "n/a"
    held = "long" if tick.held > ZERO else "flat"
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


def _positive_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    number = decimal_value(value)
    return number if number > ZERO else None


def _live_timestamp(
    last_price: dict[str, Any],
    orderbook: dict[str, Any] | None,
    fallback: datetime,
) -> datetime:
    for payload in (last_price, orderbook or {}):
        for key in ("fetched_at", "last_update", "as_of"):
            parsed = _parse_aware(payload.get(key))
            if parsed is not None:
                return parsed
    even = _from_d_even_h_even(last_price.get("d_even"), last_price.get("h_even"))
    if even is not None:
        return even
    if fallback.tzinfo is None:
        return fallback.replace(tzinfo=TEHRAN)
    return fallback


def _parse_aware(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TEHRAN)
    return parsed


def _from_d_even_h_even(d_even: Any, h_even: Any) -> datetime | None:
    day = str(d_even or "").strip()
    clock = str(h_even or "").strip().replace(":", "")
    if len(day) != 8 or not day.isdigit() or not clock.isdigit():
        return None
    clock = clock.zfill(6)[:6]
    try:
        return datetime(
            int(day[:4]),
            int(day[4:6]),
            int(day[6:8]),
            int(clock[:2]),
            int(clock[2:4]),
            int(clock[4:6]),
            tzinfo=TEHRAN,
        )
    except ValueError:
        return None


# Re-export for callers that format ticks from snapshots without a MaBandTick yet.
__all__ = [
    "SESSION_CLOSE",
    "SESSION_OPEN",
    "TEHRAN",
    "filter_session_snapshots",
    "format_tick",
    "in_iran_session",
    "session_bounds",
    "snapshot_from_live",
    "tick_record",
]
