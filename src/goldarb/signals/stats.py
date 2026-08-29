"""Shared premium / z-score helpers (gold-arbitrage F-3 / F-6 math)."""

from __future__ import annotations

import math
import statistics
from typing import Any


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def premium_from_row(row: dict[str, Any]) -> float | None:
    """Stored premium, or (close − NAV) / NAV × 100 when the column is null."""
    premium = to_float(row.get("premium"))
    if premium is None:
        premium = to_float(row.get("premium_discount_pct"))
    if premium is not None:
        return premium
    close = to_float(row.get("close"))
    if close is None:
        close = to_float(row.get("close_price"))
    nav = to_float(row.get("nav"))
    if nav is None:
        nav = to_float(row.get("nav_price"))
    if close is None or nav is None or nav <= 0:
        return None
    return (close - nav) / nav * 100


def average_rank_percentile(values: list[float], current: float) -> float:
    n = len(values)
    if n == 0:
        raise ValueError("empty sample")
    less = sum(1 for item in values if item < current)
    equal = sum(1 for item in values if item == current)
    return round(100.0 * (less + 0.5 * equal) / n, 2)


def sample_mean_std(values: list[float]) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    mean = statistics.fmean(values)
    if len(values) < 2:
        return round(mean, 2), None
    return round(mean, 2), round(statistics.stdev(values), 2)
