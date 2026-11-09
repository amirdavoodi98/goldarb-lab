"""Structural contracts for market endpoints and optional bulk capabilities.

External rows remain dictionaries because their columns vary by endpoint.
Client wrapping and optional bulk calls are handled only by the data adapters.
"""

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol, TypeVar, runtime_checkable

EndpointT = TypeVar("EndpointT", covariant=True)
DateInput = date | datetime | str


@runtime_checkable
class FundClient(Protocol[EndpointT]):
    @property
    def fund(self) -> EndpointT: ...


@runtime_checkable
class CandleFeed(Protocol):
    def candles(
        self, symbol: str, *, start: DateInput, end: DateInput, grain: str = "1s"
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class LiveMarketFeed(CandleFeed, Protocol):
    def last_price(self, symbol: str) -> dict[str, Any]: ...

    def orderbook(self, symbol: str) -> dict[str, Any]: ...


@runtime_checkable
class BulkCandleFeed(Protocol):
    def candles_many(
        self, symbols: Sequence[str], *, start: DateInput, end: DateInput, grain: str = "1s"
    ) -> dict[str, list[dict[str, Any]]]: ...


@runtime_checkable
class BulkLastPrices(Protocol):
    def last_prices(self) -> object: ...


@runtime_checkable
class BulkNavs(Protocol):
    def navs_live(self) -> object: ...


@runtime_checkable
class BulkOrderbooks(Protocol):
    def orderbooks(self) -> object: ...


class FundEndpoint(LiveMarketFeed, BulkCandleFeed, Protocol):
    """Full fund endpoint implemented by LabClient.fund."""


def historical_endpoint(client: object) -> BulkCandleFeed:
    endpoint = client.fund if isinstance(client, FundClient) else client
    if not isinstance(endpoint, BulkCandleFeed):
        raise TypeError("historical client must provide candles_many() or fund.candles_many()")
    return endpoint


def live_endpoint(client: object) -> LiveMarketFeed:
    endpoint = client.fund if isinstance(client, FundClient) else client
    if not isinstance(endpoint, LiveMarketFeed):
        raise TypeError("live client must provide last_price(), orderbook(), and candles()")
    return endpoint
