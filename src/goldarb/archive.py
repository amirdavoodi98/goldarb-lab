"""Portable JSONL archive of per-symbol bars for air-gapped backtests."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .universe import GOLD_FUND_SYMBOLS


def write_symbol_bars(
    directory: str | Path,
    by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    grain: str,
    start: date | datetime | str,
    end: date | datetime | str,
) -> Path:
    """Write one JSONL file per symbol plus ``manifest.json``."""
    dest = Path(directory)
    dest.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for symbol, rows in by_symbol.items():
        path = dest / f"{symbol}.jsonl"
        n = 0
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(dict(row), ensure_ascii=False, default=str))
                handle.write("\n")
                n += 1
        counts[symbol] = n
    manifest = {
        "grain": grain,
        "start": str(start)[:10],
        "end": str(end)[:10],
        "symbols": list(by_symbol),
        "bar_count": sum(counts.values()),
        "counts": counts,
    }
    (dest / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest


def read_symbol_bars(
    directory: str | Path,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """Load ``manifest.json`` and per-symbol JSONL files."""
    dest = Path(directory)
    manifest_path = dest / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"archive manifest not found: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    symbols = manifest.get("symbols") or []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for symbol in symbols:
        path = dest / f"{symbol}.jsonl"
        rows: list[dict[str, Any]] = []
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    rows.append(json.loads(line))
        by_symbol[str(symbol)] = rows
    return manifest, by_symbol


def download_symbol_bars(
    client: Any,
    directory: str | Path,
    *,
    days: int = 14,
    grain: str = "1s",
    symbols: Sequence[str] | None = None,
    end: date | None = None,
) -> Path:
    """Fetch ``grain`` candles for the gold-fund universe and persist them."""
    from .session import TEHRAN

    universe = tuple(symbols) if symbols is not None else GOLD_FUND_SYMBOLS
    last = end or datetime.now(TEHRAN).date()
    first = last - timedelta(days=max(1, int(days)))
    fund = getattr(client, "fund", client)
    raw = fund.candles_many(universe, start=first, end=last, grain=grain)
    if not isinstance(raw, dict):
        raw = {}
    return write_symbol_bars(directory, raw, grain=grain, start=first, end=last)
