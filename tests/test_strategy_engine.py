"""Strategy API, engines, data providers, and execution models."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from goldarb.data import HistoricalDataProvider, LiveDataProvider
from goldarb.engine import BacktestEngine, LiveSimulationEngine, RunConfig
from goldarb.execution import FixedLatency, FixedSlippage, PercentFee, PercentSlippage
from goldarb.simulation import LocalSimulator, OrderStatus, Side
from goldarb.strategies import MaBandStrategy

TEHRAN = ZoneInfo("Asia/Tehran")
ROUND_TRIP = ("100", "100", "100", "97", "97", "103")


class FakeLiveFeed:
    def __init__(self, bars: list[dict], last: dict, book: dict) -> None:
        self.bars = bars
        self.last = last
        self.book = book
        self.calls = 0

    def candles(self, symbol, *, start, end, grain="1m"):
        del symbol, start, end, grain
        self.calls += 1
        return list(self.bars)

    def last_price(self, symbol):
        del symbol
        return dict(self.last)

    def orderbook(self, symbol):
        del symbol
        return dict(self.book)


def test_backtest_engine_ma_band_round_trip(tmp_path):
    strategy = MaBandStrategy(quantity="10")
    result = BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(
            strategy_name="ma_band",
            initial_cash="10000",
            database=str(tmp_path / "bt.db"),
        ),
        fee=PercentFee("0"),
    )
    assert [fill.price for fill in result.fills] == [Decimal("97"), Decimal("103")]
    assert result.portfolio.realized_pnl == Decimal("60")
    assert result.portfolio.cash == Decimal("10060")
    assert result.metrics.n_signals == 2
    assert result.metrics.n_filled_orders == 2
    assert result.metrics.fill_rate == Decimal(1)
    assert result.metrics.total_return == Decimal("0.006")
    assert result.config.fee_model == "PercentFee"
    assert result.config.slippage_model == "NoSlippage"
    kinds = [event.kind for event in result.log]
    assert "market" in kinds and "signal" in kinds and "order" in kinds and "fill" in kinds


def test_same_config_is_deterministic(tmp_path):
    def run_once(name: str):
        return BacktestEngine().run(
            MaBandStrategy(quantity="10"),
            HistoricalDataProvider.from_closes(ROUND_TRIP),
            RunConfig(
                strategy_name="ma_band",
                initial_cash="10000",
                database=str(tmp_path / name),
            ),
            fee=PercentFee("0"),
        )

    first = run_once("a.db")
    second = run_once("b.db")
    assert [fill.price for fill in first.fills] == [fill.price for fill in second.fills]
    assert first.portfolio.equity == second.portfolio.equity
    assert first.metrics.total_pnl == second.metrics.total_pnl


def test_percent_fee_matches_account_rate(tmp_path):
    result = BacktestEngine().run(
        MaBandStrategy(quantity="10"),
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "fee.db"),
        fee=PercentFee("0.001"),
    )
    assert result.portfolio.fees_paid == Decimal("2.000000")
    assert result.metrics.total_fees == Decimal("2.000000")
    assert result.config.fee_config == {"fee_rate": "0.001"}


def test_percent_slippage_worsens_market_buy(tmp_path):
    result = BacktestEngine().run(
        MaBandStrategy(quantity="10"),
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "slip.db"),
        fee=PercentFee("0"),
        slippage=PercentSlippage("0.01"),
    )
    buy = result.fills[0]
    sell = result.fills[1]
    assert buy.price == Decimal("97.97")
    assert sell.price == Decimal("101.97")
    assert buy.price > Decimal("97")
    assert sell.price < Decimal("103")


def test_fixed_latency_shifts_execution_clock(tmp_path):
    result = BacktestEngine().run(
        MaBandStrategy(quantity="10"),
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "lat.db"),
        fee=PercentFee("0"),
        latency=FixedLatency(250),
    )
    origin = datetime.fromisoformat(result.fills[0].filled_at)
    expected = datetime(2026, 8, 29, 9, 3, tzinfo=origin.tzinfo) + timedelta(
        milliseconds=250
    )
    assert origin == expected
    assert result.config.latency_config == {"milliseconds": "250"}


def test_strategy_sees_true_price_when_slippage_applied(tmp_path):
    strategy = MaBandStrategy(quantity="10")
    BacktestEngine().run(
        strategy,
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "true.db"),
        fee=PercentFee("0"),
        slippage=FixedSlippage("5"),
    )
    assert strategy.signals[0].close == Decimal("97")
    assert strategy.signals[0].side == Side.BUY


def test_live_engine_uses_same_strategy(tmp_path):
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    bars = [
        {
            "close": price,
            "bar_at": (start + timedelta(minutes=index)).isoformat(),
        }
        for index, price in enumerate(ROUND_TRIP)
    ]
    feed = FakeLiveFeed(
        bars=bars,
        last={
            "last_price": "103",
            "status": "ok",
            "fetched_at": (start + timedelta(minutes=5)).isoformat(),
        },
        book={
            "best_bid": "103",
            "best_ask": "103",
            "buy_orders": [{"volume": 10}],
            "sell_orders": [{"volume": 10}],
        },
    )
    clock = start + timedelta(minutes=5)
    strategy = MaBandStrategy(quantity="10")
    result = LiveSimulationEngine().run(
        strategy,
        LiveDataProvider(
            feed,
            symbol="طلا",
            include_session_bars=True,
            bar_grain="1m",
            session_day=start.date(),
            max_polls=1,
            sleep=lambda _: None,
            now=lambda: clock,
        ),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "live.db"),
        fee=PercentFee("0"),
    )
    assert result.metrics.n_signals == 2
    assert [order.status for order in result.orders] == [
        OrderStatus.FILLED,
        OrderStatus.FILLED,
    ]
    status = {
        "cash": result.portfolio.cash,
        "open_orders": 0,
    }
    assert status["cash"] == Decimal("10060")


def test_live_provider_skips_duplicates_and_survives_errors():
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    errors: list[str] = []

    class FlakyFeed(FakeLiveFeed):
        def last_price(self, symbol):
            if self.calls == 1:
                raise RuntimeError("timeout")
            return super().last_price(symbol)

    feed = FlakyFeed(
        bars=[
            {"close": "100", "bar_at": start.isoformat()},
            {
                "close": "101",
                "bar_at": (start + timedelta(minutes=1)).isoformat(),
            },
        ],
        last={"last_price": "101", "fetched_at": start.isoformat()},
        book={},
    )
    provider = LiveDataProvider(
        feed,
        session_day=start.date(),
        bar_grain="1m",
        max_polls=3,
        sleep=lambda _: None,
        now=lambda: start + timedelta(minutes=1),
        on_error=lambda exc: errors.append(str(exc)),
    )
    events = list(provider.events())
    ids = [item.event_id for item in events]
    assert len(ids) == len(set(ids))
    assert errors == ["timeout"]
    assert len(events) >= 2


def test_max_drawdown_from_equity_history(tmp_path):
    result = BacktestEngine().run(
        MaBandStrategy(quantity="10"),
        HistoricalDataProvider.from_closes(ROUND_TRIP),
        RunConfig(strategy_name="ma_band", initial_cash="10000"),
        simulator=LocalSimulator(tmp_path / "dd.db"),
        fee=PercentFee("0"),
    )
    assert result.metrics.max_drawdown >= 0
    assert result.metrics.final_equity == result.portfolio.equity
    assert len(result.equity_history) == len(ROUND_TRIP)
