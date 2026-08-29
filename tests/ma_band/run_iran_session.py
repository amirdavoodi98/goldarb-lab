"""Run the MA-band LocalSimulator during today's Iran cash session (12:00–17:00)."""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ma_band import MaBandEngine, snapshots_from_bars
from session import (
    TEHRAN,
    filter_session_snapshots,
    format_tick,
    in_iran_session,
    session_bounds,
    snapshot_from_live,
    tick_record,
)

from goldarb import LabClient
from goldarb.simulation import LocalSimulator

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
    seen: set[str] = set()
    signal_count = 0
    with LocalSimulator(DB_PATH) as simulator:
        account = simulator.create_account(
            initial_cash="1000000000",
            fee_rate="0.0005",
            allow_short=False,
            label="ma-band-iran-session",
        )
        engine = MaBandEngine(
            simulator=simulator,
            account_id=account.id,
            symbol=SYMBOL,
            window=WINDOW,
            buy_band=BUY_BAND,
            sell_band=SELL_BAND,
            quantity=QUANTITY,
        )
        try:
            while datetime.now(TEHRAN) <= end:
                day = datetime.now(TEHRAN).date()
                try:
                    bars = client.fund.candles(
                        SYMBOL,
                        start=day.isoformat(),
                        end=day.isoformat(),
                        grain="1m",
                    )
                    last = client.fund.last_price(SYMBOL)
                    book = client.fund.orderbook(SYMBOL)
                except Exception as exc:
                    _emit(f"feed error: {exc}")
                    time.sleep(POLL_SECONDS)
                    continue

                pending = []
                if not seen:
                    pending.extend(
                        filter_session_snapshots(
                            snapshots_from_bars(bars, symbol=SYMBOL)
                        )
                    )
                live = snapshot_from_live(
                    symbol=SYMBOL,
                    last_price=last if isinstance(last, dict) else {},
                    orderbook=book if isinstance(book, dict) else None,
                )
                if live is not None and in_iran_session(live.timestamp):
                    pending.append(live)

                new_ticks = 0
                for snapshot in pending:
                    if snapshot.event_id in seen:
                        continue
                    seen.add(snapshot.event_id)
                    tick = engine.on_snapshot(snapshot)
                    if tick is None:
                        continue
                    new_ticks += 1
                    line = format_tick(
                        tick,
                        symbol=SYMBOL,
                        buy_band=Decimal(BUY_BAND),
                        sell_band=Decimal(SELL_BAND),
                    )
                    _emit(line)
                    if tick.signal is not None:
                        signal_count += 1
                        _write_signal(tick_record(tick, symbol=SYMBOL))
                        _emit(
                            "  order submitted  cash="
                            f"{simulator.portfolio(account.id).cash}"
                        )

                if new_ticks == 0:
                    _emit(
                        f"{datetime.now(TEHRAN).strftime('%H:%M:%S')}  "
                        f"no new bar  seen={len(seen)}  signals={signal_count}"
                    )
                time.sleep(POLL_SECONDS)
        finally:
            client.close()
            result = engine.result()
            _emit(
                f"session end  signals={len(result.signals)}  "
                f"orders={len(result.orders)}  fills={len(result.fills)}  "
                f"equity={result.portfolio.equity}  "
                f"realized={result.portfolio.realized_pnl}"
            )


if __name__ == "__main__":
    sys.exit(main())
