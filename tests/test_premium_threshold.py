"""Unit tests for premium_threshold backtest (offline)."""

from __future__ import annotations

from goldarb.premium_threshold import bar_premium, run_premium_threshold


def _bar(day: str, close: float, prem: float) -> dict:
    return {
        "bar_at": f"{day}T00:00:00Z",
        "close": close,
        "premium_discount_pct": prem,
        "nav_price": close / (1 + prem / 100.0) if prem != -100 else close,
    }


def test_bar_premium_from_nav_fallback():
    assert bar_premium({"close": 110.0, "nav_price": 100.0}) == 10.0
    assert bar_premium({"premium_discount_pct": -1.5}) == -1.5


def test_enter_on_cheap_exit_on_rich_next_bar():
    # t0: prem -3 → signal BUY (fills t1)
    # t1: fill BUY @ 100
    # t2: prem +3 → signal SELL (fills t3)
    # t3: fill SELL @ 110
    bars = [
        _bar("2026-01-01", 100.0, -3.0),
        _bar("2026-01-02", 100.0, -2.5),
        _bar("2026-01-03", 105.0, 3.0),
        _bar("2026-01-04", 110.0, 3.5),
    ]
    result = run_premium_threshold(
        bars,
        buy_lte=-2.0,
        sell_gte=2.0,
        capital_per_side=1000.0,
        initial_cash=10_000.0,
        fee_rate=0.0,
        fill_mode="next_bar",
    )
    assert result.n_trades == 1
    assert [e.kind for e in result.events] == ["enter_long", "exit_long"]
    assert result.events[0].price == 100.0
    assert result.events[1].price == 110.0
    # qty = 1000/100 = 10; buy 1000, sell 1100 → +100 on 10k = +1%
    assert abs(result.return_pct - 1.0) < 1e-6


def test_no_entry_when_premium_above_buy_lte():
    bars = [_bar("2026-01-01", 100.0, -1.0), _bar("2026-01-02", 101.0, -1.0)]
    result = run_premium_threshold(
        bars,
        capital_per_side=1000.0,
        initial_cash=10_000.0,
        fee_rate=0.0,
    )
    assert result.n_trades == 0
    assert result.events == []
    assert abs(result.return_pct) < 1e-9


def test_same_bar_fill():
    bars = [
        _bar("2026-01-01", 100.0, -3.0),
        _bar("2026-01-02", 110.0, 3.0),
    ]
    result = run_premium_threshold(
        bars,
        capital_per_side=1000.0,
        initial_cash=10_000.0,
        fee_rate=0.0,
        fill_mode="same_bar",
    )
    assert result.n_trades == 1
    assert result.events[0].price == 100.0
    assert result.events[1].price == 110.0
