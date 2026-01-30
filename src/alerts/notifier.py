"""
Notification System

다양한 채널을 통해 알림을 발송합니다.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from loguru import logger

from ..core.config import settings


class AlertType(str, Enum):
    """알림 유형"""
    VCP_DETECTED = "vcp_detected"       # VCP 패턴 탐지
    BREAKOUT = "breakout"               # 돌파 신호
    ENTRY = "entry"                     # 진입 완료
    STOP_LOSS = "stop_loss"             # 손절
    TRAILING_STOP = "trailing_stop"     # 트레일링 스탑
    TAKE_PROFIT = "take_profit"         # 익절
    POSITION_UPDATE = "position_update" # 포지션 업데이트
    SYSTEM_ERROR = "system_error"       # 시스템 에러
    DAILY_SUMMARY = "daily_summary"     # 일일 요약


@dataclass
class Alert:
    """알림 메시지"""
    alert_type: AlertType
    title: str
    message: str
    symbol: Optional[str] = None
    price: Optional[float] = None
    extra_data: Optional[dict] = None
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
    
    def to_telegram_message(self) -> str:
        """Telegram 메시지 형식으로 변환"""
        emoji = self._get_emoji()
        
        lines = [
            f"{emoji} *{self.title}*",
            f"━━━━━━━━━━━━━━━━━━━━",
        ]
        
        if self.symbol:
            lines.append(f"종목: `{self.symbol}`")
        
        if self.price:
            lines.append(f"가격: {self.price:,.0f}원")
        
        lines.append("")
        lines.append(self.message)
        
        if self.extra_data:
            lines.append("")
            for key, value in self.extra_data.items():
                if isinstance(value, float):
                    lines.append(f"• {key}: {value:,.2f}")
                else:
                    lines.append(f"• {key}: {value}")
        
        lines.append("")
        lines.append(f"⏰ {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def _get_emoji(self) -> str:
        """알림 유형별 이모지"""
        emoji_map = {
            AlertType.VCP_DETECTED: "🎯",
            AlertType.BREAKOUT: "🚀",
            AlertType.ENTRY: "✅",
            AlertType.STOP_LOSS: "🔴",
            AlertType.TRAILING_STOP: "⚠️",
            AlertType.TAKE_PROFIT: "💰",
            AlertType.POSITION_UPDATE: "📊",
            AlertType.SYSTEM_ERROR: "❌",
            AlertType.DAILY_SUMMARY: "📈",
        }
        return emoji_map.get(self.alert_type, "📢")


class Notifier:
    """
    알림 발송기
    
    지원 채널:
    - Telegram (권장)
    - Console (기본)
    
    Usage:
        >>> notifier = Notifier()
        >>> await notifier.initialize()
        >>> 
        >>> # VCP 패턴 탐지 알림
        >>> await notifier.send_vcp_alert(
        ...     symbol="005930",
        ...     score=85,
        ...     pivot_price=72000,
        ... )
        >>> 
        >>> # 손절 알림
        >>> await notifier.send_stop_loss_alert(
        ...     symbol="005930",
        ...     entry_price=70000,
        ...     exit_price=65100,
        ...     loss_pct=-7.0,
        ... )
    """
    
    def __init__(
        self,
        telegram_token: str = None,
        telegram_chat_id: str = None,
        enable_telegram: bool = True,
        enable_console: bool = True,
    ):
        """
        Args:
            telegram_token: Telegram 봇 토큰
            telegram_chat_id: Telegram 채팅 ID
            enable_telegram: Telegram 알림 활성화
            enable_console: 콘솔 출력 활성화
        """
        self.telegram_token = telegram_token or settings.telegram_bot_token
        self.telegram_chat_id = telegram_chat_id or settings.telegram_chat_id
        self.enable_telegram = enable_telegram and self.telegram_token
        self.enable_console = enable_console
        
        self._telegram_bot = None
    
    async def initialize(self):
        """알림 시스템을 초기화합니다."""
        if self.enable_telegram:
            try:
                from telegram import Bot
                self._telegram_bot = Bot(token=self.telegram_token)
                # 연결 테스트
                me = await self._telegram_bot.get_me()
                logger.info(f"Telegram bot initialized: @{me.username}")
            except ImportError:
                logger.warning("python-telegram-bot not installed")
                self.enable_telegram = False
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
                self.enable_telegram = False
    
    async def send(self, alert: Alert):
        """알림을 발송합니다."""
        tasks = []
        
        if self.enable_console:
            self._print_to_console(alert)
        
        if self.enable_telegram:
            tasks.append(self._send_telegram(alert))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def _print_to_console(self, alert: Alert):
        """콘솔에 출력합니다."""
        emoji = alert._get_emoji()
        
        if alert.alert_type in [AlertType.STOP_LOSS, AlertType.SYSTEM_ERROR]:
            logger.warning(f"{emoji} [{alert.alert_type.value}] {alert.title}: {alert.message}")
        else:
            logger.info(f"{emoji} [{alert.alert_type.value}] {alert.title}: {alert.message}")
    
    async def _send_telegram(self, alert: Alert):
        """Telegram으로 발송합니다."""
        if not self._telegram_bot or not self.telegram_chat_id:
            return
        
        try:
            message = alert.to_telegram_message()
            await self._telegram_bot.send_message(
                chat_id=self.telegram_chat_id,
                text=message,
                parse_mode="Markdown",
            )
            logger.debug(f"Telegram alert sent: {alert.title}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    # ===== 편의 메서드 =====
    
    async def send_vcp_alert(
        self,
        symbol: str,
        score: int,
        pivot_price: float,
        contractions: int = 0,
        tightening_quality: str = "",
    ):
        """VCP 패턴 탐지 알림"""
        alert = Alert(
            alert_type=AlertType.VCP_DETECTED,
            title="VCP 패턴 포착",
            symbol=symbol,
            price=pivot_price,
            message=f"VCP 점수 {score}/100의 패턴이 감지되었습니다.",
            extra_data={
                "VCP 점수": score,
                "수축 횟수": contractions,
                "타이트닝": tightening_quality,
                "피벗 포인트": f"{pivot_price:,.0f}원",
            }
        )
        await self.send(alert)
    
    async def send_breakout_alert(
        self,
        symbol: str,
        breakout_price: float,
        volume_ratio: float = 1.0,
    ):
        """돌파 신호 알림"""
        alert = Alert(
            alert_type=AlertType.BREAKOUT,
            title="돌파 신호",
            symbol=symbol,
            price=breakout_price,
            message=f"피벗 포인트를 돌파했습니다!",
            extra_data={
                "돌파 가격": f"{breakout_price:,.0f}원",
                "거래량 비율": f"{volume_ratio:.1f}x",
            }
        )
        await self.send(alert)
    
    async def send_entry_alert(
        self,
        symbol: str,
        entry_price: float,
        quantity: int,
        stop_price: float,
    ):
        """진입 알림"""
        risk_pct = abs((entry_price - stop_price) / entry_price * 100)
        position_value = entry_price * quantity
        
        alert = Alert(
            alert_type=AlertType.ENTRY,
            title="매수 체결",
            symbol=symbol,
            price=entry_price,
            message=f"{quantity:,}주 매수 완료",
            extra_data={
                "매수가": f"{entry_price:,.0f}원",
                "수량": f"{quantity:,}주",
                "투자금액": f"{position_value:,.0f}원",
                "손절가": f"{stop_price:,.0f}원",
                "리스크": f"{risk_pct:.1f}%",
            }
        )
        await self.send(alert)
    
    async def send_stop_loss_alert(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        loss_pct: float,
    ):
        """손절 알림"""
        loss_amount = (exit_price - entry_price) * quantity
        
        alert = Alert(
            alert_type=AlertType.STOP_LOSS,
            title="손절 체결",
            symbol=symbol,
            price=exit_price,
            message=f"손절 조건 충족으로 청산되었습니다.",
            extra_data={
                "진입가": f"{entry_price:,.0f}원",
                "청산가": f"{exit_price:,.0f}원",
                "손실률": f"{loss_pct:.1f}%",
                "손실금액": f"{loss_amount:,.0f}원",
            }
        )
        await self.send(alert)
    
    async def send_trailing_stop_alert(
        self,
        symbol: str,
        entry_price: float,
        highest_price: float,
        exit_price: float,
        quantity: int,
        profit_pct: float,
        trailing_level: int,
    ):
        """트레일링 스탑 알림"""
        profit_amount = (exit_price - entry_price) * quantity
        
        alert = Alert(
            alert_type=AlertType.TRAILING_STOP,
            title="트레일링 스탑 체결",
            symbol=symbol,
            price=exit_price,
            message=f"트레일링 레벨 {trailing_level}에서 청산되었습니다.",
            extra_data={
                "진입가": f"{entry_price:,.0f}원",
                "최고가": f"{highest_price:,.0f}원",
                "청산가": f"{exit_price:,.0f}원",
                "수익률": f"{profit_pct:.1f}%",
                "수익금액": f"{profit_amount:,.0f}원",
            }
        )
        await self.send(alert)
    
    async def send_take_profit_alert(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        profit_pct: float,
    ):
        """익절 알림"""
        profit_amount = (exit_price - entry_price) * quantity
        
        alert = Alert(
            alert_type=AlertType.TAKE_PROFIT,
            title="익절 체결",
            symbol=symbol,
            price=exit_price,
            message=f"목표가 도달로 청산되었습니다!",
            extra_data={
                "진입가": f"{entry_price:,.0f}원",
                "청산가": f"{exit_price:,.0f}원",
                "수익률": f"+{profit_pct:.1f}%",
                "수익금액": f"+{profit_amount:,.0f}원",
            }
        )
        await self.send(alert)
    
    async def send_daily_summary(
        self,
        total_value: float,
        daily_pnl: float,
        daily_pnl_pct: float,
        positions_count: int,
        signals_count: int,
    ):
        """일일 요약 알림"""
        alert = Alert(
            alert_type=AlertType.DAILY_SUMMARY,
            title="일일 리포트",
            message="오늘의 거래 요약입니다.",
            extra_data={
                "총 자산": f"{total_value:,.0f}원",
                "일일 손익": f"{daily_pnl:+,.0f}원",
                "일일 수익률": f"{daily_pnl_pct:+.2f}%",
                "보유 포지션": f"{positions_count}개",
                "오늘의 신호": f"{signals_count}개",
            }
        )
        await self.send(alert)
    
    async def send_error_alert(self, error_message: str, error_type: str = "ERROR"):
        """시스템 에러 알림"""
        alert = Alert(
            alert_type=AlertType.SYSTEM_ERROR,
            title=f"시스템 {error_type}",
            message=error_message,
        )
        await self.send(alert)
