"""
Performance Analyzer - 백테스트 성과 분석

주요 지표:
- 총 수익률, CAGR
- 최대 낙폭 (MDD)
- 샤프 비율, 소르티노 비율
- 승률, 손익비
"""

import logging
from typing import List, Optional
from dataclasses import dataclass

import pandas as pd
import numpy as np

from src.backtesting.backtest_engine import BacktestResult, Trade

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """성과 지표"""
    # 수익률 지표
    total_return: float  # 총 수익률 (%)
    cagr: float  # 연환산 수익률 (%)
    
    # 리스크 지표
    max_drawdown: float  # 최대 낙폭 (%)
    volatility: float  # 연간 변동성 (%)
    
    # 위험조정 수익률
    sharpe_ratio: float  # 샤프 비율
    sortino_ratio: float  # 소르티노 비율
    calmar_ratio: float  # 칼마 비율 (CAGR / MDD)
    
    # 거래 통계
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # 승률 (%)
    
    # 손익 분석
    avg_win: float  # 평균 수익 (%)
    avg_loss: float  # 평균 손실 (%)
    profit_factor: float  # 손익비
    expectancy: float  # 기대값 (%)
    
    # 기타
    avg_holding_days: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    
    # 월별/연도별 수익률
    monthly_returns: Optional[pd.Series] = None
    yearly_returns: Optional[pd.Series] = None


class PerformanceAnalyzer:
    """
    백테스트 성과 분석기
    """
    
    def __init__(self, risk_free_rate: float = 0.03):
        """
        Args:
            risk_free_rate: 무위험 수익률 (연간, 기본 3%)
        """
        self.risk_free_rate = risk_free_rate
    
    def analyze(self, result: BacktestResult) -> PerformanceMetrics:
        """
        백테스트 결과 분석
        
        Args:
            result: BacktestResult 객체
            
        Returns:
            PerformanceMetrics
        """
        # 일별 수익률 계산
        daily_values = pd.Series(
            [s.total_value for s in result.daily_snapshots],
            index=[s.date for s in result.daily_snapshots]
        )
        daily_returns = daily_values.pct_change().dropna()
        
        # 기본 수익률 지표
        total_return = result.total_return
        years = (result.end_date - result.start_date).days / 365.25
        cagr = self._calculate_cagr(result.initial_capital, result.final_capital, years)
        
        # 리스크 지표
        max_drawdown = self._calculate_max_drawdown(daily_values)
        volatility = self._calculate_volatility(daily_returns)
        
        # 위험조정 수익률
        sharpe = self._calculate_sharpe_ratio(daily_returns)
        sortino = self._calculate_sortino_ratio(daily_returns)
        calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else 0
        
        # 거래 통계
        completed_trades = [t for t in result.trades if t.exit_date is not None]
        trade_stats = self._analyze_trades(completed_trades)
        
        # 월별/연도별 수익률
        monthly_returns = self._calculate_periodic_returns(daily_values, "M")
        yearly_returns = self._calculate_periodic_returns(daily_values, "Y")
        
        return PerformanceMetrics(
            total_return=total_return,
            cagr=cagr,
            max_drawdown=max_drawdown,
            volatility=volatility,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            calmar_ratio=calmar,
            total_trades=trade_stats["total_trades"],
            winning_trades=trade_stats["winning_trades"],
            losing_trades=trade_stats["losing_trades"],
            win_rate=trade_stats["win_rate"],
            avg_win=trade_stats["avg_win"],
            avg_loss=trade_stats["avg_loss"],
            profit_factor=trade_stats["profit_factor"],
            expectancy=trade_stats["expectancy"],
            avg_holding_days=trade_stats["avg_holding_days"],
            max_consecutive_wins=trade_stats["max_consecutive_wins"],
            max_consecutive_losses=trade_stats["max_consecutive_losses"],
            monthly_returns=monthly_returns,
            yearly_returns=yearly_returns
        )
    
    def _calculate_cagr(
        self,
        initial: float,
        final: float,
        years: float
    ) -> float:
        """연환산 수익률 (CAGR)"""
        if years <= 0 or initial <= 0:
            return 0.0
        return ((final / initial) ** (1 / years) - 1) * 100
    
    def _calculate_max_drawdown(self, values: pd.Series) -> float:
        """최대 낙폭 (MDD)"""
        peak = values.expanding(min_periods=1).max()
        drawdown = (values - peak) / peak * 100
        return drawdown.min()
    
    def _calculate_volatility(self, returns: pd.Series) -> float:
        """연간 변동성"""
        if len(returns) < 2:
            return 0.0
        return returns.std() * np.sqrt(252) * 100
    
    def _calculate_sharpe_ratio(self, returns: pd.Series) -> float:
        """샤프 비율"""
        if len(returns) < 2:
            return 0.0
        
        excess_returns = returns - self.risk_free_rate / 252
        if returns.std() == 0:
            return 0.0
        
        return np.sqrt(252) * excess_returns.mean() / returns.std()
    
    def _calculate_sortino_ratio(self, returns: pd.Series) -> float:
        """소르티노 비율 (하방 변동성만 사용)"""
        if len(returns) < 2:
            return 0.0
        
        excess_returns = returns - self.risk_free_rate / 252
        downside_returns = returns[returns < 0]
        
        if len(downside_returns) == 0 or downside_returns.std() == 0:
            return 0.0
        
        downside_std = downside_returns.std()
        return np.sqrt(252) * excess_returns.mean() / downside_std
    
    def _analyze_trades(self, trades: List[Trade]) -> dict:
        """거래 분석"""
        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "avg_holding_days": 0.0,
                "max_consecutive_wins": 0,
                "max_consecutive_losses": 0
            }
        
        pnl_pcts = [t.pnl_pct for t in trades]
        winners = [p for p in pnl_pcts if p > 0]
        losers = [p for p in pnl_pcts if p <= 0]
        
        total_trades = len(trades)
        winning_trades = len(winners)
        losing_trades = len(losers)
        win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
        
        avg_win = np.mean(winners) if winners else 0.0
        avg_loss = np.mean(losers) if losers else 0.0
        
        gross_profit = sum(winners) if winners else 0
        gross_loss = abs(sum(losers)) if losers else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        expectancy = np.mean(pnl_pcts) if pnl_pcts else 0.0
        
        avg_holding = np.mean([t.holding_days for t in trades])
        
        # 연속 승/패
        max_wins, max_losses = self._max_consecutive(pnl_pcts)
        
        return {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_factor": profit_factor,
            "expectancy": expectancy,
            "avg_holding_days": avg_holding,
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses
        }
    
    def _max_consecutive(self, pnl_list: List[float]) -> tuple:
        """연속 승/패 횟수"""
        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0
        
        for pnl in pnl_list:
            if pnl > 0:
                current_wins += 1
                current_losses = 0
                max_wins = max(max_wins, current_wins)
            else:
                current_losses += 1
                current_wins = 0
                max_losses = max(max_losses, current_losses)
        
        return max_wins, max_losses
    
    def _calculate_periodic_returns(
        self,
        values: pd.Series,
        period: str = "M"
    ) -> pd.Series:
        """월별/연도별 수익률"""
        if len(values) < 2:
            return pd.Series()
        
        # 리샘플링
        resampled = values.resample(period).last()
        returns = resampled.pct_change().dropna() * 100
        
        return returns
    
    def get_drawdown_series(self, result: BacktestResult) -> pd.Series:
        """Drawdown 시계열 데이터"""
        values = pd.Series(
            [s.total_value for s in result.daily_snapshots],
            index=[s.date for s in result.daily_snapshots]
        )
        peak = values.expanding(min_periods=1).max()
        drawdown = (values - peak) / peak * 100
        return drawdown
    
    def get_equity_curve(self, result: BacktestResult) -> pd.Series:
        """자산 곡선"""
        return pd.Series(
            [s.total_value for s in result.daily_snapshots],
            index=[s.date for s in result.daily_snapshots]
        )
    
    def print_summary(self, metrics: PerformanceMetrics):
        """성과 요약 출력"""
        print("\n" + "=" * 60)
        print("📊 백테스트 성과 분석")
        print("=" * 60)
        
        print("\n📈 수익률 지표")
        print(f"  총 수익률: {metrics.total_return:,.2f}%")
        print(f"  연환산 수익률 (CAGR): {metrics.cagr:.2f}%")
        
        print("\n📉 리스크 지표")
        print(f"  최대 낙폭 (MDD): {metrics.max_drawdown:.2f}%")
        print(f"  연간 변동성: {metrics.volatility:.2f}%")
        
        print("\n⚖️ 위험조정 수익률")
        print(f"  샤프 비율: {metrics.sharpe_ratio:.2f}")
        print(f"  소르티노 비율: {metrics.sortino_ratio:.2f}")
        print(f"  칼마 비율: {metrics.calmar_ratio:.2f}")
        
        print("\n🎯 거래 통계")
        print(f"  총 거래 수: {metrics.total_trades}")
        print(f"  승률: {metrics.win_rate:.1f}%")
        print(f"  평균 수익: {metrics.avg_win:.2f}%")
        print(f"  평균 손실: {metrics.avg_loss:.2f}%")
        print(f"  손익비: {metrics.profit_factor:.2f}")
        print(f"  기대값: {metrics.expectancy:.2f}%")
        print(f"  평균 보유 기간: {metrics.avg_holding_days:.1f}일")
        
        print("\n🔥 연속 기록")
        print(f"  최대 연승: {metrics.max_consecutive_wins}회")
        print(f"  최대 연패: {metrics.max_consecutive_losses}회")
        
        print("=" * 60 + "\n")
