"""Built-in sample strategies."""

from .bubble_rank import BubbleRankStrategy
from .bubble_sign import BubbleSignStrategy
from .ma_band import MaBandSignal, MaBandStrategy, MaBandTick, ma_band_side
from .pair_zscore import PairZScoreStrategy
from .price_momentum import PriceMomentumStrategy

__all__ = [
    "BubbleRankStrategy",
    "BubbleSignStrategy",
    "MaBandSignal",
    "MaBandStrategy",
    "MaBandTick",
    "PairZScoreStrategy",
    "PriceMomentumStrategy",
    "ma_band_side",
]
