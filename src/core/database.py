"""
VCP Trader Database Module

SQLAlchemy 기반 데이터베이스 모델 및 연결 관리
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from .config import settings


class Base(DeclarativeBase):
    """SQLAlchemy Base Class"""
    pass


# ===== Enums =====

class MarketType(str, PyEnum):
    """시장 타입"""
    KOSPI = "KOSPI"
    KOSDAQ = "KOSDAQ"
    NYSE = "NYSE"
    NASDAQ = "NASDAQ"
    CRYPTO = "CRYPTO"


class OrderSide(str, PyEnum):
    """주문 방향"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, PyEnum):
    """주문 유형"""
    MARKET = "MARKET"       # 시장가
    LIMIT = "LIMIT"         # 지정가
    STOP = "STOP"           # 스탑
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(str, PyEnum):
    """주문 상태"""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class PositionStatus(str, PyEnum):
    """포지션 상태"""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SignalType(str, PyEnum):
    """신호 유형"""
    VCP_DETECTED = "VCP_DETECTED"
    BREAKOUT = "BREAKOUT"
    ENTRY = "ENTRY"
    STOP_LOSS = "STOP_LOSS"
    TRAILING_STOP = "TRAILING_STOP"
    TAKE_PROFIT = "TAKE_PROFIT"


# ===== Models =====

class Stock(Base):
    """주식 종목 정보"""
    __tablename__ = "stocks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), nullable=False, unique=True, index=True)
    name = Column(String(100), nullable=False)
    market = Column(Enum(MarketType), nullable=False)
    sector = Column(String(100), nullable=True)
    industry = Column(String(100), nullable=True)
    
    # 최신 Trend Template 상태
    passes_trend_template = Column(Boolean, default=False)
    rs_rating = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    prices = relationship("DailyPrice", back_populates="stock", cascade="all, delete-orphan")
    signals = relationship("Signal", back_populates="stock", cascade="all, delete-orphan")
    positions = relationship("Position", back_populates="stock")
    
    __table_args__ = (
        Index("ix_stocks_market_sector", "market", "sector"),
    )


class DailyPrice(Base):
    """일봉 데이터"""
    __tablename__ = "daily_prices"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    date = Column(Date, nullable=False)
    
    open = Column(Numeric(20, 4), nullable=False)
    high = Column(Numeric(20, 4), nullable=False)
    low = Column(Numeric(20, 4), nullable=False)
    close = Column(Numeric(20, 4), nullable=False)
    volume = Column(Integer, nullable=False)
    
    # 계산된 지표들
    sma_50 = Column(Numeric(20, 4), nullable=True)
    sma_150 = Column(Numeric(20, 4), nullable=True)
    sma_200 = Column(Numeric(20, 4), nullable=True)
    atr_20 = Column(Numeric(20, 4), nullable=True)
    
    # Relationships
    stock = relationship("Stock", back_populates="prices")
    
    __table_args__ = (
        UniqueConstraint("stock_id", "date", name="uq_stock_date"),
        Index("ix_daily_prices_date", "date"),
        Index("ix_daily_prices_stock_date", "stock_id", "date"),
    )


class Signal(Base):
    """패턴 탐지 및 거래 신호"""
    __tablename__ = "signals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id", ondelete="CASCADE"), nullable=False)
    signal_type = Column(Enum(SignalType), nullable=False)
    
    # 신호 상세
    price = Column(Numeric(20, 4), nullable=False)
    pivot_price = Column(Numeric(20, 4), nullable=True)  # VCP 피벗 포인트
    vcp_score = Column(Integer, nullable=True)           # VCP 패턴 점수 (0-100)
    contractions = Column(Integer, nullable=True)        # 수축 횟수
    
    message = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    
    # Relationships
    stock = relationship("Stock", back_populates="signals")
    
    __table_args__ = (
        Index("ix_signals_type_active", "signal_type", "is_active"),
        Index("ix_signals_created", "created_at"),
    )


class Position(Base):
    """보유 포지션"""
    __tablename__ = "positions"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    stock_id = Column(Integer, ForeignKey("stocks.id"), nullable=False)
    
    # 진입 정보
    entry_price = Column(Numeric(20, 4), nullable=False)
    entry_date = Column(DateTime, nullable=False)
    quantity = Column(Integer, nullable=False)
    
    # 손절/익절 설정
    initial_stop_price = Column(Numeric(20, 4), nullable=False)
    current_stop_price = Column(Numeric(20, 4), nullable=False)
    target_price = Column(Numeric(20, 4), nullable=True)
    
    # 트레일링 스탑 상태
    highest_price = Column(Numeric(20, 4), nullable=False)  # 진입 후 최고가
    trailing_level = Column(Integer, default=0)              # 현재 트레일링 레벨
    
    # 상태
    status = Column(Enum(PositionStatus), default=PositionStatus.OPEN)
    exit_price = Column(Numeric(20, 4), nullable=True)
    exit_date = Column(DateTime, nullable=True)
    exit_reason = Column(String(50), nullable=True)
    
    # 손익
    realized_pnl = Column(Numeric(20, 4), nullable=True)
    realized_pnl_pct = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    stock = relationship("Stock", back_populates="positions")
    orders = relationship("Order", back_populates="position")
    
    __table_args__ = (
        Index("ix_positions_status", "status"),
    )


class Order(Base):
    """주문 내역"""
    __tablename__ = "orders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    
    # 주문 정보
    symbol = Column(String(20), nullable=False)
    side = Column(Enum(OrderSide), nullable=False)
    order_type = Column(Enum(OrderType), nullable=False)
    
    # 가격 및 수량
    quantity = Column(Integer, nullable=False)
    price = Column(Numeric(20, 4), nullable=True)  # 지정가인 경우
    stop_price = Column(Numeric(20, 4), nullable=True)  # 스탑 주문인 경우
    
    # 체결 정보
    filled_quantity = Column(Integer, default=0)
    filled_price = Column(Numeric(20, 4), nullable=True)
    
    # 상태
    status = Column(Enum(OrderStatus), default=OrderStatus.PENDING)
    broker_order_id = Column(String(50), nullable=True)  # 증권사 주문번호
    
    # 메모
    reason = Column(String(100), nullable=True)  # 주문 사유
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    position = relationship("Position", back_populates="orders")
    
    __table_args__ = (
        Index("ix_orders_symbol_status", "symbol", "status"),
        Index("ix_orders_created", "created_at"),
    )


class TradeJournal(Base):
    """거래 일지"""
    __tablename__ = "trade_journals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=False)
    
    # 거래 요약
    symbol = Column(String(20), nullable=False)
    entry_date = Column(DateTime, nullable=False)
    exit_date = Column(DateTime, nullable=True)
    
    entry_price = Column(Numeric(20, 4), nullable=False)
    exit_price = Column(Numeric(20, 4), nullable=True)
    quantity = Column(Integer, nullable=False)
    
    # VCP 패턴 정보
    vcp_score = Column(Integer, nullable=True)
    contractions = Column(Integer, nullable=True)
    
    # 손익
    realized_pnl = Column(Numeric(20, 4), nullable=True)
    realized_pnl_pct = Column(Float, nullable=True)
    r_multiple = Column(Float, nullable=True)  # R 배수 (손익 / 초기 리스크)
    
    # 분석 메모
    notes = Column(Text, nullable=True)
    lessons = Column(Text, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)


# ===== Database Connection =====

# Async Engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level == "DEBUG",
    pool_pre_ping=True,
)

# Async Session Factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncSession:
    """데이터베이스 세션을 반환합니다."""
    async with async_session_maker() as session:
        yield session


async def init_db():
    """데이터베이스 테이블을 생성합니다."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """데이터베이스 연결을 종료합니다."""
    await engine.dispose()
