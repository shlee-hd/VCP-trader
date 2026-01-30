"""
Risk Manager

포지션 사이징과 전체 포트폴리오 리스크를 관리합니다.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from loguru import logger

from ..core.config import settings


@dataclass
class PositionSizeResult:
    """포지션 사이징 결과"""
    symbol: str
    
    # 계산 입력값
    account_value: float          # 계좌 총 자산
    entry_price: float            # 진입 예정 가격
    stop_price: float             # 손절 가격
    
    # 계산 결과
    risk_amount: float            # 거래당 리스크 금액
    risk_per_share: float         # 주당 리스크 (진입가 - 손절가)
    risk_percent: float           # 리스크 비율 (%)
    
    position_size: int            # 권장 주식 수
    position_value: float         # 포지션 금액
    position_percent: float       # 포트폴리오 대비 비중 (%)
    
    # 제약 조건 적용 여부
    size_limited_by: Optional[str] = None  # 제한 사유
    original_size: int = 0                 # 제한 전 원래 수량
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "entry_price": self.entry_price,
            "stop_price": self.stop_price,
            "risk_amount": self.risk_amount,
            "risk_per_share": self.risk_per_share,
            "risk_percent": self.risk_percent,
            "position_size": self.position_size,
            "position_value": self.position_value,
            "position_percent": self.position_percent,
            "size_limited_by": self.size_limited_by,
        }


@dataclass 
class PortfolioRiskResult:
    """포트폴리오 리스크 분석 결과"""
    total_value: float             # 총 자산
    invested_value: float          # 투자 금액
    cash_value: float              # 현금
    
    num_positions: int             # 포지션 수
    total_risk_amount: float       # 전체 리스크 금액
    total_risk_percent: float      # 전체 리스크 비율
    
    largest_position_pct: float    # 최대 포지션 비중
    sector_concentrations: dict    # 섹터별 집중도
    
    # 여유 공간
    can_add_position: bool         # 추가 포지션 가능 여부
    available_risk_amount: float   # 추가 가능 리스크 금액


class RiskManager:
    """
    리스크 관리자
    
    핵심 원칙:
    1. 단일 거래 리스크 제한: 총 자본의 1-2%
    2. 포지션 수 제한: 최대 8-10개
    3. 섹터 집중도 제한: 단일 섹터 30% 이하
    4. 전체 시장 노출: 최대 100% (레버리지 없음)
    
    포지션 사이징 공식:
        Position Size = (Account Value × Risk %) / (Entry Price - Stop Price)
    
    Usage:
        >>> risk_mgr = RiskManager()
        >>> size = risk_mgr.calculate_position_size(
        ...     symbol="005930",
        ...     account_value=100_000_000,
        ...     entry_price=70000,
        ...     stop_price=65100,  # -7%
        ... )
        >>> print(f"Recommended size: {size.position_size} shares")
    """
    
    def __init__(
        self,
        max_risk_per_trade: float = None,
        max_positions: int = None,
        max_sector_concentration: float = None,
        max_single_position_pct: float = 15.0,
        max_portfolio_exposure: float = 100.0,
        min_position_value: float = 1_000_000,  # 최소 100만원
    ):
        """
        Args:
            max_risk_per_trade: 거래당 최대 리스크 (%)
            max_positions: 최대 동시 보유 포지션 수
            max_sector_concentration: 단일 섹터 최대 비중 (%)
            max_single_position_pct: 단일 포지션 최대 비중 (%)
            max_portfolio_exposure: 최대 투자 비율 (%)
            min_position_value: 최소 포지션 금액
        """
        self.max_risk_per_trade = (max_risk_per_trade or settings.max_risk_per_trade) / 100
        self.max_positions = max_positions or settings.max_positions
        self.max_sector_concentration = (max_sector_concentration or settings.max_sector_concentration) / 100
        self.max_single_position_pct = max_single_position_pct / 100
        self.max_portfolio_exposure = max_portfolio_exposure / 100
        self.min_position_value = min_position_value
        
        logger.info(
            f"RiskManager initialized: max_risk={self.max_risk_per_trade*100:.1f}%, "
            f"max_positions={self.max_positions}, "
            f"max_sector={self.max_sector_concentration*100:.0f}%"
        )
    
    def calculate_position_size(
        self,
        symbol: str,
        account_value: float,
        entry_price: float,
        stop_price: float,
        current_positions: int = 0,
        current_exposure: float = 0.0,
        sector: Optional[str] = None,
        sector_exposure: float = 0.0,
        lot_size: int = 1,  # 최소 거래 단위
    ) -> PositionSizeResult:
        """
        포지션 사이즈를 계산합니다.
        
        Args:
            symbol: 종목 코드
            account_value: 계좌 총 자산
            entry_price: 진입 예정 가격
            stop_price: 손절 가격
            current_positions: 현재 보유 포지션 수
            current_exposure: 현재 투자 비율
            sector: 종목의 섹터
            sector_exposure: 해당 섹터의 현재 비중
            lot_size: 최소 거래 단위 (한국 주식은 1)
        
        Returns:
            PositionSizeResult: 포지션 사이징 결과
        """
        # 기본 계산
        risk_per_share = abs(entry_price - stop_price)
        risk_percent = risk_per_share / entry_price
        risk_amount = account_value * self.max_risk_per_trade
        
        # 포지션 사이즈 계산 (리스크 기반)
        if risk_per_share > 0:
            position_size = int(risk_amount / risk_per_share)
        else:
            position_size = 0
        
        original_size = position_size
        size_limited_by = None
        
        # 제약 조건 1: 최대 포지션 수
        if current_positions >= self.max_positions:
            position_size = 0
            size_limited_by = f"최대 포지션 수 초과 ({current_positions}/{self.max_positions})"
        
        # 제약 조건 2: 단일 포지션 최대 비중
        max_position_value = account_value * self.max_single_position_pct
        if position_size * entry_price > max_position_value:
            position_size = int(max_position_value / entry_price)
            if size_limited_by is None:
                size_limited_by = f"단일 포지션 비중 제한 ({self.max_single_position_pct*100:.0f}%)"
        
        # 제약 조건 3: 전체 노출 제한
        available_exposure = self.max_portfolio_exposure - current_exposure
        if available_exposure <= 0:
            position_size = 0
            size_limited_by = f"총 투자 비율 초과 ({current_exposure*100:.0f}%)"
        else:
            max_from_exposure = int(account_value * available_exposure / entry_price)
            if position_size > max_from_exposure:
                position_size = max_from_exposure
                if size_limited_by is None:
                    size_limited_by = f"총 투자 비율 제한 ({self.max_portfolio_exposure*100:.0f}%)"
        
        # 제약 조건 4: 섹터 집중도 제한
        if sector:
            available_sector = self.max_sector_concentration - sector_exposure
            if available_sector <= 0:
                position_size = 0
                size_limited_by = f"섹터 집중도 초과 ({sector}: {sector_exposure*100:.0f}%)"
            else:
                max_from_sector = int(account_value * available_sector / entry_price)
                if position_size > max_from_sector:
                    position_size = max_from_sector
                    if size_limited_by is None:
                        size_limited_by = f"섹터 집중도 제한 ({sector}: {self.max_sector_concentration*100:.0f}%)"
        
        # 최소 포지션 금액 체크
        if position_size * entry_price < self.min_position_value:
            position_size = 0
            size_limited_by = f"최소 포지션 금액 미달 ({self.min_position_value:,.0f}원)"
        
        # Lot size 적용
        position_size = (position_size // lot_size) * lot_size
        
        # 결과 계산
        position_value = position_size * entry_price
        position_percent = position_value / account_value if account_value > 0 else 0
        
        result = PositionSizeResult(
            symbol=symbol,
            account_value=account_value,
            entry_price=entry_price,
            stop_price=stop_price,
            risk_amount=risk_amount,
            risk_per_share=risk_per_share,
            risk_percent=risk_percent * 100,
            position_size=position_size,
            position_value=position_value,
            position_percent=position_percent * 100,
            size_limited_by=size_limited_by,
            original_size=original_size,
        )
        
        logger.debug(
            f"{symbol}: position_size={position_size}, value={position_value:,.0f}, "
            f"risk={risk_amount:,.0f}, limited_by={size_limited_by}"
        )
        
        return result
    
    def calculate_portfolio_risk(
        self,
        account_value: float,
        positions: list[dict],  # [{symbol, entry_price, current_price, stop_price, quantity, sector}]
    ) -> PortfolioRiskResult:
        """
        포트폴리오 전체 리스크를 분석합니다.
        
        Args:
            account_value: 계좌 총 자산
            positions: 보유 포지션 리스트
        
        Returns:
            PortfolioRiskResult: 포트폴리오 리스크 분석 결과
        """
        invested_value = 0.0
        total_risk_amount = 0.0
        sector_values = {}
        largest_position_value = 0.0
        
        for pos in positions:
            position_value = pos["current_price"] * pos["quantity"]
            invested_value += position_value
            
            # 포지션별 리스크 금액
            risk_per_share = abs(pos["current_price"] - pos["stop_price"])
            position_risk = risk_per_share * pos["quantity"]
            total_risk_amount += position_risk
            
            # 섹터별 집계
            sector = pos.get("sector", "Unknown")
            sector_values[sector] = sector_values.get(sector, 0) + position_value
            
            # 최대 포지션 추적
            if position_value > largest_position_value:
                largest_position_value = position_value
        
        cash_value = account_value - invested_value
        total_risk_percent = (total_risk_amount / account_value * 100) if account_value > 0 else 0
        largest_position_pct = (largest_position_value / account_value * 100) if account_value > 0 else 0
        
        # 섹터별 집중도
        sector_concentrations = {
            sector: value / account_value * 100
            for sector, value in sector_values.items()
        }
        
        # 추가 포지션 가능 여부
        can_add_position = (
            len(positions) < self.max_positions and
            invested_value / account_value < self.max_portfolio_exposure
        )
        
        # 추가 가능 리스크 금액
        max_total_risk = account_value * self.max_risk_per_trade * self.max_positions
        available_risk_amount = max(0, max_total_risk - total_risk_amount)
        
        return PortfolioRiskResult(
            total_value=account_value,
            invested_value=invested_value,
            cash_value=cash_value,
            num_positions=len(positions),
            total_risk_amount=total_risk_amount,
            total_risk_percent=total_risk_percent,
            largest_position_pct=largest_position_pct,
            sector_concentrations=sector_concentrations,
            can_add_position=can_add_position,
            available_risk_amount=available_risk_amount,
        )
    
    def validate_trade(
        self,
        symbol: str,
        entry_price: float,
        stop_price: float,
        quantity: int,
        account_value: float,
        current_positions: int = 0,
    ) -> tuple[bool, str]:
        """
        거래가 리스크 규칙을 준수하는지 검증합니다.
        
        Returns:
            (valid, message): 유효 여부와 메시지
        """
        # 리스크 비율 체크
        risk_per_share = abs(entry_price - stop_price)
        total_risk = risk_per_share * quantity
        risk_percent = total_risk / account_value
        
        if risk_percent > self.max_risk_per_trade:
            return False, f"리스크 초과: {risk_percent*100:.1f}% > {self.max_risk_per_trade*100:.1f}%"
        
        # 포지션 수 체크
        if current_positions >= self.max_positions:
            return False, f"최대 포지션 수 도달: {current_positions}/{self.max_positions}"
        
        # 포지션 크기 체크
        position_value = entry_price * quantity
        position_pct = position_value / account_value
        
        if position_pct > self.max_single_position_pct:
            return False, f"포지션 비중 초과: {position_pct*100:.1f}% > {self.max_single_position_pct*100:.1f}%"
        
        return True, "OK"
    
    def get_r_multiple(
        self,
        entry_price: float,
        exit_price: float,
        stop_price: float,
    ) -> float:
        """
        R 배수를 계산합니다.
        
        R = (Exit - Entry) / (Entry - Stop)
        R > 0: 수익
        R < 0: 손실
        R = 1: 초기 리스크만큼 수익
        R = -1: 손절
        
        Args:
            entry_price: 진입 가격
            exit_price: 청산 가격
            stop_price: 손절 가격
        
        Returns:
            R 배수
        """
        initial_risk = abs(entry_price - stop_price)
        if initial_risk == 0:
            return 0.0
        
        profit = exit_price - entry_price
        return profit / initial_risk
