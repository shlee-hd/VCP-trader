"""
Data Fetcher

여러 소스에서 주가 데이터를 수집합니다.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
from loguru import logger

from .broker_client import KISBrokerClient
from ..core.config import settings
from ..core.database import MarketType


class DataFetcher:
    """
    주가 데이터 수집기
    
    기능:
    - 일봉 데이터 수집
    - 전체 종목 데이터 일괄 수집
    - 캐싱 및 증분 업데이트
    
    Usage:
        >>> fetcher = DataFetcher()
        >>> await fetcher.initialize()
        >>> 
        >>> # 단일 종목 데이터
        >>> df = await fetcher.get_daily_data("005930", days=365)
        >>> 
        >>> # 전체 KOSPI 종목
        >>> all_data = await fetcher.fetch_all_kospi(days=365)
    """
    
    def __init__(self, broker_client: KISBrokerClient = None):
        self.broker = broker_client
        self._cache: dict[str, pd.DataFrame] = {}
    
    async def initialize(self):
        """데이터 수집기를 초기화합니다."""
        if self.broker is None:
            self.broker = KISBrokerClient()
            await self.broker.initialize()
        logger.info("DataFetcher initialized")
    
    async def close(self):
        """리소스를 정리합니다."""
        if self.broker:
            await self.broker.close()
    
    async def get_daily_data(
        self,
        symbol: str,
        days: int = 365,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        일봉 데이터를 가져옵니다.
        
        Args:
            symbol: 종목 코드
            days: 조회 기간 (일)
            use_cache: 캐시 사용 여부
        
        Returns:
            OHLCV DataFrame
        """
        # 캐시 확인
        cache_key = f"{symbol}_{days}"
        if use_cache and cache_key in self._cache:
            return self._cache[cache_key]
        
        # 데이터 수집 (API는 최대 100일씩 조회 가능)
        all_data = []
        remaining_days = days
        
        while remaining_days > 0:
            fetch_count = min(remaining_days, 100)
            
            try:
                prices = await self.broker.get_daily_prices(
                    symbol=symbol,
                    period_type="D",
                    count=fetch_count,
                )
                
                if not prices:
                    break
                
                all_data.extend(prices)
                remaining_days -= fetch_count
                
                # API Rate Limit 방지
                await asyncio.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Failed to fetch data for {symbol}: {e}")
                break
        
        if not all_data:
            return pd.DataFrame()
        
        # DataFrame 변환
        df = pd.DataFrame(all_data)
        df = df.sort_values("date", ascending=True).reset_index(drop=True)
        
        # 이동평균 계산
        df["sma_50"] = df["close"].rolling(window=50).mean()
        df["sma_150"] = df["close"].rolling(window=150).mean()
        df["sma_200"] = df["close"].rolling(window=200).mean()
        
        # ATR 계산
        df["atr_20"] = self._calculate_atr(df, period=20)
        
        # 캐시 저장
        if use_cache:
            self._cache[cache_key] = df
        
        logger.debug(f"Fetched {len(df)} days of data for {symbol}")
        
        return df
    
    async def fetch_batch(
        self,
        symbols: list[str],
        days: int = 365,
        max_concurrent: int = 5,
    ) -> dict[str, pd.DataFrame]:
        """
        여러 종목의 데이터를 일괄 수집합니다.
        
        Args:
            symbols: 종목 코드 리스트
            days: 조회 기간
            max_concurrent: 최대 동시 요청 수
        
        Returns:
            {symbol: DataFrame} 딕셔너리
        """
        results = {}
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def fetch_one(symbol: str):
            async with semaphore:
                try:
                    df = await self.get_daily_data(symbol, days)
                    return symbol, df
                except Exception as e:
                    logger.error(f"Failed to fetch {symbol}: {e}")
                    return symbol, pd.DataFrame()
        
        tasks = [fetch_one(symbol) for symbol in symbols]
        completed = await asyncio.gather(*tasks)
        
        for symbol, df in completed:
            if not df.empty:
                results[symbol] = df
        
        logger.info(f"Fetched data for {len(results)}/{len(symbols)} symbols")
        
        return results
    
    async def get_current_prices(self, symbols: list[str]) -> dict[str, float]:
        """
        현재가를 일괄 조회합니다.
        
        Args:
            symbols: 종목 코드 리스트
        
        Returns:
            {symbol: price} 딕셔너리
        """
        results = {}
        
        for symbol in symbols:
            try:
                data = await self.broker.get_current_price(symbol)
                results[symbol] = data["price"]
                await asyncio.sleep(0.05)  # Rate limit
            except Exception as e:
                logger.error(f"Failed to get price for {symbol}: {e}")
        
        return results
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 20) -> pd.Series:
        """ATR (Average True Range)를 계산합니다."""
        high = df["high"]
        low = df["low"]
        close = df["close"].shift(1)
        
        tr1 = high - low
        tr2 = abs(high - close)
        tr3 = abs(low - close)
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        return tr.rolling(window=period).mean()
    
    def clear_cache(self, symbol: str = None):
        """캐시를 삭제합니다."""
        if symbol:
            keys_to_remove = [k for k in self._cache if k.startswith(symbol)]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()
        logger.debug(f"Cache cleared: {symbol or 'all'}")


# ===== 종목 리스트 관리 =====

# KOSPI/KOSDAQ 종목 리스트는 별도 파일이나 API에서 로드해야 함
# 아래는 테스트용 샘플 종목

SAMPLE_KOSPI_SYMBOLS = [
    {"symbol": "005930", "name": "삼성전자", "sector": "반도체"},
    {"symbol": "000660", "name": "SK하이닉스", "sector": "반도체"},
    {"symbol": "035420", "name": "NAVER", "sector": "인터넷"},
    {"symbol": "035720", "name": "카카오", "sector": "인터넷"},
    {"symbol": "005380", "name": "현대차", "sector": "자동차"},
    {"symbol": "051910", "name": "LG화학", "sector": "화학"},
    {"symbol": "006400", "name": "삼성SDI", "sector": "배터리"},
    {"symbol": "207940", "name": "삼성바이오로직스", "sector": "바이오"},
    {"symbol": "003670", "name": "포스코퓨처엠", "sector": "소재"},
    {"symbol": "068270", "name": "셀트리온", "sector": "바이오"},
]

SAMPLE_KOSDAQ_SYMBOLS = [
    {"symbol": "247540", "name": "에코프로비엠", "sector": "배터리"},
    {"symbol": "086520", "name": "에코프로", "sector": "배터리"},
    {"symbol": "091990", "name": "셀트리온헬스케어", "sector": "바이오"},
    {"symbol": "196170", "name": "알테오젠", "sector": "바이오"},
    {"symbol": "357780", "name": "솔브레인", "sector": "반도체"},
]


def get_sample_symbols(market: MarketType = MarketType.KOSPI) -> list[dict]:
    """테스트용 샘플 종목 리스트를 반환합니다."""
    if market == MarketType.KOSPI:
        return SAMPLE_KOSPI_SYMBOLS
    elif market == MarketType.KOSDAQ:
        return SAMPLE_KOSDAQ_SYMBOLS
    return []
