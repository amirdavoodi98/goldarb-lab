#!/usr/bin/env python3
"""Offline strategy path. Same call as examples/run.py.

    .venv/bin/python examples/run_strategy_path.py

``examples/run.py`` loads one config and runs
``StrategyRunner.from_config(config).run()``. This script does that three
times. Pass one config path to run a single case.

- backtest, quote_fill=last, NoOp, broker=agah (local paper)
- OffsetLimit on the same bars
- live_broker with runtime.gateway=recording

``BubbleRankStrategy`` comes from ``strategy.name``. Nothing here opens a
socket. The submit trace is ``result.trace``.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from goldarb import AppConfig, StrategyRunner

CONFIGS = (
    "examples/runtime.strategy-path.backtest.json",
    "examples/runtime.strategy-path.offset.json",
    "examples/runtime.strategy-path.live.json",
)


def _show(config: AppConfig, result) -> None:
    print(
        f"strategy={result.config.strategy_name} mode={config.runtime.mode} "
        f"quote_fill={config.data.quote_fill} policy={config.execution_policy.name} "
        f"broker={config.runtime.broker} gateway={result.gateway} "
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity}"
    )
    for step in result.trace:
        limit = step["limit_price"] or "-"
        print(
            f"  gateway={step['gateway']} symbol={step['symbol']} side={step['side']} "
            f"type={step['order_type']} limit={limit} status={step['status']} "
            f"filled={step['filled_quantity']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        help="JSON, TOML, or YAML AppConfig. Default: the three strategy-path configs.",
    )
    args = parser.parse_args()
    paths = [args.config] if args.config else list(CONFIGS)
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            raise SystemExit(f"config not found: {path}")
        config = AppConfig.from_file(path)
        result = StrategyRunner.from_config(config).run()
        _show(config, result)


if __name__ == "__main__":
    main()
