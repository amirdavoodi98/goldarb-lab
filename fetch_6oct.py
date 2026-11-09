#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from goldarb import LabClient

ROOT = Path(__file__).resolve().parent


def _client() -> LabClient:
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        load_dotenv()
    except ImportError:
        pass

    try:
        return LabClient.from_env(timeout=120.0)
    except RuntimeError:
        username = os.environ.get("GOLDARB_USERNAME", "").strip()
        password = os.environ.get("GOLDARB_PASSWORD", "").strip()
        base = os.environ.get("GOLDARB_BASE_URL", "https://goldarb.ir").strip()
        if not username or not password:
            raise SystemExit(
                "Set GOLDARB_TOKEN or GOLDARB_USERNAME+GOLDARB_PASSWORD in .env"
            )
        return LabClient.login(
            base_url=base,
            username=username,
            password=password,
            timeout=120.0,
        )


def main() -> None:
    with _client() as client:
        bars = client.fund.candles(
            "گوهر",
            start="2026-10-06",
            end="2026-10-06",
            grain="1s",
        )

    print(f"bars={len(bars)}")
    if not bars:
        return
    first = bars[0]
    print(
        first.get("bar_at"),
        first.get("close"),
        first.get("nav_price"),
        first.get("premium_discount_pct"),
    )
    last = bars[-1]
    print(
        last.get("bar_at"),
        last.get("close"),
        last.get("nav_price"),
        last.get("premium_discount_pct"),
    )


if __name__ == "__main__":
    main()
