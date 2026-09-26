#!/usr/bin/env python3
"""Live paper-test a strategy against Iran gold-fund quotes.

Uses Lab live feed + LocalPaperBroker (no real orders).
Requires GOLDARB_USERNAME/PASSWORD or GOLDARB_TOKEN in the environment / .env.

Default universe: first 20 symbols from GOLD_FUND_SYMBOLS (30 funds total).

Short smoke test (~30 polls, 20 funds):

    .venv/bin/python examples/try_strategy_live.py

All 30 gold funds until session close:

    .venv/bin/python examples/try_strategy_live.py --all-funds --until-close

Custom list:

    .venv/bin/python examples/try_strategy_live.py --symbols طلا,عیار,زر,گوهر
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

from goldarb import LabClient, LiveSimulationEngine, PriceMomentumStrategy, RunConfig
from goldarb.data import LabLiveFeed, LiveDataProvider
from goldarb.execution import PercentFee
from goldarb.session import TEHRAN, in_iran_session, is_iran_trading_day, session_bounds
from goldarb.simulation import LocalSimulator, get_broker
from goldarb.universe import GOLD_FUND_SYMBOLS

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DEFAULT_MIN_FUNDS = 20


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv()
    except ImportError:
        pass


def _client() -> LabClient:
    _load_env()
    try:
        return LabClient.from_env(timeout=120.0)
    except RuntimeError:
        username = os.environ.get("GOLDARB_USERNAME", "").strip()
        password = os.environ.get("GOLDARB_PASSWORD", "").strip()
        base = os.environ.get("GOLDARB_BASE_URL", "https://goldarb.ir").strip()
        if not username or not password:
            raise SystemExit(
                "Set GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD "
                "(see .env / LabClient.from_env)."
            )
        return LabClient.login(
            base_url=base,
            username=username,
            password=password,
            timeout=120.0,
        )


def _resolve_symbols(args: argparse.Namespace) -> tuple[str, ...]:
    if args.symbols:
        symbols = tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    elif args.all_funds:
        symbols = GOLD_FUND_SYMBOLS
    else:
        symbols = GOLD_FUND_SYMBOLS[: max(args.min_funds, DEFAULT_MIN_FUNDS)]
    if len(symbols) < args.min_funds:
        raise SystemExit(
            f"need at least {args.min_funds} symbols, got {len(symbols)}: {symbols}"
        )
    unknown = [symbol for symbol in symbols if symbol not in GOLD_FUNDS_SET]
    if unknown:
        raise SystemExit(f"unknown fund symbol(s): {', '.join(unknown)}")
    return symbols


GOLD_FUNDS_SET = set(GOLD_FUND_SYMBOLS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated fund names (default: first 20 GOLD_FUND_SYMBOLS)",
    )
    parser.add_argument(
        "--min-funds",
        type=int,
        default=DEFAULT_MIN_FUNDS,
        help=f"Minimum universe size (default: {DEFAULT_MIN_FUNDS})",
    )
    parser.add_argument(
        "--all-funds",
        action="store_true",
        help=f"Use full universe ({len(GOLD_FUND_SYMBOLS)} funds)",
    )
    parser.add_argument("--quantity", default="1")
    parser.add_argument("--threshold-pct", default="0.1")
    parser.add_argument("--fee", default="0.0005")
    parser.add_argument("--poll", type=float, default=2.0, help="Seconds between polls")
    parser.add_argument(
        "--max-polls",
        type=int,
        default=30,
        help="Stop after N polls (ignored with --until-close)",
    )
    parser.add_argument(
        "--until-close",
        action="store_true",
        help="Run until today's 18:00 Tehran session close",
    )
    parser.add_argument(
        "--db",
        default=str(HERE / "try_strategy_live.sqlite3"),
        help="SQLite path for paper fills",
    )
    args = parser.parse_args()
    symbols = _resolve_symbols(args)

    open_at, close_at = session_bounds()
    now = datetime.now(TEHRAN)
    print(
        f"Tehran now={now.strftime('%Y-%m-%d %H:%M:%S')}  "
        f"session={open_at.strftime('%H:%M')}–{close_at.strftime('%H:%M')}  "
        f"trading_day={is_iran_trading_day(now.date())}  "
        f"in_session={in_iran_session(now)}",
        flush=True,
    )
    if not is_iran_trading_day(now.date()):
        raise SystemExit("today is not a gold-fund trading day (Saturday–Wednesday)")
    if now > close_at:
        raise SystemExit("today's session has already closed")
    if now < open_at:
        wait = (open_at - now).total_seconds()
        print(f"waiting for open ({wait:.0f}s)…", flush=True)
        time.sleep(min(wait, 30.0))
        now = datetime.now(TEHRAN)
        if now < open_at:
            raise SystemExit(
                f"session opens at {open_at.isoformat()}; re-run closer to open"
            )

    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()

    strategy = PriceMomentumStrategy(
        quantity=args.quantity,
        threshold_pct=args.threshold_pct,
    )
    max_polls = None if args.until_close else args.max_polls
    print(
        f"live paper  funds={len(symbols)}  poll={args.poll}s  "
        f"max_polls={max_polls or 'until-close'}  threshold={args.threshold_pct}%",
        flush=True,
    )
    print(f"universe: {', '.join(symbols)}", flush=True)

    with _client() as client, LocalSimulator(db_path, broker=get_broker("agah")) as simulator:
        provider = LiveDataProvider(
            LabLiveFeed(client),
            symbols=symbols,
            poll_seconds=args.poll,
            bar_grain="1s",
            include_session_bars=False,
            lookback_days=0,
            stop_at=close_at,
            max_polls=max_polls,
            on_error=lambda exc: print(f"feed error: {exc}", flush=True),
            on_idle=lambda: print(".", end="", flush=True),
        )
        result = LiveSimulationEngine().run(
            strategy,
            provider,
            RunConfig(
                strategy_name=strategy.name,
                strategy_version=strategy.version,
                initial_cash="1000000000",
                label="try-strategy-live",
            ),
            simulator=simulator,
            fee=PercentFee(args.fee),
        )

    print()
    print("=== live result ===")
    print(
        f"funds={len(symbols)}  signals={result.metrics.n_signals}  "
        f"orders={result.metrics.n_orders}  fills={result.metrics.n_trades}  "
        f"equity={result.portfolio.equity}  fees={result.portfolio.fees_paid}"
    )
    by_symbol: dict[str, int] = {}
    for signal in result.signals:
        by_symbol[signal.symbol] = by_symbol.get(signal.symbol, 0) + 1
        print(f"  SIGNAL {signal.side.value} {signal.symbol} {dict(signal.extra)}")
    if by_symbol:
        print("=== signals by fund ===")
        for symbol, count in sorted(by_symbol.items(), key=lambda item: (-item[1], item[0])):
            print(f"  {symbol}: {count}")
    for fill in result.fills:
        print(
            f"  FILL qty={fill.quantity} price={fill.price} fee={fill.fee} "
            f"at={fill.filled_at}"
        )
    if not result.signals and not result.fills:
        print(
            "  (no trades yet — live moves may be smaller than --threshold-pct; "
            "try a lower threshold or --until-close)"
        )
    print(f"paper db: {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
