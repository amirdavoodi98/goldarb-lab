"""Source acquisition times survive the live feed and quote normalization."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import respx

from goldarb import LabClient
from goldarb.data import LabLiveFeed, LiveDataProvider
from goldarb.session import TEHRAN, snapshot_from_live, source_read_timestamp
from goldarb.simulation.models import DomainError, Quote, jsonable


@pytest.mark.parametrize("quote_fill", ["last", "book"])
@respx.mock
def test_bulk_prices_keep_independent_source_times_across_polls(quote_fill):
    clock = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    old = (clock - timedelta(minutes=5)).astimezone(UTC).replace(microsecond=123456)
    recent = clock - timedelta(seconds=1, microseconds=654321)
    prices = {"funds": [
        {"symbol": "طلا", "last_price": "100", "fetched_at": old.isoformat()},
        {"symbol": "عیار", "last_price": "200", "fetched_at": recent.isoformat()},
    ]}
    respx.get("https://example.test/api/v1/funds/last-price/").mock(
        return_value=httpx.Response(200, json=prices)
    )
    respx.get("https://example.test/api/v1/funds/nav/live/").mock(
        return_value=httpx.Response(200, json={"funds": [
            {"symbol": "طلا", "nav": "99", "fetched_at": clock.isoformat()},
        ]})
    )
    respx.get("https://example.test/api/v1/funds/orderbook/").mock(
        return_value=httpx.Response(200, json={"funds": [
            {"symbol": symbol, "best_bid": "90", "best_ask": "110",
             "fetched_at": clock.isoformat()}
            for symbol in ("طلا", "عیار")
        ]})
    )
    with LabClient(base_url="https://example.test", token="test") as client:
        assert client.fund.last_prices() == prices
        provider = LiveDataProvider(
            LabLiveFeed(client), symbols=("طلا", "عیار"),
            include_session_bars=False, now=lambda: clock, quote_fill=quote_fill,
        )
        first = provider.poll()[0]
        clock += timedelta(seconds=1)
        second = provider.poll()[0]
    assert second.timestamp == first.timestamp + timedelta(seconds=1)
    for snapshot in (first, second):
        assert [q.fetched_at for q in snapshot.quotes] == [old, recent]
        assert snapshot.quotes[0].nav == Decimal("99")
        assert snapshot.quotes[0].orderbook_fetched_at == clock - timedelta(seconds=1)
    assert jsonable(first.quotes[0])["fetched_at"] == old.isoformat()


@pytest.mark.parametrize("raw", [None, "bad", "2026-08-29T12:00:00", "2026-08-29"])
def test_unknown_source_time_is_not_inferred_from_trade_nav_or_book(raw):
    clock = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    snapshot = snapshot_from_live(
        symbol="طلا",
        last_price={"last_price": "100", "fetched_at": raw,
                    "as_of": clock.isoformat(), "d_even": "20260829", "h_even": "125959"},
        orderbook={"best_bid": "90", "best_ask": "110", "fetched_at": clock.isoformat()},
        now=clock,
    )
    assert snapshot.quotes[0].fetched_at is None
    assert snapshot.quotes[0].orderbook_fetched_at == clock


def test_old_timestamp_is_not_replaced_by_current_time():
    clock = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    old = clock - timedelta(minutes=5)
    snapshot = snapshot_from_live(
        symbol="طلا", last_price={"last_price": "100", "fetched_at": old.isoformat()},
        now=clock,
    )
    assert snapshot.timestamp == old
    assert snapshot.quotes[0].fetched_at == old


def test_midpoint_uses_book_acquisition_time():
    clock = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    book_time = clock - timedelta(seconds=10)
    snapshot = snapshot_from_live(
        symbol="طلا",
        last_price={"last_price": "100", "status": "stale", "fetched_at": clock.isoformat()},
        orderbook={"best_bid": "90", "best_ask": "110", "fetched_at": book_time.isoformat()},
        now=clock,
    )
    assert snapshot.quotes[0].last == Decimal("100")
    assert snapshot.quotes[0].fetched_at == book_time


@respx.mock
def test_single_price_passes_through_source_time():
    payload = {"symbol": "طلا", "last_price": "100",
               "fetched_at": "2026-08-29T09:30:00.123456Z"}
    respx.get("https://example.test/api/v1/funds/طلا/last-price/").mock(
        return_value=httpx.Response(200, json=payload)
    )
    with LabClient(base_url="https://example.test", token="test") as client:
        assert client.fund.last_price("طلا") == payload


def test_legacy_alias_and_timezone_validation():
    stamp = "2026-08-29T12:00:00.123456+03:30"
    assert source_read_timestamp({"last_update": stamp}) == datetime.fromisoformat(stamp)
    with pytest.raises(DomainError, match="timezone-aware"):
        Quote(symbol="طلا", fetched_at=datetime(2026, 8, 29))


def test_nav_timestamp_does_not_fill_missing_price_timestamp():
    from goldarb.data import _quote_from_live

    clock = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    quote = _quote_from_live(
        "طلا", {"last_price": "100"},
        nav={"nav": "99", "fetched_at": clock.isoformat()}, now=clock,
    )
    assert quote.last == Decimal("100")
    assert quote.nav == Decimal("99")
    assert quote.fetched_at is None


def test_forward_fill_retains_original_source_read_time():
    from goldarb.data import snapshots_from_symbol_bars

    start = datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN)
    acquired = start - timedelta(seconds=1, microseconds=123456)
    snapshots = snapshots_from_symbol_bars({"طلا": [
        {"bar_at": start.isoformat(), "close": "100", "fetched_at": acquired.isoformat()},
        {"bar_at": (start + timedelta(seconds=2)).isoformat(), "close": "101"},
    ]})
    assert len(snapshots) == 3
    assert snapshots[0].quotes[0].fetched_at == acquired
    assert snapshots[1].quotes[0].fetched_at == acquired
    assert snapshots[2].quotes[0].fetched_at is None
