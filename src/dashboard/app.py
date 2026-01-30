"""
VCP Trader Dashboard

FastAPI 기반 실시간 대시보드 웹 애플리케이션

Usage:
    uvicorn src.dashboard.app:app --reload
"""

from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ..core.config import settings


app = FastAPI(
    title="VCP Trader Dashboard",
    description="Mark Minervini VCP Strategy Trading Dashboard",
    version="0.1.0",
)


# ===== API Endpoints =====

@app.get("/")
async def root():
    """루트 엔드포인트"""
    return {
        "name": "VCP Trader",
        "version": "0.1.0",
        "status": "running",
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/health")
async def health_check():
    """헬스 체크"""
    return {"status": "healthy"}


@app.get("/api/settings")
async def get_settings():
    """현재 설정을 반환합니다."""
    return {
        "max_risk_per_trade": settings.max_risk_per_trade,
        "max_positions": settings.max_positions,
        "initial_stop_loss": settings.initial_stop_loss,
        "trailing_stop_levels": settings.trailing_stop_levels,
        "min_rs_rating": settings.min_rs_rating,
        "min_vcp_score": settings.min_vcp_score,
    }


@app.get("/api/positions")
async def get_positions():
    """
    현재 보유 포지션을 반환합니다.
    
    TODO: 실제 데이터베이스/트레이더와 연동
    """
    # 샘플 데이터
    return {
        "count": 0,
        "positions": [],
        "total_value": 0,
        "total_pnl": 0,
    }


@app.get("/api/signals")
async def get_signals(limit: int = 20):
    """
    최근 VCP 신호를 반환합니다.
    
    TODO: 실제 데이터베이스와 연동
    """
    return {
        "count": 0,
        "signals": [],
    }


@app.get("/api/scan")
async def run_scan():
    """
    수동으로 VCP 스캔을 실행합니다.
    
    TODO: 스캐너와 연동
    """
    return {
        "status": "scan_started",
        "message": "VCP scan has been triggered",
    }


@app.get("/api/trailing-levels")
async def get_trailing_levels():
    """트레일링 스탑 레벨 정보를 반환합니다."""
    from ..trading.stop_loss import StopLossManager
    
    manager = StopLossManager()
    levels = manager.get_all_levels()
    
    return {
        "levels": [level.to_dict() for level in levels],
    }


# ===== Dashboard HTML =====

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VCP Trader Dashboard</title>
    <style>
        :root {
            --bg-primary: #0a0a0a;
            --bg-secondary: #1a1a2e;
            --bg-card: #16213e;
            --text-primary: #e0e0e0;
            --text-secondary: #888888;
            --accent-green: #00ff88;
            --accent-red: #ff4444;
            --accent-blue: #0094ff;
            --accent-yellow: #ffcc00;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'SF Pro Display', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 20px 0;
            border-bottom: 1px solid #333;
            margin-bottom: 30px;
        }
        
        .logo {
            font-size: 24px;
            font-weight: 700;
            background: linear-gradient(135deg, var(--accent-blue), var(--accent-green));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        
        .status-badge {
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        
        .status-badge.running {
            background: rgba(0, 255, 136, 0.1);
            color: var(--accent-green);
            border: 1px solid var(--accent-green);
        }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }
        
        .card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 24px;
            border: 1px solid #2a2a4a;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.3);
        }
        
        .card-title {
            font-size: 14px;
            color: var(--text-secondary);
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 16px;
        }
        
        .card-value {
            font-size: 32px;
            font-weight: 700;
        }
        
        .card-value.positive {
            color: var(--accent-green);
        }
        
        .card-value.negative {
            color: var(--accent-red);
        }
        
        .positions-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        
        .positions-table th,
        .positions-table td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #2a2a4a;
        }
        
        .positions-table th {
            color: var(--text-secondary);
            font-size: 12px;
            text-transform: uppercase;
        }
        
        .signal-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
            border-bottom: 1px solid #2a2a4a;
        }
        
        .signal-symbol {
            font-weight: 600;
        }
        
        .signal-score {
            padding: 4px 12px;
            border-radius: 10px;
            font-size: 12px;
            font-weight: 600;
        }
        
        .signal-score.high {
            background: rgba(0, 255, 136, 0.2);
            color: var(--accent-green);
        }
        
        .trailing-level {
            display: flex;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #2a2a4a;
        }
        
        .level-number {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: var(--accent-blue);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            margin-right: 16px;
        }
        
        .level-info {
            flex: 1;
        }
        
        .level-title {
            font-weight: 500;
        }
        
        .level-desc {
            color: var(--text-secondary);
            font-size: 13px;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        
        .btn-primary {
            background: var(--accent-blue);
            color: white;
        }
        
        .btn-primary:hover {
            background: #0077cc;
        }
        
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
        }
        
        .empty-state .icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div class="logo">📈 VCP Trader</div>
            <div class="status-badge running">Running</div>
        </header>
        
        <div class="grid">
            <!-- Portfolio Summary -->
            <div class="card">
                <div class="card-title">Total Portfolio Value</div>
                <div class="card-value" id="portfolio-value">₩0</div>
            </div>
            
            <div class="card">
                <div class="card-title">Today's P&L</div>
                <div class="card-value positive" id="daily-pnl">+₩0</div>
            </div>
            
            <div class="card">
                <div class="card-title">Active Positions</div>
                <div class="card-value" id="positions-count">0</div>
            </div>
            
            <div class="card">
                <div class="card-title">VCP Signals Today</div>
                <div class="card-value" id="signals-count">0</div>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 30px;">
            <!-- Positions -->
            <div class="card" style="grid-column: span 2;">
                <div class="card-title">Open Positions</div>
                <div id="positions-container">
                    <div class="empty-state">
                        <div class="icon">📭</div>
                        <div>No open positions</div>
                    </div>
                </div>
            </div>
            
            <!-- VCP Signals -->
            <div class="card">
                <div class="card-title">Recent VCP Signals</div>
                <div id="signals-container">
                    <div class="empty-state">
                        <div class="icon">🔍</div>
                        <div>No signals yet</div>
                    </div>
                </div>
                <button class="btn btn-primary" style="margin-top: 20px; width: 100%;" onclick="runScan()">
                    Run VCP Scan Now
                </button>
            </div>
        </div>
        
        <div class="grid" style="margin-top: 30px;">
            <!-- Trailing Stop Levels -->
            <div class="card">
                <div class="card-title">Trailing Stop Levels</div>
                <div id="trailing-levels">
                    <div class="trailing-level">
                        <div class="level-number">0</div>
                        <div class="level-info">
                            <div class="level-title">Initial Stop</div>
                            <div class="level-desc">Entry -7%</div>
                        </div>
                    </div>
                    <div class="trailing-level">
                        <div class="level-number">1</div>
                        <div class="level-info">
                            <div class="level-title">Trailing Level 1</div>
                            <div class="level-desc">Profit 5%+ → High -5%</div>
                        </div>
                    </div>
                    <div class="trailing-level">
                        <div class="level-number">2</div>
                        <div class="level-info">
                            <div class="level-title">Trailing Level 2</div>
                            <div class="level-desc">Profit 10%+ → High -8%</div>
                        </div>
                    </div>
                    <div class="trailing-level">
                        <div class="level-number">3</div>
                        <div class="level-info">
                            <div class="level-title">Trailing Level 3</div>
                            <div class="level-desc">Profit 20%+ → High -10%</div>
                        </div>
                    </div>
                    <div class="trailing-level">
                        <div class="level-number">4</div>
                        <div class="level-info">
                            <div class="level-title">Trailing Level 4</div>
                            <div class="level-desc">Profit 50%+ → High -15%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Settings -->
            <div class="card">
                <div class="card-title">Risk Settings</div>
                <div id="settings-container">
                    <div style="margin-bottom: 16px;">
                        <div style="color: var(--text-secondary); font-size: 13px;">Max Risk per Trade</div>
                        <div style="font-size: 20px; font-weight: 600;">2%</div>
                    </div>
                    <div style="margin-bottom: 16px;">
                        <div style="color: var(--text-secondary); font-size: 13px;">Max Positions</div>
                        <div style="font-size: 20px; font-weight: 600;">8</div>
                    </div>
                    <div style="margin-bottom: 16px;">
                        <div style="color: var(--text-secondary); font-size: 13px;">Min RS Rating</div>
                        <div style="font-size: 20px; font-weight: 600;">70</div>
                    </div>
                    <div>
                        <div style="color: var(--text-secondary); font-size: 13px;">Min VCP Score</div>
                        <div style="font-size: 20px; font-weight: 600;">70</div>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        async function fetchData() {
            try {
                const [positions, signals, settings] = await Promise.all([
                    fetch('/api/positions').then(r => r.json()),
                    fetch('/api/signals').then(r => r.json()),
                    fetch('/api/settings').then(r => r.json()),
                ]);
                
                document.getElementById('positions-count').textContent = positions.count;
                document.getElementById('signals-count').textContent = signals.count;
                
                // Update settings
                // ...
            } catch (e) {
                console.error('Failed to fetch data:', e);
            }
        }
        
        async function runScan() {
            try {
                const response = await fetch('/api/scan');
                const data = await response.json();
                alert(data.message);
            } catch (e) {
                alert('Scan failed: ' + e.message);
            }
        }
        
        // Fetch data on load
        fetchData();
        
        // Refresh every 30 seconds
        setInterval(fetchData, 30000);
    </script>
</body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """대시보드 HTML을 반환합니다."""
    return DASHBOARD_HTML


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
