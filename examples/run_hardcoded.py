#!/usr/bin/env python3
"""Hardcoded AppConfig via fluent setters (no YAML).

    .venv/bin/python examples/run_hardcoded.py
"""

from __future__ import annotations

from goldarb import AppConfig, StrategyRunner, GOLD_FUND_SYMBOLS


def main() -> None:
    config = (
        AppConfig.builder()
        .set_archive(
            "examples/data/price-momentum-demo",
            symbols=["طلا", "عیار"],
            start="2026-09-15",
            end="2026-09-15",
        )
        .set_initial_cash("1000000")
        .set_database(":memory:")
        .set_strategy("price_momentum", quantity="1", threshold_pct="0.5")
        .set_fee("PercentFee", fee_rate="0.0005")
        .set_slippage("NoSlippage")
        .set_latency("NoLatency")
        .build()
    )
    result = StrategyRunner.from_config(config).run()
    print(
        f"strategy={result.config.strategy_name} mode={config.runtime.mode} "
        f"events={len(result.equity_history)} orders={result.metrics.n_orders} "
        f"equity={result.portfolio.equity}"
    )

    # Same builder can flip to live paper without rewriting strategy params:
    live = (
        config.to_builder()
        .set_live(symbols=GOLD_FUND_SYMBOLS[:20], max_polls=5, poll_seconds=2.0)
        .set_label("price_momentum_live_hardcoded")
        .build()
    )
    print(f"live-ready mode={live.runtime.mode} symbols={len(live.data.symbols)}")


if __name__ == "__main__":
    main()
