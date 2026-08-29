"""Gold Arbitrage strategy-lab Python client."""

from .client import LabClient
from .premium_threshold import PremiumThresholdResult, run_premium_threshold

__all__ = [
    "LabClient",
    "PremiumThresholdResult",
    "run_premium_threshold",
]
__version__ = "0.7.0"
