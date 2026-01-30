#!/usr/bin/env python3
"""
Historical Data Download Script

10년간의 한국 시장 히스토리컬 데이터를 다운로드합니다.

Usage:
    python scripts/download_history.py --years 10 --market ALL
    python scripts/download_history.py --years 5 --market KOSPI
"""

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.historical_data import HistoricalDataManager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("data_download.log")
    ]
)
logger = logging.getLogger(__name__)


def progress_callback(current: int, total: int, code: str, name: str):
    """다운로드 진행 상황 출력"""
    pct = (current / total) * 100
    bar_len = 30
    filled = int(bar_len * current / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r[{bar}] {pct:5.1f}% ({current}/{total}) {code} {name[:10]:10}", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="한국 시장 히스토리컬 데이터 다운로드"
    )
    parser.add_argument(
        "--years",
        type=int,
        default=10,
        help="다운로드할 과거 데이터 기간 (년, 기본: 10)"
    )
    parser.add_argument(
        "--market",
        type=str,
        default="ALL",
        choices=["KOSPI", "KOSDAQ", "ALL"],
        help="대상 시장 (기본: ALL)"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/historical",
        help="데이터 저장 디렉토리 (기본: data/historical)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="기존 데이터 무시하고 전체 재다운로드"
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="지수 데이터만 다운로드"
    )
    
    args = parser.parse_args()
    
    # 날짜 계산
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=365 * args.years)).strftime("%Y-%m-%d")
    
    logger.info("=" * 60)
    logger.info("📊 한국 시장 히스토리컬 데이터 다운로더")
    logger.info("=" * 60)
    logger.info(f"기간: {start_date} ~ {end_date} ({args.years}년)")
    logger.info(f"시장: {args.market}")
    logger.info(f"저장 경로: {args.data_dir}")
    logger.info(f"강제 재다운로드: {args.force}")
    logger.info("=" * 60)
    
    # 데이터 매니저 초기화
    manager = HistoricalDataManager(data_dir=args.data_dir)
    
    # 지수 데이터 다운로드
    logger.info("\n📈 지수 데이터 다운로드 중...")
    for index in ["KOSPI", "KOSDAQ"]:
        try:
            data = manager.get_index_data(index, start_date, end_date)
            logger.info(f"  {index}: {len(data)} 거래일 데이터")
        except Exception as e:
            logger.error(f"  {index}: 다운로드 실패 - {e}")
    
    if args.index_only:
        logger.info("지수 데이터만 다운로드 완료")
        return
    
    # 전체 종목 다운로드
    logger.info(f"\n📥 {args.market} 종목 데이터 다운로드 시작...")
    print()  # 프로그레스 바를 위한 새 줄
    
    result = manager.download_all_stocks(
        market=args.market,
        start_date=start_date,
        end_date=end_date,
        force=args.force,
        progress_callback=progress_callback
    )
    
    print()  # 프로그레스 바 후 새 줄
    
    # 결과 출력
    logger.info("\n" + "=" * 60)
    logger.info("✅ 다운로드 완료")
    logger.info("=" * 60)
    logger.info(f"전체 종목: {result['total']}")
    logger.info(f"성공: {result['success']}")
    logger.info(f"실패: {result['failed']}")
    
    # 저장 통계
    stats = manager.get_data_stats()
    logger.info(f"\n📁 저장 통계:")
    logger.info(f"  저장된 종목 수: {stats['total_stocks']}")
    logger.info(f"  총 파일 크기: {stats['total_size_mb']:.1f} MB")
    logger.info(f"  저장 경로: {stats['data_dir']}")


if __name__ == "__main__":
    main()
