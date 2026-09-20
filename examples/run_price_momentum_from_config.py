#!/usr/bin/env python3
"""Run PriceMomentumStrategy with the same configuration-driven runtime."""

from __future__ import annotations

import argparse

from goldarb import AppConfig, PriceMomentumStrategy, StrategyRunner


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config",
        nargs="?",
        default="examples/runtime.price_momentum.yaml",
    )
    args = parser.parse_args()

    config = AppConfig.from_file(args.config)
    strategy = PriceMomentumStrategy(**config.strategy.params)
    result = StrategyRunner.from_config(config).run(strategy)
    print(
        f"strategy={strategy.name} mode={config.runtime.mode} "
        f"signals={result.metrics.n_signals} orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} equity={result.portfolio.equity}"
    )


if __name__ == "__main__":
    main()
