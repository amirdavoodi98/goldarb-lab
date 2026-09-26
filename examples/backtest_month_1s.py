"""Backtest a pair strategy on the past month of 1s Iran-session bars.

Requires GOLDARB_BASE_URL + GOLDARB_TOKEN (or GOLDARB_USERNAME/PASSWORD).

    python examples/backtest_month_1s.py
"""

from __future__ import annotations

import os
from pathlib import Path

from goldarb import BubbleRankStrategy, LabClient, PairZScoreStrategy, month_backtest
from goldarb.execution import PercentFee
from goldarb.simulation import LocalSimulator, get_broker
from goldarb.universe import GOLD_FUND_SYMBOLS

HERE = Path(__file__).resolve().parent
DAYS = int(os.environ.get("GOLDARB_DAYS", "30"))
FILL_SESSION = os.environ.get("GOLDARB_FILL_SESSION", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
STRATEGY = os.environ.get("GOLDARB_STRATEGY", "bubble_rank").strip().lower()
DB_PATH = HERE / "month_1s.sqlite3"


def _client() -> LabClient:
    try:
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv(HERE.parent / ".env")
    except ImportError:
        pass
    try:
        return LabClient.from_env(timeout=180.0)
    except RuntimeError:
        username = os.environ.get("GOLDARB_USERNAME", "").strip()
        password = os.environ.get("GOLDARB_PASSWORD", "").strip()
        base = os.environ.get("GOLDARB_BASE_URL", "https://goldarb.ir").strip()
        if not username or not password:
            raise RuntimeError(
                "Set GOLDARB_BASE_URL+GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD"
            )
        return LabClient.login(
            base_url=base,
            username=username,
            password=password,
            timeout=180.0,
        )


def _strategy():
    if STRATEGY == "pair_zscore":
        return PairZScoreStrategy(
            capital_per_side="100000000",
            window_days=min(90, DAYS),
            min_samples=10,
        )
    return BubbleRankStrategy(capital_per_side="100000000", min_samples=10, min_gap=1.0)


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    strategy = _strategy()
    print(
        f"month backtest days={DAYS} grain=1s fill_session={FILL_SESSION} "
        f"symbols={len(GOLD_FUND_SYMBOLS)} strategy={strategy.name}"
    )
    with _client() as client, LocalSimulator(DB_PATH, broker=get_broker("agah")) as simulator:
        result = month_backtest(
            strategy,
            client,
            days=DAYS,
            grain="1s",
            fill_session=FILL_SESSION,
            allow_short=True,
            fee=PercentFee("0.0005"),
            simulator=simulator,
        )
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"signals={result.metrics.n_signals} equity={result.portfolio.equity} "
        f"return={result.metrics.total_return}"
    )
    events = getattr(strategy, "events", [])
    print(f"pair_events={[item.get('type') for item in events]}")
    for position in result.portfolio.positions:
        if position.quantity:
            print(f"  {position.symbol} qty={position.quantity}")


if __name__ == "__main__":
    main()
