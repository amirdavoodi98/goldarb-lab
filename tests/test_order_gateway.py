"""OrderGateway: strategy orders do not go through submit_buy."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from goldarb import AppConfig, StrategyRunner
from goldarb.archive import write_symbol_bars
from goldarb.gateway import (
    LocalPaperOrderGateway,
    OrderGateway,
    RemoteSimulatorOrderGateway,
)
from goldarb.simulation import LocalSimulator, OrderStatus, RemoteSimulator, Side
from goldarb.simulation.brokers import PaperBroker
from goldarb.simulation.inmemory_remote import InMemoryRemoteVenue
from goldarb.simulation.models import MarketSnapshot, Quote
from goldarb.strategies import PriceMomentumStrategy
from goldarb.strategy import Strategy

TEHRAN = ZoneInfo("Asia/Tehran")
WHEN = datetime(2026, 8, 29, 12, 30, tzinfo=TEHRAN)


class _BuyOnce(Strategy):
    name = "buy_once"

    def __init__(self) -> None:
        self._sent = False

    def on_market_data(self, ctx) -> None:
        if self._sent or ctx.market is None or not ctx.market.quotes:
            return
        self._sent = True
        ctx.submit_order(
            symbol=ctx.market.quotes[0].symbol,
            side="BUY",
            quantity="1",
            order_type="MARKET",
            client_order_id="gateway-buy",
        )


class _Fund:
    def __init__(self, prices: tuple[str, ...]) -> None:
        self._prices = prices
        self._index = 0

    def last_price(self, symbol: str) -> dict[str, str]:
        price = self._prices[min(self._index, len(self._prices) - 1)]
        self._index += 1
        return {"symbol": symbol, "last_price": price}

    def orderbook(self, symbol: str) -> dict[str, str]:
        del symbol
        return {}

    def candles(self, symbol: str, *, start: str, end: str, grain: str = "1s") -> list[dict]:
        del symbol, start, end, grain
        return []


class _Client:
    def __init__(
        self,
        simulation: RemoteSimulator | None = None,
        prices: tuple[str, ...] = ("100", "110"),
    ) -> None:
        self.fund = _Fund(prices)
        self.simulation = simulation

    def close(self) -> None:
        return None


def _snapshot(*, last: str = "100", ask: str = "100") -> MarketSnapshot:
    return MarketSnapshot(
        event_id="book-1",
        timestamp=datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN),
        quotes=(
            Quote(
                symbol="طلا",
                last=Decimal(last),
                ask=Decimal(ask),
                bid=Decimal("99"),
                ask_size=Decimal("5"),
                bid_size=Decimal("5"),
            ),
        ),
    )


def _archive(directory, closes: tuple[str, str] = ("100", "110")) -> None:
    origin = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    rows = [
        {"bar_at": (origin + timedelta(seconds=index)).isoformat(), "close": close}
        for index, close in enumerate(closes)
    ]
    write_symbol_bars(
        directory,
        {"طلا": rows},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )


def test_local_adapter_submit_cancel_positions_cash_without_feed(tmp_path):
    sim = LocalSimulator(tmp_path / "local.db", fee=None)
    account = sim.create_account(initial_cash="100000", fee_rate="0")
    sim.feed(_snapshot())
    fed: list[str] = []
    real_feed = sim.feed

    def spy_feed(snapshot: MarketSnapshot) -> bool:
        fed.append(snapshot.event_id)
        return real_feed(snapshot)

    sim.feed = spy_feed  # type: ignore[method-assign]
    gateway = LocalPaperOrderGateway(sim, account.id)
    assert isinstance(gateway, OrderGateway)
    assert not hasattr(LocalPaperOrderGateway, "create_account")
    assert not hasattr(LocalPaperOrderGateway, "equity_history")
    assert not hasattr(LocalPaperOrderGateway, "feed")

    resting = gateway.submit(
        symbol="طلا",
        side="BUY",
        quantity="1",
        order_type="LIMIT",
        limit_price="50",
        client_order_id="rest",
    )
    assert resting.status == OrderStatus.ACCEPTED
    assert gateway.positions() == ()
    assert gateway.cash() == Decimal("100000")
    cancelled = gateway.cancel(resting.id)
    assert cancelled.status == OrderStatus.CANCELLED

    filled = gateway.submit(
        symbol="طلا",
        side=Side.BUY,
        quantity="1",
        order_type="MARKET",
        client_order_id="fill",
    )
    assert filled.status == OrderStatus.FILLED
    assert gateway.positions()[0].quantity == Decimal("1")
    assert gateway.cash() < Decimal("100000")
    assert fed == []


def test_remote_adapter_does_not_feed_or_add_http_fields():
    venue = InMemoryRemoteVenue(fee_rate=Decimal("0"))
    venue.set_quote(
        Quote(symbol="طلا", ask=Decimal("101"), last=Decimal("100"), ask_size=Decimal("5"))
    )
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="10000", fee_rate="0")
    fed: list[str] = []

    def spy_feed(snapshot: object) -> bool:
        fed.append("feed")
        del snapshot
        return False

    remote.feed = spy_feed  # type: ignore[method-assign]
    gateway = RemoteSimulatorOrderGateway(remote, account.id)
    assert isinstance(gateway, OrderGateway)
    assert not hasattr(RemoteSimulatorOrderGateway, "feed")
    order = gateway.submit(
        symbol="طلا",
        side="BUY",
        quantity="1",
        order_type="LIMIT",
        limit_price="102",
        client_order_id="remote-gw",
        time_in_force="IOC",
    )
    assert order.id in venue.orders
    body_keys = set(venue.orders[order.id].__dict__)
    assert "time_in_force" not in body_keys or order.time_in_force.value == "DAY"
    assert fed == []
    snap = _snapshot()
    assert RemoteSimulator.feed(remote, snap) is False
    assert gateway.cash() == remote.get_account(account.id).cash


def test_same_strategy_switches_modes_only_through_order_gateway(tmp_path, monkeypatch):
    archive = tmp_path / "bars"
    _archive(archive)
    submits: list[str] = []
    constructed: list[str] = []
    preset_calls: list[str] = []
    buy_calls: list[str] = []

    real_submit = LocalPaperOrderGateway.submit
    real_init = LocalPaperOrderGateway.__init__
    real_get = __import__(
        "goldarb.simulation.brokers", fromlist=["get_broker"]
    ).get_broker

    def spy_init(self, broker, account_id=None):
        real_init(self, broker, account_id)
        constructed.append(type(self).__name__)

    def spy_submit(self, **kwargs):
        submits.append(type(self).__name__)
        return real_submit(self, **kwargs)

    def spy_get(code: str):
        preset_calls.append(code)
        return real_get(code)

    def spy_buy(self, account, **kwargs):
        buy_calls.append(type(self).__name__)
        raise AssertionError("submit_buy is not the Strategy path")

    monkeypatch.setattr(LocalPaperOrderGateway, "__init__", spy_init)
    monkeypatch.setattr(LocalPaperOrderGateway, "submit", spy_submit)
    monkeypatch.setattr("goldarb.runtime.get_broker", spy_get)
    monkeypatch.setattr("goldarb.simulation.brokers.get_broker", spy_get)
    monkeypatch.setattr(PaperBroker, "submit_buy", spy_buy)
    monkeypatch.setattr(PaperBroker, "submit_sell", spy_buy)

    strategy = PriceMomentumStrategy(quantity="1", threshold_pct="0.5")
    backtest = (
        AppConfig.builder()
        .set_archive(
            archive,
            symbols=["طلا"],
            start="2026-08-29",
            end="2026-08-29",
            mode="backtest",
        )
        .set_broker("agah")
        .set_strategy("price_momentum", quantity="1", threshold_pct="0.5")
        .set_initial_cash("100000")
        .build()
    )
    back = StrategyRunner.from_config(backtest).run(strategy)
    assert back.metrics.n_orders >= 1
    assert back.config.fee_rate == "0.0005"
    assert back.config.allow_short is False
    assert preset_calls == ["agah"]
    assert constructed == ["LocalPaperOrderGateway"]
    assert submits == ["LocalPaperOrderGateway"]
    assert buy_calls == []

    live = (
        AppConfig.builder()
        .set_live(symbols=["طلا"], max_polls=2)
        .set_broker("agah")
        .set_strategy("price_momentum", quantity="1", threshold_pct="0.5")
        .set_initial_cash("100000")
        .build()
    )
    paper = (
        StrategyRunner.from_config(live)
        .set_client(_Client())
        .set_live_clock(sleep=lambda _seconds: None, now=lambda: WHEN)
        .run(strategy)
    )
    assert paper.metrics.n_orders >= 1
    assert paper.config.fee_rate == "0.0005"
    assert preset_calls == ["agah", "agah"]
    assert constructed == ["LocalPaperOrderGateway", "LocalPaperOrderGateway"]
    assert submits == ["LocalPaperOrderGateway", "LocalPaperOrderGateway"]
    assert buy_calls == []


def test_live_paper_remote_gateway_does_not_feed(monkeypatch):
    venue = InMemoryRemoteVenue(fee_rate=Decimal("0"))
    venue.set_quote(
        Quote(symbol="طلا", last=Decimal("100"), ask=Decimal("101"), ask_size=Decimal("5"))
    )
    remote = RemoteSimulator(venue)
    fed: list[str] = []
    constructed: list[str] = []
    real_init = RemoteSimulatorOrderGateway.__init__

    def spy_init(self, broker, account_id=None):
        real_init(self, broker, account_id)
        constructed.append(type(self).__name__)

    def spy_feed(snapshot: object) -> bool:
        fed.append("feed")
        del snapshot
        return False

    remote.feed = spy_feed  # type: ignore[method-assign]
    monkeypatch.setattr(RemoteSimulatorOrderGateway, "__init__", spy_init)
    config = (
        AppConfig.builder()
        .set_live(symbols=["طلا"], max_polls=1, mode="live_paper_remote")
        .set_fee("NoFee")
        .set_initial_cash("100000")
        .build()
    )
    result = (
        StrategyRunner.from_config(config)
        .set_client(_Client(remote, prices=("100",)))
        .set_live_clock(sleep=lambda _seconds: None, now=lambda: WHEN)
        .set_strategy(_BuyOnce())
        .run()
    )
    assert result.metrics.n_orders == 1
    assert constructed == ["RemoteSimulatorOrderGateway"]
    assert fed == []
    assert RemoteSimulator.feed(remote, _snapshot()) is False


def test_unknown_transport_is_rejected():
    with pytest.raises(TypeError, match="OrderGateway"):
        from goldarb.gateway import order_gateway_for

        order_gateway_for(object())
