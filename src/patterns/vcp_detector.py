"""
VCP (Volatility Contraction Pattern) Detector

마크 미너비니의 VCP 패턴을 자동으로 탐지합니다.

VCP 패턴의 핵심:
1. 변동성 수축 (Volatility Contraction): 가격 변동폭이 점점 줄어듦
2. 거래량 감소 (Volume Dry-Up): 조정 시 거래량이 줄어듦
3. 피벗 포인트 (Pivot Point): 명확한 돌파 기준점
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from ..core.config import settings


@dataclass
class Contraction:
    """개별 수축 구간"""
    start_date: datetime
    end_date: datetime
    high_price: float
    low_price: float
    depth_pct: float          # 수축 깊이 (%)
    duration_days: int
    avg_volume: float
    volume_ratio: float       # 평균 대비 거래량 비율


@dataclass
class VCPPattern:
    """VCP 패턴 탐지 결과"""
    
    symbol: str
    detected: bool                    # 패턴 탐지 여부
    score: int                        # 패턴 점수 (0-100)
    
    # 패턴 상세
    pivot_price: float = 0.0          # 피벗 포인트 (돌파 기준가)
    base_low: float = 0.0             # 베이스 저점
    pattern_depth_pct: float = 0.0    # 전체 패턴 깊이 (%)
    
    # 수축 정보
    num_contractions: int = 0         # 수축 횟수
    contractions: list[Contraction] = field(default_factory=list)
    
    # 거래량 분석
    volume_dry_up: bool = False       # 거래량 감소 여부
    avg_volume_ratio: float = 1.0     # 평균 거래량 비율
    
    # 타이트닝 분석
    tightening_quality: str = "none"  # excellent, good, fair, poor, none
    last_contraction_tight: bool = False  # 마지막 수축이 타이트한가
    
    # 추가 정보
    pattern_start_date: Optional[datetime] = None
    pattern_end_date: Optional[datetime] = None
    days_since_breakout_zone: int = 0
    
    # 진입 관련
    ideal_buy_point: float = 0.0      # 이상적 매수 가격
    stop_loss_price: float = 0.0      # 권장 손절가
    risk_reward_ratio: float = 0.0    # 리스크/리워드 비율
    
    message: str = ""
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "symbol": self.symbol,
            "detected": self.detected,
            "score": self.score,
            "pivot_price": self.pivot_price,
            "base_low": self.base_low,
            "pattern_depth_pct": self.pattern_depth_pct,
            "num_contractions": self.num_contractions,
            "volume_dry_up": self.volume_dry_up,
            "tightening_quality": self.tightening_quality,
            "ideal_buy_point": self.ideal_buy_point,
            "stop_loss_price": self.stop_loss_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "message": self.message,
        }


class VCPDetector:
    """
    VCP (Volatility Contraction Pattern) 탐지기
    
    VCP 패턴의 특징:
    - 상승 후 횡보하며 변동폭이 점점 줄어듦
    - 각 수축은 이전 수축보다 작아야 함 (예: 20% → 12% → 6%)
    - 조정 시 거래량 감소, 돌파 시 거래량 증가
    - 명확한 피벗 포인트(돌파 기준선) 형성
    
    Usage:
        >>> detector = VCPDetector()
        >>> pattern = detector.detect(df, symbol="005930")
        >>> if pattern.detected and pattern.score >= 70:
        ...     print(f"VCP detected! Pivot: {pattern.pivot_price}")
    """
    
    def __init__(
        self,
        min_contractions: int = None,
        max_contractions: int = 6,
        contraction_ratio: float = 0.7,     # 다음 수축은 이전의 70% 이하
        max_pattern_depth: float = 35.0,    # 최대 패턴 깊이 35%
        min_pattern_depth: float = 10.0,    # 최소 패턴 깊이 10%
        volume_decline_threshold: float = 0.7,  # 거래량 30% 이상 감소
        lookback_days: int = 120,           # 분석 기간 (일)
        min_base_days: int = 20,            # 최소 베이스 기간
    ):
        """
        Args:
            min_contractions: 최소 수축 횟수 (기본값: settings에서 로드)
            max_contractions: 최대 수축 횟수
            contraction_ratio: 수축 비율 한계
            max_pattern_depth: 최대 패턴 깊이 (%)
            min_pattern_depth: 최소 패턴 깊이 (%)
            volume_decline_threshold: 거래량 감소 기준
            lookback_days: 분석 기간
            min_base_days: 최소 베이스 형성 기간
        """
        self.min_contractions = min_contractions or settings.min_contractions
        self.max_contractions = max_contractions
        self.contraction_ratio = contraction_ratio
        self.max_pattern_depth = max_pattern_depth
        self.min_pattern_depth = min_pattern_depth
        self.volume_decline_threshold = volume_decline_threshold
        self.lookback_days = lookback_days
        self.min_base_days = min_base_days
        
        logger.debug(
            f"VCPDetector initialized: min_contractions={self.min_contractions}, "
            f"lookback={self.lookback_days}d"
        )
    
    def detect(self, df: pd.DataFrame, symbol: str) -> VCPPattern:
        """
        VCP 패턴을 탐지합니다.
        
        Args:
            df: OHLCV 데이터 (columns: date, open, high, low, close, volume)
            symbol: 종목 코드
        
        Returns:
            VCPPattern: 패턴 탐지 결과
        """
        if len(df) < self.lookback_days:
            logger.warning(f"{symbol}: 데이터 부족 ({len(df)}일 < {self.lookback_days}일)")
            return VCPPattern(
                symbol=symbol, detected=False, score=0,
                message="데이터 부족"
            )
        
        # 데이터 정렬 (최신이 뒤로)
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        
        # 분석 구간 추출
        analysis_df = df.tail(self.lookback_days).copy()
        
        # 베이스 탐지
        base_info = self._find_base(analysis_df)
        if not base_info["found"]:
            return VCPPattern(
                symbol=symbol, detected=False, score=0,
                message="베이스 패턴을 찾을 수 없습니다"
            )
        
        # 수축 패턴 탐지
        contractions = self._find_contractions(analysis_df, base_info)
        if len(contractions) < self.min_contractions:
            return VCPPattern(
                symbol=symbol, detected=False, score=0,
                num_contractions=len(contractions),
                message=f"수축 횟수 부족 ({len(contractions)} < {self.min_contractions})"
            )
        
        # 수축 품질 검증
        is_progressive = self._validate_progressive_contractions(contractions)
        if not is_progressive:
            return VCPPattern(
                symbol=symbol, detected=False, score=15,
                num_contractions=len(contractions),
                contractions=contractions,
                message="수축이 점진적으로 줄어들지 않음"
            )
        
        # 거래량 분석
        volume_analysis = self._analyze_volume(analysis_df, contractions)
        
        # 피벗 포인트 계산
        pivot_price = self._calculate_pivot(analysis_df, contractions)
        base_low = base_info["low"]
        pattern_depth = ((base_info["high"] - base_low) / base_info["high"]) * 100
        
        # 패턴 깊이 검증
        if pattern_depth > self.max_pattern_depth:
            return VCPPattern(
                symbol=symbol, detected=False, score=25,
                pivot_price=pivot_price,
                base_low=base_low,
                pattern_depth_pct=pattern_depth,
                num_contractions=len(contractions),
                message=f"패턴 깊이 과다 ({pattern_depth:.1f}% > {self.max_pattern_depth}%)"
            )
        
        if pattern_depth < self.min_pattern_depth:
            return VCPPattern(
                symbol=symbol, detected=False, score=20,
                pivot_price=pivot_price,
                base_low=base_low,
                pattern_depth_pct=pattern_depth,
                num_contractions=len(contractions),
                message=f"패턴 깊이 부족 ({pattern_depth:.1f}% < {self.min_pattern_depth}%)"
            )
        
        # 타이트닝 품질 평가
        tightening_quality = self._evaluate_tightening(contractions)
        last_contraction_tight = self._is_last_contraction_tight(contractions)
        
        # 최종 점수 계산
        score = self._calculate_score(
            contractions=contractions,
            pattern_depth=pattern_depth,
            volume_dry_up=volume_analysis["dry_up"],
            tightening_quality=tightening_quality,
            last_contraction_tight=last_contraction_tight,
        )
        
        # 진입 정보 계산
        ideal_buy_point = pivot_price * 1.01  # 피벗 1% 위
        stop_loss_price = base_low * 0.98     # 베이스 저점 2% 아래
        current_price = float(df.iloc[-1]["close"])
        
        potential_gain = ((pivot_price * 1.20) - ideal_buy_point) / ideal_buy_point * 100
        potential_loss = (ideal_buy_point - stop_loss_price) / ideal_buy_point * 100
        risk_reward = potential_gain / potential_loss if potential_loss > 0 else 0
        
        detected = score >= settings.min_vcp_score
        
        pattern = VCPPattern(
            symbol=symbol,
            detected=detected,
            score=score,
            pivot_price=pivot_price,
            base_low=base_low,
            pattern_depth_pct=pattern_depth,
            num_contractions=len(contractions),
            contractions=contractions,
            volume_dry_up=volume_analysis["dry_up"],
            avg_volume_ratio=volume_analysis["avg_ratio"],
            tightening_quality=tightening_quality,
            last_contraction_tight=last_contraction_tight,
            pattern_start_date=base_info["start_date"],
            pattern_end_date=base_info["end_date"],
            ideal_buy_point=ideal_buy_point,
            stop_loss_price=stop_loss_price,
            risk_reward_ratio=risk_reward,
            message=f"VCP 탐지됨 - 점수: {score}/100" if detected else f"VCP 미달 - 점수: {score}/100",
        )
        
        logger.info(
            f"{symbol}: VCP {'detected' if detected else 'not detected'} - "
            f"score={score}, contractions={len(contractions)}, "
            f"depth={pattern_depth:.1f}%, pivot={pivot_price:.0f}"
        )
        
        return pattern
    
    def _find_base(self, df: pd.DataFrame) -> dict:
        """베이스(횡보 구간)를 찾습니다."""
        # 고점 찾기 (최근 데이터에서 역방향으로)
        highs = df["high"].values
        lows = df["low"].values
        
        # 롤링 최고가로 베이스 시작점 찾기
        peak_idx = np.argmax(highs)
        peak_price = highs[peak_idx]
        
        # 피크 이후 데이터로 베이스 분석
        if peak_idx >= len(df) - self.min_base_days:
            return {"found": False}
        
        base_df = df.iloc[peak_idx:]
        if len(base_df) < self.min_base_days:
            return {"found": False}
        
        base_high = float(base_df["high"].max())
        base_low = float(base_df["low"].min())
        
        return {
            "found": True,
            "high": base_high,
            "low": base_low,
            "start_date": base_df.iloc[0]["date"],
            "end_date": base_df.iloc[-1]["date"],
            "peak_idx": peak_idx,
        }
    
    def _find_contractions(self, df: pd.DataFrame, base_info: dict) -> list[Contraction]:
        """수축 구간들을 찾습니다."""
        contractions = []
        peak_idx = base_info["peak_idx"]
        
        # 베이스 구간 데이터
        base_df = df.iloc[peak_idx:].copy()
        if len(base_df) < self.min_base_days:
            return contractions
        
        # 스윙 포인트 찾기
        swing_highs = self._find_swing_points(base_df, "high", window=5)
        swing_lows = self._find_swing_points(base_df, "low", window=5)
        
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return contractions
        
        # 전체 평균 거래량
        avg_volume = df["volume"].mean()
        
        # 수축 구간 매칭
        for i in range(len(swing_highs) - 1):
            start_idx = swing_highs[i][0]
            end_idx = swing_highs[i + 1][0] if i + 1 < len(swing_highs) else len(base_df) - 1
            
            if end_idx <= start_idx:
                continue
            
            segment = base_df.iloc[start_idx:end_idx + 1]
            if len(segment) < 3:
                continue
            
            high_price = float(segment["high"].max())
            low_price = float(segment["low"].min())
            depth_pct = ((high_price - low_price) / high_price) * 100
            
            segment_volume = float(segment["volume"].mean())
            volume_ratio = segment_volume / avg_volume if avg_volume > 0 else 1.0
            
            contraction = Contraction(
                start_date=segment.iloc[0]["date"],
                end_date=segment.iloc[-1]["date"],
                high_price=high_price,
                low_price=low_price,
                depth_pct=depth_pct,
                duration_days=len(segment),
                avg_volume=segment_volume,
                volume_ratio=volume_ratio,
            )
            contractions.append(contraction)
        
        return contractions[:self.max_contractions]
    
    def _find_swing_points(
        self,
        df: pd.DataFrame,
        column: str,
        window: int = 5,
    ) -> list[tuple[int, float]]:
        """스윙 고점/저점을 찾습니다."""
        values = df[column].values
        swing_points = []
        
        for i in range(window, len(values) - window):
            if column == "high":
                if values[i] == max(values[i - window:i + window + 1]):
                    swing_points.append((i, values[i]))
            else:
                if values[i] == min(values[i - window:i + window + 1]):
                    swing_points.append((i, values[i]))
        
        return swing_points
    
    def _validate_progressive_contractions(self, contractions: list[Contraction]) -> bool:
        """수축이 점진적으로 줄어드는지 검증합니다."""
        if len(contractions) < 2:
            return False
        
        for i in range(1, len(contractions)):
            prev_depth = contractions[i - 1].depth_pct
            curr_depth = contractions[i].depth_pct
            
            # 현재 수축이 이전의 70% 이하여야 함
            if curr_depth > prev_depth * self.contraction_ratio:
                return False
        
        return True
    
    def _analyze_volume(self, df: pd.DataFrame, contractions: list[Contraction]) -> dict:
        """거래량 패턴을 분석합니다."""
        if not contractions:
            return {"dry_up": False, "avg_ratio": 1.0}
        
        volume_ratios = [c.volume_ratio for c in contractions]
        avg_ratio = np.mean(volume_ratios)
        
        # 후반부 수축의 거래량이 감소하는지 확인
        dry_up = False
        if len(contractions) >= 2:
            first_half_vol = np.mean(volume_ratios[:len(volume_ratios) // 2 + 1])
            second_half_vol = np.mean(volume_ratios[len(volume_ratios) // 2:])
            dry_up = second_half_vol < first_half_vol * self.volume_decline_threshold
        
        return {"dry_up": dry_up, "avg_ratio": avg_ratio}
    
    def _calculate_pivot(self, df: pd.DataFrame, contractions: list[Contraction]) -> float:
        """피벗 포인트를 계산합니다."""
        if not contractions:
            return float(df.iloc[-1]["high"])
        
        # 마지막 수축의 고점이 피벗 포인트
        return contractions[-1].high_price
    
    def _evaluate_tightening(self, contractions: list[Contraction]) -> str:
        """타이트닝 품질을 평가합니다."""
        if not contractions:
            return "none"
        
        last_depth = contractions[-1].depth_pct
        
        if last_depth <= 3:
            return "excellent"
        elif last_depth <= 5:
            return "good"
        elif last_depth <= 8:
            return "fair"
        else:
            return "poor"
    
    def _is_last_contraction_tight(self, contractions: list[Contraction]) -> bool:
        """마지막 수축이 타이트한지 확인합니다."""
        if not contractions:
            return False
        return contractions[-1].depth_pct <= 5.0
    
    def _calculate_score(
        self,
        contractions: list[Contraction],
        pattern_depth: float,
        volume_dry_up: bool,
        tightening_quality: str,
        last_contraction_tight: bool,
    ) -> int:
        """VCP 패턴 점수를 계산합니다 (0-100)."""
        score = 0
        
        # 1. 수축 횟수 (최대 25점)
        num_contractions = len(contractions)
        if num_contractions >= 4:
            score += 25
        elif num_contractions >= 3:
            score += 20
        elif num_contractions >= 2:
            score += 15
        
        # 2. 패턴 깊이 (최대 20점) - 15-25%가 이상적
        if 15 <= pattern_depth <= 25:
            score += 20
        elif 10 <= pattern_depth <= 30:
            score += 15
        elif pattern_depth <= 35:
            score += 10
        
        # 3. 타이트닝 품질 (최대 25점)
        tightening_scores = {
            "excellent": 25,
            "good": 20,
            "fair": 15,
            "poor": 5,
            "none": 0,
        }
        score += tightening_scores.get(tightening_quality, 0)
        
        # 4. 거래량 감소 (최대 15점)
        if volume_dry_up:
            score += 15
        
        # 5. 마지막 수축 타이트함 (최대 15점)
        if last_contraction_tight:
            score += 15
        elif contractions and contractions[-1].depth_pct <= 8:
            score += 10
        
        return min(score, 100)
    
    def detect_batch(
        self,
        stock_data: dict[str, pd.DataFrame],
        min_score: int = None,
    ) -> list[VCPPattern]:
        """
        여러 종목에 대해 일괄 탐지를 수행합니다.
        
        Args:
            stock_data: {symbol: DataFrame} 딕셔너리
            min_score: 최소 VCP 점수 (기본값: settings에서 로드)
        
        Returns:
            VCP 패턴 리스트 (점수순 정렬)
        """
        min_score = min_score or settings.min_vcp_score
        results = []
        
        for symbol, df in stock_data.items():
            try:
                pattern = self.detect(df, symbol)
                if pattern.score >= min_score:
                    results.append(pattern)
            except Exception as e:
                logger.error(f"{symbol}: VCP 탐지 실패 - {e}")
        
        # 점수순 정렬
        results.sort(key=lambda x: x.score, reverse=True)
        
        return results
