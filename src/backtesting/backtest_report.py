"""
Backtest Report Generator - HTML/PDF 리포트 생성

백테스트 결과를 시각적으로 표현한 리포트를 생성합니다.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.backtesting.backtest_engine import BacktestResult
from src.backtesting.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics

logger = logging.getLogger(__name__)

# Plotly import (선택적)
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False
    logger.warning("Plotly not installed. Charts will not be available.")


class BacktestReporter:
    """
    백테스트 리포트 생성기
    """
    
    def __init__(self, output_dir: str = "results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.analyzer = PerformanceAnalyzer()
    
    def generate_report(
        self,
        result: BacktestResult,
        filename: Optional[str] = None
    ) -> str:
        """
        HTML 리포트 생성
        
        Args:
            result: BacktestResult 객체
            filename: 출력 파일명 (기본: backtest_YYYYMMDD_HHMMSS.html)
            
        Returns:
            생성된 파일 경로
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"backtest_{timestamp}.html"
        
        filepath = self.output_dir / filename
        
        # 성과 분석
        metrics = self.analyzer.analyze(result)
        
        # HTML 생성
        html_content = self._build_html(result, metrics)
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"리포트 생성 완료: {filepath}")
        return str(filepath)
    
    def _build_html(self, result: BacktestResult, metrics: PerformanceMetrics) -> str:
        """HTML 문서 생성"""
        
        # 차트 생성
        equity_chart = self._create_equity_chart(result) if PLOTLY_AVAILABLE else ""
        drawdown_chart = self._create_drawdown_chart(result) if PLOTLY_AVAILABLE else ""
        monthly_chart = self._create_monthly_returns_chart(metrics) if PLOTLY_AVAILABLE else ""
        
        # 거래 내역 테이블
        trades_table = self._create_trades_table(result)
        
        html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VCP 백테스트 리포트</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        :root {{
            --bg-primary: #0f0f0f;
            --bg-secondary: #1a1a1a;
            --bg-card: #242424;
            --text-primary: #ffffff;
            --text-secondary: #a0a0a0;
            --accent-green: #00d26a;
            --accent-red: #ff4757;
            --accent-blue: #3742fa;
            --border-color: #333;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
            padding: 2rem;
        }}
        
        .container {{ max-width: 1400px; margin: 0 auto; }}
        
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 0.5rem;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        
        .subtitle {{
            color: var(--text-secondary);
            margin-bottom: 2rem;
        }}
        
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 2rem;
        }}
        
        .card {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            border: 1px solid var(--border-color);
        }}
        
        .card-label {{
            font-size: 0.875rem;
            color: var(--text-secondary);
            margin-bottom: 0.5rem;
        }}
        
        .card-value {{
            font-size: 1.75rem;
            font-weight: 700;
        }}
        
        .positive {{ color: var(--accent-green); }}
        .negative {{ color: var(--accent-red); }}
        
        .chart-container {{
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid var(--border-color);
        }}
        
        .chart-title {{
            font-size: 1.25rem;
            margin-bottom: 1rem;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.875rem;
        }}
        
        th, td {{
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid var(--border-color);
        }}
        
        th {{
            background: var(--bg-secondary);
            color: var(--text-secondary);
            font-weight: 600;
        }}
        
        tr:hover {{ background: var(--bg-secondary); }}
        
        .section-title {{
            font-size: 1.5rem;
            margin: 2rem 0 1rem;
            padding-bottom: 0.5rem;
            border-bottom: 2px solid var(--accent-blue);
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 VCP 전략 백테스트 리포트</h1>
        <p class="subtitle">
            {result.start_date.strftime('%Y-%m-%d')} ~ {result.end_date.strftime('%Y-%m-%d')} | 
            초기 자본: ₩{result.initial_capital:,.0f}
        </p>
        
        <!-- 핵심 지표 카드 -->
        <div class="grid">
            <div class="card">
                <div class="card-label">총 수익률</div>
                <div class="card-value {'positive' if metrics.total_return >= 0 else 'negative'}">
                    {metrics.total_return:+,.2f}%
                </div>
            </div>
            <div class="card">
                <div class="card-label">연환산 수익률 (CAGR)</div>
                <div class="card-value {'positive' if metrics.cagr >= 0 else 'negative'}">
                    {metrics.cagr:+,.2f}%
                </div>
            </div>
            <div class="card">
                <div class="card-label">최대 낙폭 (MDD)</div>
                <div class="card-value negative">{metrics.max_drawdown:.2f}%</div>
            </div>
            <div class="card">
                <div class="card-label">샤프 비율</div>
                <div class="card-value">{metrics.sharpe_ratio:.2f}</div>
            </div>
            <div class="card">
                <div class="card-label">승률</div>
                <div class="card-value">{metrics.win_rate:.1f}%</div>
            </div>
            <div class="card">
                <div class="card-label">손익비</div>
                <div class="card-value">{metrics.profit_factor:.2f}</div>
            </div>
            <div class="card">
                <div class="card-label">총 거래 수</div>
                <div class="card-value">{metrics.total_trades}</div>
            </div>
            <div class="card">
                <div class="card-label">최종 자산</div>
                <div class="card-value">₩{result.final_capital:,.0f}</div>
            </div>
        </div>
        
        <!-- 자산 곡선 차트 -->
        <div class="chart-container">
            <h3 class="chart-title">📈 자산 곡선 (Equity Curve)</h3>
            <div id="equity-chart"></div>
        </div>
        
        <!-- Drawdown 차트 -->
        <div class="chart-container">
            <h3 class="chart-title">📉 Drawdown</h3>
            <div id="drawdown-chart"></div>
        </div>
        
        <!-- 월별 수익률 히트맵 -->
        <div class="chart-container">
            <h3 class="chart-title">📅 월별 수익률</h3>
            <div id="monthly-chart"></div>
        </div>
        
        <!-- 상세 통계 -->
        <h2 class="section-title">📊 상세 통계</h2>
        <div class="grid" style="grid-template-columns: repeat(2, 1fr);">
            <div class="card">
                <h4 style="margin-bottom: 1rem;">수익률 지표</h4>
                <table>
                    <tr><td>총 수익률</td><td>{metrics.total_return:+,.2f}%</td></tr>
                    <tr><td>CAGR</td><td>{metrics.cagr:+,.2f}%</td></tr>
                    <tr><td>연간 변동성</td><td>{metrics.volatility:.2f}%</td></tr>
                </table>
            </div>
            <div class="card">
                <h4 style="margin-bottom: 1rem;">리스크 지표</h4>
                <table>
                    <tr><td>MDD</td><td>{metrics.max_drawdown:.2f}%</td></tr>
                    <tr><td>샤프 비율</td><td>{metrics.sharpe_ratio:.2f}</td></tr>
                    <tr><td>소르티노 비율</td><td>{metrics.sortino_ratio:.2f}</td></tr>
                    <tr><td>칼마 비율</td><td>{metrics.calmar_ratio:.2f}</td></tr>
                </table>
            </div>
            <div class="card">
                <h4 style="margin-bottom: 1rem;">거래 통계</h4>
                <table>
                    <tr><td>총 거래</td><td>{metrics.total_trades}</td></tr>
                    <tr><td>수익 거래</td><td>{metrics.winning_trades}</td></tr>
                    <tr><td>손실 거래</td><td>{metrics.losing_trades}</td></tr>
                    <tr><td>승률</td><td>{metrics.win_rate:.1f}%</td></tr>
                </table>
            </div>
            <div class="card">
                <h4 style="margin-bottom: 1rem;">손익 분석</h4>
                <table>
                    <tr><td>평균 수익</td><td>{metrics.avg_win:+,.2f}%</td></tr>
                    <tr><td>평균 손실</td><td>{metrics.avg_loss:+,.2f}%</td></tr>
                    <tr><td>손익비</td><td>{metrics.profit_factor:.2f}</td></tr>
                    <tr><td>기대값</td><td>{metrics.expectancy:+,.2f}%</td></tr>
                    <tr><td>평균 보유 기간</td><td>{metrics.avg_holding_days:.1f}일</td></tr>
                </table>
            </div>
        </div>
        
        <!-- 거래 내역 -->
        <h2 class="section-title">📝 거래 내역</h2>
        <div class="card" style="overflow-x: auto;">
            {trades_table}
        </div>
        
        <!-- 차트 스크립트 -->
        {equity_chart}
        {drawdown_chart}
        {monthly_chart}
        
        <p style="text-align: center; color: var(--text-secondary); margin-top: 3rem;">
            Generated by VCP Trader | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>
    </div>
</body>
</html>
        """
        
        return html
    
    def _create_equity_chart(self, result: BacktestResult) -> str:
        """자산 곡선 차트"""
        if not PLOTLY_AVAILABLE:
            return ""
        
        equity = self.analyzer.get_equity_curve(result)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=equity.index,
            y=equity.values,
            mode='lines',
            name='Portfolio Value',
            line=dict(color='#667eea', width=2),
            fill='tozeroy',
            fillcolor='rgba(102, 126, 234, 0.1)'
        ))
        
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=0, b=0),
            height=400,
            xaxis=dict(gridcolor='#333'),
            yaxis=dict(gridcolor='#333', tickformat=',.0f'),
            showlegend=False
        )
        
        chart_json = fig.to_json()
        return f"""
        <script>
            var equityData = {chart_json};
            Plotly.newPlot('equity-chart', equityData.data, equityData.layout);
        </script>
        """
    
    def _create_drawdown_chart(self, result: BacktestResult) -> str:
        """Drawdown 차트"""
        if not PLOTLY_AVAILABLE:
            return ""
        
        drawdown = self.analyzer.get_drawdown_series(result)
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=drawdown.index,
            y=drawdown.values,
            mode='lines',
            name='Drawdown',
            line=dict(color='#ff4757', width=2),
            fill='tozeroy',
            fillcolor='rgba(255, 71, 87, 0.3)'
        ))
        
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=0, b=0),
            height=250,
            xaxis=dict(gridcolor='#333'),
            yaxis=dict(gridcolor='#333', ticksuffix='%'),
            showlegend=False
        )
        
        chart_json = fig.to_json()
        return f"""
        <script>
            var drawdownData = {chart_json};
            Plotly.newPlot('drawdown-chart', drawdownData.data, drawdownData.layout);
        </script>
        """
    
    def _create_monthly_returns_chart(self, metrics: PerformanceMetrics) -> str:
        """월별 수익률 차트"""
        if not PLOTLY_AVAILABLE or metrics.monthly_returns is None:
            return ""
        
        returns = metrics.monthly_returns
        colors = ['#00d26a' if r >= 0 else '#ff4757' for r in returns.values]
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=returns.index.strftime('%Y-%m'),
            y=returns.values,
            marker_color=colors
        ))
        
        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=0, b=0),
            height=300,
            xaxis=dict(gridcolor='#333'),
            yaxis=dict(gridcolor='#333', ticksuffix='%'),
            showlegend=False
        )
        
        chart_json = fig.to_json()
        return f"""
        <script>
            var monthlyData = {chart_json};
            Plotly.newPlot('monthly-chart', monthlyData.data, monthlyData.layout);
        </script>
        """
    
    def _create_trades_table(self, result: BacktestResult) -> str:
        """거래 내역 테이블 생성"""
        completed_trades = [t for t in result.trades if t.exit_date is not None]
        
        if not completed_trades:
            return "<p>거래 내역이 없습니다.</p>"
        
        rows = []
        for trade in completed_trades[-50:]:  # 최근 50개만
            pnl_class = 'positive' if trade.pnl_pct >= 0 else 'negative'
            rows.append(f"""
                <tr>
                    <td>{trade.entry_date.strftime('%Y-%m-%d')}</td>
                    <td>{trade.exit_date.strftime('%Y-%m-%d')}</td>
                    <td>{trade.symbol}</td>
                    <td>{trade.name}</td>
                    <td>₩{trade.entry_price:,.0f}</td>
                    <td>₩{trade.exit_price:,.0f}</td>
                    <td>{trade.shares:,}</td>
                    <td class="{pnl_class}">{trade.pnl_pct:+.2f}%</td>
                    <td>₩{trade.pnl:+,.0f}</td>
                    <td>{trade.exit_reason}</td>
                </tr>
            """)
        
        return f"""
        <table>
            <thead>
                <tr>
                    <th>진입일</th>
                    <th>청산일</th>
                    <th>종목코드</th>
                    <th>종목명</th>
                    <th>진입가</th>
                    <th>청산가</th>
                    <th>수량</th>
                    <th>수익률</th>
                    <th>손익</th>
                    <th>청산사유</th>
                </tr>
            </thead>
            <tbody>
                {''.join(rows)}
            </tbody>
        </table>
        """
