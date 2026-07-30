"""Unit tests for goldarb-lab (no live network)."""

from datetime import date

from goldarb._http import iter_date_chunks


def test_iter_date_chunks_splits():
    chunks = list(
        iter_date_chunks(date(2026, 7, 1), date(2026, 7, 10), max_span_days=7)
    )
    assert chunks == [
        (date(2026, 7, 1), date(2026, 7, 8)),
        (date(2026, 7, 9), date(2026, 7, 10)),
    ]


def test_iter_date_chunks_single():
    chunks = list(
        iter_date_chunks("2026-07-01", "2026-07-03", max_span_days=7)
    )
    assert len(chunks) == 1
    assert chunks[0] == (date(2026, 7, 1), date(2026, 7, 3))
