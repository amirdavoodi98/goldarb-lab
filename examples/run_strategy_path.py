#!/usr/bin/env python3
"""Walk one registered strategy through the strategy path, offline.

``BubbleRankStrategy`` is built from ``strategy.name``. Bars are a tiny
archive in a temp directory. Nothing here opens a socket or reads a secret.

1. ``backtest`` with ``data.quote_fill=last``, execution policy ``NoOp``,
   and ``runtime.broker=agah`` as the paper fee preset. Orders go through
   ``OrderGateway`` to local paper.
2. The same strategy and bars with ``OffsetLimit``, so a ``MARKET`` intent
   is stored as the translated venue order.
3. The same strategy with ``mode=live_broker`` and ``RecordingOrderGateway``.
   ``submit`` is recorded and does not fill. The runner then releases that
   fill into ``on_fill``, which is what sets the pair.
4. ``runtime.broker=agah`` with ``mode=backtest`` does not select a live
   transport. A registered recording gateway stays unused.

``simulate_local.py``, ``simulate_remote.py``, and ``simulate_agah_broker.py``
are direct paper (``submit_buy``), not this path.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from goldarb import RecordingOrderGateway, StrategyRunner, build_strategy
from goldarb.archive import write_symbol_bars
from goldarb.config import AppConfig
from goldarb.gateway import LocalPaperOrderGateway
from goldarb.simulation import get_broker
from goldarb.simulation.models import Fill
from goldarb.strategies import BubbleRankStrategy

TEHRAN = ZoneInfo("Asia/Tehran")


def _num(value: Decimal | None) -> str:
    if value is None:
        return "None"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _pair(pair: tuple[str, str] | None) -> str:
    if pair is None:
        return "None"
    return f"{pair[0]}/{pair[1]}"


def _held(gateway: RecordingOrderGateway) -> str:
    positions = gateway.positions()
    if not positions:
        return "none"
    return ",".join(f"{item.symbol}:{_num(item.quantity)}" for item in positions)


def _archive(directory: Path) -> None:
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


def _config(archive: Path) -> AppConfig:
    """Shared backtest config. ``agah`` is not given a fee override."""
    return (
        AppConfig.builder()
        .set_archive(
            archive,
            symbols=["طلا", "زر"],
            start="2026-08-29",
            end="2026-08-29",
            grain="1s",
            fill_session=False,
            session_hours=False,
            mode="backtest",
        )
        .set_quote_fill("last")
        .set_strategy(
            "bubble_rank",
            capital_per_side="100000",
            window_days=20,
            min_samples=10,
            min_gap=1.0,
        )
        .set_broker("agah")
        .set_allow_short(True)
        .set_initial_cash("1000000")
        .set_execution_policy("NoOp")
        .build()
    )


def _strategy(config: AppConfig) -> BubbleRankStrategy:
    strategy = build_strategy(config.strategy)
    if not isinstance(strategy, BubbleRankStrategy):
        raise RuntimeError(f"expected BubbleRankStrategy, got {type(strategy).__name__}")
    return strategy


def _run_local(config: AppConfig, strategy: BubbleRankStrategy, gateway=None):
    """Run backtest and record the OrderGateway class that submit hit."""
    calls: list[str] = []
    real_submit = LocalPaperOrderGateway.submit

    def submit(self, **kwargs):
        calls.append(type(self).__name__)
        return real_submit(self, **kwargs)

    LocalPaperOrderGateway.submit = submit  # type: ignore[method-assign]
    try:
        runner = StrategyRunner.from_config(config)
        if gateway is not None:
            runner.set_order_gateway(gateway)
        result = runner.run(strategy)
    finally:
        LocalPaperOrderGateway.submit = real_submit  # type: ignore[method-assign]
    if not calls or any(name != "LocalPaperOrderGateway" for name in calls):
        raise RuntimeError(f"backtest OrderGateway calls: {calls}")
    return result, calls[0]


def _print_orders(phase: str, result, *, policy: str) -> None:
    if not result.orders:
        raise RuntimeError(f"phase {phase} stored no orders")
    print(
        f"phase {phase}: quote_fill=last policy={policy} "
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades}"
    )
    # submitted_at can tie, so uuid order is not the short-then-long submit order.
    stored = sorted(result.orders, key=lambda order: (order.side.value != "SELL", order.symbol))
    for order in stored:
        print(
            f"phase {phase}: symbol={order.symbol} side={order.side.value} "
            f"stored_type={order.order_type.value} limit={_num(order.limit_price)} "
            f"status={order.status.value}"
        )


def main() -> None:
    preset = get_broker("agah")
    with tempfile.TemporaryDirectory() as raw:
        archive = Path(raw)
        _archive(archive)

        backtest = _config(archive)
        if backtest.fee_set:
            raise RuntimeError("agah must stay the fee preset; do not set fee")
        back_result, gateway_name = _run_local(backtest, _strategy(backtest))
        print(
            f"phase backtest: quote_fill={backtest.data.quote_fill} "
            f"policy={backtest.execution_policy.name} runtime.broker={backtest.runtime.broker} "
            f"fee_set={backtest.fee_set} preset_fee={_num(preset.fee_rate)} "
            f"run_fee={back_result.config.fee_rate} gateway={gateway_name}"
        )
        _print_orders("backtest", back_result, policy="NoOp")

        offset = (
            backtest.to_builder()
            .set_execution_policy(
                "OffsetLimit",
                quantity_quantum="1",
                price_tick="1",
                min_quantity="1",
                market_offset="1",
            )
            .build()
        )
        offset_result = StrategyRunner.from_config(offset).run(_strategy(offset))
        print(
            "phase backtest: policy=OffsetLimit quote_fill=last "
            "MARKET intent stored as the venue order"
        )
        _print_orders("backtest", offset_result, policy="OffsetLimit")

        live = backtest.to_builder().set_mode("live_broker").build()
        strategy = _strategy(live)
        runner = StrategyRunner.from_config(live).use_recording_gateway()
        gateway = runner.order_gateway
        if not isinstance(gateway, RecordingOrderGateway):
            raise RuntimeError(f"expected RecordingOrderGateway, got {type(gateway).__name__}")
        original_submit = gateway.submit

        def submit(**kwargs):
            order = original_submit(**kwargs)
            print(
                f"phase live_broker: submit recorded symbol={order.symbol} "
                f"side={order.side.value} status={order.status.value} "
                f"filled_quantity={_num(order.filled_quantity)} "
                f"positions={_held(gateway)} pair={_pair(strategy._current_pair)}"
            )
            return order

        gateway.submit = submit  # type: ignore[method-assign]
        original_on_fill = strategy.on_fill

        def on_fill(ctx, fill: Fill):
            before = strategy._current_pair
            original_on_fill(ctx, fill)
            symbol = next(
                (item.symbol for item in gateway.submits if item.order.id == fill.order_id),
                fill.order_id,
            )
            print(
                f"phase live_broker: on_fill symbol={symbol} "
                f"pair_before={_pair(before)} pair_after={_pair(strategy._current_pair)} "
                f"positions={_held(gateway)}"
            )

        strategy.on_fill = on_fill  # type: ignore[method-assign]
        runner.run(strategy)
        if len(gateway.submits) != 2 or strategy._current_pair != ("طلا", "زر"):
            raise RuntimeError("live_broker did not record both legs into on_fill")

        recording = RecordingOrderGateway()
        paper_result, paper_gateway = _run_local(
            backtest,
            _strategy(backtest),
            gateway=recording,
        )
        print(
            f"phase backtest: runtime.broker={backtest.runtime.broker} "
            f"mode={backtest.runtime.mode} gateway={paper_gateway} "
            f"recording_submits={len(recording.submits)} "
            f"filled={paper_result.metrics.n_filled_orders} live_transport=no"
        )
        if recording.submits or paper_gateway != "LocalPaperOrderGateway":
            raise RuntimeError("backtest selected a live transport")


if __name__ == "__main__":
    main()
