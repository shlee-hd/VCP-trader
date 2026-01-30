"""
Historical Data Manager - 한국 시장 히스토리컬 데이터 수집 및 관리

FinanceDataReader를 사용하여 KOSPI/KOSDAQ 전 종목의 10년치 데이터를 
Parquet 형식으로 저장하고 관리합니다.
"""

import os
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import pandas as pd
import FinanceDataReader as fdr

logger = logging.getLogger(__name__)


@dataclass
class StockInfo:
    """종목 정보"""
    code: str
    name: str
    market: str  # KOSPI or KOSDAQ


class HistoricalDataManager:
    """
    히스토리컬 데이터 수집 및 관리
    
    - KOSPI/KOSDAQ 전 종목 데이터 수집
    - Parquet 파일 형식으로 저장
    - 증분 업데이트 지원
    """
    
    def __init__(self, data_dir: str = "data/historical"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._stock_list_cache: Optional[pd.DataFrame] = None
        
    def get_stock_list(self, market: str = "ALL", refresh: bool = False) -> pd.DataFrame:
        """
        종목 리스트 가져오기
        
        Args:
            market: KOSPI, KOSDAQ, or ALL
            refresh: 캐시 무시하고 새로 가져오기
            
        Returns:
            종목 코드, 이름, 마켓 정보 DataFrame
        """
        if self._stock_list_cache is not None and not refresh:
            if market == "ALL":
                return self._stock_list_cache
            return self._stock_list_cache[self._stock_list_cache["Market"] == market]
        
        logger.info("종목 리스트 수집 중...")
        
        # KOSPI 종목
        kospi = fdr.StockListing("KOSPI")
        kospi["Market"] = "KOSPI"
        
        # KOSDAQ 종목
        kosdaq = fdr.StockListing("KOSDAQ")
        kosdaq["Market"] = "KOSDAQ"
        
        # 통합
        all_stocks = pd.concat([kospi, kosdaq], ignore_index=True)
        
        # 필요한 컬럼만 선택
        columns = ["Code", "Name", "Market"]
        if all(col in all_stocks.columns for col in columns):
            all_stocks = all_stocks[columns]
        else:
            # 컬럼 이름이 다를 수 있음
            all_stocks = all_stocks.rename(columns={
                "Symbol": "Code",
                "종목코드": "Code",
                "종목명": "Name"
            })
            all_stocks = all_stocks[["Code", "Name", "Market"]]
        
        self._stock_list_cache = all_stocks
        logger.info(f"총 {len(all_stocks)} 종목 수집 완료")
        
        if market == "ALL":
            return all_stocks
        return all_stocks[all_stocks["Market"] == market]
    
    def download_stock_data(
        self,
        code: str,
        start_date: str = "2015-01-01",
        end_date: Optional[str] = None,
        force: bool = False
    ) -> Optional[pd.DataFrame]:
        """
        개별 종목 데이터 다운로드
        
        Args:
            code: 종목 코드
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (기본값: 오늘)
            force: 기존 데이터 무시하고 새로 다운로드
            
        Returns:
            OHLCV DataFrame
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        file_path = self._get_file_path(code)
        
        # 기존 데이터 확인
        if file_path.exists() and not force:
            existing = self._load_parquet(file_path)
            if existing is not None and len(existing) > 0:
                last_date = existing.index.max()
                if last_date.strftime("%Y-%m-%d") >= end_date:
                    return existing
                # 증분 업데이트
                start_date = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
        
        try:
            df = fdr.DataReader(code, start_date, end_date)
            
            if df is None or len(df) == 0:
                logger.warning(f"{code}: 데이터 없음")
                return None
            
            # 컬럼명 표준화
            df = df.rename(columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
                "Change": "change"
            })
            
            # 기존 데이터와 병합
            if file_path.exists() and not force:
                existing = self._load_parquet(file_path)
                if existing is not None:
                    df = pd.concat([existing, df])
                    df = df[~df.index.duplicated(keep="last")]
                    df = df.sort_index()
            
            # 저장
            self._save_parquet(df, file_path)
            return df
            
        except Exception as e:
            logger.error(f"{code}: 다운로드 오류 - {e}")
            return None
    
    def download_all_stocks(
        self,
        market: str = "ALL",
        start_date: str = "2015-01-01",
        end_date: Optional[str] = None,
        force: bool = False,
        progress_callback: Optional[callable] = None
    ) -> dict:
        """
        전체 종목 데이터 다운로드
        
        Args:
            market: KOSPI, KOSDAQ, or ALL
            start_date: 시작일
            end_date: 종료일
            force: 강제 재다운로드
            progress_callback: 진행 상황 콜백 함수
            
        Returns:
            결과 요약 딕셔너리
        """
        stocks = self.get_stock_list(market)
        total = len(stocks)
        success = 0
        failed = 0
        skipped = 0
        
        logger.info(f"총 {total}개 종목 다운로드 시작...")
        
        for idx, row in stocks.iterrows():
            code = row["Code"]
            name = row["Name"]
            
            if progress_callback:
                progress_callback(idx + 1, total, code, name)
            
            result = self.download_stock_data(
                code=code,
                start_date=start_date,
                end_date=end_date,
                force=force
            )
            
            if result is not None:
                success += 1
            else:
                failed += 1
        
        summary = {
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped
        }
        
        logger.info(f"다운로드 완료: 성공 {success}, 실패 {failed}")
        return summary
    
    def load_stock_data(self, code: str) -> Optional[pd.DataFrame]:
        """저장된 종목 데이터 로드"""
        file_path = self._get_file_path(code)
        if not file_path.exists():
            return None
        return self._load_parquet(file_path)
    
    def get_market_data(
        self,
        date: str,
        market: str = "ALL"
    ) -> pd.DataFrame:
        """
        특정 날짜의 전체 시장 데이터 가져오기
        
        Args:
            date: 조회 날짜 (YYYY-MM-DD)
            market: KOSPI, KOSDAQ, or ALL
            
        Returns:
            해당 날짜 전 종목 데이터 DataFrame
        """
        stocks = self.get_stock_list(market)
        results = []
        
        for _, row in stocks.iterrows():
            code = row["Code"]
            data = self.load_stock_data(code)
            
            if data is None:
                continue
            
            try:
                if date in data.index.strftime("%Y-%m-%d").values:
                    day_data = data.loc[date].copy()
                    day_data["code"] = code
                    day_data["name"] = row["Name"]
                    day_data["market"] = row["Market"]
                    results.append(day_data)
            except (KeyError, TypeError):
                continue
        
        if not results:
            return pd.DataFrame()
        
        return pd.DataFrame(results)
    
    def get_index_data(
        self,
        index: str = "KOSPI",
        start_date: str = "2015-01-01",
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        지수 데이터 가져오기
        
        Args:
            index: KOSPI, KOSDAQ
            start_date: 시작일
            end_date: 종료일
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        file_path = self.data_dir / f"INDEX_{index}.parquet"
        
        if file_path.exists():
            existing = self._load_parquet(file_path)
            last_date = existing.index.max()
            if last_date.strftime("%Y-%m-%d") >= end_date:
                return existing
        
        # 지수 코드 매핑
        index_codes = {
            "KOSPI": "KS11",
            "KOSDAQ": "KQ11"
        }
        
        code = index_codes.get(index, index)
        df = fdr.DataReader(code, start_date, end_date)
        
        if df is not None and len(df) > 0:
            self._save_parquet(df, file_path)
        
        return df
    
    def _get_file_path(self, code: str) -> Path:
        """종목 코드에 해당하는 파일 경로"""
        return self.data_dir / f"{code}.parquet"
    
    def _save_parquet(self, df: pd.DataFrame, path: Path):
        """Parquet 형식으로 저장"""
        df.to_parquet(path, engine="pyarrow", compression="snappy")
    
    def _load_parquet(self, path: Path) -> Optional[pd.DataFrame]:
        """Parquet 파일 로드"""
        try:
            return pd.read_parquet(path, engine="pyarrow")
        except Exception as e:
            logger.error(f"파일 로드 오류: {path} - {e}")
            return None
    
    def get_data_stats(self) -> dict:
        """저장된 데이터 통계"""
        parquet_files = list(self.data_dir.glob("*.parquet"))
        
        total_size = sum(f.stat().st_size for f in parquet_files)
        stock_files = [f for f in parquet_files if not f.name.startswith("INDEX_")]
        
        return {
            "total_stocks": len(stock_files),
            "total_files": len(parquet_files),
            "total_size_mb": total_size / (1024 * 1024),
            "data_dir": str(self.data_dir)
        }
