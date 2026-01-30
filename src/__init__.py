"""VCP Trader - Package Init

Lazy import 방식으로 변경하여 DB 의존성 없이 백테스팅 모듈 사용 가능
"""

__version__ = "0.1.0"

# Lazy imports - 실제 사용 시점에 로드됨
def __getattr__(name):
    """Lazy import를 위한 __getattr__ 구현"""
    if name == "settings":
        from .core.config import settings
        return settings
    elif name == "Settings":
        from .core.config import Settings
        return Settings
    elif name == "TrendTemplate":
        from .patterns.trend_template import TrendTemplate
        return TrendTemplate
    elif name == "VCPDetector":
        from .patterns.vcp_detector import VCPDetector
        return VCPDetector
    elif name == "RSCalculator":
        from .patterns.rs_calculator import RSCalculator
        return RSCalculator
    elif name == "StopLossManager":
        from .trading.stop_loss import StopLossManager
        return StopLossManager
    elif name == "RiskManager":
        from .trading.risk_manager import RiskManager
        return RiskManager
    elif name == "OrderExecutor":
        from .trading.order_executor import OrderExecutor
        return OrderExecutor
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
