"""Iran cash-market session helpers (12:00–17:00 Asia/Tehran)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from .simulation.models import MarketSnapshot, Quote, decimal_value

TEHRAN = ZoneInfo("Asia/Tehran")
SESSION_OPEN = time(12, 0)
SESSION_CLOSE = time(17, 0)
ONE_SECOND = timedelta(seconds=1)
ZERO = Decimal(0)


def grain_step(grain: str) -> timedelta:
    """Map API bar grain to the snapshot grid step (default: 1s)."""
    key = (grain or "1s").strip().lower()
    if key in {"1m", "1min", "minute"}:
        return timedelta(minutes=1)
    if key in {"daily", "1d", "day"}:
        return timedelta(days=1)
    return ONE_SECOND


def session_bounds(
    day: date | None = None,
    *,
    zone: ZoneInfo = TEHRAN,
    open_time: time = SESSION_OPEN,
    close_time: time = SESSION_CLOSE,
) -> tuple[datetime, datetime]:
    """Return [12:00, 17:00] Asia/Tehran for ``day`` (default: today in Tehran)."""
    local_day = day or datetime.now(zone).date()
    start = datetime.combine(local_day, open_time, tzinfo=zone)
    end = datetime.combine(local_day, close_time, tzinfo=zone)
    return start, end


def in_session(
    timestamp: datetime,
    *,
    day: date | None = None,
    zone: ZoneInfo = TEHRAN,
    open_time: time = SESSION_OPEN,
    close_time: time = SESSION_CLOSE,
) -> bool:
    """True when ``timestamp`` falls inside the configured session."""
    if timestamp.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    local = timestamp.astimezone(zone)
    if day is not None and local.date() != day:
        return False
    start, end = session_bounds(local.date(), zone=zone, open_time=open_time, close_time=close_time)
    return start <= local <= end


def in_iran_session(timestamp: datetime, *, day: date | None = None) -> bool:
    """Backward-compatible Iran cash-session predicate."""
    return in_session(timestamp, day=day)


def session_timeline(
    day: date,
    *,
    first: datetime | None = None,
    last: datetime | None = None,
    step: timedelta = ONE_SECOND,
    fill_session: bool = False,
    zone: ZoneInfo = TEHRAN,
    open_time: time = SESSION_OPEN,
    close_time: time = SESSION_CLOSE,
) -> list[datetime]:
    """1s (or ``step``) timestamps for one Iran cash session.

    ``fill_session=True`` covers 12:00–17:00 inclusive. Otherwise the grid
    spans only ``[first, last]`` clipped to the session.
    """
    open_at, close_at = session_bounds(day, zone=zone, open_time=open_time, close_time=close_time)
    if fill_session:
        start, end = open_at, close_at
    else:
        if first is None or last is None:
            return []
        start = max(first.astimezone(zone), open_at)
        end = min(last.astimezone(zone), close_at)
    start = start.replace(microsecond=0)
    end = end.replace(microsecond=0)
    if step <= timedelta(0) or start > end:
        return []
    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor += step
    return points


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
    last = (
        None
        if stale
        else _positive_decimal(
            last_price.get("last_price")
            or last_price.get("display_price")
            or last_price.get("close_price")
            or last_price.get("close")
        )
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
