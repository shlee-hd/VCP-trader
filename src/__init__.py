"""VCP Trader - Package Init"""

from .core.config import settings, Settings
from .patterns import TrendTemplate, VCPDetector, RSCalculator
from .trading import StopLossManager, RiskManager, OrderExecutor

__version__ = "0.1.0"
__all__ = [
    "settings",
    "Settings",
    "TrendTemplate",
    "VCPDetector",
    "RSCalculator",
    "StopLossManager",
    "RiskManager",
    "OrderExecutor",
]
