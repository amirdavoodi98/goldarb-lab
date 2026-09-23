"""In-memory best quotes keyed by symbol."""

from __future__ import annotations

from datetime import datetime

from .models import DomainError, MarketSnapshot, Quote


class MarketBook:
    def __init__(self) -> None:
        self._quotes: dict[str, Quote] = {}
        self._event_id: str | None = None
        self._timestamp: datetime | None = None

    @property
    def event_id(self) -> str | None:
        return self._event_id

    @property
    def timestamp(self) -> datetime | None:
        return self._timestamp

    def quote(self, symbol: str) -> Quote | None:
        return self._quotes.get(symbol)

    def update(self, snapshot: MarketSnapshot) -> None:
        if snapshot.timestamp.tzinfo is None:
            raise DomainError("snapshot timestamp must be timezone-aware")
        if self._timestamp is not None and self._timestamp > snapshot.timestamp:
            raise DomainError("snapshot timestamps must be monotonic")
        self._event_id = snapshot.event_id
        self._timestamp = snapshot.timestamp
        for quote in snapshot.quotes:
            self._quotes[quote.symbol] = quote

    def clear(self) -> None:
        self._quotes.clear()
        self._event_id = None
        self._timestamp = None
