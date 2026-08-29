"""F-6 pair premium-spread z-score (gold-arbitrage ``compute_pair_spread_stats``)."""

from __future__ import annotations

from typing import Any

from .stats import average_rank_percentile, sample_mean_std

PAIR_SPREAD_DEFAULT_WINDOW = 90
PAIR_SPREAD_MIN_SAMPLES = 10
PAIR_SPREAD_Z_THRESHOLD = 2.0


def compute_pair_spread_stats(
    *,
    fund_a: str,
    fund_b: str,
    series: list[float],
    premium_a: float | None,
    premium_b: float | None,
    price_a: float | None,
    price_b: float | None,
    window_days: int = PAIR_SPREAD_DEFAULT_WINDOW,
    min_samples: int = PAIR_SPREAD_MIN_SAMPLES,
    z_threshold: float = PAIR_SPREAD_Z_THRESHOLD,
) -> dict[str, Any]:
    """Z-score of overlapping same-snapshot premium spreads.

    ``series`` should already be truncated to the last ``window_days`` observations.
    """
    n = len(series)
    mean, std = sample_mean_std(series)
    current_spread = series[-1] if series else None
    if current_spread is None and premium_a is not None and premium_b is not None:
        current_spread = round(premium_a - premium_b, 4)

    min_samples_met = n >= min_samples
    z_score: float | None = None
    percentile: float | None = None
    status = "insufficient_samples"

    if min_samples_met and current_spread is not None and mean is not None:
        percentile = average_rank_percentile(series, current_spread)
        if std is None or std == 0:
            status = "zero_variance"
            z_score = None
        else:
            status = "ok"
            z_score = round((current_spread - mean) / std, 2)

    price_spread: float | None = None
    if price_a is not None and price_b is not None and price_b != 0:
        price_spread = round((price_a / price_b - 1) * 100, 3)

    signal = _pair_signal(
        fund_a=fund_a,
        fund_b=fund_b,
        z_score=z_score,
        premium_a=premium_a,
        premium_b=premium_b,
        z_threshold=z_threshold,
        status=status,
    )

    return {
        "fund_a": fund_a,
        "fund_b": fund_b,
        "price_a": price_a,
        "price_b": price_b,
        "spread_pct": price_spread,
        "premium_a": premium_a,
        "premium_b": premium_b,
        "premium_spread_pct": (
            round(current_spread, 4) if current_spread is not None else None
        ),
        "window_days": window_days,
        "sample_count": n,
        "min_sample_count": min_samples,
        "min_samples_met": min_samples_met,
        "mean": mean,
        "std": std,
        "percentile": percentile,
        "z_score": z_score,
        "z_threshold": z_threshold,
        "status": status,
        "pair_signal": signal,
    }


def _pair_signal(
    *,
    fund_a: str,
    fund_b: str,
    z_score: float | None,
    premium_a: float | None,
    premium_b: float | None,
    z_threshold: float,
    status: str,
) -> dict[str, Any]:
    base = {
        "active": False,
        "side": None,
        "long": None,
        "short": None,
        "abs_z": None,
        "label_fa": "بدون سیگنال جفتی",
        "detail_fa": "اسپرد حباب نسبت به تاریخچهٔ جفت در محدودهٔ معمول است.",
    }
    if status != "ok" or z_score is None:
        if status == "insufficient_samples":
            base["label_fa"] = "داده ناکافی"
            base["detail_fa"] = "نمونهٔ هم‌پوشان برای z-score جفت کافی نیست."
        elif status == "zero_variance":
            base["label_fa"] = "بدون پراکندگی"
            base["detail_fa"] = "اسپرد حباب در پنجره تقریباً ثابت بوده است."
        return base

    abs_z = abs(z_score)
    base["abs_z"] = round(abs_z, 2)
    if abs_z < z_threshold:
        return base

    if z_score >= z_threshold:
        long_sym, short_sym = fund_b, fund_a
        side = "long_b_short_a"
    else:
        long_sym, short_sym = fund_a, fund_b
        side = "long_a_short_b"

    return {
        "active": True,
        "side": side,
        "long": long_sym,
        "short": short_sym,
        "abs_z": round(abs_z, 2),
        "label_fa": "فرصت نسبی",
        "detail_fa": (
            f"خرید {long_sym} / فروش {short_sym} "
            f"(z={z_score:+.2f}، آستانه ±{z_threshold:g})"
        ),
        "premium_long": premium_a if long_sym == fund_a else premium_b,
        "premium_short": premium_a if short_sym == fund_a else premium_b,
    }
