"""Archive quality metadata and legacy manifests keep their serialized contracts."""

import json

import pytest

from goldarb.archive import JsonlDatasetStore, ParquetDatasetStore, read_symbol_bars


@pytest.fixture(params=[JsonlDatasetStore, ParquetDatasetStore], ids=["jsonl", "parquet"])
def store(request, tmp_path):
    if request.param is ParquetDatasetStore:
        pytest.importorskip("pyarrow")
    return request.param(tmp_path)


def test_archive_quality_tracks_invalid_duplicate_and_missing_days(store):
    store.write(
        {"A": [
            {"bar_at": "2026-08-31T12:00:00+00:00", "close": 300},
            {"bar_at": "2026-08-29T12:00:00+00:00", "close": 100},
            {"close": 999},
            {"bar_at": "2026-08-29T12:00:00+00:00", "close": 200},
        ]},
        grain="1s", start="2026-08-29", end="2026-08-31",
    )
    manifest, rows = read_symbol_bars(store.directory)
    assert manifest["quality"]["A"] == {
        "duplicates_removed": 1,
        "invalid_rows": 1,
        "out_of_order_rows": 1,
        "covered_days": ["2026-08-29", "2026-08-31"],
        "missing_days": ["2026-08-30"],
    }
    assert [row["close"] for row in rows["A"]] == [200, 300]
    assert manifest["counts"] == {"A": 2}
    assert manifest["bar_count"] == 2
    assert manifest["actual_start"] == "2026-08-29T12:00:00+00:00"
    assert manifest["actual_end"] == "2026-08-31T12:00:00+00:00"
    assert json.loads(json.dumps(manifest)) == manifest


def test_empty_archive_keeps_nullable_bounds_and_empty_mappings(store):
    store.write({}, grain="1s", start="2026-08-29", end="2026-08-29")
    manifest = store.read_manifest()
    assert manifest["actual_start"] is None
    assert manifest["actual_end"] is None
    assert manifest["symbols"] == []
    assert manifest["counts"] == {}
    assert manifest["quality"] == {}
    assert manifest["checksums"] == {}
    assert manifest["bar_count"] == 0


def test_reading_legacy_manifest_preserves_missing_and_extension_fields(tmp_path):
    manifest = {"grain": "1s", "symbols": [], "custom_metadata": {"owner": "lab"}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert JsonlDatasetStore(tmp_path).read_manifest() == manifest
