"""
Backtest Engine - VCP 전략 백테스팅 엔진

과거 데이터를 기반으로 VCP 전략을 시뮬레이션하고 성과를 계산합니다.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd
import numpy as np

# 직접 모듈 임포트 (DB 의존성 회피)
from src.patterns.trend_template import TrendTemplate
from src.patterns.vcp_detector import VCPDetector
from src.patterns.rs_calculator import RSCalculator
from src.trading.stop_loss import StopLossManager
from src.trading.risk_manager import RiskManager
from src.backtesting.historical_data import HistoricalDataManager

logger = logging.getLogger(__name__)


class TradeAction(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Trade:
    """개별 거래 기록"""
    entry_date: datetime
    exit_date: Optional[datetime]
    symbol: str
    name: str
    action: TradeAction
    entry_price: float
    exit_price: Optional[float]
    shares: int
    stop_loss: float
    exit_reason: Optional[str] = None
    
    @property
    def pnl(self) -> float:
        """손익 (수익금액)"""
        if self.exit_price is None:
            return 0.0
        return (self.exit_price - self.entry_price) * self.shares
    
    @property
    def pnl_pct(self) -> float:
        """손익률 (%)"""
        if self.exit_price is None:
            return 0.0
        return ((self.exit_price / self.entry_price) - 1) * 100
    
    @property
    def holding_days(self) -> int:
        """보유 기간 (일)"""
        if self.exit_date is None:
            return 0
        return (self.exit_date - self.entry_date).days


@dataclass
class Position:
    """오픈 포지션"""
    trade: Trade
    current_price: float
    highest_price: float
    stop_loss: float
    
    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.trade.entry_price) * self.trade.shares
    
    @property
    def unrealized_pnl_pct(self) -> float:
        return ((self.current_price / self.trade.entry_price) - 1) * 100


@dataclass
class DailySnapshot:
    """일별 포트폴리오 스냅샷"""
    date: datetime
    cash: float
    positions_value: float
    total_value: float
    positions_count: int
    daily_pnl: float
    daily_pnl_pct: float


@dataclass
class BacktestResult:
    """백테스트 결과"""
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_capital: float
    trades: List[Trade]
    daily_snapshots: List[DailySnapshot]
    parameters: Dict[str, Any]
    
    @property
    def total_return(self) -> float:
        return ((self.final_capital / self.initial_capital) - 1) * 100
    
    @property
    def trade_count(self) -> int:
        return len([t for t in self.trades if t.exit_date is not None])


class BacktestEngine:
    """
    VCP 전략 백테스팅 엔진
    
    주요 기능:
    - 과거 데이터 시뮬레이션
    - VCP 패턴 감지 및 진입
    - 트레일링 스탑 적용
    - 포트폴리오 가치 추적
    """
    
    def __init__(
        self,
        data_manager: HistoricalDataManager,
        initial_capital: float = 100_000_000,  # 1억 원
        max_positions: int = 10,
        risk_per_trade: float = 0.01,  # 1% 리스크
        commission_rate: float = 0.00015,  # 0.015%
        slippage_rate: float = 0.001,  # 0.1% 슬리피지
    ):
        self.data_manager = data_manager
        self.initial_capital = initial_capital
        self.max_positions = max_positions
        self.risk_per_trade = risk_per_trade
        self.commission_rate = commission_rate
        self.slippage_rate = slippage_rate
        
        # 컴포넌트 초기화
        self.trend_template = TrendTemplate()
        self.vcp_detector = VCPDetector()
        self.rs_calculator = RSCalculator()
        self.stop_loss_manager = StopLossManager()
        self.risk_manager = RiskManager(
            max_risk_per_trade=risk_per_trade,
            max_positions=max_positions
        )
        
        # 상태 변수
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.daily_snapshots: List[DailySnapshot] = []
        
    def run(
        self,
        start_date: str,
        end_date: str,
        market: str = "ALL",
        min_rs_rating: float = 70.0,
        min_vcp_score: float = 60.0,
        progress_callback: Optional[callable] = None
    ) -> BacktestResult:
        """
        백테스트 실행
        
        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일
            market: KOSPI, KOSDAQ, or ALL
            min_rs_rating: 최소 RS Rating
            min_vcp_score: 최소 VCP 점수
            progress_callback: 진행 콜백
            
        Returns:
            BacktestResult 객체
        """
        logger.info(f"백테스트 시작: {start_date} ~ {end_date}")
        
        # 초기화
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.daily_snapshots = []
        
        # 지수 데이터 (RS 계산용)
        index_data = self.data_manager.get_index_data("KOSPI", start_date, end_date)
        
        # 종목 리스트
        stocks = self.data_manager.get_stock_list(market)
        
        # 날짜 범위 생성
        date_range = pd.date_range(start=start_date, end=end_date, freq="B")
        total_days = len(date_range)
        
        prev_total_value = self.initial_capital
        
        for day_idx, current_date in enumerate(date_range):
            date_str = current_date.strftime("%Y-%m-%d")
            
            if progress_callback:
                progress_callback(day_idx + 1, total_days, date_str)
            
            # 1. 기존 포지션 업데이트 및 스탑로스 체크
            self._update_positions(current_date)
            
            # 2. 신규 진입 신호 스캔
            if len(self.positions) < self.max_positions:
                signals = self._scan_for_signals(
                    stocks=stocks,
                    current_date=current_date,
                    index_data=index_data,
                    min_rs_rating=min_rs_rating,
                    min_vcp_score=min_vcp_score
                )
                
                # 상위 신호로 진입
                for signal in signals[:self.max_positions - len(self.positions)]:
                    self._execute_entry(signal, current_date)
            
            # 3. 일별 스냅샷 저장
            total_value = self._calculate_portfolio_value()
            daily_pnl = total_value - prev_total_value
            daily_pnl_pct = (daily_pnl / prev_total_value) * 100 if prev_total_value > 0 else 0
            
            snapshot = DailySnapshot(
                date=current_date,
                cash=self.cash,
                positions_value=sum(p.current_price * p.trade.shares for p in self.positions.values()),
                total_value=total_value,
                positions_count=len(self.positions),
                daily_pnl=daily_pnl,
                daily_pnl_pct=daily_pnl_pct
            )
            self.daily_snapshots.append(snapshot)
            prev_total_value = total_value
        
        # 남은 포지션 청산
        self._close_all_positions(date_range[-1], "백테스트 종료")
        
        # 결과 생성
        result = BacktestResult(
            start_date=pd.Timestamp(start_date),
            end_date=pd.Timestamp(end_date),
            initial_capital=self.initial_capital,
            final_capital=self._calculate_portfolio_value(),
            trades=self.trades,
            daily_snapshots=self.daily_snapshots,
            parameters={
                "max_positions": self.max_positions,
                "risk_per_trade": self.risk_per_trade,
                "min_rs_rating": min_rs_rating,
                "min_vcp_score": min_vcp_score,
                "commission_rate": self.commission_rate,
                "slippage_rate": self.slippage_rate
            }
        )
        
        logger.info(f"백테스트 완료: 총 수익률 {result.total_return:.2f}%")
        return result
    
    def _scan_for_signals(
        self,
        stocks: pd.DataFrame,
        current_date: datetime,
        index_data: pd.DataFrame,
        min_rs_rating: float,
        min_vcp_score: float
    ) -> List[Dict]:
        """VCP 신호 스캔"""
        signals = []
        
        for _, stock in stocks.iterrows():
            code = stock["Code"]
            name = stock["Name"]
            
            # 이미 보유 중인 종목 스킵
            if code in self.positions:
                continue
            
            # 데이터 로드
            data = self.data_manager.load_stock_data(code)
            if data is None or len(data) < 200:
                continue
            
            # 현재 날짜까지의 데이터만 사용
            data = data[data.index <= current_date]
            if len(data) < 200:
                continue
            
            try:
                # Trend Template 체크
                tt_result = self.trend_template.check(data)
                if not tt_result.passes:
                    continue
                
                # RS Rating 계산
                rs_rating = self.rs_calculator.calculate(data, index_data)
                if rs_rating < min_rs_rating:
                    continue
                
                # VCP 패턴 감지
                vcp_result = self.vcp_detector.detect(data)
                if vcp_result is None or vcp_result.score < min_vcp_score:
                    continue
                
                # 신호 추가
                signals.append({
                    "code": code,
                    "name": name,
                    "price": data["close"].iloc[-1],
                    "vcp_score": vcp_result.score,
                    "rs_rating": rs_rating,
                    "pivot_price": vcp_result.pivot_price,
                    "stop_loss": vcp_result.stop_loss_price
                })
                
            except Exception as e:
                logger.debug(f"{code} 분석 오류: {e}")
                continue
        
        # VCP 점수 + RS Rating으로 정렬
        signals.sort(key=lambda x: x["vcp_score"] + x["rs_rating"], reverse=True)
        return signals
    
    def _execute_entry(self, signal: Dict, current_date: datetime):
        """진입 실행"""
        entry_price = signal["price"] * (1 + self.slippage_rate)  # 슬리피지 적용
        stop_loss = signal["stop_loss"]
        
        # 포지션 사이징
        position_size = self.risk_manager.calculate_position_size(
            account_value=self._calculate_portfolio_value(),
            entry_price=entry_price,
            stop_price=stop_loss,
            current_positions=len(self.positions)
        )
        
        shares = position_size.recommended_shares
        if shares <= 0:
            return
        
        # 비용 계산
        cost = entry_price * shares
        commission = cost * self.commission_rate
        total_cost = cost + commission
        
        if total_cost > self.cash:
            shares = int((self.cash * 0.95) / entry_price)  # 95%만 사용
            if shares <= 0:
                return
            cost = entry_price * shares
            commission = cost * self.commission_rate
            total_cost = cost + commission
        
        # 거래 기록
        trade = Trade(
            entry_date=current_date,
            exit_date=None,
            symbol=signal["code"],
            name=signal["name"],
            action=TradeAction.BUY,
            entry_price=entry_price,
            exit_price=None,
            shares=shares,
            stop_loss=stop_loss
        )
        
        # 포지션 생성
        position = Position(
            trade=trade,
            current_price=entry_price,
            highest_price=entry_price,
            stop_loss=stop_loss
        )
        
        self.positions[signal["code"]] = position
        self.cash -= total_cost
        
        logger.debug(f"진입: {signal['name']} @ {entry_price:,.0f} x {shares}주")
    
    def _update_positions(self, current_date: datetime):
        """포지션 업데이트 및 스탑로스 체크"""
        to_close = []
        
        for code, position in self.positions.items():
            data = self.data_manager.load_stock_data(code)
            if data is None:
                continue
            
            # 현재 날짜 데이터
            try:
                day_data = data.loc[current_date.strftime("%Y-%m-%d")]
                current_price = day_data["close"]
                low_price = day_data["low"]
            except (KeyError, TypeError):
                continue
            
            # 가격 업데이트
            position.current_price = current_price
            if current_price > position.highest_price:
                position.highest_price = current_price
            
            # 트레일링 스탑 업데이트
            new_stop = self.stop_loss_manager.update_stop(
                entry_price=position.trade.entry_price,
                current_price=current_price,
                highest_price=position.highest_price,
                current_stop=position.stop_loss
            )
            position.stop_loss = new_stop.stop_price
            
            # 스탑로스 체크 (당일 저가 기준)
            if low_price <= position.stop_loss:
                to_close.append((code, position.stop_loss, "스탑로스"))
        
        # 포지션 청산
        for code, exit_price, reason in to_close:
            self._close_position(code, current_date, exit_price, reason)
    
    def _close_position(
        self,
        code: str,
        date: datetime,
        exit_price: float,
        reason: str
    ):
        """포지션 청산"""
        if code not in self.positions:
            return
        
        position = self.positions[code]
        trade = position.trade
        
        # 슬리피지 및 수수료 적용
        actual_exit = exit_price * (1 - self.slippage_rate)
        proceeds = actual_exit * trade.shares
        commission = proceeds * self.commission_rate
        net_proceeds = proceeds - commission
        
        # 거래 완료
        trade.exit_date = date
        trade.exit_price = actual_exit
        trade.exit_reason = reason
        
        self.trades.append(trade)
        self.cash += net_proceeds
        del self.positions[code]
        
        logger.debug(f"청산: {trade.name} @ {actual_exit:,.0f} ({reason}) PnL: {trade.pnl_pct:.1f}%")
    
    def _close_all_positions(self, date: datetime, reason: str):
        """모든 포지션 청산"""
        codes = list(self.positions.keys())
        for code in codes:
            position = self.positions[code]
            self._close_position(code, date, position.current_price, reason)
    
    def _calculate_portfolio_value(self) -> float:
        """포트폴리오 총 가치 계산"""
        positions_value = sum(
            p.current_price * p.trade.shares
            for p in self.positions.values()
        )
        return self.cash + positions_value
