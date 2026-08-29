"""Market data providers. Strategy never talks to HTTP or archives directly."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from .session import (
    TEHRAN,
    filter_session_snapshots,
    in_iran_session,
    snapshot_from_live,
)
from .signals.stats import premium_from_row, to_float
from .simulation.models import MarketSnapshot, Quote, decimal_value

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
        grain: str = "1m",
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
        grain: str = "1m",
    ) -> list[dict[str, Any]]:
        rows = self._fund.candles(symbol, start=start, end=end, grain=grain)
        return list(rows or [])


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

    def __init__(self, snapshots: Sequence[MarketSnapshot]) -> None:
        self._snapshots = list(snapshots)

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

    def events(self) -> Iterator[MarketSnapshot]:
        yield from self._snapshots


class LiveDataProvider:
    """Poll a live feed during the Iran cash session.

    The first successful poll optionally replays today's 1m bars, then each poll
    appends a live last+orderbook snapshot. Duplicate ``event_id`` values are
    skipped. Feed errors do not stop the iterator.
    """

    def __init__(
        self,
        feed: LiveMarketFeed,
        *,
        symbol: str = "طلا",
        poll_seconds: float = 15.0,
        include_session_bars: bool = True,
        session_day: date | None = None,
        stop_at: datetime | None = None,
        max_polls: int | None = None,
        sleep: Callable[[float], None] | None = None,
        now: Callable[[], datetime] | None = None,
        on_error: Callable[[BaseException], None] | None = None,
        on_idle: Callable[[], None] | None = None,
    ) -> None:
        self.feed = feed
        self.symbol = symbol
        self.poll_seconds = poll_seconds
        self.include_session_bars = include_session_bars
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
            if self.include_session_bars and not self._bars_loaded:
                bars = self.feed.candles(
                    self.symbol,
                    start=day.isoformat(),
                    end=day.isoformat(),
                    grain="1m",
                )
                pending.extend(
                    filter_session_snapshots(
                        snapshots_from_bars(bars, symbol=self.symbol),
                        day=day,
                    )
                )
            last = self.feed.last_price(self.symbol)
            book = self.feed.orderbook(self.symbol)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(exc)
            return []
        if self.include_session_bars:
            self._bars_loaded = True

        live = snapshot_from_live(
            symbol=self.symbol,
            last_price=last if isinstance(last, dict) else {},
            orderbook=book if isinstance(book, dict) else None,
            now=clock,
        )
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
]
