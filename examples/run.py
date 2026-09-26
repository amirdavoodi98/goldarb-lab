#!/usr/bin/env python3
"""Unified config-driven strategy runner (backtest or live paper).

Mode is set only in the YAML (`runtime.mode`); the strategy class is built
from `strategy.name` via the registry.

Backtest:

    .venv/bin/python examples/run.py examples/runtime.backtest.yaml

Live paper (local matching, ≥20 funds by default):

    .venv/bin/python examples/run.py examples/runtime.live.yaml

Needs: uv pip install --python .venv/bin/python -e '.[yaml]'
Live needs GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from goldarb import AppConfig, StrategyRunner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "config",
        nargs="?",
        default="examples/runtime.backtest.yaml",
        help="Path to JSON, TOML, or YAML AppConfig",
    )
    args = parser.parse_args()
    path = Path(args.config)
    if not path.is_file():
        raise SystemExit(f"config not found: {path}")

    config = AppConfig.from_file(path)
    result = StrategyRunner.from_config(config).run()
    print(
        f"strategy={result.config.strategy_name} mode={config.runtime.mode} "
        f"events={len(result.equity_history)} "
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} equity={result.portfolio.equity}"
    )


if __name__ == "__main__":
    main()
