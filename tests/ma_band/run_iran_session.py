"""Run the MA-band strategy during today's Iran cash session (12:00–17:00).

This file is a runner only: data comes from ``LiveDataProvider``, decisions
from ``MaBandStrategy``, and fills from ``LiveSimulationEngine``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from session import TEHRAN, format_tick, session_bounds, tick_record

from goldarb import LabClient
from goldarb.data import LabLiveFeed, LiveDataProvider
from goldarb.engine import LiveSimulationEngine, RunConfig
from goldarb.execution import PercentFee
from goldarb.simulation import LocalSimulator
from goldarb.strategies import MaBandStrategy

HERE = Path(__file__).resolve().parent
SYMBOL = os.environ.get("GOLDARB_SYMBOL", "طلا")
WINDOW = int(os.environ.get("GOLDARB_MA_WINDOW", "3"))
BUY_BAND = os.environ.get("GOLDARB_BUY_BAND", "0.02")
SELL_BAND = os.environ.get("GOLDARB_SELL_BAND", "0.02")
QUANTITY = os.environ.get("GOLDARB_QUANTITY", "1")
POLL_SECONDS = float(os.environ.get("GOLDARB_POLL_SECONDS", "15"))
DB_PATH = HERE / "iran_session.sqlite3"
SIGNAL_LOG = HERE / "iran_session_signals.jsonl"
TICK_LOG = HERE / "iran_session_ticks.log"


def _client() -> LabClient:
    try:
        from dotenv import load_dotenv

        load_dotenv()
        load_dotenv(HERE.parents[1] / ".env")
    except ImportError:
        pass
    base = os.environ.get("GOLDARB_BASE_URL", "https://goldarb.ir").strip()
    username = os.environ.get("GOLDARB_USERNAME", "").strip()
    password = os.environ.get("GOLDARB_PASSWORD", "").strip()
    if not username or not password:
        raise RuntimeError("Set GOLDARB_USERNAME and GOLDARB_PASSWORD")
    return LabClient.login(
        base_url=base,
        username=username,
        password=password,
        timeout=180.0,
    )


def _emit(line: str) -> None:
    print(line, flush=True)
    with TICK_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _write_signal(record: dict[str, str]) -> None:
    with SIGNAL_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _wait_for_open(start: datetime) -> None:
    while True:
        now = datetime.now(TEHRAN)
        if now >= start:
            return
        remaining = (start - now).total_seconds()
        _emit(f"waiting for session open {start.isoformat()} ({remaining:.0f}s)")
        time.sleep(min(30.0, max(1.0, remaining)))


def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    TICK_LOG.write_text("", encoding="utf-8")
    SIGNAL_LOG.write_text("", encoding="utf-8")
    start, end = session_bounds()
    now = datetime.now(TEHRAN)
    _emit(
        f"Iran session {start.strftime('%Y-%m-%d %H:%M')}–{end.strftime('%H:%M')} "
        f"{TEHRAN.key}  now={now.strftime('%H:%M:%S')}  symbol={SYMBOL}  "
        f"window={WINDOW}  band={BUY_BAND}/{SELL_BAND}"
    )
    if now > end:
        raise SystemExit("today's 12:00–17:00 session has already closed")

    _wait_for_open(start)
    client = _client()
    _emit(f"logged in as {os.environ.get('GOLDARB_USERNAME', '').strip()}")
    strategy = MaBandStrategy(
        symbol=SYMBOL,
        window=WINDOW,
        buy_band=BUY_BAND,
        sell_band=SELL_BAND,
        quantity=QUANTITY,
    )

    def on_event(kind: str, ctx) -> None:
        if kind != "tick":
            return
        tick = strategy.last_tick
        if tick is None:
            return
        line = format_tick(
            tick,
            symbol=SYMBOL,
            buy_band=Decimal(BUY_BAND),
            sell_band=Decimal(SELL_BAND),
        )
        _emit(line)
        if tick.signal is not None:
            _write_signal(tick_record(tick, symbol=SYMBOL))
            status = ctx.status()
            _emit(f"  order submitted  cash={status['cash']}")

    def on_error(exc: BaseException) -> None:
        _emit(f"feed error: {exc}")

    def on_idle() -> None:
        _emit(
            f"{datetime.now(TEHRAN).strftime('%H:%M:%S')}  "
            f"no new bar  signals={len(strategy.signals)}"
        )

    provider = LiveDataProvider(
        LabLiveFeed(client),
        symbol=SYMBOL,
        poll_seconds=POLL_SECONDS,
        stop_at=end,
        on_error=on_error,
        on_idle=on_idle,
    )
    try:
        with LocalSimulator(DB_PATH) as simulator:
            result = LiveSimulationEngine().run(
                strategy,
                provider,
                RunConfig(
                    strategy_name=strategy.name,
                    strategy_version=strategy.version,
                    initial_cash="1000000000",
                    label="ma-band-iran-session",
                    database=str(DB_PATH),
                    strategy_config={
                        "symbol": SYMBOL,
                        "window": str(WINDOW),
                        "buy_band": BUY_BAND,
                        "sell_band": SELL_BAND,
                        "quantity": QUANTITY,
                    },
                ),
                simulator=simulator,
                fee=PercentFee("0.0005"),
                on_event=on_event,
            )
            portfolio = result.portfolio
            _emit(
                f"session end  signals={len(strategy.signals)}  "
                f"orders={len(result.orders)}  fills={len(result.fills)}  "
                f"equity={portfolio.equity}  "
                f"realized={portfolio.realized_pnl}"
            )
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
