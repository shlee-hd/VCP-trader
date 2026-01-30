"""VCP Pattern Detection Tests"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


def generate_test_data(days: int = 300, trend: str = "up") -> pd.DataFrame:
    """테스트용 OHLCV 데이터를 생성합니다."""
    dates = [datetime.now() - timedelta(days=days - i) for i in range(days)]
    
    if trend == "up":
        # 상승 추세 데이터
        base_price = 10000
        prices = []
        for i in range(days):
            # 전반적 상승 + 랜덤 노이즈
            price = base_price * (1 + i * 0.002) + np.random.normal(0, 100)
            prices.append(max(price, 1000))
    else:
        # 하락 추세 데이터
        base_price = 15000
        prices = []
        for i in range(days):
            price = base_price * (1 - i * 0.001) + np.random.normal(0, 100)
            prices.append(max(price, 1000))
    
    data = []
    for i, (date, close) in enumerate(zip(dates, prices)):
        high = close * (1 + np.random.uniform(0, 0.02))
        low = close * (1 - np.random.uniform(0, 0.02))
        open_price = close * (1 + np.random.uniform(-0.01, 0.01))
        volume = int(np.random.uniform(100000, 1000000))
        
        data.append({
            "date": date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    
    df = pd.DataFrame(data)
    
    # 이동평균 계산
    df["sma_50"] = df["close"].rolling(window=50).mean()
    df["sma_150"] = df["close"].rolling(window=150).mean()
    df["sma_200"] = df["close"].rolling(window=200).mean()
    
    return df


class TestTrendTemplate:
    """Trend Template 테스트"""
    
    def test_analyze_uptrend(self):
        """상승 추세 종목 분석 테스트"""
        from src.patterns.trend_template import TrendTemplate
        
        template = TrendTemplate(min_rs_rating=70)
        df = generate_test_data(days=300, trend="up")
        
        result = template.analyze(df, symbol="TEST", rs_rating=85)
        
        assert result.symbol == "TEST"
        assert result.rs_rating == 85
        assert result.score >= 0
        assert result.score <= 8
    
    def test_analyze_downtrend(self):
        """하락 추세 종목 분석 테스트"""
        from src.patterns.trend_template import TrendTemplate
        
        template = TrendTemplate()
        df = generate_test_data(days=300, trend="down")
        
        result = template.analyze(df, symbol="TEST", rs_rating=30)
        
        # 하락 추세는 대부분의 기준을 통과하지 못함
        assert result.passes is False
        assert result.score < 8
    
    def test_analyze_insufficient_data(self):
        """데이터 부족 시 테스트"""
        from src.patterns.trend_template import TrendTemplate
        
        template = TrendTemplate()
        df = generate_test_data(days=100)  # 250일 미만
        
        result = template.analyze(df, symbol="TEST", rs_rating=85)
        
        assert result.passes is False
        assert result.score == 0


class TestVCPDetector:
    """VCP Detector 테스트"""
    
    def test_detect_basic(self):
        """기본 VCP 탐지 테스트"""
        from src.patterns.vcp_detector import VCPDetector
        
        detector = VCPDetector()
        df = generate_test_data(days=200, trend="up")
        
        result = detector.detect(df, symbol="TEST")
        
        assert result.symbol == "TEST"
        assert 0 <= result.score <= 100
        assert result.num_contractions >= 0
    
    def test_detect_insufficient_data(self):
        """데이터 부족 시 테스트"""
        from src.patterns.vcp_detector import VCPDetector
        
        detector = VCPDetector(lookback_days=120)
        df = generate_test_data(days=50)  # 120일 미만
        
        result = detector.detect(df, symbol="TEST")
        
        assert result.detected is False
        assert "데이터 부족" in result.message


class TestRSCalculator:
    """RS Calculator 테스트"""
    
    def test_calculate_raw_rs(self):
        """Raw RS 계산 테스트"""
        from src.patterns.rs_calculator import RSCalculator
        
        calculator = RSCalculator()
        df = generate_test_data(days=300, trend="up")
        
        result = calculator.calculate_raw_rs(df)
        
        assert "raw_rs" in result
        assert "performance_3m" in result
        assert "performance_6m" in result
        assert "performance_12m" in result
    
    def test_calculate_ratings(self):
        """RS Rating 일괄 계산 테스트"""
        from src.patterns.rs_calculator import RSCalculator
        
        calculator = RSCalculator()
        
        stock_data = {
            "A": generate_test_data(days=300, trend="up"),
            "B": generate_test_data(days=300, trend="down"),
            "C": generate_test_data(days=300, trend="up"),
        }
        
        results = calculator.calculate_ratings(stock_data)
        
        assert len(results) == 3
        assert all(0 <= r.rs_rating <= 100 for r in results.values())


class TestStopLossManager:
    """Stop Loss Manager 테스트"""
    
    def test_calculate_initial_stop(self):
        """초기 손절가 계산 테스트"""
        from src.trading.stop_loss import StopLossManager
        
        manager = StopLossManager(initial_stop_pct=7.0)
        
        stop_price = manager.calculate_stop_price(
            entry_price=10000,
            highest_price=10000,
            current_level=0,
        )
        
        assert stop_price == pytest.approx(9300, rel=0.01)  # 10000 * 0.93
    
    def test_calculate_trailing_stop(self):
        """트레일링 스탑 계산 테스트"""
        from src.trading.stop_loss import StopLossManager
        
        manager = StopLossManager(
            initial_stop_pct=7.0,
            trailing_levels=[
                {"profit_threshold": 10.0, "trail_percent": 8.0},
            ]
        )
        
        result = manager.calculate_stop(
            symbol="TEST",
            entry_price=10000,
            current_price=11500,  # +15% 수익
            highest_price=12000,   # 고점은 +20%
            current_level=0,
        )
        
        # 수익 10% 이상 → 트레일링 레벨 1 활성화
        assert result.current_level >= 1
        assert result.stop_price > 9300  # 초기 손절가보다 높음
    
    def test_should_exit(self):
        """청산 신호 테스트"""
        from src.trading.stop_loss import StopLossManager
        
        manager = StopLossManager(initial_stop_pct=7.0)
        
        result = manager.calculate_stop(
            symbol="TEST",
            entry_price=10000,
            current_price=9200,  # 손절가 이하
            highest_price=10000,
            current_level=0,
        )
        
        assert result.should_exit is True
        assert result.exit_reason is not None


class TestRiskManager:
    """Risk Manager 테스트"""
    
    def test_calculate_position_size(self):
        """포지션 사이즈 계산 테스트"""
        from src.trading.risk_manager import RiskManager
        
        manager = RiskManager(max_risk_per_trade=2.0)
        
        result = manager.calculate_position_size(
            symbol="TEST",
            account_value=100_000_000,  # 1억
            entry_price=50000,
            stop_price=46500,  # -7%
        )
        
        # 2% 리스크 = 200만원
        # 주당 리스크 = 3500원
        # 포지션 = 200만 / 3500 ≈ 571주
        assert result.risk_amount == pytest.approx(2_000_000, rel=0.01)
        assert result.position_size > 0
        assert result.position_size <= 600
    
    def test_position_size_limits(self):
        """포지션 사이즈 제한 테스트"""
        from src.trading.risk_manager import RiskManager
        
        manager = RiskManager(
            max_risk_per_trade=2.0,
            max_positions=8,
            max_single_position_pct=15.0,
        )
        
        result = manager.calculate_position_size(
            symbol="TEST",
            account_value=100_000_000,
            entry_price=50000,
            stop_price=49000,  # 작은 손절폭 → 큰 포지션
            current_positions=0,
        )
        
        # 15% 제한 적용되어야 함
        max_value = 100_000_000 * 0.15
        assert result.position_value <= max_value
    
    def test_validate_trade(self):
        """거래 검증 테스트"""
        from src.trading.risk_manager import RiskManager
        
        manager = RiskManager(max_risk_per_trade=2.0)
        
        # 정상 거래
        valid, msg = manager.validate_trade(
            symbol="TEST",
            entry_price=50000,
            stop_price=46500,
            quantity=100,
            account_value=100_000_000,
        )
        
        # 리스크 = (50000 - 46500) * 100 = 350,000 = 0.35%
        assert valid is True
        
        # 리스크 초과 거래
        valid, msg = manager.validate_trade(
            symbol="TEST",
            entry_price=50000,
            stop_price=46500,
            quantity=1000,  # 10배 → 3.5% 리스크
            account_value=100_000_000,
        )
        
        assert valid is False
        assert "리스크 초과" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
