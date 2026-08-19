#!/usr/bin/env python3
"""
merge_missing_data_archive.py — ONE-TIME cleanup script.

This merges the deeper history stored under archive/missing_data/... into
the canonical archive/... locations.

Dedup rules:
- fund bars: dedup by bar_at
- ime cdc daily: dedup by trade_date
- holdings/issued_units snapshots: dedup by (symbol, captured_at)

Safe to re-run.
"""

from __future__ import annotations

import json
from pathlib import Path

ARCHIVE = Path("archive")
OLD_BASE = ARCHIVE / "missing_data"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def merge_by_key(canonical: Path, old: Path, key_field: str) -> int:
    canon_records = _read_jsonl(canonical)
    old_records = _read_jsonl(old)
    if not old_records:
        return 0

    seen = {str(r.get(key_field)) for r in canon_records if r.get(key_field)}
    added = 0
    for rec in old_records:
        key = str(rec.get(key_field))
        if not key or key in seen:
            continue
        canon_records.append(rec)
        seen.add(key)
        added += 1

    canon_records.sort(key=lambda r: str(r.get(key_field, "")))
    _write_jsonl(canonical, canon_records)
    return added


def merge_snapshots(canonical: Path, old: Path) -> int:
    canon_records = _read_jsonl(canonical)
    old_records = _read_jsonl(old)
    if not old_records:
        return 0

    seen = {(r.get("symbol"), r.get("captured_at")) for r in canon_records}
    added = 0
    for rec in old_records:
        key = (rec.get("symbol"), rec.get("captured_at"))
        if key in seen:
            continue
        canon_records.append(rec)
        seen.add(key)
        added += 1

    canon_records.sort(key=lambda r: str(r.get("captured_at", "")))
    _write_jsonl(canonical, canon_records)
    return added


def main() -> None:
    total_added = 0

    fund_bars_old_dir = OLD_BASE / "fund_bars_1m"
    if fund_bars_old_dir.exists():
        for old_file in fund_bars_old_dir.glob("*.jsonl"):
            symbol = old_file.stem
            canonical = ARCHIVE / "fund_bars_1m" / f"{symbol}.jsonl"
            added = merge_by_key(canonical, old_file, "bar_at")
            print(f"fund_bars_1m:{symbol} -> +{added} rows merged")
            total_added += added

    ime_old_dir = OLD_BASE / "ime_cdc_daily"
    if ime_old_dir.exists():
        for old_file in ime_old_dir.glob("*.jsonl"):
            contract = old_file.stem
            canonical = ARCHIVE / "ime_cdc_daily" / f"{contract}.jsonl"
            added = merge_by_key(canonical, old_file, "trade_date")
            print(f"ime_cdc_daily:{contract} -> +{added} rows merged")
            total_added += added

    snapshots_old_dir = OLD_BASE / "fund_snapshots"
    if snapshots_old_dir.exists():
        holdings_old = snapshots_old_dir / "holdings_history.jsonl"
        units_old = snapshots_old_dir / "issued_units_history.jsonl"
        added = merge_snapshots(ARCHIVE / "holdings_history.jsonl", holdings_old)
        print(f"holdings_history -> +{added} rows merged")
        total_added += added
        added = merge_snapshots(ARCHIVE / "issued_units_history.jsonl", units_old)
        print(f"issued_units_history -> +{added} rows merged")
        total_added += added

    print(f"\nTotal rows merged into canonical archive: {total_added}")
    print("\nOnce verified, you can remove the old tree:")
    print(f"  rm -rf {OLD_BASE}")


if __name__ == "__main__":
    main()
