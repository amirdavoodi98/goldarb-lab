#!/usr/bin/env python3
"""StreakStrategy: live paper and archive backtest in one file.

The live ``main`` is commented out. The active ``main`` replays one archive day.

    .venv/bin/python examples/run_streak_live.py

Live needs GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD.
"""

from goldarb import AppConfig, StrategyRunner, StreakStrategy

SYMBOLS = ("طلا", "عیار")
MAX_POLLS = 12
POLL_SECONDS = 2.0
ARCHIVE = "archive/1s-14d"
START = "2026-09-15"
END = "2026-09-15"


def _report(mode: str, result) -> None:
    print(
        f"mode={mode} "
        f"events={len(result.equity_history)} "
        f"signals={result.metrics.n_signals} "
        f"orders={result.metrics.n_orders} "
        f"fills={result.metrics.n_trades} "
        f"equity={result.portfolio.equity}"
    )
    for signal in result.signals:
        print(f"  {signal.side.value:4} {signal.symbol} price={signal.extra.get('price')}")


# def main() -> None:
#     config = (
#         AppConfig.builder()
#         .set_live(symbols=SYMBOLS, max_polls=MAX_POLLS, poll_seconds=POLL_SECONDS)
#         .build()
#     )
#     result = StrategyRunner.from_config(config).run(
#         StreakStrategy(quantity="1", length=2)
#     )
#     _report("live_paper_local", result)


def main() -> None:
    config = (
        AppConfig.builder()
        .set_archive(ARCHIVE, symbols=SYMBOLS, start=START, end=END)
        .build()
    )
    result = StrategyRunner.from_config(config).run(
        StreakStrategy(quantity="1", length=2)
    )
    _report("offline_backtest", result)


if __name__ == "__main__":
    main()
