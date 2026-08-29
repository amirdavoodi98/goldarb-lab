"""Gold Arbitrage strategy-lab Python client."""

from .client import LabClient
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .pipelines import iran_session_live, month_backtest
from .premium_threshold import PremiumThresholdResult, run_premium_threshold
from .strategies import BubbleRankStrategy, MaBandStrategy, PairZScoreStrategy
from .strategy import Strategy, StrategyContext
from .universe import GOLD_FUND_SYMBOLS, GOLD_FUNDS

__all__ = [
    "BacktestEngine",
    "BubbleRankStrategy",
    "GOLD_FUND_SYMBOLS",
    "GOLD_FUNDS",
    "LabClient",
    "LiveSimulationEngine",
    "MaBandStrategy",
    "PairZScoreStrategy",
    "PremiumThresholdResult",
    "RunConfig",
    "RunResult",
    "Strategy",
    "StrategyContext",
    "iran_session_live",
    "month_backtest",
    "run_premium_threshold",
]
__version__ = "0.8.0"
