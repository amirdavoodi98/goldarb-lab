"""Bubble-sign strategy and offline 1s archive replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from goldarb import BubbleSignStrategy, offline_backtest
from goldarb.archive import read_symbol_bars, write_symbol_bars
from goldarb.data import HistoricalDataProvider
from goldarb.engine import BacktestEngine, RunConfig
from goldarb.execution import PercentFee


def _bar(stamp: datetime, close: float, premium: float) -> dict:
    return {
        "bar_at": stamp.isoformat(),
        "close": close,
        "premium_discount_pct": premium,
        "nav_price": close / (1 + premium / 100),
    }


def test_bubble_sign_buys_discount_sells_premium(tmp_path):
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    by_symbol = {
        "طلا": [
            _bar(start, 100, -1.5),
            _bar(start + timedelta(seconds=1), 101, -0.4),
            _bar(start + timedelta(seconds=2), 102, 1.8),
        ],
        "گوهر": [
            _bar(start, 200, -2.0),
            _bar(start + timedelta(seconds=1), 201, -1.0),
            _bar(start + timedelta(seconds=2), 202, 2.0),
        ],
    }
    result = BacktestEngine().run(
        BubbleSignStrategy(quantity="1"),
        HistoricalDataProvider.from_symbol_bars(
            by_symbol, ffill=True, fill_session=False, lazy=False
        ),
        RunConfig(
            strategy_name="bubble_sign",
            initial_cash="10000",
            allow_short=False,
            database=str(tmp_path / "bubble.db"),
        ),
        fee=PercentFee("0"),
    )
    assert result.metrics.n_filled_orders == 4
    assert {fill.price for fill in result.fills} == {
        Decimal(100),
        Decimal(102),
        Decimal(200),
        Decimal(202),
    }
    assert result.portfolio.realized_pnl == Decimal(4)
    assert all(pos.quantity == 0 for pos in result.portfolio.positions)


def test_archive_roundtrip_offline_backtest(tmp_path):
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    by_symbol = {
        "طلا": [_bar(start, 100, -2.0), _bar(start + timedelta(seconds=1), 110, 2.0)],
    }
    archive = write_symbol_bars(
        tmp_path / "archive",
        by_symbol,
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )
    manifest, loaded = read_symbol_bars(archive)
    assert manifest["bar_count"] == 2
    assert loaded["طلا"][0]["premium_discount_pct"] == -2.0

    result = offline_backtest(
        BubbleSignStrategy(quantity="1"),
        archive,
        fill_session=False,
        initial_cash="10000",
        fee=PercentFee("0"),
        simulator=None,
    )
    assert result.metrics.n_filled_orders == 2
    assert result.portfolio.realized_pnl == Decimal(10)
