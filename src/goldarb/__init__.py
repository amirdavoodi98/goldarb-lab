"""Gold Arbitrage strategy-lab Python client."""

from .archive import (
    JsonlDatasetStore,
    ParquetDatasetStore,
    dataset_store,
    download_symbol_bars,
    read_symbol_bars,
)
from .client import LabClient
from .config import AppConfig, AppConfigBuilder
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .pipelines import iran_session_live, month_backtest, offline_backtest
from .premium_threshold import PremiumThresholdResult, run_premium_threshold
from .runtime import STRATEGY_REGISTRY, StrategyRunner, build_strategy
from .sources import (
    ArchiveDatasetSource,
    GoldArbApiSource,
    HistoricalDatasetSource,
)
from .strategies import (
    BubbleRankStrategy,
    BubbleSignStrategy,
    MaBandStrategy,
    PairZScoreStrategy,
    PriceMomentumStrategy,
)
from .strategy import Strategy, StrategyContext
from .universe import GOLD_FUND_SYMBOLS, GOLD_FUNDS

__all__ = [
    "BacktestEngine",
    "AppConfig",
    "AppConfigBuilder",
    "ArchiveDatasetSource",
    "BubbleRankStrategy",
    "BubbleSignStrategy",
    "GOLD_FUND_SYMBOLS",
    "GOLD_FUNDS",
    "LabClient",
    "GoldArbApiSource",
    "HistoricalDatasetSource",
    "JsonlDatasetStore",
    "LiveSimulationEngine",
    "MaBandStrategy",
    "PairZScoreStrategy",
    "PremiumThresholdResult",
    "PriceMomentumStrategy",
    "ParquetDatasetStore",
    "RunConfig",
    "RunResult",
    "STRATEGY_REGISTRY",
    "Strategy",
    "StrategyContext",
    "StrategyRunner",
    "build_strategy",
    "dataset_store",
    "download_symbol_bars",
    "iran_session_live",
    "month_backtest",
    "offline_backtest",
    "read_symbol_bars",
    "run_premium_threshold",
]
__version__ = "0.8.0"
