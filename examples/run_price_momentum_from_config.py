#!/usr/bin/env python3
"""Run PriceMomentumStrategy with the same configuration-driven runtime.

Prefer ``examples/run.py``; this wrapper remains for older docs/links.
"""

from __future__ import annotations

import argparse

from goldarb import AppConfig, StrategyRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config",
        nargs="?",
        default="examples/runtime.price_momentum.yaml",
    )
    args = parser.parse_args()

    config = AppConfig.from_file(args.config)
    result = StrategyRunner.from_config(config).run()
    print(
        f"strategy={result.config.strategy_name} mode={config.runtime.mode} "
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} equity={result.portfolio.equity}"
    )


if __name__ == "__main__":
    main()
