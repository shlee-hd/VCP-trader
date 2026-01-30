"""
VCP Auto Trader

VCP 패턴 기반 자동 트레이딩 봇

기능:
- VCP 패턴 탐지 시 자동 진입
- 다층 트레일링 스탑 관리
- 포지션 모니터링 및 청산

Usage:
    python -m scripts.run_trader
    python -m scripts.run_trader --dry-run  # 실제 주문 없이 테스트
"""

import argparse
import asyncio
from datetime import datetime, time
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from src.core.config import settings
from src.core.database import MarketType, PositionStatus
from src.data.broker_client import KISBrokerClient
from src.data.data_fetcher import DataFetcher, get_sample_symbols
from src.patterns.trend_template import TrendTemplate
from src.patterns.vcp_detector import VCPDetector
from src.patterns.rs_calculator import RSCalculator
from src.trading.stop_loss import StopLossManager
from src.trading.risk_manager import RiskManager
from src.trading.order_executor import OrderExecutor
from src.alerts.notifier import Notifier


class Position:
    """활성 포지션"""
    def __init__(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        stop_price: float,
        entry_date: datetime = None,
    ):
        self.symbol = symbol
        self.entry_price = entry_price
        self.quantity = quantity
        self.initial_stop_price = stop_price
        self.current_stop_price = stop_price
        self.highest_price = entry_price
        self.trailing_level = 0
        self.entry_date = entry_date or datetime.now()
        self.status = PositionStatus.OPEN


class VCPTrader:
    """
    VCP 자동 트레이더
    
    핵심 기능:
    1. VCP 패턴 스캔 및 진입 신호 감지
    2. 자동 포지션 진입 (리스크 관리 적용)
    3. 실시간 트레일링 스탑 모니터링
    4. 조건 충족 시 자동 청산
    """
    
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        
        # 컴포넌트
        self.broker: KISBrokerClient = None
        self.fetcher: DataFetcher = None
        self.trend_template = TrendTemplate()
        self.vcp_detector = VCPDetector()
        self.rs_calculator = RSCalculator()
        self.stop_loss_manager = StopLossManager()
        self.risk_manager = RiskManager()
        self.order_executor: OrderExecutor = None
        self.notifier: Notifier = None
        
        # 상태
        self.positions: dict[str, Position] = {}  # {symbol: Position}
        self.watchlist: list[dict] = []  # VCP 후보 종목
        self._is_running = False
        self._account_value: float = 0
    
    async def initialize(self):
        """트레이더를 초기화합니다."""
        logger.info(f"Initializing VCP Trader (dry_run={self.dry_run})...")
        
        self.broker = KISBrokerClient()
        await self.broker.initialize()
        
        self.fetcher = DataFetcher(broker_client=self.broker)
        await self.fetcher.initialize()
        
        self.order_executor = OrderExecutor(
            broker_client=self.broker,
            dry_run=self.dry_run,
        )
        
        self.notifier = Notifier()
        await self.notifier.initialize()
        
        # 계좌 정보 조회
        await self._update_account_value()
        
        logger.info(f"VCP Trader initialized. Account value: {self._account_value:,.0f}원")
    
    async def close(self):
        """리소스를 정리합니다."""
        if self.fetcher:
            await self.fetcher.close()
        if self.broker:
            await self.broker.close()
    
    async def _update_account_value(self):
        """계좌 자산을 업데이트합니다."""
        try:
            balance = await self.broker.get_balance()
            self._account_value = balance["total_value"]
            
            # 기존 포지션 로드
            for pos_info in balance["positions"]:
                symbol = pos_info["symbol"]
                if symbol not in self.positions:
                    # 기존 포지션을 불러옴 (손절가는 -7%로 추정)
                    entry_price = pos_info["avg_price"]
                    stop_price = entry_price * (1 - settings.initial_stop_loss / 100)
                    
                    self.positions[symbol] = Position(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=pos_info["quantity"],
                        stop_price=stop_price,
                    )
                    logger.info(f"Loaded existing position: {symbol}")
        except Exception as e:
            logger.error(f"Failed to update account value: {e}")
    
    async def scan_for_entries(self) -> list[dict]:
        """진입 가능한 VCP 패턴을 스캔합니다."""
        logger.info("Scanning for entry opportunities...")
        
        # 종목 리스트
        symbols_info = get_sample_symbols(MarketType.KOSPI)
        symbols_info.extend(get_sample_symbols(MarketType.KOSDAQ))
        symbols = [s["symbol"] for s in symbols_info]
        
        # 데이터 수집
        stock_data = await self.fetcher.fetch_batch(symbols, days=365)
        
        # RS Rating 계산
        rs_ratings = self.rs_calculator.calculate_ratings(stock_data)
        rs_dict = {symbol: result.rs_rating for symbol, result in rs_ratings.items()}
        
        # Trend Template + VCP 필터링
        candidates = []
        
        for symbol, df in stock_data.items():
            # 이미 보유 중이면 스킵
            if symbol in self.positions:
                continue
            
            # Trend Template 체크
            rs_rating = rs_dict.get(symbol)
            trend_result = self.trend_template.analyze(df, symbol, rs_rating)
            
            if not trend_result.passes:
                continue
            
            # VCP 체크
            vcp_pattern = self.vcp_detector.detect(df, symbol)
            
            if not vcp_pattern.detected:
                continue
            
            # 현재가 조회
            try:
                price_info = await self.broker.get_current_price(symbol)
                current_price = price_info["price"]
            except Exception:
                continue
            
            # 피벗 포인트 근접 체크 (피벗의 95~102%)
            pivot = vcp_pattern.pivot_price
            if not (0.95 * pivot <= current_price <= 1.02 * pivot):
                continue
            
            candidates.append({
                "symbol": symbol,
                "current_price": current_price,
                "pivot_price": pivot,
                "vcp_score": vcp_pattern.score,
                "rs_rating": rs_rating,
                "stop_price": vcp_pattern.stop_loss_price,
                "pattern": vcp_pattern,
            })
        
        # VCP 점수순 정렬
        candidates.sort(key=lambda x: x["vcp_score"], reverse=True)
        
        logger.info(f"Found {len(candidates)} entry candidates")
        
        return candidates
    
    async def execute_entries(self, candidates: list[dict]):
        """진입 후보에 대해 주문을 실행합니다."""
        for candidate in candidates:
            symbol = candidate["symbol"]
            
            # 리스크 매니저로 포지션 사이즈 계산
            size_result = self.risk_manager.calculate_position_size(
                symbol=symbol,
                account_value=self._account_value,
                entry_price=candidate["current_price"],
                stop_price=candidate["stop_price"],
                current_positions=len(self.positions),
            )
            
            if size_result.position_size <= 0:
                logger.warning(f"{symbol}: Position size 0 - {size_result.size_limited_by}")
                continue
            
            logger.info(
                f"{symbol}: Entry signal - "
                f"size={size_result.position_size}, "
                f"value={size_result.position_value:,.0f}원"
            )
            
            # 주문 실행
            result = await self.order_executor.buy_market(
                symbol=symbol,
                quantity=size_result.position_size,
                reason=f"VCP Entry (score={candidate['vcp_score']})",
            )
            
            if result.success:
                # 포지션 추가
                entry_price = result.filled_price or candidate["current_price"]
                
                self.positions[symbol] = Position(
                    symbol=symbol,
                    entry_price=entry_price,
                    quantity=size_result.position_size,
                    stop_price=candidate["stop_price"],
                )
                
                # 알림 발송
                await self.notifier.send_entry_alert(
                    symbol=symbol,
                    entry_price=entry_price,
                    quantity=size_result.position_size,
                    stop_price=candidate["stop_price"],
                )
                
                logger.info(f"{symbol}: Entry executed @ {entry_price:,.0f}")
            else:
                logger.error(f"{symbol}: Entry failed - {result.message}")
                await self.notifier.send_error_alert(
                    f"Entry failed for {symbol}: {result.message}"
                )
    
    async def monitor_positions(self):
        """보유 포지션을 모니터링하고 손절/트레일링 스탑을 관리합니다."""
        if not self.positions:
            return
        
        logger.debug(f"Monitoring {len(self.positions)} positions...")
        
        # 현재가 일괄 조회
        symbols = list(self.positions.keys())
        current_prices = await self.fetcher.get_current_prices(symbols)
        
        positions_to_close = []
        
        for symbol, position in self.positions.items():
            current_price = current_prices.get(symbol)
            if current_price is None:
                continue
            
            # 트레일링 스탑 계산
            stop_result = self.stop_loss_manager.calculate_stop(
                symbol=symbol,
                entry_price=position.entry_price,
                current_price=current_price,
                highest_price=position.highest_price,
                current_level=position.trailing_level,
            )
            
            # 상태 업데이트
            position.highest_price = stop_result.highest_price
            position.trailing_level = stop_result.current_level
            position.current_stop_price = stop_result.stop_price
            
            # 청산 필요?
            if stop_result.should_exit:
                positions_to_close.append({
                    "symbol": symbol,
                    "position": position,
                    "current_price": current_price,
                    "exit_reason": stop_result.exit_reason,
                    "profit_pct": stop_result.profit_pct,
                })
            else:
                # 레벨 업그레이드 로그
                if stop_result.current_level > position.trailing_level:
                    logger.info(
                        f"{symbol}: Trailing level upgraded to {stop_result.current_level}, "
                        f"new stop: {stop_result.stop_price:,.0f}"
                    )
        
        # 청산 실행
        for close_info in positions_to_close:
            await self._close_position(**close_info)
    
    async def _close_position(
        self,
        symbol: str,
        position: Position,
        current_price: float,
        exit_reason: str,
        profit_pct: float,
    ):
        """포지션을 청산합니다."""
        logger.warning(
            f"{symbol}: Closing position - {exit_reason}, "
            f"profit={profit_pct:+.1f}%"
        )
        
        # 시장가 매도
        result = await self.order_executor.sell_market(
            symbol=symbol,
            quantity=position.quantity,
            reason=exit_reason,
        )
        
        if result.success:
            exit_price = result.filled_price or current_price
            
            # 알림 발송
            if profit_pct < 0:
                await self.notifier.send_stop_loss_alert(
                    symbol=symbol,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    quantity=position.quantity,
                    loss_pct=profit_pct,
                )
            else:
                await self.notifier.send_trailing_stop_alert(
                    symbol=symbol,
                    entry_price=position.entry_price,
                    highest_price=position.highest_price,
                    exit_price=exit_price,
                    quantity=position.quantity,
                    profit_pct=profit_pct,
                    trailing_level=position.trailing_level,
                )
            
            # 포지션 제거
            del self.positions[symbol]
            
            logger.info(f"{symbol}: Position closed @ {exit_price:,.0f}")
        else:
            logger.error(f"{symbol}: Close failed - {result.message}")
            await self.notifier.send_error_alert(
                f"Failed to close {symbol}: {result.message}"
            )
    
    async def run(self):
        """트레이딩 루프를 실행합니다."""
        self._is_running = True
        
        # 시장 시간 체크 (간단 버전)
        scan_interval = 60 * 30  # 30분
        monitor_interval = 60    # 1분
        
        last_scan = datetime.min
        
        logger.info("VCP Trader started")
        
        while self._is_running:
            try:
                now = datetime.now()
                
                # 계좌 정보 업데이트
                await self._update_account_value()
                
                # 포지션 모니터링 (매분)
                await self.monitor_positions()
                
                # 스탑 주문 확인
                if self.positions:
                    current_prices = await self.fetcher.get_current_prices(
                        list(self.positions.keys())
                    )
                    await self.order_executor.check_stop_orders(current_prices)
                
                # VCP 스캔 (30분 간격)
                if (now - last_scan).total_seconds() >= scan_interval:
                    candidates = await self.scan_for_entries()
                    
                    if candidates:
                        await self.execute_entries(candidates[:3])  # 최대 3개 진입
                    
                    last_scan = now
                
                await asyncio.sleep(monitor_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Trading loop error: {e}")
                await self.notifier.send_error_alert(str(e))
                await asyncio.sleep(60)
        
        logger.info("VCP Trader stopped")
    
    def stop(self):
        """트레이딩을 중지합니다."""
        self._is_running = False


async def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(description="VCP Auto Trader")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without executing real orders",
    )
    args = parser.parse_args()
    
    trader = VCPTrader(dry_run=args.dry_run)
    
    try:
        await trader.initialize()
        await trader.run()
    except KeyboardInterrupt:
        logger.info("Trader stopped by user")
    finally:
        await trader.close()


if __name__ == "__main__":
    logger.add(
        "logs/trader_{time:YYYY-MM-DD}.log",
        rotation="1 day",
        retention="30 days",
        level="DEBUG",
    )
    
    asyncio.run(main())
