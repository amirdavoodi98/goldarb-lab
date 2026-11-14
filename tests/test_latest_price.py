"""Strategy feeds use trusted multi-source prices and never silently downgrade."""
from datetime import UTC, datetime

import httpx
import pytest
import respx

from goldarb import LabClient
from goldarb.data import LabLiveFeed
from goldarb.session import snapshot_from_live


@respx.mock
def test_latest_trade_endpoints_and_live_feed_use_new_contract():
    row = {'symbol': 'طلا', 'last_price': 100, 'source': 'agah',
           'source_timestamp': '2026-11-14T10:00:00+00:00',
           'source_time_status': 'verified', 'fetched_at': '2026-11-14T10:00:01+00:00',
           'status': 'ok', 'selection_policy': 'newest_verified_trade'}
    single = respx.get('https://example.test/api/v1/funds/طلا/latest-price/').mock(
        return_value=httpx.Response(200, json=row))
    bulk = respx.get('https://example.test/api/v1/funds/latest-price/').mock(
        return_value=httpx.Response(200, json={'count': 1, 'funds': [row]}))
    with LabClient(base_url='https://example.test', token='test-token') as client:
        assert client.fund.latest_price('طلا')['source'] == 'agah'
        assert client.fund.latest_prices()['funds'][0]['last_price'] == 100
        feed = LabLiveFeed(client)
        assert feed.last_price('طلا')['source_time_status'] == 'verified'
        assert feed.last_prices()['funds'][0]['source'] == 'agah'
    assert single.call_count == bulk.call_count == 2
    assert single.calls[0].request.headers['Authorization'] == 'Token test-token'


@respx.mock
def test_new_api_failure_does_not_fall_back_to_legacy_tsetmc():
    respx.get('https://example.test/api/v1/funds/latest-price/').mock(
        return_value=httpx.Response(503, json={'detail': 'stream disabled'}))
    with LabClient(base_url='https://example.test', token='test-token') as client:
        with pytest.raises(httpx.HTTPStatusError):
            LabLiveFeed(client).last_prices()
    assert len(respx.calls) == 1


@pytest.mark.parametrize('status', ['stale', 'unavailable'])
def test_unusable_trusted_trade_is_not_replaced_with_book_midpoint(status):
    row = {'selection_policy': 'newest_verified_trade', 'status': status,
           'last_price': 100, 'close_price': 99}
    book = {'buy': [{'price': 101}], 'sell': [{'price': 103}]}
    assert snapshot_from_live(symbol='طلا', last_price=row, orderbook=book) is None


def test_fresh_trusted_trade_keeps_source_and_acquisition_clocks_separate():
    row = {'selection_policy': 'newest_verified_trade', 'status': 'ok', 'last_price': 100,
           'source_timestamp': '2026-11-14T10:00:00+00:00', 'source_time_status': 'verified',
           'fetched_at': '2026-11-14T10:00:01+00:00'}
    snapshot = snapshot_from_live(symbol='طلا', last_price=row)
    assert snapshot is not None
    assert snapshot.quotes[0].last == 100
    assert snapshot.quotes[0].source_timestamp == datetime(2026, 11, 14, 10, tzinfo=UTC)
    assert snapshot.quotes[0].fetched_at == datetime(2026, 11, 14, 10, 0, 1, tzinfo=UTC)


@respx.mock
def test_default_strategy_poll_consumes_trusted_prices_and_skips_unavailable():
    from goldarb.data import LiveDataProvider
    from goldarb.session import TEHRAN

    clock = datetime(2026, 11, 14, 13, 30, tzinfo=TEHRAN)
    rows = [
        {'symbol': 'طلا', 'last_price': 100, 'source': 'agah',
         'source_timestamp': '2026-11-14T10:00:00+00:00',
         'source_time_status': 'verified', 'fetched_at': '2026-11-14T10:00:00+00:00',
         'status': 'ok', 'selection_policy': 'newest_verified_trade'},
        {'symbol': 'عیار', 'last_price': None, 'status': 'unavailable',
         'selection_policy': 'newest_verified_trade'},
    ]
    respx.get('https://example.test/api/v1/funds/latest-price/').respond(
        200, json={'funds': rows})
    respx.get('https://example.test/api/v1/funds/nav/live/').respond(200, json={'funds': []})
    respx.get('https://example.test/api/v1/funds/orderbook/').respond(200, json={'funds': [
        {'symbol': symbol, 'best_bid': 98, 'best_ask': 102}
        for symbol in ('طلا', 'عیار')
    ]})
    with LabClient(base_url='https://example.test', token='test-token') as client:
        provider = LiveDataProvider(LabLiveFeed(client), symbols=['طلا', 'عیار'],
                                    include_session_bars=False, now=lambda: clock)
        snapshot = provider.poll()[0]
    assert [(quote.symbol, quote.last) for quote in snapshot.quotes] == [('طلا', 100)]
    assert snapshot.quotes[0].source_time_status == 'verified'
    assert all('/last-price/' not in str(call.request.url) for call in respx.calls)


@pytest.mark.parametrize('payload', [[], {'funds': [{}]}, {'funds': 'invalid'}])
@respx.mock
def test_malformed_bulk_response_fails_closed(payload):
    respx.get('https://example.test/api/v1/funds/latest-price/').respond(200, json=payload)
    with LabClient(base_url='https://example.test', token='test-token') as client:
        with pytest.raises(ValueError, match='latest-price'):
            LabLiveFeed(client).last_prices()
