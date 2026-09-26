"""Paper-simulate a pair strategy for the 6-hour Iran cash session at 1s.

Waits until 12:00 Tehran if needed, polls every second until 18:00.
Requires GOLDARB_BASE_URL + GOLDARB_TOKEN (or username/password).

    python examples/simulate_iran_session_1s.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from goldarb import (
    BubbleRankStrategy,
    LabClient,
    PairZScoreStrategy,
    iran_session_live,
)
from goldarb.execution import PercentFee
from goldarb.session import TEHRAN, is_iran_trading_day, session_bounds
from goldarb.simulation import LocalSimulator, get_broker
from goldarb.universe import GOLD_FUND_SYMBOLS

HERE = Path(__file__).resolve().parent
POLL_SECONDS = float(os.environ.get("GOLDARB_POLL_SECONDS", "1"))
LOOKBACK_DAYS = int(os.environ.get("GOLDARB_LOOKBACK_DAYS", "20"))
STRATEGY = os.environ.get("GOLDARB_STRATEGY", "bubble_rank").strip().lower()
DB_PATH = HERE / "iran_session_1s.sqlite3"


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
        return PairZScoreStrategy(capital_per_side="100000000", min_samples=10)
    return BubbleRankStrategy(capital_per_side="100000000", min_samples=10, min_gap=1.0)


def _wait_for_open(start: datetime) -> None:
    while True:
        now = datetime.now(TEHRAN)
        if now >= start:
            return
        remaining = (start - now).total_seconds()
        print(f"waiting for session open {start.isoformat()} ({remaining:.0f}s)", flush=True)
        time.sleep(min(30.0, max(1.0, remaining)))


def main() -> int:
    open_at, close_at = session_bounds()
    now = datetime.now(TEHRAN)
    print(
        f"Iran session {open_at.strftime('%Y-%m-%d %H:%M')}–{close_at.strftime('%H:%M')} "
        f"poll={POLL_SECONDS}s lookback={LOOKBACK_DAYS}d symbols={len(GOLD_FUND_SYMBOLS)}"
    )
    if not is_iran_trading_day(open_at.date()):
        raise SystemExit("today is not a gold-fund trading day (Saturday–Wednesday)")
    if now > close_at:
        raise SystemExit("today's 12:00–18:00 session has already closed")
    _wait_for_open(open_at)
    if DB_PATH.exists():
        DB_PATH.unlink()
    strategy = _strategy()
    with _client() as client, LocalSimulator(DB_PATH, broker=get_broker("agah")) as simulator:
        result = iran_session_live(
            strategy,
            client,
            poll_seconds=POLL_SECONDS,
            lookback_days=LOOKBACK_DAYS,
            grain="1s",
            allow_short=True,
            fee=PercentFee("0.0005"),
            simulator=simulator,
            stop_at=close_at,
        )
    print(
        f"session end orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"signals={result.metrics.n_signals} equity={result.portfolio.equity}"
    )
    events = getattr(strategy, "events", [])
    print(f"pair_events={[item.get('type') for item in events]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
