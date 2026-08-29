"""Market data providers. Strategy never talks to HTTP or archives directly."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from .session import (
    ONE_SECOND,
    TEHRAN,
    grain_step,
    in_iran_session,
    session_timeline,
    snapshot_from_live,
)
from .signals.stats import premium_from_row, to_float
from .simulation.models import MarketSnapshot, Quote, decimal_value
from .universe import GOLD_FUND_SYMBOLS

ZERO = Decimal(0)


@runtime_checkable
class DataProvider(Protocol):
    def events(self) -> Iterator[MarketSnapshot]: ...


@runtime_checkable
class LiveMarketFeed(Protocol):
    """Narrow live-data surface; ``LabClient.fund`` satisfies this."""

    def last_price(self, symbol: str) -> dict[str, Any]: ...

    def orderbook(self, symbol: str) -> dict[str, Any]: ...

    def candles(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1s",
    ) -> list[dict[str, Any]]: ...


class LabLiveFeed:
    """Adapt ``LabClient`` (or ``client.fund``) to ``LiveMarketFeed``."""

    def __init__(self, client: Any) -> None:
        self._fund = getattr(client, "fund", client)

    def last_price(self, symbol: str) -> dict[str, Any]:
        payload = self._fund.last_price(symbol)
        return payload if isinstance(payload, dict) else {}

    def orderbook(self, symbol: str) -> dict[str, Any]:
        payload = self._fund.orderbook(symbol)
        return payload if isinstance(payload, dict) else {}

    def candles(
        self,
        symbol: str,
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1s",
    ) -> list[dict[str, Any]]:
        rows = self._fund.candles(symbol, start=start, end=end, grain=grain)
        return list(rows or [])

    def candles_many(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str,
        end: date | datetime | str,
        grain: str = "1s",
    ) -> dict[str, list[dict[str, Any]]]:
        many = getattr(self._fund, "candles_many", None)
        if many is not None:
            payload = many(symbols, start=start, end=end, grain=grain)
            return payload if isinstance(payload, dict) else {}
        return {
            symbol: self.candles(symbol, start=start, end=end, grain=grain)
            for symbol in symbols
        }

    def last_prices(self) -> Any:
        bulk = getattr(self._fund, "last_prices", None)
        if bulk is not None:
            return bulk()
        return None

    def navs_live(self) -> Any:
        bulk = getattr(self._fund, "navs_live", None)
        if bulk is not None:
            return bulk()
        return None

    def orderbooks(self) -> Any:
        bulk = getattr(self._fund, "orderbooks", None)
        if bulk is not None:
            return bulk()
        return None


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


def snapshots_from_cross_section(
    bars: Sequence[tuple[datetime | date, Mapping[str, Mapping[str, Any]]]],
    *,
    event_prefix: str = "cross",
) -> list[MarketSnapshot]:
    """Build aligned multi-symbol snapshots (close + optional premium/NAV)."""
    snapshots: list[MarketSnapshot] = []
    for stamp, by_symbol in bars:
        timestamp = _aware_timestamp(stamp)
        quotes: list[Quote] = []
        for symbol, fields in by_symbol.items():
            quote = _quote_from_fields(symbol, fields)
            if quote is not None:
                quotes.append(quote)
        if not quotes:
            continue
        snapshots.append(
            MarketSnapshot(
                event_id=f"{event_prefix}:{timestamp.isoformat()}",
                timestamp=timestamp,
                quotes=tuple(quotes),
            )
        )
    return snapshots


def cross_section_1s(
    n: int,
    *,
    premiums: Mapping[str, Sequence[float]] | None = None,
    start: datetime | None = None,
    symbols: Sequence[str] | None = None,
    default_premium: float = 0.0,
) -> list[tuple[datetime, dict[str, dict[str, Any]]]]:
    """Build ``n`` consecutive 1s snapshots covering the gold-fund universe."""
    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    origin = start or datetime(2026, 8, 29, 8, 30, 0, tzinfo=UTC)
    rows: list[tuple[datetime, dict[str, dict[str, Any]]]] = []
    for index in range(n):
        by_symbol: dict[str, dict[str, Any]] = {}
        for offset, symbol in enumerate(universe):
            series = None if premiums is None else premiums.get(symbol)
            if series is None:
                prem = default_premium
            elif index < len(series):
                prem = float(series[index])
            elif series:
                prem = float(series[-1])
            else:
                prem = default_premium
            by_symbol[symbol] = {
                "close": 10000.0 + offset * 250.0,
                "premium": prem,
            }
        rows.append((origin + timedelta(seconds=index), by_symbol))
    return rows


def snapshots_from_symbol_bars(
    by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    ffill: bool = True,
    step: timedelta = ONE_SECOND,
    session_hours: bool = True,
    fill_session: bool = False,
    event_prefix: str = "1s",
) -> list[MarketSnapshot]:
    """Align sparse per-symbol bars onto a 1s grid.

    With ``session_hours=True`` (default) each Iran session day is a separate
    grid so nights and weekends are not filled. ``fill_session=True`` covers
    the full 12:00–17:00 window on every day that has data.
    """
    return list(
        iter_symbol_bar_snapshots(
            by_symbol,
            ffill=ffill,
            step=step,
            session_hours=session_hours,
            fill_session=fill_session,
            event_prefix=event_prefix,
        )
    )


def iter_symbol_bar_snapshots(
    by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    ffill: bool = True,
    step: timedelta = ONE_SECOND,
    session_hours: bool = True,
    fill_session: bool = False,
    event_prefix: str = "1s",
) -> Iterator[MarketSnapshot]:
    parsed: dict[str, dict[datetime, Quote]] = {}
    stamps: list[datetime] = []
    for symbol, rows in by_symbol.items():
        bucket: dict[datetime, Quote] = {}
        for row in rows:
            timestamp = _bar_timestamp(dict(row))
            quote = _quote_from_fields(symbol, row)
            if timestamp is None or quote is None:
                continue
            timestamp = timestamp.astimezone(UTC).replace(microsecond=0)
            bucket[timestamp] = quote
            stamps.append(timestamp)
        if bucket:
            parsed[symbol] = bucket
    if not parsed:
        return

    last: dict[str, Quote] = {}
    for timestamp in _symbol_bar_timeline(
        stamps,
        step=step,
        session_hours=session_hours,
        fill_session=fill_session,
        ffill=ffill,
    ):
        quotes: list[Quote] = []
        for symbol, bucket in parsed.items():
            quote = bucket.get(timestamp)
            if quote is not None:
                last[symbol] = quote
                quotes.append(quote)
            elif ffill and symbol in last:
                quotes.append(last[symbol])
        if not quotes:
            continue
        yield MarketSnapshot(
            event_id=f"{event_prefix}:{timestamp.isoformat()}",
            timestamp=timestamp,
            quotes=tuple(quotes),
        )


def _symbol_bar_timeline(
    stamps: Sequence[datetime],
    *,
    step: timedelta,
    session_hours: bool,
    fill_session: bool,
    ffill: bool,
) -> list[datetime]:
    unique = sorted({item.astimezone(UTC).replace(microsecond=0) for item in stamps})
    if not unique:
        return []
    if not session_hours:
        if ffill:
            return _second_grid(unique[0], unique[-1], step)
        return unique

    by_day: dict[date, list[datetime]] = {}
    for stamp in unique:
        if not in_iran_session(stamp):
            continue
        by_day.setdefault(stamp.astimezone(TEHRAN).date(), []).append(stamp)

    timeline: list[datetime] = []
    for day in sorted(by_day):
        day_stamps = by_day[day]
        points = session_timeline(
            day,
            first=min(day_stamps),
            last=max(day_stamps),
            step=step,
            fill_session=fill_session,
        )
        timeline.extend(point.astimezone(UTC) for point in points)
    return timeline


def _second_grid(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    if step <= timedelta(0):
        raise ValueError("step must be positive")
    points: list[datetime] = []
    cursor = start
    while cursor <= end:
        points.append(cursor)
        cursor += step
    return points


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


class HistoricalDataProvider:
    """Finite, ordered market events from memory, bars, or close prices."""

    def __init__(
        self,
        snapshots: Sequence[MarketSnapshot]
        | Callable[[], Iterator[MarketSnapshot]],
    ) -> None:
        if isinstance(snapshots, Sequence) and not isinstance(snapshots, (str, bytes)):
            self._snapshots: list[MarketSnapshot] = list(snapshots)
            self._factory: Callable[[], Iterator[MarketSnapshot]] | None = None
        else:
            self._snapshots = []
            self._factory = snapshots  # type: ignore[assignment]

    @classmethod
    def from_bars(
        cls,
        bars: Sequence[dict[str, Any]],
        *,
        symbol: str = "طلا",
    ) -> HistoricalDataProvider:
        return cls(snapshots_from_bars(bars, symbol=symbol))

    @classmethod
    def from_closes(
        cls,
        closes: Sequence[Decimal | float | str],
        *,
        symbol: str = "طلا",
        start: datetime | None = None,
        step: timedelta = timedelta(minutes=1),
    ) -> HistoricalDataProvider:
        return cls(snapshots_from_closes(closes, symbol=symbol, start=start, step=step))

    @classmethod
    def from_cross_section(
        cls,
        bars: Sequence[tuple[datetime | date, Mapping[str, Mapping[str, Any]]]],
        *,
        event_prefix: str = "cross",
    ) -> HistoricalDataProvider:
        return cls(snapshots_from_cross_section(bars, event_prefix=event_prefix))

    @classmethod
    def from_1s(
        cls,
        n: int,
        *,
        premiums: Mapping[str, Sequence[float]] | None = None,
        start: datetime | None = None,
        symbols: Sequence[str] | None = None,
        event_prefix: str = "1s",
    ) -> HistoricalDataProvider:
        """Consecutive 1s last-only snapshots for the full gold-fund universe."""
        return cls.from_cross_section(
            cross_section_1s(n, premiums=premiums, start=start, symbols=symbols),
            event_prefix=event_prefix,
        )

    @classmethod
    def from_symbol_bars(
        cls,
        by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        ffill: bool = True,
        step: timedelta = ONE_SECOND,
        session_hours: bool = True,
        fill_session: bool = False,
        event_prefix: str = "1s",
        lazy: bool = True,
    ) -> HistoricalDataProvider:
        """Align API ``grain=1s`` bars onto a 1s Iran-session grid."""

        def factory() -> Iterator[MarketSnapshot]:
            yield from iter_symbol_bar_snapshots(
                by_symbol,
                ffill=ffill,
                step=step,
                session_hours=session_hours,
                fill_session=fill_session,
                event_prefix=event_prefix,
            )

        if lazy:
            return cls(factory)
        return cls(list(factory()))

    def events(self) -> Iterator[MarketSnapshot]:
        if self._factory is not None:
            yield from self._factory()
            return
        yield from self._snapshots


class LiveDataProvider:
    """Poll live quotes during the Iran cash session at 1s resolution.

    Optional ``lookback_days`` replays recent ``grain=1s`` session bars so a
    pair strategy already has its calendar window before live ticks start.
    Duplicate ``event_id`` values are skipped. Feed errors do not stop the
    iterator.
    """

    def __init__(
        self,
        feed: LiveMarketFeed,
        *,
        symbol: str = "طلا",
        symbols: Sequence[str] | None = None,
        poll_seconds: float = 1.0,
        bar_grain: str = "1s",
        include_session_bars: bool = True,
        lookback_days: int = 0,
        session_day: date | None = None,
        stop_at: datetime | None = None,
        max_polls: int | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], datetime] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        self.feed = feed
        self.symbols = tuple(symbols) if symbols is not None else (symbol,)
        self.symbol = self.symbols[0]
        self.poll_seconds = poll_seconds
        self.bar_grain = bar_grain.strip().lower() or "1s"
        self.include_session_bars = include_session_bars
        self.lookback_days = max(0, int(lookback_days))
        self.session_day = session_day
        self.stop_at = stop_at
        self.max_polls = max_polls
        self._sleep = sleep
        self._now = now
        self.on_error = on_error
        self.on_idle = on_idle
        self._seen: set[str] = set()
        self._bars_loaded = False
        self._polls = 0

    def now(self) -> datetime:
        if self._now is not None:
            return self._now()
        return datetime.now(TEHRAN)

    def done(self) -> bool:
        if self.max_polls is not None and self._polls >= self.max_polls:
            return True
        if self.stop_at is not None and self.now() > self.stop_at:
            return True
        return False

    def poll(self) -> list[MarketSnapshot]:
        """One poll cycle; empty when nothing new or the feed errors."""
        self._polls += 1
        pending: list[MarketSnapshot] = []
        clock = self.now()
        day = self.session_day or clock.astimezone(TEHRAN).date()
        try:
            if not self._bars_loaded:
                pending.extend(self._history_snapshots(day, before=clock))
            live = self._live_snapshot(clock)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(exc)
            return []
        self._bars_loaded = True
        if live is not None and in_iran_session(live.timestamp, day=day):
            pending.append(live)

        fresh: list[MarketSnapshot] = []
        for snapshot in pending:
            if snapshot.event_id in self._seen:
                continue
            self._seen.add(snapshot.event_id)
            fresh.append(snapshot)
        return fresh

    def events(self) -> Iterator[MarketSnapshot]:
        sleeper = self._sleep
        if sleeper is None:
            import time

            sleeper = time.sleep
        while not self.done():
            fresh = self.poll()
            if not fresh and self.on_idle is not None:
                self.on_idle()
            yield from fresh
            if self.done():
                return
            sleeper(self.poll_seconds)

    def _history_snapshots(
        self,
        day: date,
        *,
        before: datetime | None = None,
    ) -> list[MarketSnapshot]:
        if not self.include_session_bars and self.lookback_days <= 0:
            return []
        start = day
        if self.lookback_days > 0:
            start = day - timedelta(days=self.lookback_days)
        elif not self.include_session_bars:
            return []
        by_symbol = self._candles_many(start=start, end=day)
        snapshots = list(
            iter_symbol_bar_snapshots(
                by_symbol,
                ffill=True,
                step=grain_step(self.bar_grain),
                session_hours=True,
                fill_session=False,
                event_prefix=f"hist-{self.bar_grain}",
            )
        )
        if not self.include_session_bars:
            snapshots = [
                item
                for item in snapshots
                if item.timestamp.astimezone(TEHRAN).date() < day
            ]
        if before is not None:
            cutoff = before.astimezone(TEHRAN).replace(microsecond=0)
            snapshots = [item for item in snapshots if item.timestamp < cutoff]
        return snapshots

    def _candles_many(
        self,
        *,
        start: date,
        end: date,
    ) -> dict[str, list[dict[str, Any]]]:
        many = getattr(self.feed, "candles_many", None)
        if many is not None:
            payload = many(
                self.symbols,
                start=start.isoformat(),
                end=end.isoformat(),
                grain=self.bar_grain,
            )
            if isinstance(payload, dict):
                return {
                    str(symbol): list(rows or [])
                    for symbol, rows in payload.items()
                }
        out: dict[str, list[dict[str, Any]]] = {}
        for symbol in self.symbols:
            out[symbol] = list(
                self.feed.candles(
                    symbol,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    grain=self.bar_grain,
                )
                or []
            )
        return out

    def _live_snapshot(self, clock: datetime) -> MarketSnapshot | None:
        lasts = _symbol_payload_map(
            getattr(self.feed, "last_prices", lambda: None)()
        )
        navs = _symbol_payload_map(getattr(self.feed, "navs_live", lambda: None)())
        books = _symbol_payload_map(getattr(self.feed, "orderbooks", lambda: None)())
        quotes: list[Quote] = []
        for symbol in self.symbols:
            last = lasts.get(symbol)
            if last is None:
                last = self.feed.last_price(symbol)
            book = books.get(symbol)
            if book is None and len(self.symbols) == 1:
                book = self.feed.orderbook(symbol)
            quote = _quote_from_live(
                symbol,
                last if isinstance(last, dict) else {},
                nav=navs.get(symbol),
                orderbook=book if isinstance(book, dict) else None,
                now=clock,
            )
            if quote is not None:
                quotes.append(quote)
        if not quotes:
            return None
        stamp = clock.astimezone(TEHRAN).replace(microsecond=0)
        fingerprint = ",".join(
            f"{quote.symbol}:{quote.last}:{quote.premium}" for quote in quotes
        )
        return MarketSnapshot(
            event_id=f"live:{stamp.isoformat()}:{fingerprint}",
            timestamp=stamp,
            quotes=tuple(quotes),
        )


def _symbol_payload_map(payload: Any) -> dict[str, dict[str, Any]]:
    if payload is None:
        return {}
    rows: Any = payload
    if isinstance(payload, dict):
        for key in ("results", "funds", "data", "items"):
            nested = payload.get(key)
            if isinstance(nested, list):
                rows = nested
                break
        else:
            mapped: dict[str, dict[str, Any]] = {}
            for key, value in payload.items():
                if key in {"raw", "count", "next", "previous"}:
                    continue
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("symbol", key)
                    mapped[str(row.get("symbol") or key)] = row
                else:
                    mapped[str(key)] = {"symbol": str(key), "last_price": value}
            return mapped
    if not isinstance(rows, list):
        return {}
    mapped = {}
    for item in rows:
        if isinstance(item, dict) and item.get("symbol"):
            mapped[str(item["symbol"])] = item
    return mapped


def _quote_from_live(
    symbol: str,
    last_price: Mapping[str, Any],
    *,
    nav: Mapping[str, Any] | None = None,
    orderbook: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> Quote | None:
    payload = dict(last_price)
    if nav:
        for key, value in nav.items():
            payload.setdefault(key, value)
    snapshot = snapshot_from_live(
        symbol=symbol,
        last_price=payload,
        orderbook=dict(orderbook) if orderbook else None,
        now=now,
    )
    if snapshot is None:
        return None
    base = snapshot.quotes[0]
    nav_value = to_float(
        payload.get("nav")
        or payload.get("nav_price")
        or payload.get("nav_red")
        or payload.get("nav_value")
    )
    premium = premium_from_row({"close": base.last, "nav": nav_value, **payload})
    return Quote(
        symbol=base.symbol,
        last=base.last,
        bid=base.bid,
        ask=base.ask,
        bid_size=base.bid_size,
        ask_size=base.ask_size,
        premium=None if premium is None else decimal_value(premium),
        nav=None if nav_value is None else decimal_value(nav_value),
    )


def _aware_timestamp(stamp: datetime | date) -> datetime:
    if isinstance(stamp, datetime):
        if stamp.tzinfo is None:
            return stamp.replace(tzinfo=UTC)
        return stamp
    return datetime.combine(stamp, time.min, tzinfo=UTC)


def _quote_from_fields(symbol: str, fields: Mapping[str, Any]) -> Quote | None:
    close = _bar_close(dict(fields))
    if close is None:
        return None
    premium = premium_from_row(dict(fields))
    nav_raw = fields.get("nav")
    if nav_raw is None:
        nav_raw = fields.get("nav_price")
    nav = to_float(nav_raw)
    return Quote(
        symbol=symbol,
        last=close,
        premium=None if premium is None else decimal_value(premium),
        nav=None if nav is None else decimal_value(nav),
    )


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


__all__ = [
    "DataProvider",
    "HistoricalDataProvider",
    "LabLiveFeed",
    "LiveDataProvider",
    "LiveMarketFeed",
    "snapshot_close",
    "snapshots_from_bars",
    "snapshots_from_closes",
    "snapshots_from_cross_section",
    "snapshots_from_symbol_bars",
    "iter_symbol_bar_snapshots",
    "cross_section_1s",
]
