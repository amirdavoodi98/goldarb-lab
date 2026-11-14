"""The ordinary fund/strategy path exposes independent source and read clocks."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import respx

from goldarb import LabClient
from goldarb._source_time import with_price_source_time
from goldarb.data import LabLiveFeed, LiveDataProvider, snapshots_from_symbol_bars
from goldarb.session import TEHRAN, snapshot_from_live
from goldarb.simulation.models import DomainError, Quote, jsonable

SOURCE = "2026-11-11T09:05:00+03:30"
FETCH = "2026-11-11T09:05:35.123456+03:30"
ROW = {"symbol": "طلا", "last_price": "100", "d_even": "20261111",
       "h_even": "90500", "fetched_at": FETCH}


@respx.mock
def test_single_price_uses_legacy_source_clock_without_extra_requests():
    route = respx.get("https://example.test/api/v1/funds/طلا/last-price/").respond(200, json=ROW)
    with LabClient(base_url="https://example.test", token="test") as client:
        result = client.fund.last_price("طلا")
    assert result == {**ROW, "source_timestamp": SOURCE, "source_time_status": "unverified"}
    assert route.call_count == 1
    assert (datetime.fromisoformat(result["fetched_at"])
            - datetime.fromisoformat(result["source_timestamp"])).total_seconds() == 35.123456


@pytest.mark.parametrize("envelope", [None, "funds", "results", "data", "items", "symbol_map"])
@respx.mock
def test_bulk_preserves_shape_metadata_and_independent_times(envelope):
    other = {**ROW, "symbol": "عیار", "h_even": "90000"}
    rows = [ROW, other]
    expected_rows = [
        {**ROW, "source_timestamp": SOURCE, "source_time_status": "unverified"},
        {**other, "source_timestamp": "2026-11-11T09:00:00+03:30",
         "source_time_status": "unverified"},
    ]
    if envelope == "symbol_map":
        payload = {row["symbol"]: row for row in rows}
        expected = {row["symbol"]: row for row in expected_rows}
    elif envelope:
        payload = {envelope: rows, "count": 2, "session": {"open": True}}
        expected = {envelope: expected_rows, "count": 2, "session": {"open": True}}
    else:
        payload, expected = rows, expected_rows
    original = deepcopy(payload)
    respx.get("https://example.test/api/v1/funds/last-price/").respond(200, json=payload)
    with LabClient(base_url="https://example.test", token="test") as client:
        assert client.fund.last_prices() == expected
    assert payload == original


@pytest.mark.parametrize("fields", [
    {}, {"h_even": "90500"}, {"d_even": "20261111"},
    {"d_even": "0", "h_even": "90500"},
    {"d_even": "20261111", "h_even": "0"},
    {"d_even": "20260230", "h_even": "90500"},
    {"d_even": "20261111", "h_even": "9050012"},
    {"d_even": "20261111", "h_even": "25:05:00"},
    {"source_timestamp": None}, {"source_timestamp": "bad"},
    {"source_timestamp": "2026-11-11T09:05:00"},
])
def test_missing_or_invalid_source_clock_never_uses_fetch_time(fields):
    result = with_price_source_time({"last_price": "100", "fetched_at": FETCH,
                                    "last_update": FETCH, "as_of": FETCH, **fields})
    assert result["source_timestamp"] is None
    assert result["source_time_status"] == "missing"
    assert result["fetched_at"] == FETCH


def test_explicit_server_source_time_wins_and_preserves_verification():
    payload = {**ROW, "source_timestamp": "2026-11-11T05:35:00.654321Z",
               "source_time_status": "verified", "source_time_field": "trade_time"}
    assert with_price_source_time(payload) == payload
    unknown = {**payload, "source_timestamp": None, "source_time_status": "missing_date"}
    assert with_price_source_time(unknown) == unknown  # no legacy substitution


@pytest.mark.parametrize("mode", ["last", "book"])
@respx.mock
def test_both_clocks_reach_strategy_across_polls_without_nav_contamination(mode):
    clock = datetime(2026, 11, 11, 13, 0, tzinfo=TEHRAN)
    rows = [ROW, {**ROW, "symbol": "عیار", "h_even": "90000"}]
    respx.get("https://example.test/api/v1/funds/last-price/").respond(200, json={"funds": rows})
    respx.get("https://example.test/api/v1/funds/nav/live/").respond(
        200, json={"funds": [{"symbol": "طلا", "nav": "99", "source_timestamp": FETCH}]}
    )
    respx.get("https://example.test/api/v1/funds/orderbook/").respond(
        200, json={"funds": [{"symbol": row["symbol"], "best_bid": "99", "best_ask": "101",
                              "fetched_at": FETCH} for row in rows]}
    )
    with LabClient(base_url="https://example.test", token="test") as client:
        provider = LiveDataProvider(
            LabLiveFeed(client, price_policy="tsetmc"), symbols=("طلا", "عیار"),
            include_session_bars=False, now=lambda: clock, quote_fill=mode,
        )
        first = provider.poll()[0]
        clock += timedelta(seconds=1)
        second = provider.poll()[0]
    assert first.timestamp != second.timestamp
    for event in (first, second):
        assert event.quotes[0].source_timestamp == datetime.fromisoformat(SOURCE)
        assert event.quotes[1].source_timestamp != event.quotes[0].source_timestamp
        assert event.quotes[0].fetched_at == datetime.fromisoformat(FETCH)
        assert event.quotes[0].source_time_status == "unverified"
        assert jsonable(event.quotes[0])["source_timestamp"] == SOURCE


def test_missing_price_source_clock_is_not_taken_from_nav():
    from goldarb.data import _quote_from_live

    quote = _quote_from_live("طلا", {"last_price": "100", "fetched_at": FETCH},
                             nav={"nav": "99", "source_timestamp": SOURCE})
    assert quote.source_timestamp is None
    assert quote.source_time_status == "missing"


def test_midpoint_uses_book_source_clock_instead_of_discarded_trade_clock():
    last = {**ROW, "status": "stale"}
    book = {"best_bid": "98", "best_ask": "104", "fetched_at": FETCH}
    for source in (None, "2026-11-11T09:05:20+03:30"):
        depth = {**book, "source_timestamp": source}
        quote = snapshot_from_live(symbol="طلا", last_price=last, orderbook=depth).quotes[0]
        assert quote.last == Decimal("101")
        assert quote.source_timestamp == (datetime.fromisoformat(source) if source else None)
        assert quote.fetched_at == datetime.fromisoformat(FETCH)


def test_forward_fill_retains_both_original_clocks():
    start = datetime.fromisoformat(SOURCE)
    bars = [
        {"bar_at": start.isoformat(), "close": "100", "source_timestamp": SOURCE,
         "fetched_at": FETCH},
        {"bar_at": (start + timedelta(minutes=5)).isoformat(), "close": "101"},
    ]
    events = snapshots_from_symbol_bars({"طلا": bars}, session_hours=False,
                                       step=timedelta(minutes=1))
    assert events[1].quotes[0].source_timestamp == start
    assert events[1].quotes[0].fetched_at == datetime.fromisoformat(FETCH)
    assert events[-1].quotes[0].source_timestamp is None  # bar_at is not publication time


def test_quote_source_timestamp_requires_timezone():
    with pytest.raises(DomainError, match="timezone-aware"):
        Quote(symbol="طلا", source_timestamp=datetime(2026, 11, 11, 9, 5))
