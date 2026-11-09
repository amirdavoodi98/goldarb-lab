"""Pure signal math ported from gold-arbitrage Lab templates."""

from .bubble_rank import (
    compute_rankings,
    compute_symbol_score,
    empty_bubble_rank,
    evaluate_rankings,
)
from .pair_spread import compute_pair_spread_stats, evaluate_pair_spread
from .results import PairSignalResult, PairSpreadResult, RankingPair, RankingResult, SymbolRanking
from .stats import premium_from_row, sample_mean_std

__all__ = [
    "PairSignalResult",
    "PairSpreadResult",
    "RankingPair",
    "RankingResult",
    "SymbolRanking",
    "evaluate_pair_spread",
    "evaluate_rankings",
    "compute_pair_spread_stats",
    "compute_rankings",
    "compute_symbol_score",
    "empty_bubble_rank",
    "premium_from_row",
    "sample_mean_std",
]
