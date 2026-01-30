"""
Stop Loss Manager

다층 손절 및 트레일링 스탑 시스템을 관리합니다.
수익 구간에서 급락에 당하지 않도록 동적으로 손절가를 조정합니다.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from loguru import logger

from ..core.config import settings


class StopType(str, Enum):
    """손절 유형"""
    INITIAL = "initial"           # 초기 손절
    BREAKEVEN = "breakeven"       # 본전 손절
    TRAILING = "trailing"         # 트레일링 손절
    TIME = "time"                 # 시간 손절
    VOLATILITY = "volatility"     # 변동성 기반 손절


@dataclass
class StopLossLevel:
    """손절 레벨 정보"""
    level: int                    # 레벨 번호 (0=초기, 1=첫번째 트레일링, ...)
    stop_type: StopType
    profit_threshold: float       # 이 수익률 도달 시 활성화 (%)
    trail_percent: float          # 고점 대비 손절 비율 (%)
    description: str
    
    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "stop_type": self.stop_type.value,
            "profit_threshold": self.profit_threshold,
            "trail_percent": self.trail_percent,
            "description": self.description,
        }


@dataclass
class TrailingStopResult:
    """트레일링 스탑 계산 결과"""
    symbol: str
    entry_price: float
    current_price: float
    highest_price: float
    
    # 손익 상태
    profit_pct: float             # 현재 수익률 (%)
    profit_from_high: float       # 고점 대비 하락률 (%)
    
    # 손절 정보
    current_level: int            # 현재 트레일링 레벨
    stop_price: float             # 현재 손절가
    stop_distance_pct: float      # 현재가 대비 손절가까지 거리 (%)
    
    # 상태
    should_exit: bool             # 청산 필요 여부
    exit_reason: Optional[str]    # 청산 사유
    
    # 다음 레벨 정보
    next_level_profit: Optional[float]  # 다음 레벨 도달 필요 수익률
    next_level_trail: Optional[float]   # 다음 레벨 트레일 비율
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "highest_price": self.highest_price,
            "profit_pct": self.profit_pct,
            "profit_from_high": self.profit_from_high,
            "current_level": self.current_level,
            "stop_price": self.stop_price,
            "stop_distance_pct": self.stop_distance_pct,
            "should_exit": self.should_exit,
            "exit_reason": self.exit_reason,
        }


class StopLossManager:
    """
    다층 손절 및 트레일링 스탑 관리자
    
    손절 전략 레벨:
    - Level 0 (Initial): 진입가 대비 -7% 손절
    - Level 1 (Breakeven): 수익 10% 도달 시 본전 손절로 이동
    - Level 2 (Trailing 1): 수익 5% 이상 시, 고점 대비 -5% 트레일링
    - Level 3 (Trailing 2): 수익 10% 이상 시, 고점 대비 -8% 트레일링
    - Level 4 (Trailing 3): 수익 20% 이상 시, 고점 대비 -10% 트레일링
    - Level 5 (Trailing 4): 수익 50% 이상 시, 고점 대비 -15% 트레일링
    
    핵심 원칙:
    1. 손절가는 절대로 하향 조정하지 않음 (only up)
    2. 고점 갱신 시 자동으로 손절가 상향
    3. 급락 시 감정 개입 없이 즉시 청산
    
    Usage:
        >>> manager = StopLossManager()
        >>> result = manager.calculate_stop(
        ...     entry_price=10000,
        ...     current_price=11500,
        ...     highest_price=12000,
        ...     current_level=2,
        ... )
        >>> if result.should_exit:
        ...     print(f"Exit signal! Reason: {result.exit_reason}")
    """
    
    def __init__(
        self,
        initial_stop_pct: float = None,
        trailing_levels: list[dict] = None,
        use_breakeven: bool = True,
        breakeven_profit_threshold: float = 10.0,
    ):
        """
        Args:
            initial_stop_pct: 초기 손절 비율 (%)
            trailing_levels: 트레일링 레벨 설정 리스트
            use_breakeven: 본전 손절 사용 여부
            breakeven_profit_threshold: 본전 손절 활성화 수익률 (%)
        """
        self.initial_stop_pct = initial_stop_pct or settings.initial_stop_loss
        self.trailing_levels = trailing_levels or settings.trailing_stop_levels
        self.use_breakeven = use_breakeven
        self.breakeven_profit_threshold = breakeven_profit_threshold
        
        # 손절 레벨 생성
        self.levels = self._build_levels()
        
        logger.info(
            f"StopLossManager initialized: initial={self.initial_stop_pct}%, "
            f"levels={len(self.levels)}"
        )
    
    def _build_levels(self) -> list[StopLossLevel]:
        """손절 레벨들을 구성합니다."""
        levels = []
        
        # Level 0: 초기 손절
        levels.append(StopLossLevel(
            level=0,
            stop_type=StopType.INITIAL,
            profit_threshold=-100.0,  # 항상 활성
            trail_percent=self.initial_stop_pct,
            description=f"초기 손절 (진입가 -{self.initial_stop_pct}%)",
        ))
        
        # 트레일링 레벨들 추가
        for i, level_config in enumerate(self.trailing_levels):
            levels.append(StopLossLevel(
                level=i + 1,
                stop_type=StopType.TRAILING,
                profit_threshold=level_config["profit_threshold"],
                trail_percent=level_config["trail_percent"],
                description=f"트레일링 L{i+1} (수익 {level_config['profit_threshold']}%+ → 고점 -{level_config['trail_percent']}%)",
            ))
        
        return levels
    
    def get_current_level(
        self,
        entry_price: float,
        highest_price: float,
    ) -> int:
        """현재 적용되어야 하는 트레일링 레벨을 반환합니다."""
        profit_pct = ((highest_price - entry_price) / entry_price) * 100
        
        current_level = 0
        for level in self.levels:
            if profit_pct >= level.profit_threshold:
                current_level = level.level
        
        return current_level
    
    def calculate_stop_price(
        self,
        entry_price: float,
        highest_price: float,
        current_level: int = None,
    ) -> float:
        """현재 손절가를 계산합니다."""
        if current_level is None:
            current_level = self.get_current_level(entry_price, highest_price)
        
        level_info = self.levels[current_level] if current_level < len(self.levels) else self.levels[-1]
        
        if level_info.stop_type == StopType.INITIAL:
            # 초기 손절: 진입가 기준
            stop_price = entry_price * (1 - level_info.trail_percent / 100)
        else:
            # 트레일링: 고점 기준
            stop_price = highest_price * (1 - level_info.trail_percent / 100)
        
        # 본전 손절 체크
        if self.use_breakeven:
            profit_pct = ((highest_price - entry_price) / entry_price) * 100
            if profit_pct >= self.breakeven_profit_threshold:
                # 손절가는 최소한 본전 이상
                stop_price = max(stop_price, entry_price * 1.001)  # 0.1% 마진
        
        return stop_price
    
    def calculate_stop(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
        highest_price: float,
        current_level: int = 0,
    ) -> TrailingStopResult:
        """
        현재 상태에서 트레일링 스탑을 계산합니다.
        
        Args:
            symbol: 종목 코드
            entry_price: 진입 가격
            current_price: 현재 가격
            highest_price: 진입 후 최고가
            current_level: 현재 트레일링 레벨 (저장된 값)
        
        Returns:
            TrailingStopResult: 계산 결과
        """
        # 고점 업데이트
        highest_price = max(highest_price, current_price)
        
        # 현재 적용 가능한 레벨 계산
        new_level = self.get_current_level(entry_price, highest_price)
        
        # 레벨은 상향만 가능
        actual_level = max(current_level, new_level)
        
        # 손절가 계산
        stop_price = self.calculate_stop_price(entry_price, highest_price, actual_level)
        
        # 이전 레벨의 손절가도 계산하여 더 높은 값 사용 (손절가 하향 방지)
        if current_level > 0:
            prev_stop = self.calculate_stop_price(entry_price, highest_price, current_level)
            stop_price = max(stop_price, prev_stop)
        
        # 수익률 계산
        profit_pct = ((current_price - entry_price) / entry_price) * 100
        profit_from_high = ((current_price - highest_price) / highest_price) * 100
        
        # 청산 여부 판단
        should_exit = current_price <= stop_price
        exit_reason = None
        if should_exit:
            if profit_pct < 0:
                exit_reason = f"손절 (Level {actual_level}: -{abs(profit_pct):.1f}%)"
            else:
                exit_reason = f"트레일링 스탑 (Level {actual_level}: 고점 대비 {profit_from_high:.1f}%)"
        
        # 손절가까지 거리
        stop_distance_pct = ((current_price - stop_price) / current_price) * 100
        
        # 다음 레벨 정보
        next_level_profit = None
        next_level_trail = None
        if actual_level < len(self.levels) - 1:
            next_level = self.levels[actual_level + 1]
            next_level_profit = next_level.profit_threshold
            next_level_trail = next_level.trail_percent
        
        result = TrailingStopResult(
            symbol=symbol,
            entry_price=entry_price,
            current_price=current_price,
            highest_price=highest_price,
            profit_pct=profit_pct,
            profit_from_high=profit_from_high,
            current_level=actual_level,
            stop_price=stop_price,
            stop_distance_pct=stop_distance_pct,
            should_exit=should_exit,
            exit_reason=exit_reason,
            next_level_profit=next_level_profit,
            next_level_trail=next_level_trail,
        )
        
        if should_exit:
            logger.warning(
                f"{symbol}: EXIT SIGNAL - {exit_reason}, "
                f"current={current_price:.0f}, stop={stop_price:.0f}"
            )
        else:
            logger.debug(
                f"{symbol}: Level {actual_level}, profit={profit_pct:.1f}%, "
                f"stop={stop_price:.0f}, distance={stop_distance_pct:.1f}%"
            )
        
        return result
    
    def get_level_info(self, level: int) -> Optional[StopLossLevel]:
        """특정 레벨의 정보를 반환합니다."""
        if 0 <= level < len(self.levels):
            return self.levels[level]
        return None
    
    def get_all_levels(self) -> list[StopLossLevel]:
        """모든 레벨 정보를 반환합니다."""
        return self.levels
    
    def simulate_trailing(
        self,
        entry_price: float,
        price_series: list[float],
    ) -> list[TrailingStopResult]:
        """
        가격 시리즈에 대해 트레일링 스탑을 시뮬레이션합니다.
        
        Args:
            entry_price: 진입 가격
            price_series: 가격 리스트 (시간순)
        
        Returns:
            각 시점의 TrailingStopResult 리스트
        """
        results = []
        highest_price = entry_price
        current_level = 0
        
        for i, price in enumerate(price_series):
            result = self.calculate_stop(
                symbol="SIM",
                entry_price=entry_price,
                current_price=price,
                highest_price=highest_price,
                current_level=current_level,
            )
            results.append(result)
            
            # 상태 업데이트
            highest_price = result.highest_price
            current_level = result.current_level
            
            # 청산 시 중단
            if result.should_exit:
                break
        
        return results
