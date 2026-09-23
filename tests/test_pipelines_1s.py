"""1s Iran-session alignment, month backtest, and live universe poll."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from goldarb import (
    BubbleRankStrategy,
    iran_session_live,
    month_backtest,
)
from goldarb.data import (
    HistoricalDataProvider,
    LiveDataProvider,
    snapshots_from_symbol_bars,
)
from goldarb.execution import PercentFee
from goldarb.session import ONE_SECOND, TEHRAN, grain_step, session_bounds, session_timeline
from goldarb.simulation import LocalSimulator
from goldarb.universe import GOLD_FUND_SYMBOLS


def _bar(stamp: datetime, close: float, premium: float) -> dict:
    return {
        "bar_at": stamp.isoformat(),
        "close": close,
        "premium_discount_pct": premium,
        "nav_price": close / (1 + premium / 100) if premium != -100 else close,
    }


def test_grain_step_defaults_to_one_second():
    assert grain_step("1s") == ONE_SECOND
    assert grain_step("1m") == timedelta(minutes=1)
    assert grain_step("daily") == timedelta(days=1)


def test_session_timeline_covers_each_second():
    day = date(2026, 8, 29)
    first = datetime(2026, 8, 29, 12, 0, 0, tzinfo=TEHRAN)
    last = datetime(2026, 8, 29, 12, 0, 4, tzinfo=TEHRAN)
    points = session_timeline(day, first=first, last=last, step=ONE_SECOND)
    assert points == [first + timedelta(seconds=index) for index in range(5)]
    assert all(
        (later - earlier) == ONE_SECOND for earlier, later in zip(points, points[1:])
    )


def test_session_timeline_skips_thursday_and_friday():
    thursday = date(2026, 8, 27)
    friday = date(2026, 8, 28)
    noon = datetime(2026, 8, 27, 12, 0, tzinfo=TEHRAN)
    assert session_timeline(thursday, fill_session=True) == []
    assert session_timeline(friday, first=noon, last=noon) == []


def _pair_series(
    start: datetime, n: int = 12
) -> tuple[list[dict], list[dict], dict[str, list[dict]]]:
    tala = [
        _bar(start + timedelta(seconds=index), 20000, 0.0 if index < n - 1 else -2.5)
        for index in range(n)
    ]
    zar = [
        _bar(start + timedelta(seconds=index), 10000, 0.0 if index < n - 1 else 2.5)
        for index in range(n)
    ]
    others = {
        symbol: [_bar(start + timedelta(seconds=index), 15000, 0.0) for index in range(n)]
        for symbol in GOLD_FUND_SYMBOLS
        if symbol not in {"طلا", "زر"}
    }
    return tala, zar, others


def test_session_hours_do_not_fill_overnight():
    day1 = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)  # 12:00 Tehran
    day2 = datetime(2026, 8, 30, 8, 30, tzinfo=UTC)
    by_symbol = {
        "طلا": [_bar(day1, 20000, 0.0), _bar(day1 + timedelta(seconds=2), 20100, -1.0)],
        "زر": [_bar(day1, 10000, 0.0), _bar(day2, 10100, 1.0)],
    }
    snapshots = snapshots_from_symbol_bars(
        by_symbol,
        ffill=True,
        step=timedelta(seconds=1),
        session_hours=True,
        fill_session=False,
    )
    stamps = [item.timestamp.astimezone(UTC) for item in snapshots]
    assert stamps[0] == day1
    assert (stamps[1] - stamps[0]) == timedelta(seconds=1)
    assert (stamps[2] - stamps[1]) == timedelta(seconds=1)
    gaps = [stamps[index] - stamps[index - 1] for index in range(1, len(stamps))]
    assert all(gap == timedelta(seconds=1) or gap >= timedelta(hours=12) for gap in gaps)
    assert any(gap >= timedelta(hours=12) for gap in gaps)
    assert max(gaps) < timedelta(hours=24)


def test_fill_session_covers_12_to_18_hourly():
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    snapshots = snapshots_from_symbol_bars(
        {"طلا": [_bar(start, 20000, 0.0)]},
        ffill=True,
        step=timedelta(hours=1),
        session_hours=True,
        fill_session=True,
    )
    open_at, close_at = session_bounds(start.astimezone(TEHRAN).date())
    assert snapshots[0].timestamp.astimezone(TEHRAN) == open_at
    assert snapshots[-1].timestamp.astimezone(TEHRAN) == close_at
    assert len(snapshots) == 7


def test_month_backtest_pipeline_1s(tmp_path):
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    tala, zar, others = _pair_series(start)

    class Fund:
        def candles_many(self, symbols, *, start, end, grain="1s"):
            del start, end
            assert grain == "1s"
            payload = {"طلا": tala, "زر": zar, **others}
            return {symbol: payload[symbol] for symbol in symbols if symbol in payload}

    class Client:
        fund = Fund()

    strategy = BubbleRankStrategy(capital_per_side="100000", min_samples=10, min_gap=1.0)
    result = month_backtest(
        strategy,
        Client(),
        days=30,
        fill_session=False,
        initial_cash="1000000",
        fee=PercentFee("0"),
        simulator=LocalSimulator(tmp_path / "month.db"),
    )
    assert any(item["type"] == "enter_pair" for item in strategy.events)
    assert result.metrics.n_filled_orders >= 2
    snapshots = list(
        HistoricalDataProvider.from_symbol_bars(
            {"طلا": tala, "زر": zar, **others},
            fill_session=False,
        ).events()
    )
    assert (snapshots[1].timestamp - snapshots[0].timestamp) == timedelta(seconds=1)
    assert {quote.symbol for quote in snapshots[0].quotes} == set(GOLD_FUND_SYMBOLS)


def test_live_universe_polls_every_second_with_premium(tmp_path):
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    clock = {"now": start}

    class Feed:
        def candles(self, symbol, *, start, end, grain="1s"):
            del start, end, grain
            prem = -2.5 if symbol == "طلا" else 2.5 if symbol == "زر" else 0.0
            price = 20000 if symbol == "طلا" else 10000
            origin = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
            return [
                _bar(origin + timedelta(seconds=index), price, 0.0 if index < 11 else prem)
                for index in range(12)
            ]

        def last_price(self, symbol):
            prem = -2.5 if symbol == "طلا" else 2.5 if symbol == "زر" else 0.0
            price = 20000 if symbol == "طلا" else 10000
            return {
                "symbol": symbol,
                "last_price": price,
                "premium_discount_pct": prem,
                "status": "ok",
                "fetched_at": clock["now"].isoformat(),
            }

        def last_prices(self):
            return {symbol: self.last_price(symbol) for symbol in GOLD_FUND_SYMBOLS}

        def navs_live(self):
            return {}

        def orderbook(self, symbol):
            del symbol
            return {}

        def orderbooks(self):
            return {}

    def sleep(_seconds):
        clock["now"] = clock["now"] + timedelta(seconds=1)

    strategy = BubbleRankStrategy(capital_per_side="100000", min_samples=10, min_gap=1.0)
    result = iran_session_live(
        strategy,
        Feed(),
        poll_seconds=1.0,
        lookback_days=0,
        include_session_bars=False,
        grain="1s",
        initial_cash="1000000",
        fee=PercentFee("0"),
        simulator=LocalSimulator(tmp_path / "live.db"),
        stop_at=start + timedelta(seconds=12),
        sleep=sleep,
        now=lambda: clock["now"],
    )
    live_ticks = [
        item
        for item in result.log
        if item.kind == "market" and item.payload.get("event_id", "").startswith("live:")
    ]
    assert live_ticks
    assert strategy.last_ranking is not None
    assert len(strategy.last_ranking["rankings"]) == len(GOLD_FUND_SYMBOLS)


def test_live_history_ffills_each_second():
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    clock = start + timedelta(seconds=2)

    class Feed:
        def candles(self, symbol, *, start, end, grain="1s"):
            del symbol, start, end, grain
            origin = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
            return [_bar(origin, 10000, 0.0), _bar(origin + timedelta(seconds=2), 10200, 0.0)]

        def last_price(self, symbol):
            return {
                "symbol": symbol,
                "last_price": 10200,
                "premium_discount_pct": 0.0,
                "status": "ok",
                "fetched_at": clock.isoformat(),
            }

        def orderbook(self, symbol):
            del symbol
            return {}

    provider = LiveDataProvider(
        Feed(),
        symbol="طلا",
        poll_seconds=1.0,
        bar_grain="1s",
        include_session_bars=True,
        lookback_days=0,
        session_day=start.date(),
        max_polls=1,
        sleep=lambda _: None,
        now=lambda: clock,
    )
    events = list(provider.events())
    stamps = [item.timestamp.astimezone(TEHRAN) for item in events]
    assert stamps == [start, start + timedelta(seconds=1), start + timedelta(seconds=2)]
    assert all((later - earlier) == ONE_SECOND for earlier, later in zip(stamps, stamps[1:]))


def test_chained_live_keeps_month_premium_window(tmp_path):
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    tala, zar, others = _pair_series(start)

    class Fund:
        def candles_many(self, symbols, *, start, end, grain="1s"):
            del start, end
            payload = {"طلا": tala, "زر": zar, **others}
            return {symbol: payload[symbol] for symbol in symbols if symbol in payload}

    class Client:
        fund = Fund()

    class Feed:
        def last_price(self, symbol):
            prem = -2.5 if symbol == "طلا" else 2.5 if symbol == "زر" else 0.0
            price = 20000 if symbol == "طلا" else 10000 if symbol == "زر" else 15000
            return {
                "symbol": symbol,
                "last_price": price,
                "premium_discount_pct": prem,
                "status": "ok",
                "fetched_at": live_clock["now"].isoformat(),
            }

        def last_prices(self):
            return {symbol: self.last_price(symbol) for symbol in GOLD_FUND_SYMBOLS}

        def navs_live(self):
            return {}

        def orderbooks(self):
            return {}

        def orderbook(self, symbol):
            del symbol
            return {}

        def candles(self, symbol, *, start, end, grain="1s"):
            del symbol, start, end, grain
            return []

    live_clock = {"now": datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)}

    def sleep(_seconds):
        live_clock["now"] = live_clock["now"] + timedelta(seconds=1)

    strategy = BubbleRankStrategy(capital_per_side="100000", min_samples=10, min_gap=1.0)
    month_backtest(
        strategy,
        Client(),
        days=30,
        fill_session=False,
        initial_cash="1000000",
        fee=PercentFee("0"),
        simulator=LocalSimulator(tmp_path / "month.db"),
    )
    history_len = len(strategy._premiums["طلا"])
    assert history_len >= 10
    iran_session_live(
        strategy,
        Feed(),
        poll_seconds=1.0,
        lookback_days=0,
        include_session_bars=False,
        grain="1s",
        initial_cash="1000000",
        fee=PercentFee("0"),
        simulator=LocalSimulator(tmp_path / "live.db"),
        stop_at=live_clock["now"] + timedelta(seconds=2),
        sleep=sleep,
        now=lambda: live_clock["now"],
    )
    assert len(strategy._premiums["طلا"]) >= history_len
    assert strategy.last_ranking is not None
    assert strategy.last_ranking["best_pair"]["active"] is True


def test_live_provider_default_poll_is_one_second():
    provider = LiveDataProvider(object())  # type: ignore[arg-type]
    assert provider.poll_seconds == 1.0
    assert provider.bar_grain == "1s"
