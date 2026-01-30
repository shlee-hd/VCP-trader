"""VCP Trader Trading Package

Lazy import 방식으로 OrderExecutor는 실제 사용 시점에 로드
(DB 의존성 회피)
"""

from .stop_loss import StopLossManager, StopLossLevel, TrailingStopResult
from .risk_manager import RiskManager, PositionSizeResult

# OrderExecutor는 lazy import (DB 의존성이 있음)
def __getattr__(name):
    if name == "OrderExecutor":
        from .order_executor import OrderExecutor
        return OrderExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "StopLossManager",
    "StopLossLevel",
    "TrailingStopResult",
    "RiskManager",
    "PositionSizeResult",
    "OrderExecutor",
]
