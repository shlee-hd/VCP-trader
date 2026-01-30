"""
VCP Trader Configuration Module

환경 변수와 설정값을 관리합니다.
"""

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """거래 환경"""
    REAL = "real"       # 실거래
    PAPER = "paper"     # 모의투자


class BrokerType(str, Enum):
    """증권사 타입"""
    KIS = "kis"         # 한국투자증권
    KIWOOM = "kiwoom"   # 키움증권


class Settings(BaseSettings):
    """
    VCP Trader 설정
    
    환경 변수 또는 .env 파일에서 설정값을 로드합니다.
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # ===== Broker Settings =====
    broker_type: BrokerType = Field(
        default=BrokerType.KIS,
        description="사용할 증권사"
    )
    
    # KIS (한국투자증권) API
    kis_app_key: str = Field(
        default="",
        description="KIS Developers 앱 키"
    )
    kis_app_secret: str = Field(
        default="",
        description="KIS Developers 앱 시크릿"
    )
    kis_account_number: str = Field(
        default="",
        description="계좌번호 (예: 12345678-01)"
    )
    kis_environment: Environment = Field(
        default=Environment.PAPER,
        description="거래 환경 (real/paper)"
    )
    
    # ===== Database Settings =====
    database_url: str = Field(
        default="postgresql+asyncpg://localhost:5432/vcp_trader",
        description="PostgreSQL 연결 URL"
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 연결 URL"
    )
    
    # ===== Notification Settings =====
    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram 봇 토큰"
    )
    telegram_chat_id: Optional[str] = Field(
        default=None,
        description="Telegram 채팅 ID"
    )
    
    # ===== Risk Management Settings =====
    max_risk_per_trade: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="거래당 최대 리스크 (%)"
    )
    max_positions: int = Field(
        default=8,
        ge=1,
        le=20,
        description="최대 동시 보유 포지션 수"
    )
    initial_stop_loss: float = Field(
        default=7.0,
        ge=1.0,
        le=20.0,
        description="초기 손절 비율 (%)"
    )
    max_sector_concentration: float = Field(
        default=30.0,
        ge=10.0,
        le=100.0,
        description="단일 섹터 최대 비중 (%)"
    )
    
    # ===== Trailing Stop Settings =====
    trailing_stop_levels: list[dict] = Field(
        default=[
            {"profit_threshold": 5.0, "trail_percent": 5.0},
            {"profit_threshold": 10.0, "trail_percent": 8.0},
            {"profit_threshold": 20.0, "trail_percent": 10.0},
            {"profit_threshold": 50.0, "trail_percent": 15.0},
        ],
        description="단계별 트레일링 스탑 설정"
    )
    
    # ===== Pattern Detection Settings =====
    min_rs_rating: int = Field(
        default=70,
        ge=0,
        le=100,
        description="최소 RS Rating"
    )
    min_vcp_score: int = Field(
        default=70,
        ge=0,
        le=100,
        description="최소 VCP 패턴 점수"
    )
    min_contractions: int = Field(
        default=2,
        ge=1,
        le=6,
        description="VCP 최소 수축 횟수"
    )
    
    # ===== Trend Template Criteria =====
    price_above_52w_low_pct: float = Field(
        default=30.0,
        description="52주 저점 대비 최소 상승률 (%)"
    )
    price_within_52w_high_pct: float = Field(
        default=25.0,
        description="52주 고점 대비 최대 하락률 (%)"
    )
    
    # ===== Logging =====
    log_level: str = Field(
        default="INFO",
        description="로그 레벨"
    )
    
    @field_validator("kis_account_number")
    @classmethod
    def validate_account_number(cls, v: str) -> str:
        """계좌번호 형식 검증"""
        if v and "-" not in v:
            raise ValueError("계좌번호는 '12345678-01' 형식이어야 합니다")
        return v
    
    @property
    def kis_base_url(self) -> str:
        """KIS API 기본 URL"""
        if self.kis_environment == Environment.REAL:
            return "https://openapi.koreainvestment.com:9443"
        return "https://openapivts.koreainvestment.com:29443"
    
    @property
    def kis_websocket_url(self) -> str:
        """KIS WebSocket URL"""
        if self.kis_environment == Environment.REAL:
            return "ws://ops.koreainvestment.com:21000"
        return "ws://ops.koreainvestment.com:31000"
    
    @property
    def account_prefix(self) -> str:
        """계좌번호 앞 8자리"""
        return self.kis_account_number.split("-")[0] if self.kis_account_number else ""
    
    @property
    def account_suffix(self) -> str:
        """계좌번호 뒤 2자리"""
        return self.kis_account_number.split("-")[1] if self.kis_account_number else ""


@lru_cache
def get_settings() -> Settings:
    """
    설정 인스턴스를 반환합니다.
    
    캐싱되어 여러 번 호출해도 동일한 인스턴스를 반환합니다.
    """
    return Settings()


# 전역 설정 인스턴스
settings = get_settings()
