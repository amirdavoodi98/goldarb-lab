"""Align sparse 1s fund bars onto a one-second grid."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from goldarb.config import AppConfig, DataConfig
from goldarb.data import HistoricalDataProvider, LiveDataProvider, snapshots_from_symbol_bars
from goldarb.universe import GOLD_FUND_SYMBOLS

TEHRAN = ZoneInfo("Asia/Tehran")


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
    assert snapshots[0].quotes[0].bid is None
    assert snapshots[0].quotes[0].ask is None


def _session_bar(**fields: object) -> dict[str, object]:
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    row: dict[str, object] = {"bar_at": start.isoformat(), "close": "100"}
    row.update(fields)
    return row


def test_quote_fill_last_is_default_and_clears_a_historical_book():
    assert DataConfig().quote_fill == "last"
    loaded = AppConfig.from_mapping(
        {"data": {"start": "2026-08-01", "end": "2026-08-02", "quote_fill": "BOOK"}}
    )
    assert loaded.data.quote_fill == "book"
    built = (
        AppConfig.builder()
        .set_period("2026-08-01", "2026-08-02")
        .set_data(quote_fill="last")
        .build()
    )
    assert built.data.quote_fill == "last"
    with pytest.raises(ValueError, match="quote_fill"):
        DataConfig(quote_fill="mid")

    snapshots = snapshots_from_symbol_bars(
        {
            "طلا": [
                _session_bar(
                    bid="90",
                    ask="110",
                    bid_size="5",
                    ask_size="4",
                )
            ]
        },
        quote_fill="last",
    )
    quote = snapshots[0].quotes[0]
    assert quote.last == Decimal("100")
    assert quote.bid is None
    assert quote.ask is None
    assert quote.bid_size is None
    assert quote.ask_size is None


def test_quote_fill_book_copies_last_or_keeps_a_bar_book():
    copied = snapshots_from_symbol_bars({"طلا": [_session_bar()]}, quote_fill="book")
    quote = copied[0].quotes[0]
    assert quote.last == Decimal("100")
    assert quote.bid == Decimal("100")
    assert quote.ask == Decimal("100")

    kept = snapshots_from_symbol_bars(
        {"طلا": [_session_bar(bid="90", ask="110", ask_size="4")]},
        quote_fill="book",
    )
    booked = kept[0].quotes[0]
    assert booked.bid == Decimal("90")
    assert booked.ask == Decimal("110")
    assert booked.ask_size == Decimal("4")
    assert booked.last == Decimal("100")


class _BookFeed:
    def __init__(self, clock: datetime) -> None:
        self.clock = clock

    def candles(self, symbol, *, start, end, grain="1s"):
        del symbol, start, end, grain
        return []

    def last_price(self, symbol):
        del symbol
        return {
            "last_price": "100",
            "status": "ok",
            "fetched_at": self.clock.isoformat(),
        }

    def orderbook(self, symbol):
        del symbol
        return {
            "best_bid": "90",
            "best_ask": "110",
            "buy_orders": [{"volume": "5"}],
            "sell_orders": [{"volume": "4"}],
            "fetched_at": self.clock.isoformat(),
        }


def _live_quote(quote_fill: str):
    clock = datetime(2026, 8, 29, 12, 0, 5, tzinfo=TEHRAN)
    provider = LiveDataProvider(
        _BookFeed(clock),
        symbol="طلا",
        include_session_bars=False,
        session_day=clock.date(),
        max_polls=1,
        sleep=lambda _seconds: None,
        now=lambda: clock,
        quote_fill=quote_fill,
    )
    events = list(provider.events())
    assert len(events) == 1
    return events[0].quotes[0]


def test_live_quote_fill_last_clears_book_and_book_keeps_it():
    cleared = _live_quote("last")
    assert cleared.last == Decimal("100")
    assert cleared.bid is None
    assert cleared.ask is None
    assert cleared.bid_size is None
    assert cleared.ask_size is None

    booked = _live_quote("book")
    assert booked.last == Decimal("100")
    assert booked.bid == Decimal("90")
    assert booked.ask == Decimal("110")
    assert booked.bid_size == Decimal("5")
    assert booked.ask_size == Decimal("4")
