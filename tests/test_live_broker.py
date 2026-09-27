"""live_broker records orders and does not call a brokerage network."""

from __future__ import annotations

import socket
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from goldarb import StrategyRunner, build_strategy
from goldarb.archive import write_symbol_bars
from goldarb.config import LIVE_PAPER_MODES, RUNTIME_MODES, AppConfig, RuntimeConfig
from goldarb.gateway import (
    LocalPaperOrderGateway,
    RecordingOrderGateway,
    TransportNotConfigured,
)
from goldarb.simulation import OrderStatus
from goldarb.simulation.models import MarketSnapshot, Quote
from goldarb.strategies import BubbleRankStrategy

TEHRAN = ZoneInfo("Asia/Tehran")


def _block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _refused(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("brokerage network is not used")

    monkeypatch.setattr(socket, "create_connection", _refused)


def _gap_archive(directory) -> None:
    origin = datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN)
    premiums = [(0.0, 0.0)] * 11 + [(-2.5, 2.5)]
    tala: list[dict[str, str]] = []
    zar: list[dict[str, str]] = []
    for index, (prem_long, prem_short) in enumerate(premiums):
        stamp = (origin + timedelta(seconds=index)).isoformat()
        tala.append({"bar_at": stamp, "close": "100", "premium": str(prem_long)})
        zar.append({"bar_at": stamp, "close": "100", "premium": str(prem_short)})
    write_symbol_bars(
        directory,
        {"طلا": tala, "زر": zar},
        grain="1s",
        start="2026-08-29",
        end="2026-08-29",
    )


def _config(directory, mode: str):
    return (
        AppConfig.builder()
        .set_archive(
            directory,
            symbols=["طلا", "زر"],
            start="2026-08-29",
            end="2026-08-29",
            grain="1s",
            fill_session=False,
            session_hours=False,
        )
        .set_mode(mode)
        .set_strategy(
            "bubble_rank",
            capital_per_side="100000",
            min_samples=10,
            min_gap=1.0,
            window_days=20,
        )
        .set_allow_short(True)
        .set_fee("NoFee")
        .build()
    )


def test_live_broker_is_opt_in(tmp_path):
    assert "live_broker" in RUNTIME_MODES
    assert "live_broker" not in LIVE_PAPER_MODES
    assert RuntimeConfig().mode == "backtest"
    assert AppConfig().runtime.mode == "backtest"
    live = AppConfig.builder().set_live(symbols=["طلا"], max_polls=1).build()
    assert live.runtime.mode == "live_paper_local"
    with pytest.raises(ValueError, match="live runtime"):
        (
            AppConfig.builder()
            .set_archive(
                tmp_path,
                symbols=["طلا"],
                start="2026-08-29",
                end="2026-08-29",
            )
            .set_mode("live_paper_local")
            .build()
        )
    selected = (
        AppConfig.builder()
        .set_archive(
            tmp_path,
            symbols=["طلا"],
            start="2026-08-29",
            end="2026-08-29",
        )
        .set_mode("live_broker")
        .build()
    )
    assert selected.runtime.mode == "live_broker"


def test_agah_alone_does_not_send_a_live_order(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    directory = tmp_path / "bars"
    _gap_archive(directory)
    config = (
        AppConfig.builder()
        .set_archive(
            directory,
            symbols=["طلا", "زر"],
            start="2026-08-29",
            end="2026-08-29",
            fill_session=False,
            session_hours=False,
        )
        .set_mode("live_broker")
        .set_broker("agah")
        .set_strategy("bubble_rank", capital_per_side="100000", min_samples=10, min_gap=1.0)
        .build()
    )
    strategy = build_strategy(config.strategy)
    with pytest.raises(TransportNotConfigured, match="transport not configured"):
        StrategyRunner(config).run(strategy)


def test_recording_gateway_cancel_does_not_fill():
    gateway = RecordingOrderGateway()
    account = gateway.ledger.create_account(initial_cash="100000", allow_short=True)
    gateway.bind_account(account.id)
    gateway.note_market(
        MarketSnapshot(
            event_id="book-1",
            timestamp=datetime(2026, 8, 29, 12, 0, tzinfo=TEHRAN),
            quotes=(Quote(symbol="طلا", last=Decimal("100")),),
        )
    )
    order = gateway.submit(
        symbol="طلا",
        side="BUY",
        quantity="1",
        order_type="MARKET",
        client_order_id="rec-1",
    )
    assert order.status == OrderStatus.ACCEPTED
    assert gateway.positions() == ()
    cancelled = gateway.cancel(order.id)
    assert cancelled.status == OrderStatus.CANCELLED
    assert gateway.cancels == [order.id]
    assert len(gateway.submits) == 1
    assert gateway.submits[0].time_in_force.value == "DAY"
    gateway.release_fills()
    assert gateway.ledger.list_fills(account.id) == []
    assert gateway.positions() == ()


def test_registered_strategy_live_broker_fills_only_on_fill(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    paper_symbols: list[str] = []

    def _paper_submit(self, **kwargs):
        del self
        paper_symbols.append(str(kwargs["symbol"]))
        raise AssertionError("live_broker must not use the local paper gateway")

    monkeypatch.setattr(LocalPaperOrderGateway, "submit", _paper_submit)
    directory = tmp_path / "bars"
    _gap_archive(directory)
    config = _config(directory, "live_broker")
    strategy = build_strategy(config.strategy)
    assert type(strategy) is BubbleRankStrategy
    runner = StrategyRunner(config).use_recording_gateway()
    gateway = runner.order_gateway
    assert isinstance(gateway, RecordingOrderGateway)

    original_submit = gateway.submit

    def spy_submit(**kwargs):
        assert strategy._current_pair is None
        assert strategy.events == []
        assert gateway.positions() == ()
        order = original_submit(**kwargs)
        assert order.status == OrderStatus.ACCEPTED
        assert order.filled_quantity == 0
        return order

    gateway.submit = spy_submit  # type: ignore[method-assign]
    pair_at_fill_start: list[tuple[str, str] | None] = []
    original_on_fill = strategy.on_fill

    def on_fill(ctx, fill):
        pair_at_fill_start.append(strategy._current_pair)
        original_on_fill(ctx, fill)

    strategy.on_fill = on_fill  # type: ignore[method-assign]
    result = runner.run(strategy)

    assert paper_symbols == []
    assert len(gateway.submits) == 2
    assert {item.side.value for item in gateway.submits} == {"BUY", "SELL"}
    assert pair_at_fill_start[0] is None
    assert strategy._current_pair == ("طلا", "زر")
    assert any(event["type"] == "enter_pair" for event in strategy.events)
    held = {item.symbol: item.quantity for item in result.portfolio.positions}
    assert held["طلا"] > 0
    assert held["زر"] < 0
    assert gateway.cancels == []


def test_same_config_backtest_still_uses_local_paper(tmp_path, monkeypatch):
    _block_network(monkeypatch)
    paper_symbols: list[str] = []
    real_submit = LocalPaperOrderGateway.submit

    def spy_submit(self, **kwargs):
        paper_symbols.append(str(kwargs["symbol"]))
        return real_submit(self, **kwargs)

    monkeypatch.setattr(LocalPaperOrderGateway, "submit", spy_submit)
    directory = tmp_path / "bars"
    _gap_archive(directory)
    live = _config(directory, "live_broker")
    backtest = replace(live, runtime=replace(live.runtime, mode="backtest"))
    gateway = RecordingOrderGateway()
    strategy = build_strategy(backtest.strategy)
    result = StrategyRunner(backtest).set_order_gateway(gateway).run(strategy)

    assert paper_symbols
    assert gateway.submits == []
    assert any(order.status == OrderStatus.FILLED for order in result.orders)
    assert strategy._current_pair == ("طلا", "زر")
