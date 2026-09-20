"""Versioned, portable archives of per-symbol bars for air-gapped backtests."""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from urllib.parse import quote

from .universe import GOLD_FUND_SYMBOLS

ARCHIVE_SCHEMA_VERSION = 2
_MANIFEST = "manifest.json"


def _day(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _bar_key(row: Mapping[str, Any]) -> str:
    return str(row.get("bar_at") or row.get("date") or "")


def _normalized(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    original_keys = [_bar_key(row) for row in rows if _bar_key(row)]
    out_of_order = sum(
        current < previous for previous, current in zip(original_keys, original_keys[1:])
    )
    ordered = sorted((dict(row) for row in rows), key=_bar_key)
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    duplicates = 0
    invalid = 0
    for row in ordered:
        key = _bar_key(row)
        if not key:
            invalid += 1
            continue
        if key in seen:
            duplicates += 1
            output[-1] = row
            continue
        seen.add(key)
        output.append(row)
    return output, {
        "duplicates_removed": duplicates,
        "invalid_rows": invalid,
        "out_of_order_rows": out_of_order,
    }


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _coverage(
    rows: Sequence[Mapping[str, Any]],
    start: date | datetime | str,
    end: date | datetime | str,
) -> dict[str, Any]:
    first = _day(start)
    last = _day(end)
    covered = sorted({_day(stamp) for row in rows if (stamp := _bar_key(row))})
    expected: list[date] = []
    cursor = first
    while cursor <= last:
        expected.append(cursor)
        cursor += timedelta(days=1)
    covered_set = set(covered)
    missing = [item.isoformat() for item in expected if item not in covered_set]
    return {
        "covered_days": [item.isoformat() for item in covered],
        "missing_days": missing,
    }


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, indent=2, default=str)
        temp = Path(handle.name)
    temp.replace(path)


@runtime_checkable
class DatasetStore(Protocol):
    """Storage contract used by archive-backed historical data sources."""

    directory: Path

    def read_manifest(self) -> dict[str, Any]: ...

    def iter_symbol(self, symbol: str) -> Iterator[dict[str, Any]]: ...

    def write(
        self,
        by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        grain: str,
        start: date | datetime | str,
        end: date | datetime | str,
        source: str = "",
        incremental: bool = False,
    ) -> Path: ...


class JsonlDatasetStore:
    """One UTF-8 JSONL file per symbol with an atomic versioned manifest."""

    format = "jsonl"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def read_manifest(self) -> dict[str, Any]:
        path = self.directory / _MANIFEST
        if not path.exists():
            raise FileNotFoundError(f"archive manifest not found: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        version = int(manifest.get("schema_version", 1))
        if version > ARCHIVE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported archive schema {version}; expected <= {ARCHIVE_SCHEMA_VERSION}"
            )
        for symbol, expected in manifest.get("checksums", {}).items():
            data_path = self.directory / f"{symbol}.jsonl"
            if not data_path.exists() or _checksum(data_path) != expected:
                raise ValueError(f"archive checksum mismatch: {data_path}")
        return manifest

    def iter_symbol(self, symbol: str) -> Iterator[dict[str, Any]]:
        path = self.directory / f"{symbol}.jsonl"
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"archive row must be an object: {path}:{line_number}")
                yield item

    def write(
        self,
        by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        grain: str,
        start: date | datetime | str,
        end: date | datetime | str,
        source: str = "",
        incremental: bool = False,
    ) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        old: dict[str, Any] = {}
        manifest_path = self.directory / _MANIFEST
        if incremental and manifest_path.exists():
            old = self.read_manifest()
        archive_start = min(str(old.get("start") or _day(start)), _day(start).isoformat())
        archive_end = max(str(old.get("end") or _day(end)), _day(end).isoformat())
        symbols = sorted(set(old.get("symbols", ())) | {str(s) for s in by_symbol})
        counts: dict[str, int] = {}
        checksums: dict[str, str] = {}
        quality: dict[str, dict[str, Any]] = {}
        actual_stamps: list[str] = []
        for symbol in symbols:
            rows: list[Mapping[str, Any]] = []
            if incremental:
                rows.extend(self.iter_symbol(symbol))
            rows.extend(by_symbol.get(symbol, ()))
            normalized, report = _normalized(rows)
            path = self.directory / f"{symbol}.jsonl"
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.directory, delete=False
            ) as handle:
                for row in normalized:
                    handle.write(json.dumps(row, ensure_ascii=False, default=str))
                    handle.write("\n")
                temp = Path(handle.name)
            temp.replace(path)
            stamps = [_bar_key(row) for row in normalized]
            actual_stamps.extend(stamps)
            counts[symbol] = len(normalized)
            checksums[symbol] = _checksum(path)
            quality[symbol] = {
                **report,
                **_coverage(normalized, archive_start, archive_end),
            }
        now = datetime.now(UTC).isoformat()
        manifest = {
            "schema_version": ARCHIVE_SCHEMA_VERSION,
            "format": self.format,
            "source": source or old.get("source", ""),
            "grain": grain,
            "start": archive_start,
            "end": archive_end,
            "actual_start": min(actual_stamps, default=None),
            "actual_end": max(actual_stamps, default=None),
            "symbols": symbols,
            "bar_count": sum(counts.values()),
            "counts": counts,
            "checksums": checksums,
            "quality": quality,
            "created_at": old.get("created_at", now),
            "updated_at": now,
        }
        _atomic_json(manifest_path, manifest)
        return self.directory


class ParquetDatasetStore:
    """Partitioned Parquet store; ``pyarrow`` is loaded only when used."""

    format = "parquet"

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def _modules() -> tuple[Any, Any]:
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise RuntimeError(
                "Parquet support requires: pip install 'goldarb-lab[parquet]'"
            ) from exc
        return pa, pq

    def _path(self, symbol: str) -> Path:
        return self.directory / f"symbol={quote(symbol, safe='')}" / "bars.parquet"

    def read_manifest(self) -> dict[str, Any]:
        path = self.directory / _MANIFEST
        if not path.exists():
            raise FileNotFoundError(f"archive manifest not found: {path}")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        version = int(manifest.get("schema_version", 1))
        if version > ARCHIVE_SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported archive schema {version}; expected <= {ARCHIVE_SCHEMA_VERSION}"
            )
        for symbol, expected in manifest.get("checksums", {}).items():
            data_path = self._path(str(symbol))
            if not data_path.exists() or _checksum(data_path) != expected:
                raise ValueError(f"archive checksum mismatch: {data_path}")
        return manifest

    def iter_symbol(self, symbol: str) -> Iterator[dict[str, Any]]:
        _, pq = self._modules()
        path = self._path(symbol)
        if not path.exists():
            return
        yield from pq.read_table(path).to_pylist()

    def write(
        self,
        by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        grain: str,
        start: date | datetime | str,
        end: date | datetime | str,
        source: str = "",
        incremental: bool = False,
    ) -> Path:
        pa, pq = self._modules()
        self.directory.mkdir(parents=True, exist_ok=True)
        old: dict[str, Any] = {}
        if incremental and (self.directory / _MANIFEST).exists():
            old = self.read_manifest()
        archive_start = min(str(old.get("start") or _day(start)), _day(start).isoformat())
        archive_end = max(str(old.get("end") or _day(end)), _day(end).isoformat())
        symbols = sorted(set(old.get("symbols", ())) | {str(s) for s in by_symbol})
        counts: dict[str, int] = {}
        checksums: dict[str, str] = {}
        quality: dict[str, dict[str, Any]] = {}
        stamps: list[str] = []
        for symbol in symbols:
            rows: list[Mapping[str, Any]] = []
            if incremental:
                rows.extend(self.iter_symbol(symbol))
            rows.extend(by_symbol.get(symbol, ()))
            normalized, report = _normalized(rows)
            path = self._path(symbol)
            path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pylist(normalized), path)
            symbol_stamps = [_bar_key(row) for row in normalized]
            stamps.extend(symbol_stamps)
            counts[symbol] = len(normalized)
            checksums[symbol] = _checksum(path)
            quality[symbol] = {
                **report,
                **_coverage(normalized, archive_start, archive_end),
            }
        now = datetime.now(UTC).isoformat()
        _atomic_json(
            self.directory / _MANIFEST,
            {
                "schema_version": ARCHIVE_SCHEMA_VERSION,
                "format": self.format,
                "source": source or old.get("source", ""),
                "grain": grain,
                "start": archive_start,
                "end": archive_end,
                "actual_start": min(stamps, default=None),
                "actual_end": max(stamps, default=None),
                "symbols": symbols,
                "bar_count": sum(counts.values()),
                "counts": counts,
                "checksums": checksums,
                "quality": quality,
                "created_at": old.get("created_at", now),
                "updated_at": now,
            },
        )
        return self.directory


def dataset_store(directory: str | Path, format: str | None = None) -> DatasetStore:
    """Open a store explicitly or infer its format from an existing manifest."""
    kind = (format or "").strip().lower()
    manifest_path = Path(directory) / _MANIFEST
    if not kind and manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        kind = str(payload.get("format") or "jsonl").lower()
    if kind in {"", "jsonl"}:
        return JsonlDatasetStore(directory)
    if kind == "parquet":
        return ParquetDatasetStore(directory)
    raise ValueError(f"unknown archive format: {kind}")


def write_symbol_bars(
    directory: str | Path,
    by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    grain: str,
    start: date | datetime | str,
    end: date | datetime | str,
    format: str | None = None,
    source: str = "",
    incremental: bool = False,
) -> Path:
    """Write a versioned archive; defaults remain compatible with JSONL v1."""
    return dataset_store(directory, format).write(
        by_symbol,
        grain=grain,
        start=start,
        end=end,
        source=source,
        incremental=incremental,
    )


def read_symbol_bars(
    directory: str | Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Load an archive into memory (legacy convenience API)."""
    store = dataset_store(directory)
    manifest = store.read_manifest()
    by_symbol = {
        str(symbol): list(store.iter_symbol(str(symbol))) for symbol in manifest.get("symbols", ())
    }
    return manifest, by_symbol


def download_symbol_bars(
    client: Any,
    directory: str | Path,
    *,
    days: int = 14,
    grain: str = "1s",
    symbols: Sequence[str] | None = None,
    end: date | None = None,
    format: str | None = None,
    source: str = "",
    incremental: bool = True,
) -> Path:
    """Fetch historical candles and merge them into a portable archive."""
    from .session import TEHRAN

    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    last = end or datetime.now(TEHRAN).date()
    requested_days = max(1, int(days))
    first = last - timedelta(days=requested_days - 1)
    fund = getattr(client, "fund", client)
    store = dataset_store(directory, format)
    existing_days: dict[str, set[date]] = {symbol: set() for symbol in universe}
    if incremental and (Path(directory) / _MANIFEST).exists():
        for symbol in universe:
            for row in store.iter_symbol(symbol):
                stamp = _bar_key(row)
                if stamp:
                    existing_days[symbol].add(_day(stamp))
    raw: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in universe}
    for symbol in universe:
        cursor = first
        while cursor <= last:
            if cursor not in existing_days[symbol]:
                rows = fund.candles(
                    symbol,
                    start=cursor,
                    end=cursor,
                    grain=grain,
                )
                raw[symbol].extend(list(rows or ()))
            cursor += timedelta(days=1)
    base_url = source or str(getattr(getattr(client, "_http", None), "base_url", ""))
    return store.write(
        raw,
        grain=grain,
        start=first,
        end=last,
        source=base_url,
        incremental=incremental,
    )


__all__ = [
    "ARCHIVE_SCHEMA_VERSION",
    "DatasetStore",
    "JsonlDatasetStore",
    "ParquetDatasetStore",
    "dataset_store",
    "download_symbol_bars",
    "read_symbol_bars",
    "write_symbol_bars",
]
