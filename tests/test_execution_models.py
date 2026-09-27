"""Unit tests for replaceable fee, slippage, and latency models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from goldarb.data import HistoricalDataProvider, LiveDataProvider
from goldarb.engine import (
    BacktestEngine,
    LiveSimulationEngine,
    RunConfig,
    SimulationLoop,
)
from goldarb.execution import (
    FixedLatency,
    FixedSlippage,
    LocalMarketIngress,
    NoLatency,
    NoOpMarketIngress,
    NoSlippage,
    PercentFee,
    PercentSlippage,
    ServerSideExecution,
)
from goldarb.simulation import LocalSimulator
from goldarb.simulation.engine import fee_for
from goldarb.simulation.matching import QuoteMatching
from goldarb.simulation.models import MarketSnapshot, Quote, Side
from goldarb.strategy import Strategy

TEHRAN = ZoneInfo("Asia/Tehran")


def _snapshot(*, last="100", bid=None, ask=None) -> MarketSnapshot:
    return MarketSnapshot(
        event_id="e1",
        timestamp=datetime(2026, 8, 29, 9, 0, tzinfo=UTC),
        quotes=(
            Quote(
                symbol="طلا",
                last=Decimal(last),
                bid=None if bid is None else Decimal(bid),
                ask=None if ask is None else Decimal(ask),
            ),
        ),
    )


def test_percent_fee_matches_simulator_formula():
    fee = PercentFee("0.001")
    assert fee.rate() == Decimal("0.001")
    assert fee.fee_for(quantity=Decimal(10), price=Decimal(97)) == fee_for(
        Decimal(10), Decimal(97), Decimal("0.001")
    )
    assert fee.config() == {"fee_rate": "0.001"}


def test_no_slippage_keeps_quotes():
    snapshot = _snapshot(bid="99", ask="101")
    assert NoSlippage().apply_snapshot(snapshot) is snapshot


def test_fixed_slippage_widens_book():
    slipped = FixedSlippage("2").apply_snapshot(_snapshot(bid="100", ask="102"))
    quote = slipped.quotes[0]
    assert quote.bid == Decimal("98")
    assert quote.ask == Decimal("104")
    assert slipped.event_id == "e1"


def test_percent_slippage_synthesizes_bid_ask_from_last():
    slipped = PercentSlippage("0.01").apply_snapshot(_snapshot(last="100"))
    quote = slipped.quotes[0]
    assert quote.bid == Decimal("99")
    assert quote.ask == Decimal("101")
    assert quote.last == Decimal("100")


def test_noop_market_ingress_alias():
    assert NoOpMarketIngress is ServerSideExecution
    assert LocalMarketIngress().name == "LocalMarketIngress"
    assert NoLatency().submit_delay().total_seconds() == 0


def test_fixed_latency_shifts_timestamp_only():
    snapshot = _snapshot()
    delayed = FixedLatency(100).apply_snapshot(snapshot)
    assert delayed.timestamp - snapshot.timestamp == timedelta(milliseconds=100)
    assert delayed.event_id == snapshot.event_id
    assert delayed.quotes == snapshot.quotes
    assert NoLatency().apply_snapshot(snapshot) is snapshot


class _OrderPathSlippage:
    """Slippage that explodes if the loop rewrites the snapshot."""

    name = "OrderPathSlippage"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        raise AssertionError("SimulationLoop must not call apply_snapshot")

    def adjust_fill_price(self, *, raw_match_price, side, quote=None):
        return FixedSlippage("5").adjust_fill_price(
            raw_match_price=raw_match_price,
            side=side,
            quote=quote,
        )

    def config(self) -> dict[str, str]:
        return {"amount": "5"}


class _OrderPathLatency:
    name = "OrderPathLatency"

    def apply_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        raise AssertionError("SimulationLoop must not call apply_snapshot")

    def delay(self) -> timedelta:
        return timedelta(0)

    def submit_delay(self) -> timedelta:
        return timedelta(0)

    def config(self) -> dict[str, str]:
        return {}


class _BuyOnce(Strategy):
    name = "buy_once"

    def __init__(self) -> None:
        self.seen: MarketSnapshot | None = None
        self._sent = False

    def on_market_data(self, ctx) -> None:
        self.seen = ctx.market
        if self._sent or ctx.market is None or not ctx.market.quotes:
            return
        self._sent = True
        ctx.submit_order(
            symbol=ctx.market.quotes[0].symbol,
            side="BUY",
            quantity="1",
            order_type="MARKET",
            client_order_id="buy-once",
        )


def test_simulation_loop_does_not_slip_snapshot(tmp_path):
    snapshot = _snapshot(last="100", bid="99", ask="101")
    slippage = _OrderPathSlippage()
    latency = _OrderPathLatency()
    broker = LocalSimulator(
        tmp_path / "loop.db",
        fee=PercentFee("0"),
        slippage=slippage,
        latency=latency,
    )
    account = broker.create_account(initial_cash="100000", fee_rate="0")
    strategy = _BuyOnce()
    loop = SimulationLoop(
        broker=broker,
        account_id=account.id,
        strategy=strategy,
        slippage=slippage,
        latency=latency,
    )
    loop.process(snapshot)
    assert strategy.seen is snapshot
    assert snapshot.quotes[0].bid == Decimal("99")
    assert snapshot.quotes[0].ask == Decimal("101")
    assert snapshot.timestamp == datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
    fills = broker.list_fills(account.id)
    assert len(fills) == 1
    assert fills[0].raw_match_price == Decimal("101")
    assert fills[0].price == slippage.adjust_fill_price(
        raw_match_price=Decimal("101"),
        side=Side.BUY,
    )


class _RecordingMatch:
    name = "RecordingMatch"

    def __init__(self) -> None:
        self.quotes: list[Quote | None] = []
        self._inner = QuoteMatching()

    def match_order(self, order, **kwargs):
        self.quotes.append(kwargs.get("quote"))
        return self._inner.match_order(order, **kwargs)


def _historical_bar() -> dict[str, str]:
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
    """Local feed of one historical bar. No live book, so only that bar trades."""

    def candles(self, symbol, *, start, end, grain="1s"):
        del symbol, start, end, grain
        return [_historical_bar()]

    def last_price(self, symbol):
        del symbol
        return {}

    def orderbook(self, symbol):
        del symbol
        return {}


class _LiveBookFeed:
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
            "buy_orders": [{"volume": "8"}],
            "sell_orders": [{"volume": "8"}],
            "fetched_at": self.clock.isoformat(),
        }


def test_quote_fill_last_fills_at_the_same_price_in_both_engines(tmp_path):
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    historical = HistoricalDataProvider.from_symbol_bars(
        {"طلا": [_historical_bar()]},
        quote_fill="last",
        lazy=False,
    )
    backtest = BacktestEngine().run(
        _BuyOnce(),
        historical,
        RunConfig(strategy_name="buy_once", initial_cash="100000"),
        simulator=LocalSimulator(tmp_path / "backtest.db"),
        fee=PercentFee("0"),
    )
    live = LiveSimulationEngine().run(
        _BuyOnce(),
        LiveDataProvider(
            _BarFeed(),
            symbol="طلا",
            bar_grain="1s",
            include_session_bars=True,
            session_day=start.date(),
            max_polls=1,
            sleep=lambda _seconds: None,
            now=lambda: start + timedelta(seconds=2),
            quote_fill="last",
        ),
        RunConfig(strategy_name="buy_once", initial_cash="100000"),
        simulator=LocalSimulator(tmp_path / "live.db"),
        fee=PercentFee("0"),
    )
    assert len(backtest.fills) == 1
    assert len(live.fills) == 1
    assert backtest.fills[0].price == live.fills[0].price == Decimal("100")
    assert backtest.fills[0].raw_match_price == Decimal("100")


def test_quote_fill_book_passes_live_book_to_quote_matching(tmp_path):
    clock = datetime(2026, 8, 29, 12, 0, 5, tzinfo=TEHRAN)
    matcher = _RecordingMatch()
    broker = LocalSimulator(
        tmp_path / "book.db",
        matching=matcher,
        fee=PercentFee("0"),
    )
    result = LiveSimulationEngine().run(
        _BuyOnce(),
        LiveDataProvider(
            _LiveBookFeed(clock),
            symbol="طلا",
            include_session_bars=False,
            session_day=clock.date(),
            max_polls=1,
            sleep=lambda _seconds: None,
            now=lambda: clock,
            quote_fill="book",
        ),
        RunConfig(strategy_name="buy_once", initial_cash="100000"),
        simulator=broker,
        fee=PercentFee("0"),
    )
    assert matcher.quotes
    seen = matcher.quotes[0]
    assert seen is not None
    assert seen.bid == Decimal("90")
    assert seen.ask == Decimal("110")
    assert seen.last == Decimal("100")
    assert len(result.fills) == 1
    assert result.fills[0].raw_match_price == Decimal("110")
    assert result.fills[0].price == Decimal("110")

