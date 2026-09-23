"""Session-window tests: Iran 12:00–18:00 Saturday–Wednesday feeding LocalSimulator."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from ma_band import MaBandEngine, snapshots_from_closes
from session import (
    TEHRAN,
    filter_session_snapshots,
    format_tick,
    in_iran_session,
    is_iran_trading_day,
    session_bounds,
    snapshot_from_live,
    tick_record,
)

from goldarb.simulation import LocalSimulator, Side

ROUND_TRIP = ("100", "100", "100", "97", "97", "103")


def test_session_bounds_are_noon_to_six_tehran():
    start, end = session_bounds(datetime(2026, 8, 29, tzinfo=TEHRAN).date())
    assert start.hour == 12 and start.minute == 0
    assert end.hour == 18 and end.minute == 0
    assert start.tzinfo == TEHRAN
    assert (end - start) == timedelta(hours=6)


def test_in_iran_session_accepts_utc_equivalent():
    noon_tehran = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    utc = noon_tehran.astimezone(ZoneInfo("UTC"))
    assert utc.hour == 8 and utc.minute == 30
    assert in_iran_session(utc)
    assert not in_iran_session(datetime(2026, 8, 29, 11, 59, tzinfo=TEHRAN))
    assert in_iran_session(datetime(2026, 8, 29, 18, 0, tzinfo=TEHRAN))
    assert not in_iran_session(datetime(2026, 8, 29, 18, 0, 1, tzinfo=TEHRAN))


def test_gold_fund_session_is_saturday_to_wednesday():
    saturday = datetime(2026, 8, 29, tzinfo=TEHRAN).date()
    thursday = datetime(2026, 8, 27, tzinfo=TEHRAN).date()
    friday = datetime(2026, 8, 28, tzinfo=TEHRAN).date()
    assert is_iran_trading_day(saturday)
    assert not is_iran_trading_day(thursday)
    assert not is_iran_trading_day(friday)
    assert in_iran_session(datetime(2026, 8, 29, 13, 0, tzinfo=TEHRAN))
    assert not in_iran_session(datetime(2026, 8, 27, 13, 0, tzinfo=TEHRAN))
    assert not in_iran_session(datetime(2026, 8, 28, 13, 0, tzinfo=TEHRAN))


def test_filter_drops_bars_outside_today_session():
    day = datetime(2026, 8, 29, tzinfo=TEHRAN).date()
    inside = snapshots_from_closes(
        ROUND_TRIP,
        start=datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN),
    )
    outside = snapshots_from_closes(
        ("100", "101"),
        start=datetime(2026, 8, 29, 11, 0, tzinfo=TEHRAN),
    )
    kept = filter_session_snapshots([*outside, *inside], day=day)
    assert [item.timestamp.astimezone(TEHRAN).hour for item in kept] == [12] * 6


def test_session_replay_prints_buy_and_sell_signals(tmp_path, capsys):
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    snapshots = filter_session_snapshots(snapshots_from_closes(ROUND_TRIP, start=start))
    with LocalSimulator(tmp_path / "session.db") as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        engine = MaBandEngine(simulator=sim, account_id=account.id)
        printed: list[str] = []
        for snapshot in snapshots:
            tick = engine.on_snapshot(snapshot)
            assert tick is not None
            line = format_tick(
                tick,
                symbol="طلا",
                buy_band=Decimal("0.02"),
                sell_band=Decimal("0.02"),
            )
            printed.append(line)
            print(line, flush=True)
        result = engine.result()

    captured = capsys.readouterr().out
    assert "SIGNAL BUY" in captured
    assert "SIGNAL SELL" in captured
    assert printed[3].startswith("SIGNAL BUY")
    assert printed[5].startswith("SIGNAL SELL")
    assert [s.side for s in result.signals] == [Side.BUY, Side.SELL]


def test_snapshot_from_live_uses_best_bid_ask_and_session_clock():
    snapshot = snapshot_from_live(
        symbol="طلا",
        last_price={
            "last_price": "1200000",
            "d_even": "20260829",
            "h_even": "134500",
        },
        orderbook={
            "best_bid": "1199000",
            "best_ask": "1201000",
            "buy_orders": [{"price": 1199000, "volume": 10, "count": 1}],
            "sell_orders": [{"price": 1201000, "volume": 8, "count": 1}],
        },
    )
    assert snapshot is not None
    assert in_iran_session(snapshot.timestamp)
    quote = snapshot.quotes[0]
    assert quote.last == Decimal("1200000")
    assert quote.bid == Decimal("1199000")
    assert quote.ask == Decimal("1201000")
    assert quote.bid_size == Decimal("10")
    assert quote.ask_size == Decimal("8")


def test_tick_record_includes_signal_side():
    start = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    snapshots = snapshots_from_closes(ROUND_TRIP[:4], start=start)
    with LocalSimulator(":memory:") as sim:
        account = sim.create_account(initial_cash="10000", fee_rate="0")
        engine = MaBandEngine(simulator=sim, account_id=account.id)
        last = None
        for snapshot in snapshots:
            last = engine.on_snapshot(snapshot)
    assert last is not None and last.signal is not None
    record = tick_record(last, symbol="طلا")
    assert record["signal"] == "BUY"
    assert record["close"] == "97"
