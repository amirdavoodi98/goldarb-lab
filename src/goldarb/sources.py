"""Replaceable historical/live sources and source registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

from .archive import DatasetStore, dataset_store
from .data import HistoricalDataProvider, LabLiveFeed, LiveMarketFeed
from .session import SESSION_CLOSE, SESSION_OPEN, TEHRAN, grain_step


@runtime_checkable
class HistoricalDatasetSource(Protocol):
    """Load normalized bar dictionaries without exposing transport details."""

    def bars(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
        grain: str = "1s",
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]: ...


@runtime_checkable
class LiveMarketSource(LiveMarketFeed, Protocol):
    """Named live-source contract used by runtime factories."""


class GoldArbApiSource:
    def __init__(self, client: Any) -> None:
        self.client = client
        self.fund = getattr(client, "fund", client)

    def bars(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
        grain: str = "1s",
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        if start is None or end is None:
            raise ValueError("API historical source requires start and end")
        payload = self.fund.candles_many(symbols, start=start, end=end, grain=grain)
        return payload if isinstance(payload, dict) else {}


class ArchiveDatasetSource:
    def __init__(self, store: DatasetStore) -> None:
        self.store = store

    def bars(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
        grain: str = "1s",
    ) -> Mapping[str, Sequence[Mapping[str, Any]]]:
        del grain
        lower = None if start is None else str(start)[:10]
        upper = None if end is None else str(end)[:10]
        output: dict[str, list[dict[str, Any]]] = {}
        for symbol in symbols:
            rows = []
            for row in self.store.iter_symbol(symbol):
                stamp = str(row.get("bar_at") or row.get("date") or "")
                day = stamp[:10]
                if lower is not None and day < lower:
                    continue
                if upper is not None and day > upper:
                    continue
                rows.append(row)
            output[symbol] = rows
        return output

    def provider(
        self,
        symbols: Sequence[str],
        *,
        start: date | datetime | str | None = None,
        end: date | datetime | str | None = None,
        grain: str | None = None,
        fill_session: bool = True,
        session_hours: bool = True,
        session_zone: ZoneInfo = TEHRAN,
        session_open: time = SESSION_OPEN,
        session_close: time = SESSION_CLOSE,
    ) -> HistoricalDataProvider:
        try:
            manifest = self.store.read_manifest()
        except FileNotFoundError:
            # Collector directories are valid JSONL sources even without a
            # bundle manifest when symbols and grain are supplied by config.
            manifest = {}
        selected_grain = grain or str(manifest.get("grain") or "1s")
        rows = self.bars(
            symbols,
            start=start,
            end=end,
            grain=selected_grain,
        )
        return HistoricalDataProvider.from_symbol_bars(
            rows,
            step=grain_step(selected_grain),
            fill_session=fill_session,
            session_hours=session_hours,
            event_prefix=f"{selected_grain}-archive",
            lazy=True,
            session_zone=session_zone,
            session_open=session_open,
            session_close=session_close,
        )


def source_path(uri: str) -> Path:
    """Resolve a local path or file URI; reject non-local archive schemes."""
    parsed = urlparse(uri)
    if parsed.scheme in {"", "file"}:
        value = unquote(parsed.path) if parsed.scheme else uri
        return Path(value).expanduser()
    raise ValueError(f"source is not a local dataset URI: {uri}")


HistoricalSourceFactory = Callable[[str, Any | None], HistoricalDatasetSource]
LiveSourceFactory = Callable[[Any | None], LiveMarketSource]


def _api_historical(source: str, client: Any | None) -> HistoricalDatasetSource:
    del source
    if client is None:
        raise ValueError("goldarb_api provider requires a LabClient")
    return GoldArbApiSource(client)


def _archive_historical(format_hint: str | None) -> HistoricalSourceFactory:
    def factory(source: str, client: Any | None) -> HistoricalDatasetSource:
        del client
        return ArchiveDatasetSource(dataset_store(source_path(source), format_hint))

    return factory


def _goldarb_live(client: Any | None) -> LiveMarketSource:
    if client is None:
        raise ValueError("GoldArb live provider requires a LabClient")
    return LabLiveFeed(client)


HISTORICAL_SOURCE_FACTORIES: dict[str, HistoricalSourceFactory] = {
    "goldarb_api": _api_historical,
    "api": _api_historical,
    "jsonl": _archive_historical("jsonl"),
    "parquet": _archive_historical("parquet"),
    "archive": _archive_historical(None),
}
LIVE_SOURCE_FACTORIES: dict[str, LiveSourceFactory] = {
    "goldarb_live": _goldarb_live,
    "goldarb_api": _goldarb_live,
    "api": _goldarb_live,
    "live": _goldarb_live,
}


def historical_source(
    provider: str,
    source: str,
    *,
    client: Any | None = None,
) -> HistoricalDatasetSource:
    kind = provider.strip().lower()
    try:
        factory = HISTORICAL_SOURCE_FACTORIES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown historical data provider: {provider}") from exc
    return factory(source, client)


def live_source(provider: str, *, client: Any | None = None) -> LiveMarketSource:
    kind = provider.strip().lower()
    try:
        factory = LIVE_SOURCE_FACTORIES[kind]
    except KeyError as exc:
        raise ValueError(f"unknown live data provider: {provider}") from exc
    return factory(client)


__all__ = [
    "ArchiveDatasetSource",
    "GoldArbApiSource",
    "HISTORICAL_SOURCE_FACTORIES",
    "HistoricalDatasetSource",
    "LiveMarketSource",
    "LIVE_SOURCE_FACTORIES",
    "historical_source",
    "live_source",
    "source_path",
]
