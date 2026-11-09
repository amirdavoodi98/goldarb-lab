"""Application-boundary regression tests for typed feeds and configuration."""

from dataclasses import FrozenInstanceError
from datetime import time
from zoneinfo import ZoneInfoNotFoundError

import pytest

from goldarb.config import AppConfig, DataConfig, SessionConfig
from goldarb.data import LabLiveFeed, LiveMarketFeed
from goldarb.feed_contracts import historical_endpoint, live_endpoint
from goldarb.sources import GoldArbApiSource


class SingleSymbolFeed:
    def __init__(self):
        self.calls = []

    def candles(self, symbol, *, start, end, grain="1s"):
        self.calls.append((symbol, start, end, grain))
        return [{"close": 100}]

    def last_price(self, symbol):
        return {"symbol": symbol, "last_price": 100}

    def orderbook(self, symbol):
        return {}


class Client:
    def __init__(self, fund):
        self.fund = fund


def test_live_feed_contract_is_reexported_and_single_symbol_fallback_works():
    endpoint = SingleSymbolFeed()
    assert isinstance(endpoint, LiveMarketFeed)
    assert live_endpoint(Client(endpoint)) is endpoint
    adapter = LabLiveFeed(Client(endpoint))
    assert adapter.candles_many(["A", "B"], start="2026-08-29", end="2026-08-29") == {
        "A": [{"close": 100}],
        "B": [{"close": 100}],
    }
    assert [call[0] for call in endpoint.calls] == ["A", "B"]
    assert adapter.last_prices() is None
    assert adapter.navs_live() is None
    assert adapter.orderbooks() is None


def test_historical_only_client_needs_no_live_or_remote_capabilities():
    class History:
        def candles_many(self, symbols, *, start, end, grain="1s"):
            return {symbol: [{"close": 100}] for symbol in symbols}

    endpoint = History()
    assert historical_endpoint(Client(endpoint)) is endpoint
    source = GoldArbApiSource(endpoint)
    assert source.bars(["A"], start="2026-08-29", end="2026-08-29") == {
        "A": [{"close": 100}],
    }


def test_optional_bulk_capabilities_are_used_independently():
    class BulkFeed(SingleSymbolFeed):
        def candles_many(self, symbols, *, start, end, grain="1s"):
            return {symbol: [{"close": 200}] for symbol in symbols}

        def navs_live(self):
            return {"A": {"nav": 90}}

    endpoint = BulkFeed()
    adapter = LabLiveFeed(endpoint)
    assert adapter.candles_many(["A"], start="2026-08-29", end="2026-08-29") == {
        "A": [{"close": 200}],
    }
    assert endpoint.calls == []
    assert adapter.navs_live() == {"A": {"nav": 90}}
    assert adapter.last_prices() is None
    assert adapter.orderbooks() is None


@pytest.mark.parametrize("resolver", [historical_endpoint, live_endpoint])
def test_client_contract_errors_are_reported_at_the_boundary(resolver):
    with pytest.raises(TypeError, match="client must provide"):
        resolver(Client(object()))


def test_builder_distinguishes_omitted_values_from_explicit_none(tmp_path):
    builder = AppConfig(data=DataConfig(provider="archive", source=str(tmp_path))).to_builder()
    builder.set_runtime(database="paper.db", account_id="account-1")
    builder.set_data(start="2026-08-29", end="2026-08-30")
    builder.set_session(max_polls=5)
    builder.set_runtime().set_data().set_session().set_live()
    preserved = builder.build()
    assert preserved.runtime.database == "paper.db"
    assert preserved.runtime.account_id == "account-1"
    assert preserved.data.start == "2026-08-29"
    assert preserved.data.end == "2026-08-30"
    assert preserved.session.max_polls == 5
    builder.set_runtime(database=None, account_id=None)
    builder.set_data(start=None)
    builder.set_live(max_polls=None)
    cleared = builder.build()
    assert cleared.runtime.database is None
    assert cleared.runtime.account_id is None
    assert cleared.data.start is None
    assert cleared.data.end == "2026-08-30"
    assert cleared.session.max_polls is None


def test_session_settings_resolve_to_immutable_domain_values():
    config = SessionConfig(timezone="Asia/Tehran", start="12:15:30", end="17:45:00")
    schedule = config.resolve_schedule()
    assert schedule.timezone.key == "Asia/Tehran"
    assert schedule.opens_at == time(12, 15, 30)
    assert schedule.closes_at == time(17, 45)
    assert config.start == "12:15:30"
    with pytest.raises(FrozenInstanceError):
        schedule.opens_at = time(10)


@pytest.mark.parametrize(
    ("config", "error"),
    [
        (SessionConfig(start="invalid"), ValueError),
        (SessionConfig(timezone="Unknown/Nowhere"), ZoneInfoNotFoundError),
    ],
)
def test_session_settings_reject_invalid_external_values(config, error):
    with pytest.raises(error):
        config.resolve_schedule()
