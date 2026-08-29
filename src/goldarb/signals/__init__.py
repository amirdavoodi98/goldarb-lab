"""Pure signal math ported from gold-arbitrage Lab templates."""

from .bubble_rank import compute_rankings, compute_symbol_score, empty_bubble_rank
from .pair_spread import compute_pair_spread_stats
from .stats import premium_from_row, sample_mean_std

__all__ = [
    "compute_pair_spread_stats",
    "compute_rankings",
    "compute_symbol_score",
    "empty_bubble_rank",
    "premium_from_row",
    "sample_mean_std",
]
