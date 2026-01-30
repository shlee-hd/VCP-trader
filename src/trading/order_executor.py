"""
Order Executor

자동 주문 실행을 관리합니다.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Callable, Any

from loguru import logger

from ..core.config import settings, Environment
from ..core.database import Order, OrderSide, OrderStatus, OrderType


class ExecutionMode(str, Enum):
    """실행 모드"""
    LIVE = "live"           # 실거래
    PAPER = "paper"         # 모의투자
    BACKTEST = "backtest"   # 백테스트


@dataclass
class OrderRequest:
    """주문 요청"""
    symbol: str
    side: OrderSide
    quantity: int
    order_type: OrderType = OrderType.MARKET
    price: Optional[float] = None          # 지정가
    stop_price: Optional[float] = None     # 스탑가
    reason: str = ""
    
    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "order_type": self.order_type.value,
            "price": self.price,
            "stop_price": self.stop_price,
            "reason": self.reason,
        }


@dataclass
class OrderResult:
    """주문 결과"""
    success: bool
    order_id: Optional[str] = None
    broker_order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: float = 0.0
    message: str = ""
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "broker_order_id": self.broker_order_id,
            "status": self.status.value,
            "filled_quantity": self.filled_quantity,
            "filled_price": self.filled_price,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class OrderExecutor:
    """
    주문 실행기
    
    기능:
    - 시장가/지정가/스탑 주문 실행
    - 주문 상태 모니터링
    - 주문 취소
    - 분할 매수/매도
    
    Usage:
        >>> from src.data.broker_client import KISBrokerClient
        >>> 
        >>> broker = KISBrokerClient()
        >>> executor = OrderExecutor(broker_client=broker)
        >>> 
        >>> # 시장가 매수
        >>> result = await executor.buy_market("005930", 10)
        >>> 
        >>> # 손절 주문
        >>> result = await executor.sell_stop("005930", 10, stop_price=65000)
    """
    
    def __init__(
        self,
        broker_client: Any = None,
        mode: ExecutionMode = None,
        dry_run: bool = False,
        order_callback: Optional[Callable] = None,
    ):
        """
        Args:
            broker_client: 증권사 API 클라이언트
            mode: 실행 모드 (live/paper/backtest)
            dry_run: True면 실제 주문 없이 시뮬레이션만
            order_callback: 주문 체결 시 콜백 함수
        """
        self.broker = broker_client
        self.dry_run = dry_run
        self.order_callback = order_callback
        
        # 모드 결정
        if mode:
            self.mode = mode
        elif settings.kis_environment == Environment.PAPER:
            self.mode = ExecutionMode.PAPER
        else:
            self.mode = ExecutionMode.LIVE
        
        # 주문 추적
        self._pending_orders: dict[str, OrderRequest] = {}
        
        logger.info(f"OrderExecutor initialized: mode={self.mode.value}, dry_run={dry_run}")
    
    async def execute(self, request: OrderRequest) -> OrderResult:
        """
        주문을 실행합니다.
        
        Args:
            request: 주문 요청
        
        Returns:
            OrderResult: 주문 결과
        """
        logger.info(
            f"Executing order: {request.side.value} {request.symbol} "
            f"x{request.quantity} @ {request.order_type.value}"
        )
        
        # Dry run 모드
        if self.dry_run:
            return await self._simulate_order(request)
        
        # 실제 주문 실행
        try:
            if request.order_type == OrderType.MARKET:
                result = await self._execute_market_order(request)
            elif request.order_type == OrderType.LIMIT:
                result = await self._execute_limit_order(request)
            elif request.order_type == OrderType.STOP:
                result = await self._execute_stop_order(request)
            else:
                result = OrderResult(
                    success=False,
                    status=OrderStatus.REJECTED,
                    message=f"지원하지 않는 주문 유형: {request.order_type.value}"
                )
            
            # 콜백 호출
            if self.order_callback and result.success:
                await self._call_callback(request, result)
            
            return result
            
        except Exception as e:
            logger.error(f"Order execution failed: {e}")
            return OrderResult(
                success=False,
                status=OrderStatus.REJECTED,
                message=str(e)
            )
    
    async def _execute_market_order(self, request: OrderRequest) -> OrderResult:
        """시장가 주문 실행"""
        if self.broker is None:
            return await self._simulate_order(request)
        
        # 증권사 API 호출
        if request.side == OrderSide.BUY:
            response = await self.broker.buy_market(
                symbol=request.symbol,
                quantity=request.quantity,
            )
        else:
            response = await self.broker.sell_market(
                symbol=request.symbol,
                quantity=request.quantity,
            )
        
        return self._parse_broker_response(response)
    
    async def _execute_limit_order(self, request: OrderRequest) -> OrderResult:
        """지정가 주문 실행"""
        if self.broker is None or request.price is None:
            return await self._simulate_order(request)
        
        if request.side == OrderSide.BUY:
            response = await self.broker.buy_limit(
                symbol=request.symbol,
                quantity=request.quantity,
                price=request.price,
            )
        else:
            response = await self.broker.sell_limit(
                symbol=request.symbol,
                quantity=request.quantity,
                price=request.price,
            )
        
        return self._parse_broker_response(response)
    
    async def _execute_stop_order(self, request: OrderRequest) -> OrderResult:
        """스탑 주문 실행 (한국 주식은 조건부 주문으로 처리)"""
        if self.broker is None or request.stop_price is None:
            return await self._simulate_order(request)
        
        # 한국 증권사는 스탑 주문을 직접 지원하지 않는 경우가 많음
        # 이 경우 모니터링 후 조건 충족 시 시장가 주문 실행
        logger.warning(
            f"{request.symbol}: Stop order registered for monitoring. "
            f"Stop price: {request.stop_price}"
        )
        
        # 대기 주문으로 등록
        order_id = f"STOP_{request.symbol}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self._pending_orders[order_id] = request
        
        return OrderResult(
            success=True,
            order_id=order_id,
            status=OrderStatus.PENDING,
            message=f"Stop order registered. Trigger: {request.stop_price}",
        )
    
    async def _simulate_order(self, request: OrderRequest) -> OrderResult:
        """주문 시뮬레이션 (dry run 또는 백테스트)"""
        # 현재가 조회 시뮬레이션
        simulated_price = request.price or request.stop_price or 0
        
        logger.info(
            f"[SIMULATED] {request.side.value} {request.symbol} "
            f"x{request.quantity} @ {simulated_price:.0f}"
        )
        
        return OrderResult(
            success=True,
            order_id=f"SIM_{datetime.now().strftime('%Y%m%d%H%M%S%f')}",
            status=OrderStatus.FILLED,
            filled_quantity=request.quantity,
            filled_price=simulated_price,
            message="Simulated order",
        )
    
    def _parse_broker_response(self, response: dict) -> OrderResult:
        """증권사 응답을 OrderResult로 변환"""
        # 공통 응답 파싱 (증권사별로 구현 필요)
        success = response.get("success", False)
        
        return OrderResult(
            success=success,
            broker_order_id=response.get("order_id"),
            status=OrderStatus.SUBMITTED if success else OrderStatus.REJECTED,
            filled_quantity=response.get("filled_quantity", 0),
            filled_price=response.get("filled_price", 0),
            message=response.get("message", ""),
        )
    
    async def _call_callback(self, request: OrderRequest, result: OrderResult):
        """주문 체결 콜백 호출"""
        try:
            if asyncio.iscoroutinefunction(self.order_callback):
                await self.order_callback(request, result)
            else:
                self.order_callback(request, result)
        except Exception as e:
            logger.error(f"Order callback failed: {e}")
    
    # ===== 편의 메서드 =====
    
    async def buy_market(
        self,
        symbol: str,
        quantity: int,
        reason: str = "",
    ) -> OrderResult:
        """시장가 매수"""
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=OrderType.MARKET,
            reason=reason,
        )
        return await self.execute(request)
    
    async def sell_market(
        self,
        symbol: str,
        quantity: int,
        reason: str = "",
    ) -> OrderResult:
        """시장가 매도"""
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
            reason=reason,
        )
        return await self.execute(request)
    
    async def buy_limit(
        self,
        symbol: str,
        quantity: int,
        price: float,
        reason: str = "",
    ) -> OrderResult:
        """지정가 매수"""
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            order_type=OrderType.LIMIT,
            price=price,
            reason=reason,
        )
        return await self.execute(request)
    
    async def sell_limit(
        self,
        symbol: str,
        quantity: int,
        price: float,
        reason: str = "",
    ) -> OrderResult:
        """지정가 매도"""
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.LIMIT,
            price=price,
            reason=reason,
        )
        return await self.execute(request)
    
    async def sell_stop(
        self,
        symbol: str,
        quantity: int,
        stop_price: float,
        reason: str = "",
    ) -> OrderResult:
        """스탑 매도 (손절)"""
        request = OrderRequest(
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.STOP,
            stop_price=stop_price,
            reason=reason,
        )
        return await self.execute(request)
    
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        # 대기 중인 스탑 주문 취소
        if order_id in self._pending_orders:
            del self._pending_orders[order_id]
            logger.info(f"Cancelled pending order: {order_id}")
            return True
        
        # 증권사 주문 취소
        if self.broker:
            try:
                await self.broker.cancel_order(order_id)
                logger.info(f"Cancelled broker order: {order_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to cancel order {order_id}: {e}")
                return False
        
        return False
    
    async def check_stop_orders(self, current_prices: dict[str, float]):
        """
        대기 중인 스탑 주문을 확인하고 조건 충족 시 실행합니다.
        
        Args:
            current_prices: {symbol: price} 현재가 딕셔너리
        """
        orders_to_execute = []
        
        for order_id, request in list(self._pending_orders.items()):
            current_price = current_prices.get(request.symbol)
            if current_price is None:
                continue
            
            # 매도 스탑 주문: 현재가가 스탑가 이하면 실행
            if request.side == OrderSide.SELL and current_price <= request.stop_price:
                orders_to_execute.append((order_id, request))
                logger.warning(
                    f"{request.symbol}: Stop triggered! "
                    f"Current: {current_price:.0f} <= Stop: {request.stop_price:.0f}"
                )
        
        # 스탑 주문 실행
        for order_id, request in orders_to_execute:
            del self._pending_orders[order_id]
            
            # 시장가로 즉시 청산
            market_request = OrderRequest(
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                order_type=OrderType.MARKET,
                reason=f"Stop triggered @ {request.stop_price}",
            )
            await self.execute(market_request)
    
    def get_pending_orders(self) -> list[tuple[str, OrderRequest]]:
        """대기 중인 주문 목록 반환"""
        return list(self._pending_orders.items())
