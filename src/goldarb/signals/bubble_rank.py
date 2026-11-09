"""F-22 bubble-rank: cheapness score = window mean − current premium."""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from .models import BubbleRanking, SymbolScore
from .results import RankingPair, RankingResult, SymbolRanking

BUBBLE_RANK_WINDOW_DAYS = 20
BUBBLE_RANK_MIN_SAMPLES = 10
BUBBLE_RANK_MIN_GAP = 1.0


def empty_bubble_rank(
    *,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
) -> BubbleRanking:
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
) -> SymbolScore:
    values = list(series) if series else []
    n = len(values)
    current = round(values[-1], 4) if values else None

    if n < min_samples or current is None:
        return {
            "current": current,
            "avg20": None,
            "score": None,
            "sample_count": n,
            "window_days": window_days,
            "status": "insufficient_samples",
        }

    avg20 = round(statistics.fmean(values), 4)
    score = round(avg20 - current, 4)
    return {
        "current": current,
        "avg20": avg20,
        "score": score,
        "sample_count": n,
        "window_days": window_days,
        "status": "ok",
    }


@dataclass(frozen=True)
class _ScoredSymbol:
    """Validated candidate: ranking arithmetic always has a numeric score."""

    symbol: str
    score: float


def evaluate_rankings(
    by_symbol: dict[str, list[float]],
    *,
    min_samples: int = BUBBLE_RANK_MIN_SAMPLES,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
    min_gap: float = BUBBLE_RANK_MIN_GAP,
) -> RankingResult:
    """Evaluate rankings as immutable domain objects."""
    rankings: list[SymbolRanking] = []
    for symbol, series in by_symbol.items():
        row = compute_symbol_score(
            series,
            min_samples=min_samples,
            window_days=window_days,
        )
        rankings.append(SymbolRanking(symbol=symbol, **row))

    rankings.sort(
        key=lambda row: (
            0 if row.status == "ok" else 1,
            -(row.score if row.score is not None else float("-inf")),
            row.symbol or "",
        )
    )

    ok = [
        _ScoredSymbol(row.symbol, score)
        for row in rankings
        if row.status == "ok" and (score := row.score) is not None
    ]
    best_pair: RankingPair | None = None
    if len(ok) >= 2:
        long_row = max(ok, key=lambda row: (row.score, row.symbol or ""))
        short_row = min(ok, key=lambda row: (row.score, row.symbol or ""))
        if long_row.symbol != short_row.symbol:
            gap = round(long_row.score - short_row.score, 4)
            active = gap >= min_gap
            best_pair = RankingPair(
                active=active,
                long_symbol=long_row.symbol,
                short_symbol=short_row.symbol,
                long_score=long_row.score,
                short_score=short_row.score,
                gap=gap,
                label_fa=(
                    f"خرید {long_row.symbol} / فروش {short_row.symbol}"
                    if active
                    else "بدون سیگنال جفتی"
                ),
            )

    return RankingResult(window_days, tuple(rankings), best_pair)


def compute_rankings(
    by_symbol: dict[str, list[float]],
    *,
    min_samples: int = BUBBLE_RANK_MIN_SAMPLES,
    window_days: int = BUBBLE_RANK_WINDOW_DAYS,
    min_gap: float = BUBBLE_RANK_MIN_GAP,
) -> BubbleRanking:
    """Backward-compatible dictionary API; domain consumers use evaluate_rankings."""
    return evaluate_rankings(
        by_symbol, min_samples=min_samples, window_days=window_days, min_gap=min_gap
    ).to_dict()
