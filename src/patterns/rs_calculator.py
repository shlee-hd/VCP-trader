"""
RS (Relative Strength) Calculator

시장 대비 개별 종목의 상대적 강도를 계산합니다.
미너비니의 RS Rating은 0-100 스케일로, 시장의 다른 종목들 대비 
해당 종목의 price performance를 나타냅니다.
"""

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger


@dataclass
class RSResult:
    """RS 계산 결과"""
    symbol: str
    rs_rating: int                    # RS Rating (0-100)
    rs_raw: float                     # Raw RS 값
    performance_3m: float             # 3개월 수익률 (%)
    performance_6m: float             # 6개월 수익률 (%)
    performance_12m: float            # 12개월 수익률 (%)
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "rs_rating": self.rs_rating,
            "rs_raw": self.rs_raw,
            "performance_3m": self.performance_3m,
            "performance_6m": self.performance_6m,
            "performance_12m": self.performance_12m,
        }


class RSCalculator:
    """
    RS (Relative Strength) Rating 계산기
    
    미너비니 스타일의 RS Rating을 계산합니다.
    RS Rating은 시장의 모든 주식 대비 해당 종목의 price performance를
    백분위(percentile)로 나타낸 값입니다.
    
    계산 방법:
    1. 각 종목의 가중 price performance 계산
       - 3개월 수익률 × 2
       - 6개월 수익률 × 1
       - 9개월 수익률 × 1
       - 12개월 수익률 × 1
    2. 전체 종목을 Raw RS로 정렬
    3. 백분위를 0-100 스케일로 변환
    
    Usage:
        >>> calculator = RSCalculator()
        >>> # 단일 종목 Raw RS 계산
        >>> raw_rs = calculator.calculate_raw_rs(df)
        >>> 
        >>> # 전체 시장 RS Rating 계산
        >>> ratings = calculator.calculate_ratings(stock_data)
    """
    
    # 기간별 가중치
    WEIGHTS = {
        "3m": 2.0,   # 최근 3개월에 가장 높은 가중치
        "6m": 1.0,
        "9m": 1.0,
        "12m": 1.0,
    }
    
    # 기간별 거래일 수
    PERIODS = {
        "3m": 63,    # 약 3개월
        "6m": 126,   # 약 6개월
        "9m": 189,   # 약 9개월
        "12m": 252,  # 약 12개월
    }
    
    def __init__(self, weights: dict[str, float] = None):
        """
        Args:
            weights: 기간별 가중치 (기본값 사용 권장)
        """
        self.weights = weights or self.WEIGHTS
        logger.debug(f"RSCalculator initialized with weights: {self.weights}")
    
    def calculate_raw_rs(self, df: pd.DataFrame) -> dict:
        """
        단일 종목의 Raw RS 값을 계산합니다.
        
        Args:
            df: OHLCV 데이터 (columns: date, close)
        
        Returns:
            dict: {raw_rs, performance_3m, performance_6m, performance_12m}
        """
        if len(df) < self.PERIODS["12m"]:
            return {
                "raw_rs": 0.0,
                "performance_3m": 0.0,
                "performance_6m": 0.0,
                "performance_9m": 0.0,
                "performance_12m": 0.0,
            }
        
        # 날짜순 정렬 (최신이 뒤)
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        current_price = float(df.iloc[-1]["close"])
        
        performances = {}
        
        for period_name, days in self.PERIODS.items():
            if len(df) >= days:
                past_price = float(df.iloc[-days]["close"])
                if past_price > 0:
                    performances[period_name] = ((current_price - past_price) / past_price) * 100
                else:
                    performances[period_name] = 0.0
            else:
                performances[period_name] = 0.0
        
        # 가중 평균 계산
        weighted_sum = sum(
            performances.get(period, 0) * weight
            for period, weight in self.weights.items()
        )
        total_weight = sum(self.weights.values())
        raw_rs = weighted_sum / total_weight if total_weight > 0 else 0
        
        return {
            "raw_rs": raw_rs,
            "performance_3m": performances.get("3m", 0.0),
            "performance_6m": performances.get("6m", 0.0),
            "performance_9m": performances.get("9m", 0.0),
            "performance_12m": performances.get("12m", 0.0),
        }
    
    def calculate_ratings(
        self,
        stock_data: dict[str, pd.DataFrame],
    ) -> dict[str, RSResult]:
        """
        여러 종목의 RS Rating을 일괄 계산합니다.
        
        Args:
            stock_data: {symbol: DataFrame} 딕셔너리
        
        Returns:
            {symbol: RSResult} 딕셔너리
        """
        # 1. 모든 종목의 Raw RS 계산
        raw_results = {}
        for symbol, df in stock_data.items():
            try:
                raw_results[symbol] = self.calculate_raw_rs(df)
            except Exception as e:
                logger.error(f"{symbol}: RS 계산 실패 - {e}")
                raw_results[symbol] = {
                    "raw_rs": 0.0,
                    "performance_3m": 0.0,
                    "performance_6m": 0.0,
                    "performance_12m": 0.0,
                }
        
        # 2. Raw RS 값으로 백분위 계산
        raw_rs_values = [r["raw_rs"] for r in raw_results.values()]
        raw_rs_array = np.array(raw_rs_values)
        
        # 백분위를 기반으로 RS Rating 계산 (0-100)
        results = {}
        for symbol, raw_data in raw_results.items():
            raw_rs = raw_data["raw_rs"]
            
            # 백분위 계산 (해당 Raw RS보다 작은 값들의 비율)
            percentile = (raw_rs_array < raw_rs).sum() / len(raw_rs_array) * 100
            rs_rating = int(round(percentile))
            
            results[symbol] = RSResult(
                symbol=symbol,
                rs_rating=rs_rating,
                rs_raw=raw_rs,
                performance_3m=raw_data["performance_3m"],
                performance_6m=raw_data["performance_6m"],
                performance_12m=raw_data["performance_12m"],
            )
        
        logger.info(f"RS Rating 계산 완료: {len(results)}개 종목")
        
        return results
    
    def get_top_rs_stocks(
        self,
        stock_data: dict[str, pd.DataFrame],
        min_rating: int = 70,
        top_n: int = None,
    ) -> list[RSResult]:
        """
        RS Rating이 높은 상위 종목들을 반환합니다.
        
        Args:
            stock_data: 종목별 데이터
            min_rating: 최소 RS Rating (기본값: 70)
            top_n: 상위 N개만 반환 (None이면 모두)
        
        Returns:
            RS Rating 기준 상위 종목 리스트
        """
        ratings = self.calculate_ratings(stock_data)
        
        # 필터링 및 정렬
        filtered = [r for r in ratings.values() if r.rs_rating >= min_rating]
        filtered.sort(key=lambda x: x.rs_rating, reverse=True)
        
        if top_n:
            return filtered[:top_n]
        
        return filtered


def calculate_relative_performance(
    stock_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    window: int = 63,
) -> pd.Series:
    """
    벤치마크 대비 상대 성과를 계산합니다.
    
    Args:
        stock_df: 종목 OHLCV 데이터
        benchmark_df: 벤치마크(코스피 등) OHLCV 데이터
        window: 비교 기간 (거래일)
    
    Returns:
        상대 성과 시리즈
    """
    # 날짜 정렬
    stock_df = stock_df.sort_values("date").set_index("date")
    benchmark_df = benchmark_df.sort_values("date").set_index("date")
    
    # 수익률 계산
    stock_returns = stock_df["close"].pct_change(window)
    benchmark_returns = benchmark_df["close"].pct_change(window)
    
    # 공통 인덱스로 정렬
    common_idx = stock_returns.index.intersection(benchmark_returns.index)
    stock_returns = stock_returns[common_idx]
    benchmark_returns = benchmark_returns[common_idx]
    
    # 상대 성과 = 종목 수익률 - 벤치마크 수익률
    return stock_returns - benchmark_returns
