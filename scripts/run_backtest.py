#!/usr/bin/env python3
"""
VCP Backtest Runner

VCP 전략 백테스트를 실행하고 리포트를 생성합니다.

Usage:
    python scripts/run_backtest.py --start 2015-01-01 --end 2024-12-31
    python scripts/run_backtest.py --start 2020-01-01 --end 2023-12-31 --capital 50000000
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtesting.historical_data import HistoricalDataManager
from src.backtesting.backtest_engine import BacktestEngine
from src.backtesting.performance_analyzer import PerformanceAnalyzer
from src.backtesting.backtest_report import BacktestReporter

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("backtest.log")
    ]
)
logger = logging.getLogger(__name__)


def progress_callback(current: int, total: int, date: str):
    """백테스트 진행 상황"""
    pct = (current / total) * 100
    bar_len = 40
    filled = int(bar_len * current / total)
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r[{bar}] {pct:5.1f}% {date}", end="", flush=True)


def main():
    parser = argparse.ArgumentParser(
        description="VCP 전략 백테스트 실행"
    )
    parser.add_argument(
        "--start",
        type=str,
        default="2015-01-01",
        help="시작일 (YYYY-MM-DD, 기본: 2015-01-01)"
    )
    parser.add_argument(
        "--end",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="종료일 (YYYY-MM-DD, 기본: 오늘)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100_000_000,
        help="초기 자본금 (원, 기본: 1억)"
    )
    parser.add_argument(
        "--market",
        type=str,
        default="ALL",
        choices=["KOSPI", "KOSDAQ", "ALL"],
        help="대상 시장 (기본: ALL)"
    )
    parser.add_argument(
        "--max-positions",
        type=int,
        default=10,
        help="최대 동시 보유 종목 수 (기본: 10)"
    )
    parser.add_argument(
        "--risk-per-trade",
        type=float,
        default=0.01,
        help="거래당 리스크 비율 (기본: 0.01 = 1%%)"
    )
    parser.add_argument(
        "--min-rs",
        type=float,
        default=70.0,
        help="최소 RS Rating (기본: 70)"
    )
    parser.add_argument(
        "--min-vcp",
        type=float,
        default=60.0,
        help="최소 VCP 점수 (기본: 60)"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data/historical",
        help="히스토리컬 데이터 디렉토리 (기본: data/historical)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="results",
        help="리포트 출력 디렉토리 (기본: results)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="출력 파일명 (기본: backtest_YYYYMMDD_HHMMSS.html)"
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="HTML 리포트 생성 건너뛰기"
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="상세 로깅 활성화"
    )
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # 헤더 출력
    print()
    print("=" * 70)
    print("📊 VCP 전략 백테스트")
    print("=" * 70)
    print(f"  기간: {args.start} ~ {args.end}")
    print(f"  초기 자본: ₩{args.capital:,.0f}")
    print(f"  시장: {args.market}")
    print(f"  최대 포지션: {args.max_positions}")
    print(f"  거래당 리스크: {args.risk_per_trade * 100:.1f}%")
    print(f"  최소 RS Rating: {args.min_rs}")
    print(f"  최소 VCP 점수: {args.min_vcp}")
    print("=" * 70)
    print()
    
    # 데이터 확인
    data_manager = HistoricalDataManager(data_dir=args.data_dir)
    stats = data_manager.get_data_stats()
    
    if stats["total_stocks"] == 0:
        logger.error("❌ 히스토리컬 데이터가 없습니다!")
        logger.error("먼저 데이터를 다운로드하세요:")
        logger.error("  python scripts/download_history.py --years 10")
        sys.exit(1)
    
    logger.info(f"📂 로드된 데이터: {stats['total_stocks']}개 종목 ({stats['total_size_mb']:.1f} MB)")
    
    # 백테스트 엔진 초기화
    engine = BacktestEngine(
        data_manager=data_manager,
        initial_capital=args.capital,
        max_positions=args.max_positions,
        risk_per_trade=args.risk_per_trade
    )
    
    # 백테스트 실행
    logger.info("\n🚀 백테스트 시작...")
    print()
    
    result = engine.run(
        start_date=args.start,
        end_date=args.end,
        market=args.market,
        min_rs_rating=args.min_rs,
        min_vcp_score=args.min_vcp,
        progress_callback=progress_callback
    )
    
    print()  # 프로그레스 바 후 새 줄
    print()
    
    # 성과 분석
    analyzer = PerformanceAnalyzer()
    metrics = analyzer.analyze(result)
    
    # 결과 출력
    analyzer.print_summary(metrics)
    
    # HTML 리포트 생성
    if not args.no_report:
        reporter = BacktestReporter(output_dir=args.output_dir)
        report_path = reporter.generate_report(result, filename=args.output)
        
        print(f"\n📄 리포트 생성: {report_path}")
        print(f"   브라우저에서 열기: file://{Path(report_path).absolute()}")
    
    # 요약 출력
    print("\n" + "=" * 70)
    print("✅ 백테스트 완료")
    print("=" * 70)
    print(f"  초기 자본: ₩{result.initial_capital:,.0f}")
    print(f"  최종 자산: ₩{result.final_capital:,.0f}")
    print(f"  총 수익률: {result.total_return:+.2f}%")
    print(f"  CAGR: {metrics.cagr:+.2f}%")
    print(f"  MDD: {metrics.max_drawdown:.2f}%")
    print(f"  샤프 비율: {metrics.sharpe_ratio:.2f}")
    print(f"  거래 횟수: {metrics.total_trades}")
    print(f"  승률: {metrics.win_rate:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
