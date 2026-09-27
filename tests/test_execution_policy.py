"""ExecutionPolicy: venue shape outside Strategy, shared by backtest and local paper."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from goldarb.archive import write_symbol_bars
from goldarb.config import AppConfig, ModelConfig
from goldarb.data import HistoricalDataProvider, LiveDataProvider
from goldarb.engine import BacktestEngine, LiveSimulationEngine, RunConfig
from goldarb.execution import FixedSlippage, PercentFee
from goldarb.execution_policy import (
    REMOTE_POLICY_ERROR,
    NoOpExecutionPolicy,
    OffsetLimitPolicy,
    RawOrder,
    policy_is_noop,
)
from goldarb.runtime import StrategyRunner, build_execution_policy
from goldarb.simulation import LocalSimulator, RemoteSimulator
from goldarb.simulation.inmemory_remote import InMemoryRemoteVenue
from goldarb.simulation.models import (
    MarketSnapshot,
    OrderType,
    Quote,
    Side,
    TimeInForce,
)
from goldarb.strategy import Strategy, StrategyContext

TEHRAN = ZoneInfo("Asia/Tehran")


def _touch_policy(**params: str) -> OffsetLimitPolicy:
    base = {
        "price_tick": "1",
        "market_offset": "0",
        "min_quantity": "1",
        "time_in_force": "DAY",
    }
    base.update(params)
    return OffsetLimitPolicy.from_params(base)


class _BuyMarket(Strategy):
    name = "buy_market"

    def __init__(self, quantity: str = "1") -> None:
        self.quantity = quantity
        self._sent = False

    def on_market_data(self, ctx) -> None:
        if self._sent or ctx.market is None or not ctx.market.quotes:
            return
        self._sent = True
        ctx.submit_order(
            symbol=ctx.market.quotes[0].symbol,
            side="BUY",
            quantity=self.quantity,
            order_type="MARKET",
            client_order_id="buy-market",
        )


def _bar() -> dict[str, str]:
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    return {
        "bar_at": start.isoformat(),
        "close": "100",
        "bid": "90",
        "ask": "110",
        "bid_size": "5",
        "ask_size": "4",
    }


class _BarFeed:
    def candles(self, symbol, *, start, end, grain="1s"):
        del symbol, start, end, grain
        return [_bar()]

    def last_price(self, symbol):
        del symbol
        return {}

    def orderbook(self, symbol):
        del symbol
        return {}


def _run_engines(tmp_path, *, quote_fill: str, policy: OffsetLimitPolicy, slippage=None):
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    historical = HistoricalDataProvider.from_symbol_bars(
        {"طلا": [_bar()]},
        quote_fill=quote_fill,
        lazy=False,
        session_hours=False,
        fill_session=False,
    )
    backtest = BacktestEngine().run(
        _BuyMarket(),
        historical,
        RunConfig(strategy_name="buy_market", initial_cash="100000"),
        simulator=LocalSimulator(tmp_path / f"backtest-{quote_fill}.db"),
        fee=PercentFee("0"),
        slippage=slippage,
        execution_policy=policy,
        quote_fill=quote_fill,
    )
    live = LiveSimulationEngine().run(
        _BuyMarket(),
        LiveDataProvider(
            _BarFeed(),
            symbol="طلا",
            bar_grain="1s",
            include_session_bars=True,
            session_day=start.date(),
            max_polls=1,
            sleep=lambda _seconds: None,
            now=lambda: start + timedelta(seconds=2),
            quote_fill=quote_fill,
        ),
        RunConfig(strategy_name="buy_market", initial_cash="100000"),
        simulator=LocalSimulator(tmp_path / f"live-{quote_fill}.db"),
        fee=PercentFee("0"),
        slippage=slippage,
        execution_policy=policy,
        quote_fill=quote_fill,
    )
    return backtest, live


def test_noop_is_the_default_and_keeps_market_orders(tmp_path):
    assert AppConfig().execution_policy.name == "NoOp"
    assert policy_is_noop(build_execution_policy(AppConfig().execution_policy))
    historical = HistoricalDataProvider.from_symbol_bars(
        {"طلا": [_bar()]},
        quote_fill="last",
        lazy=False,
        session_hours=False,
        fill_session=False,
    )
    result = BacktestEngine().run(
        _BuyMarket(),
        historical,
        RunConfig(strategy_name="buy_market", initial_cash="100000"),
        simulator=LocalSimulator(tmp_path / "noop.db"),
        fee=PercentFee("0"),
        quote_fill="last",
    )
    assert len(result.orders) == 1
    assert result.orders[0].order_type == OrderType.MARKET
    assert result.orders[0].limit_price is None
    assert result.fills[0].price == Decimal("100")


def test_market_order_stores_policy_limit_and_same_fill_in_both_engines(tmp_path):
    policy = _touch_policy()
    backtest, live = _run_engines(tmp_path, quote_fill="last", policy=policy)
    assert len(backtest.orders) == 1
    assert len(live.orders) == 1
    for result in (backtest, live):
        order = result.orders[0]
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == Decimal("100")
        assert order.quantity == Decimal("1")
        assert order.time_in_force == TimeInForce.DAY
        assert result.fills[0].raw_match_price == Decimal("100")
        assert result.fills[0].price == Decimal("100")
    assert backtest.fills[0].price == live.fills[0].price


def test_book_offset_limit_matches_at_the_touch_in_both_engines(tmp_path):
    policy = _touch_policy(market_offset="2", time_in_force="IOC")
    backtest, live = _run_engines(tmp_path, quote_fill="book", policy=policy)
    for result in (backtest, live):
        order = result.orders[0]
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == Decimal("112")
        assert order.time_in_force == TimeInForce.IOC
        assert result.fills[0].raw_match_price == Decimal("110")
        assert result.fills[0].price == Decimal("110")
    assert backtest.fills[0].price == live.fills[0].price
    assert backtest.orders[0].limit_price == live.orders[0].limit_price


def test_slippage_stays_on_adjust_fill_price(tmp_path):
    policy = _touch_policy()
    slippage = FixedSlippage("5")
    backtest, _live = _run_engines(
        tmp_path,
        quote_fill="last",
        policy=policy,
        slippage=slippage,
    )
    fill = backtest.fills[0]
    assert backtest.orders[0].order_type == OrderType.LIMIT
    assert backtest.orders[0].limit_price == Decimal("100")
    assert fill.raw_match_price == Decimal("100")
    assert fill.price == slippage.adjust_fill_price(
        raw_match_price=Decimal("100"),
        side=Side.BUY,
    )


def test_runner_applies_configured_policy_for_last_and_book(tmp_path):
    day = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    archive = tmp_path / "bars"
    write_symbol_bars(
        archive,
        {
            "طلا": [
                {
                    "bar_at": day.isoformat(),
                    "close": "100",
                    "bid": "90",
                    "ask": "110",
                }
            ]
        },
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )

    def run(quote_fill: str):
        config = (
            AppConfig.builder()
            .set_archive(archive, symbols=["طلا"], start="2026-08-29", end="2026-08-29")
            .set_quote_fill(quote_fill)
            .set_fee("NoFee")
            .set_database(tmp_path / f"runner-{quote_fill}.db")
            .set_execution_policy(
                "OffsetLimit",
                quantity_quantum="0.1",
                price_tick="1",
                min_quantity="1",
                market_offset="0",
                time_in_force="DAY",
            )
            .build()
        )
        return StrategyRunner.from_config(config).run(_BuyMarket(quantity="1.29"))

    last = run("last")
    book = run("book")
    assert last.orders[0].order_type == OrderType.LIMIT
    assert last.orders[0].limit_price == Decimal("100")
    assert last.orders[0].quantity == Decimal("1.2")
    assert last.fills[0].price == Decimal("100")
    assert book.orders[0].limit_price == Decimal("110")
    assert book.fills[0].price == Decimal("110")
    assert last.fills[0].price != book.fills[0].price


def test_translate_rounds_size_snaps_tick_and_uses_book_sides():
    policy = OffsetLimitPolicy.from_params(
        {
            "quantity_quantum": "0.00000001",
            "price_tick": "1",
            "min_quantity": "1",
            "market_offset": "0.2",
        }
    )
    quote = Quote(
        symbol="طلا",
        last=Decimal("100.4"),
        bid=Decimal("99.2"),
        ask=Decimal("101.2"),
    )
    buy = policy.translate(
        RawOrder(symbol="طلا", side=Side.BUY, quantity=Decimal("1.000000019")),
        quote=quote,
        quote_fill="last",
    )
    assert buy.order_type == OrderType.LIMIT
    assert buy.quantity == Decimal("1.00000001")
    assert buy.limit_price == Decimal("101")
    sell = policy.translate(
        RawOrder(symbol="طلا", side=Side.SELL, quantity=Decimal("2")),
        quote=quote,
        quote_fill="book",
    )
    assert sell.limit_price == Decimal("99")
    buy_book = policy.translate(
        RawOrder(symbol="طلا", side=Side.BUY, quantity=Decimal("1")),
        quote=quote,
        quote_fill="book",
    )
    assert buy_book.limit_price == Decimal("102")

    tiny = OffsetLimitPolicy.from_params({"min_quantity": "1", "quantity_quantum": "0.1"})
    with pytest.raises(ValueError, match="min_quantity"):
        tiny.translate(
            RawOrder(symbol="طلا", side=Side.BUY, quantity=Decimal("0.5")),
            quote=quote,
            quote_fill="last",
        )
    with pytest.raises(ValueError, match="rounded quantity to zero"):
        tiny.translate(
            RawOrder(symbol="طلا", side=Side.BUY, quantity=Decimal("0.05")),
            quote=quote,
            quote_fill="last",
        )


def test_policy_params_come_from_config_and_reject_unknowns():
    loaded = AppConfig.from_mapping(
        {
            "data": {
                "symbols": ["طلا"],
                "start": "2026-08-29",
                "end": "2026-08-29",
                "quote_fill": "book",
            },
            "runtime": {"mode": "backtest"},
            "execution_policy": {
                "name": "OffsetLimit",
                "params": {"price_tick": "10", "market_offset": "5"},
            },
        }
    )
    policy = build_execution_policy(loaded.execution_policy)
    assert isinstance(policy, OffsetLimitPolicy)
    assert policy.price_tick == Decimal("10")
    assert policy.market_offset == Decimal("5")
    assert policy.quantity_quantum == Decimal("0.00000001")
    with pytest.raises(ValueError, match="unknown execution policy params"):
        OffsetLimitPolicy.from_params({"lot_size": "1"})
    with pytest.raises(ValueError, match="unknown model"):
        build_execution_policy(ModelConfig("AgahTicks"))
    with pytest.raises(ValueError, match="does not take parameters"):
        build_execution_policy(ModelConfig("NoOp", {"price_tick": "1"}))
    echoed = NoOpExecutionPolicy().translate(
        RawOrder(
            symbol="طلا",
            side=Side.BUY,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
        ),
        quote=None,
        quote_fill="last",
    )
    assert echoed.order_type == OrderType.MARKET
    assert echoed.limit_price is None


def test_live_paper_remote_rejects_non_noop_policy():
    config = (
        AppConfig.builder()
        .set_mode("live_paper_remote")
        .set_symbols(["طلا"])
        .set_execution_policy("OffsetLimit", price_tick="1", market_offset="1")
        .build()
    )
    with pytest.raises(ValueError, match="live_paper_remote") as raised:
        StrategyRunner.from_config(config).run(_BuyMarket())
    assert str(raised.value) == REMOTE_POLICY_ERROR


def test_remote_broker_does_not_receive_a_local_translation():
    venue = InMemoryRemoteVenue()
    remote = RemoteSimulator(venue)
    account = remote.create_account(initial_cash="1000000", fee_rate="0")
    snapshot = MarketSnapshot(
        event_id="e1",
        timestamp=datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN),
        quotes=(Quote(symbol="طلا", last=Decimal("100")),),
    )
    ctx = StrategyContext(
        remote,
        account.id,
        execution_policy=_touch_policy(),
        quote_fill="last",
    )
    ctx.set_market(snapshot)
    with pytest.raises(ValueError, match="live_paper_remote"):
        ctx.submit_order(symbol="طلا", side="BUY", quantity="1", order_type="MARKET")
    assert venue.orders == {}

    noop = StrategyContext(remote, account.id, quote_fill="last")
    noop.set_market(snapshot)
    order = noop.submit_order(
        symbol="طلا",
        side="BUY",
        quantity="1",
        order_type="MARKET",
        client_order_id="remote-noop",
    )
    assert order.order_type == OrderType.MARKET
    assert order.limit_price is None
    assert venue.orders[order.id].order_type == OrderType.MARKET


def test_runner_rejects_remote_simulator_with_a_real_policy():
    venue = InMemoryRemoteVenue()
    remote = RemoteSimulator(venue)
    config = (
        AppConfig.builder()
        .set_period("2026-08-29", "2026-08-29")
        .set_symbols(["طلا"])
        .set_execution_policy("OffsetLimit", price_tick="1")
        .build()
    )
    with pytest.raises(ValueError, match="ExecutionPolicy"):
        StrategyRunner.from_config(config).set_broker(remote).run(_BuyMarket())
    assert venue.orders == {}
