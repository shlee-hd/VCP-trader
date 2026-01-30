"""
VCP Pattern Scanner

전체 종목을 스캔하여 VCP 패턴을 탐지하고 알림을 발송합니다.

Usage:
    python -m scripts.run_scanner
    python -m scripts.run_scanner --market KOSPI
    python -m scripts.run_scanner --once  # 1회 실행
"""

import argparse
import asyncio
from datetime import datetime, time
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.core.config import settings
from src.core.database import MarketType
from src.data.broker_client import KISBrokerClient
from src.data.data_fetcher import DataFetcher, get_sample_symbols
from src.patterns.trend_template import TrendTemplate
from src.patterns.vcp_detector import VCPDetector
from src.patterns.rs_calculator import RSCalculator
from src.alerts.notifier import Notifier


class VCPScanner:
    """
    VCP 패턴 스캐너
    
    전체 종목을 스캔하여:
    1. Trend Template 통과 종목 필터링
    2. VCP 패턴 탐지
    3. 알림 발송
    """
    
    def __init__(
        self,
        market: MarketType = MarketType.KOSPI,
        min_rs_rating: int = None,
        min_vcp_score: int = None,
    ):
        self.market = market
        self.min_rs_rating = min_rs_rating or settings.min_rs_rating
        self.min_vcp_score = min_vcp_score or settings.min_vcp_score
        
        # 컴포넌트 초기화
        self.broker: KISBrokerClient = None
        self.fetcher: DataFetcher = None
        self.trend_template = TrendTemplate(min_rs_rating=self.min_rs_rating)
        self.vcp_detector = VCPDetector()
        self.rs_calculator = RSCalculator()
        self.notifier: Notifier = None
        
        self._is_running = False
    
    async def initialize(self):
        """스캐너를 초기화합니다."""
        logger.info(f"Initializing VCP Scanner for {self.market.value}...")
        
        self.broker = KISBrokerClient()
        await self.broker.initialize()
        
        self.fetcher = DataFetcher(broker_client=self.broker)
        await self.fetcher.initialize()
        
        self.notifier = Notifier()
        await self.notifier.initialize()
        
        logger.info("VCP Scanner initialized successfully")
    
    async def close(self):
        """리소스를 정리합니다."""
        if self.fetcher:
            await self.fetcher.close()
        if self.broker:
            await self.broker.close()
    
    async def scan(self) -> dict:
        """
        전체 종목을 스캔합니다.
        
        Returns:
            스캔 결과 딕셔너리
        """
        scan_start = datetime.now()
        logger.info(f"Starting VCP scan at {scan_start}")
        
        # 1. 종목 리스트 가져오기
        symbols_info = get_sample_symbols(self.market)
        symbols = [s["symbol"] for s in symbols_info]
        symbol_names = {s["symbol"]: s["name"] for s in symbols_info}
        
        logger.info(f"Scanning {len(symbols)} symbols in {self.market.value}")
        
        # 2. 데이터 수집 (1년치)
        stock_data = await self.fetcher.fetch_batch(symbols, days=365)
        logger.info(f"Fetched data for {len(stock_data)} symbols")
        
        # 3. RS Rating 계산
        rs_ratings = self.rs_calculator.calculate_ratings(stock_data)
        rs_dict = {symbol: result.rs_rating for symbol, result in rs_ratings.items()}
        
        # 4. Trend Template 필터링
        trend_results = self.trend_template.analyze_batch(stock_data, rs_dict)
        passing_stocks = [r for r in trend_results if r.passes]
        
        logger.info(
            f"Trend Template: {len(passing_stocks)}/{len(trend_results)} stocks pass"
        )
        
        # 5. VCP 패턴 탐지 (Trend Template 통과 종목만)
        vcp_candidates = []
        for trend_result in passing_stocks:
            symbol = trend_result.symbol
            df = stock_data.get(symbol)
            
            if df is None or df.empty:
                continue
            
            vcp_pattern = self.vcp_detector.detect(df, symbol)
            
            if vcp_pattern.detected:
                vcp_candidates.append({
                    "symbol": symbol,
                    "name": symbol_names.get(symbol, symbol),
                    "rs_rating": trend_result.rs_rating,
                    "trend_score": trend_result.score,
                    "vcp_score": vcp_pattern.score,
                    "pivot_price": vcp_pattern.pivot_price,
                    "contractions": vcp_pattern.num_contractions,
                    "tightening": vcp_pattern.tightening_quality,
                    "ideal_buy": vcp_pattern.ideal_buy_point,
                    "stop_loss": vcp_pattern.stop_loss_price,
                    "pattern": vcp_pattern,
                })
        
        # VCP 점수순 정렬
        vcp_candidates.sort(key=lambda x: x["vcp_score"], reverse=True)
        
        logger.info(f"VCP Patterns detected: {len(vcp_candidates)}")
        
        # 6. 알림 발송
        for candidate in vcp_candidates:
            await self.notifier.send_vcp_alert(
                symbol=f"{candidate['symbol']} ({candidate['name']})",
                score=candidate["vcp_score"],
                pivot_price=candidate["pivot_price"],
                contractions=candidate["contractions"],
                tightening_quality=candidate["tightening"],
            )
        
        scan_end = datetime.now()
        scan_duration = (scan_end - scan_start).total_seconds()
        
        result = {
            "scan_time": scan_start.isoformat(),
            "duration_seconds": scan_duration,
            "market": self.market.value,
            "total_scanned": len(symbols),
            "trend_template_pass": len(passing_stocks),
            "vcp_detected": len(vcp_candidates),
            "candidates": vcp_candidates,
        }
        
        logger.info(
            f"Scan completed in {scan_duration:.1f}s: "
            f"{len(vcp_candidates)} VCP candidates found"
        )
        
        return result
    
    async def run_scheduler(self, scan_times: list[time] = None):
        """
        스케줄러를 실행합니다.
        
        Args:
            scan_times: 스캔 실행 시간 리스트 (기본: 08:50, 15:40)
        """
        scan_times = scan_times or [
            time(8, 50),   # 장 시작 전
            time(15, 40),  # 장 마감 전
        ]
        
        self._is_running = True
        logger.info(f"Scanner scheduler started. Scan times: {scan_times}")
        
        while self._is_running:
            now = datetime.now()
            current_time = now.time()
            
            # 다음 스캔 시간 계산
            for scan_time in sorted(scan_times):
                if current_time < scan_time:
                    next_scan = datetime.combine(now.date(), scan_time)
                    break
            else:
                # 오늘 스캔 모두 완료, 내일 첫 스캔
                from datetime import timedelta
                next_scan = datetime.combine(
                    now.date() + timedelta(days=1),
                    sorted(scan_times)[0]
                )
            
            wait_seconds = (next_scan - now).total_seconds()
            
            logger.info(f"Next scan at {next_scan}, waiting {wait_seconds/60:.1f} minutes")
            
            # 대기
            try:
                await asyncio.sleep(wait_seconds)
                await self.scan()
            except asyncio.CancelledError:
                logger.info("Scanner scheduler cancelled")
                break
            except Exception as e:
                logger.error(f"Scan error: {e}")
                await self.notifier.send_error_alert(str(e))
                await asyncio.sleep(60)  # 에러 시 1분 대기
    
    def stop(self):
        """스케줄러를 중지합니다."""
        self._is_running = False


def print_result_table(result: dict):
    """스캔 결과를 테이블 형태로 출력합니다."""
    candidates = result.get("candidates", [])
    
    if not candidates:
        print("\n📭 No VCP patterns detected")
        return
    
    print("\n" + "=" * 80)
    print(f"🎯 VCP SCAN RESULTS - {result['scan_time']}")
    print("=" * 80)
    print(f"  Market: {result['market']}")
    print(f"  Scanned: {result['total_scanned']} → Trend Template: {result['trend_template_pass']} → VCP: {result['vcp_detected']}")
    print("-" * 80)
    print(f"{'Symbol':<12} {'Name':<15} {'RS':>4} {'VCP':>4} {'Contr':>5} {'Pivot':>10} {'Tight':<10}")
    print("-" * 80)
    
    for c in candidates:
        print(
            f"{c['symbol']:<12} "
            f"{c['name'][:15]:<15} "
            f"{c['rs_rating']:>4} "
            f"{c['vcp_score']:>4} "
            f"{c['contractions']:>5} "
            f"{c['pivot_price']:>10,.0f} "
            f"{c['tightening']:<10}"
        )
    
    print("=" * 80)


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="VCP Pattern Scanner")
    parser.add_argument(
        "--market",
        type=str,
        default="KOSPI",
        choices=["KOSPI", "KOSDAQ"],
        help="Market to scan",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (no scheduler)",
    )
    parser.add_argument(
        "--min-rs",
        type=int,
        default=None,
        help="Minimum RS Rating",
    )
    parser.add_argument(
        "--min-vcp",
        type=int,
        default=None,
        help="Minimum VCP Score",
    )
    args = parser.parse_args()
    
    # 마켓 타입 변환
    market = MarketType.KOSPI if args.market == "KOSPI" else MarketType.KOSDAQ
    
    # 스캐너 초기화
    scanner = VCPScanner(
        market=market,
        min_rs_rating=args.min_rs,
        min_vcp_score=args.min_vcp,
    )
    
    try:
        await scanner.initialize()
        
        if args.once:
            # 1회 실행
            result = await scanner.scan()
            print_result_table(result)
        else:
            # 스케줄러 실행
            await scanner.run_scheduler()
    
    except KeyboardInterrupt:
        logger.info("Scanner stopped by user")
    finally:
        await scanner.close()


if __name__ == "__main__":
    # 로깅 설정
    logger.add(
        "logs/scanner_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )
    
    asyncio.run(main())
