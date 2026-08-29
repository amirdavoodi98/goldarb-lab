"""Gold Arbitrage strategy-lab Python client."""

from .client import LabClient
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .premium_threshold import PremiumThresholdResult, run_premium_threshold
from .strategies import BubbleRankStrategy, MaBandStrategy, PairZScoreStrategy
from .strategy import Strategy, StrategyContext

__all__ = [
    "BacktestEngine",
    "BubbleRankStrategy",
    "LabClient",
    "LiveSimulationEngine",
    "MaBandStrategy",
    "PairZScoreStrategy",
    "PremiumThresholdResult",
    "RunConfig",
    "RunResult",
    "Strategy",
    "StrategyContext",
    "run_premium_threshold",
]
__version__ = "0.8.0"
