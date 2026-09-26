#!/usr/bin/env python3
"""Download 14 days of 1s bars for all gold funds, then backtest bubble sign offline.

حباب منفی → خرید؛ حباب مثبت → فروش.

دانلود و بک‌تست:
    python examples/backtest_two_weeks_1s.py --download

فقط آرشیو موجود، بدون اینترنت:
    python examples/backtest_two_weeks_1s.py --archive archive/1s-14d

دمو بدون API:
    python examples/backtest_two_weeks_1s.py --demo
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from goldarb import (
    BubbleSignStrategy,
    LabClient,
    download_symbol_bars,
    offline_backtest,
)
from goldarb.archive import write_symbol_bars
from goldarb.execution import PercentFee
from goldarb.simulation import LocalSimulator, get_broker
from goldarb.universe import GOLD_FUND_SYMBOLS

HERE = Path(__file__).resolve().parent
DEFAULT_ARCHIVE = HERE.parent / "archive" / "1s-14d"
DEFAULT_PAPER = HERE / "two_weeks_1s.sqlite3"


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


def _demo_archive(path: Path) -> Path:
    start = datetime(2026, 8, 29, 8, 30, tzinfo=UTC)
    funds = (("طلا", 100), ("گوهر", 200), ("عیار", 300))
    bubbles = (-2.0, -0.5, 1.5, 2.0)
    by_symbol: dict[str, list[dict]] = {}
    for symbol, base in funds:
        rows = []
        for second, prem in enumerate(bubbles):
            close = base + second
            rows.append(
                {
                    "bar_at": (start + timedelta(seconds=second)).isoformat(),
                    "close": close,
                    "premium_discount_pct": prem,
                    "nav_price": close / (1 + prem / 100),
                }
            )
        by_symbol[symbol] = rows
    return write_symbol_bars(
        path, by_symbol, grain="1s", start="2026-08-29", end="2026-08-29"
    )


def _print_result(result) -> None:
    print(
        f"orders={result.metrics.n_orders} fills={result.metrics.n_trades} "
        f"signals={result.metrics.n_signals} equity={result.portfolio.equity} "
        f"realized={result.portfolio.realized_pnl} fees={result.portfolio.fees_paid}"
    )
    for position in result.portfolio.positions:
        if position.quantity:
            print(
                f"  {position.symbol:<12} qty={position.quantity} "
                f"mark={position.mark_price} uPnL={position.unrealized_pnl}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--paper", type=Path, default=DEFAULT_PAPER)
    parser.add_argument("--days", type=int, default=14)
    args = parser.parse_args()

    if args.demo:
        archive = _demo_archive(args.archive)
        print(f"demo archive {archive}")
    elif (args.archive / "manifest.json").exists() and not args.download:
        archive = args.archive
        print(f"offline archive {archive}")
    else:
        if not args.download:
            parser.error("pass --download, --demo, or an existing --archive")
        print(
            f"downloading last {args.days}d grain=1s "
            f"symbols={len(GOLD_FUND_SYMBOLS)} → {args.archive}"
        )
        with _client() as client:
            archive = download_symbol_bars(
                client, args.archive, days=args.days, grain="1s"
            )
        print(f"saved {archive / 'manifest.json'}")

    if args.paper.exists():
        args.paper.unlink()
    with LocalSimulator(args.paper, broker=get_broker("agah")) as simulator:
        result = offline_backtest(
            BubbleSignStrategy(quantity="1"),
            archive,
            fill_session=False,
            allow_short=False,
            fee=PercentFee("0.0005"),
            simulator=simulator,
        )
    _print_result(result)
    print(f"paper={args.paper}")


if __name__ == "__main__":
    main()
