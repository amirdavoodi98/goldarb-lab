"""Gold Arbitrage strategy-lab Python client."""

from .archive import (
    JsonlDatasetStore,
    ParquetDatasetStore,
    dataset_store,
    download_symbol_bars,
    read_symbol_bars,
)
from .client import LabClient
from .config import AppConfig
from .engine import BacktestEngine, LiveSimulationEngine, RunConfig, RunResult
from .pipelines import iran_session_live, month_backtest, offline_backtest
from .premium_threshold import PremiumThresholdResult, run_premium_threshold
from .runtime import StrategyRunner
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
    "Strategy",
    "StrategyContext",
    "StrategyRunner",
    "dataset_store",
    "download_symbol_bars",
    "iran_session_live",
    "month_backtest",
    "offline_backtest",
    "read_symbol_bars",
    "run_premium_threshold",
]
__version__ = "0.8.0"
