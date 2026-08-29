"""Align sparse 1s fund bars onto a one-second grid."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from goldarb.data import HistoricalDataProvider, snapshots_from_symbol_bars
from goldarb.universe import GOLD_FUND_SYMBOLS


def test_from_1s_covers_full_universe():
    provider = HistoricalDataProvider.from_1s(3)
    snapshots = list(provider.events())
    assert len(snapshots) == 3
    assert (snapshots[1].timestamp - snapshots[0].timestamp) == timedelta(seconds=1)
    for snapshot in snapshots:
        assert {quote.symbol for quote in snapshot.quotes} == set(GOLD_FUND_SYMBOLS)


def test_symbol_bars_ffill_every_second():
    start = datetime(2026, 8, 29, 8, 30, 0, tzinfo=UTC)
    by_symbol = {
        "طلا": [
            {
                "bar_at": start.isoformat(),
                "close": 20000.0,
                "premium_discount_pct": -1.0,
            },
            {
                "bar_at": (start + timedelta(seconds=2)).isoformat(),
                "close": 20100.0,
                "premium_discount_pct": -1.2,
            },
        ],
        "زر": [
            {
                "bar_at": start.isoformat(),
                "close": 10000.0,
                "premium_discount_pct": 1.0,
            }
        ],
    }
    snapshots = snapshots_from_symbol_bars(by_symbol, ffill=True, step=timedelta(seconds=1))
    assert len(snapshots) == 3
    assert [len(snapshot.quotes) for snapshot in snapshots] == [2, 2, 2]

    def last_of(snapshot, symbol):
        return next(quote.last for quote in snapshot.quotes if quote.symbol == symbol)

    assert float(last_of(snapshots[1], "طلا")) == 20000.0
    assert float(last_of(snapshots[2], "طلا")) == 20100.0
