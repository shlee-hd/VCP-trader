"""
Mark Minervini Trend Template

미너비니의 8가지 Trend Template 기준을 구현합니다.
Stage 2 상승 추세에 있는 종목만 필터링하여 승률을 높입니다.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from ..core.config import settings


@dataclass
class TrendTemplateResult:
    """Trend Template 분석 결과"""
    
    symbol: str
    passes: bool                    # 모든 기준 통과 여부
    score: int                      # 통과한 기준 수 (0-8)
    rs_rating: Optional[int]        # RS Rating (0-100)
    
    # 개별 기준 통과 여부
    price_above_150ma: bool = False
    price_above_50ma: bool = False
    ma_alignment: bool = False      # 50MA > 150MA > 200MA
    ma200_rising: bool = False      # 200MA 상승 중
    above_52w_low: bool = False     # 52주 저점 대비 30%+ 상승
    within_52w_high: bool = False   # 52주 고점 대비 25% 이내
    rs_above_threshold: bool = False
    above_base: bool = False        # 베이스 위에서 거래
    
    # 추가 정보
    current_price: float = 0.0
    sma_50: float = 0.0
    sma_150: float = 0.0
    sma_200: float = 0.0
    week_52_high: float = 0.0
    week_52_low: float = 0.0
    pct_from_52w_high: float = 0.0
    pct_from_52w_low: float = 0.0
    
    def to_dict(self) -> dict:
        """딕셔너리로 변환"""
        return {
            "symbol": self.symbol,
            "passes": self.passes,
            "score": self.score,
            "rs_rating": self.rs_rating,
            "criteria": {
                "price_above_150ma": self.price_above_150ma,
                "price_above_50ma": self.price_above_50ma,
                "ma_alignment": self.ma_alignment,
                "ma200_rising": self.ma200_rising,
                "above_52w_low": self.above_52w_low,
                "within_52w_high": self.within_52w_high,
                "rs_above_threshold": self.rs_above_threshold,
                "above_base": self.above_base,
            },
            "metrics": {
                "current_price": self.current_price,
                "sma_50": self.sma_50,
                "sma_150": self.sma_150,
                "sma_200": self.sma_200,
                "week_52_high": self.week_52_high,
                "week_52_low": self.week_52_low,
                "pct_from_52w_high": self.pct_from_52w_high,
                "pct_from_52w_low": self.pct_from_52w_low,
            }
        }


class TrendTemplate:
    """
    마크 미너비니의 Trend Template (8가지 기준)
    
    Stage 2 상승 추세를 확인하기 위한 8가지 필수 조건:
    
    1. 현재가 > 150일 이동평균 > 200일 이동평균
    2. 현재가 > 50일 이동평균
    3. 50일 이동평균 > 150일 이동평균 > 200일 이동평균
    4. 200일 이동평균이 최소 30일간 상승 중
    5. 현재가가 52주 저점 대비 30% 이상 상승
    6. 현재가가 52주 고점 대비 25% 이내
    7. RS (Relative Strength) Rating이 70 이상 (가급적 80+)
    8. 현재가가 베이스(횡보 구간) 위에서 거래
    
    Usage:
        >>> template = TrendTemplate()
        >>> result = template.analyze(df, symbol="005930", rs_rating=85)
        >>> if result.passes:
        ...     print(f"{result.symbol} passes Trend Template!")
    """
    
    def __init__(
        self,
        min_rs_rating: int = None,
        price_above_52w_low_pct: float = None,
        price_within_52w_high_pct: float = None,
        ma200_lookback_days: int = 30,
    ):
        """
        Args:
            min_rs_rating: 최소 RS Rating (기본값: settings에서 로드)
            price_above_52w_low_pct: 52주 저점 대비 최소 상승률 %
            price_within_52w_high_pct: 52주 고점 대비 최대 하락률 %
            ma200_lookback_days: 200MA 상승 확인 기간 (일)
        """
        self.min_rs_rating = min_rs_rating or settings.min_rs_rating
        self.price_above_52w_low_pct = price_above_52w_low_pct or settings.price_above_52w_low_pct
        self.price_within_52w_high_pct = price_within_52w_high_pct or settings.price_within_52w_high_pct
        self.ma200_lookback_days = ma200_lookback_days
        
        logger.debug(
            f"TrendTemplate initialized: min_rs={self.min_rs_rating}, "
            f"52w_low_pct={self.price_above_52w_low_pct}, "
            f"52w_high_pct={self.price_within_52w_high_pct}"
        )
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str,
        rs_rating: Optional[int] = None,
    ) -> TrendTemplateResult:
        """
        주어진 데이터에 대해 Trend Template 분석을 수행합니다.
        
        Args:
            df: OHLCV 데이터 (최소 250일 이상, columns: date, open, high, low, close, volume)
            symbol: 종목 코드
            rs_rating: RS Rating (외부에서 계산됨, 없으면 None)
        
        Returns:
            TrendTemplateResult: 분석 결과
        """
        if len(df) < 250:
            logger.warning(f"{symbol}: 데이터 부족 (최소 250일 필요, 현재 {len(df)}일)")
            return TrendTemplateResult(symbol=symbol, passes=False, score=0, rs_rating=rs_rating)
        
        # 데이터를 최신순으로 정렬 (인덱스 0이 가장 최근)
        df = df.sort_values("date", ascending=False).reset_index(drop=True)
        
        # 이동평균 계산 (없는 경우)
        if "sma_50" not in df.columns:
            df["sma_50"] = df["close"].rolling(window=50).mean()
        if "sma_150" not in df.columns:
            df["sma_150"] = df["close"].rolling(window=150).mean()
        if "sma_200" not in df.columns:
            df["sma_200"] = df["close"].rolling(window=200).mean()
        
        # 최신 데이터 추출
        current = df.iloc[0]
        current_price = float(current["close"])
        sma_50 = float(current["sma_50"]) if pd.notna(current["sma_50"]) else 0
        sma_150 = float(current["sma_150"]) if pd.notna(current["sma_150"]) else 0
        sma_200 = float(current["sma_200"]) if pd.notna(current["sma_200"]) else 0
        
        # 52주 (252 거래일) 고가/저가
        week_52_data = df.head(252)
        week_52_high = float(week_52_data["high"].max())
        week_52_low = float(week_52_data["low"].min())
        
        # 52주 대비 위치 계산
        pct_from_52w_high = ((current_price - week_52_high) / week_52_high) * 100
        pct_from_52w_low = ((current_price - week_52_low) / week_52_low) * 100
        
        # 200MA 30일 전 값
        ma200_30d_ago = float(df.iloc[self.ma200_lookback_days]["sma_200"]) if len(df) > self.ma200_lookback_days else 0
        
        # 베이스 계산 (최근 50일 중 최저가)
        recent_base = float(df.head(50)["low"].min())
        
        # ===== 8가지 기준 체크 =====
        
        # 1. 현재가 > 150MA > 200MA
        price_above_150ma = current_price > sma_150 > sma_200 if sma_150 > 0 and sma_200 > 0 else False
        
        # 2. 현재가 > 50MA
        price_above_50ma = current_price > sma_50 if sma_50 > 0 else False
        
        # 3. 50MA > 150MA > 200MA (이동평균 정배열)
        ma_alignment = sma_50 > sma_150 > sma_200 if sma_50 > 0 and sma_150 > 0 and sma_200 > 0 else False
        
        # 4. 200MA 상승 중 (30일 전보다 높음)
        ma200_rising = sma_200 > ma200_30d_ago if sma_200 > 0 and ma200_30d_ago > 0 else False
        
        # 5. 52주 저점 대비 30% 이상 상승
        above_52w_low = pct_from_52w_low >= self.price_above_52w_low_pct
        
        # 6. 52주 고점 대비 25% 이내
        within_52w_high = abs(pct_from_52w_high) <= self.price_within_52w_high_pct
        
        # 7. RS Rating >= 70
        rs_above_threshold = rs_rating is not None and rs_rating >= self.min_rs_rating
        
        # 8. 베이스 위에서 거래
        above_base = current_price > recent_base
        
        # 점수 계산
        criteria = [
            price_above_150ma,
            price_above_50ma,
            ma_alignment,
            ma200_rising,
            above_52w_low,
            within_52w_high,
            rs_above_threshold,
            above_base,
        ]
        score = sum(criteria)
        passes = all(criteria)
        
        result = TrendTemplateResult(
            symbol=symbol,
            passes=passes,
            score=score,
            rs_rating=rs_rating,
            price_above_150ma=price_above_150ma,
            price_above_50ma=price_above_50ma,
            ma_alignment=ma_alignment,
            ma200_rising=ma200_rising,
            above_52w_low=above_52w_low,
            within_52w_high=within_52w_high,
            rs_above_threshold=rs_above_threshold,
            above_base=above_base,
            current_price=current_price,
            sma_50=sma_50,
            sma_150=sma_150,
            sma_200=sma_200,
            week_52_high=week_52_high,
            week_52_low=week_52_low,
            pct_from_52w_high=pct_from_52w_high,
            pct_from_52w_low=pct_from_52w_low,
        )
        
        logger.debug(
            f"{symbol}: Trend Template score={score}/8, passes={passes}, "
            f"price={current_price:.2f}, RS={rs_rating}"
        )
        
        return result
    
    def analyze_batch(
        self,
        stock_data: dict[str, pd.DataFrame],
        rs_ratings: dict[str, int] = None,
    ) -> list[TrendTemplateResult]:
        """
        여러 종목에 대해 일괄 분석을 수행합니다.
        
        Args:
            stock_data: {symbol: DataFrame} 형태의 딕셔너리
            rs_ratings: {symbol: rs_rating} 형태의 딕셔너리
        
        Returns:
            List[TrendTemplateResult]: 분석 결과 리스트
        """
        rs_ratings = rs_ratings or {}
        results = []
        
        for symbol, df in stock_data.items():
            rs_rating = rs_ratings.get(symbol)
            try:
                result = self.analyze(df, symbol, rs_rating)
                results.append(result)
            except Exception as e:
                logger.error(f"{symbol}: Trend Template 분석 실패 - {e}")
                results.append(TrendTemplateResult(
                    symbol=symbol,
                    passes=False,
                    score=0,
                    rs_rating=rs_rating
                ))
        
        # 점수순으로 정렬
        results.sort(key=lambda x: (x.passes, x.score), reverse=True)
        
        return results
    
    def get_passing_stocks(
        self,
        stock_data: dict[str, pd.DataFrame],
        rs_ratings: dict[str, int] = None,
        min_score: int = 8,
    ) -> list[TrendTemplateResult]:
        """
        기준을 통과한 종목만 반환합니다.
        
        Args:
            stock_data: 종목별 데이터
            rs_ratings: RS Rating 딕셔너리
            min_score: 최소 점수 (기본값 8 = 모든 기준 통과)
        
        Returns:
            통과한 종목 리스트
        """
        results = self.analyze_batch(stock_data, rs_ratings)
        return [r for r in results if r.score >= min_score]
