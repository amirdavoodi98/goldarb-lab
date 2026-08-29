"""F-22 bubble-rank: cheapness score = window mean − current premium."""

from __future__ import annotations

import statistics
from typing import Any

BUBBLE_RANK_WINDOW_DAYS = 20
BUBBLE_RANK_MIN_SAMPLES = 10
BUBBLE_RANK_MIN_GAP = 1.0


def empty_bubble_rank(
    *,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
) -> dict[str, Any]:
    return {
        "window_days": window_days,
        "rankings": [],
        "best_pair": None,
    }


def compute_symbol_score(
    series: list[float],
    *,
    min_samples: int = BUBBLE_RANK_MIN_SAMPLES,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
) -> dict[str, Any]:
    # ``window_days`` is last N observations (Lab daily bars ≡ calendar days).
    values = list(series[-window_days:]) if series else []
    n = len(values)
    current = round(values[-1], 4) if values else None

    if n < min_samples or current is None:
        return {
            "current": current,
            "avg20": None,
            "score": None,
            "sample_count": n,
            "status": "insufficient_samples",
        }

    avg20 = round(statistics.fmean(values), 4)
    score = round(avg20 - current, 4)
    return {
        "current": current,
        "avg20": avg20,
        "score": score,
        "sample_count": n,
        "status": "ok",
    }


def compute_rankings(
    by_symbol: dict[str, list[float]],
    *,
    min_samples: int = BUBBLE_RANK_MIN_SAMPLES,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
    min_gap: float = BUBBLE_RANK_MIN_GAP,
) -> dict[str, Any]:
    rankings: list[dict[str, Any]] = []
    for symbol, series in by_symbol.items():
        row = compute_symbol_score(
            series,
            min_samples=min_samples,
            window_days=window_days,
        )
        rankings.append({"symbol": symbol, **row})

    rankings.sort(
        key=lambda row: (
            0 if row["status"] == "ok" else 1,
            -(row["score"] if row["score"] is not None else float("-inf")),
            row["symbol"] or "",
        )
    )

    ok = [row for row in rankings if row["status"] == "ok" and row["score"] is not None]
    best_pair: dict[str, Any] | None = None
    if len(ok) >= 2:
        long_row = max(ok, key=lambda row: (row["score"], row["symbol"] or ""))
        short_row = min(ok, key=lambda row: (row["score"], row["symbol"] or ""))
        if long_row["symbol"] != short_row["symbol"]:
            gap = round(float(long_row["score"]) - float(short_row["score"]), 4)
            active = gap >= min_gap
            best_pair = {
                "active": active,
                "long": long_row["symbol"],
                "short": short_row["symbol"],
                "long_score": long_row["score"],
                "short_score": short_row["score"],
                "gap": gap,
                "label_fa": (
                    f"خرید {long_row['symbol']} / فروش {short_row['symbol']}"
                    if active
                    else "بدون سیگنال جفتی"
                ),
            }

    return {
        "window_days": window_days,
        "rankings": rankings,
        "best_pair": best_pair,
    }
