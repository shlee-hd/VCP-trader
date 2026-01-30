"""
한국투자증권 KIS Developers API Client

REST API와 WebSocket을 통해 시세 조회 및 주문을 실행합니다.
공식 문서: https://apiportal.koreainvestment.com/
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Optional, Callable, Any

import httpx
from loguru import logger

from ..core.config import settings, Environment


class KISBrokerClient:
    """
    한국투자증권 KIS Developers API 클라이언트
    
    기능:
    - OAuth 토큰 관리 (자동 갱신)
    - 국내 주식 시세 조회
    - 국내 주식 주문 (매수/매도)
    - 잔고 조회
    - 체결 내역 조회
    
    Usage:
        >>> client = KISBrokerClient()
        >>> await client.initialize()
        >>> 
        >>> # 현재가 조회
        >>> price = await client.get_current_price("005930")
        >>> print(f"삼성전자: {price:,}원")
        >>> 
        >>> # 시장가 매수
        >>> result = await client.buy_market("005930", 10)
    """
    
    def __init__(
        self,
        app_key: str = None,
        app_secret: str = None,
        account_number: str = None,
        environment: Environment = None,
    ):
        """
        Args:
            app_key: KIS Developers 앱 키
            app_secret: KIS Developers 앱 시크릿
            account_number: 계좌번호 (예: 12345678-01)
            environment: 거래 환경 (real/paper)
        """
        self.app_key = app_key or settings.kis_app_key
        self.app_secret = app_secret or settings.kis_app_secret
        self.account_number = account_number or settings.kis_account_number
        self.environment = environment or settings.kis_environment
        
        # URL 설정
        self.base_url = settings.kis_base_url
        self.ws_url = settings.kis_websocket_url
        
        # 토큰 관리
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        
        # HTTP 클라이언트
        self._client: Optional[httpx.AsyncClient] = None
        
        logger.info(
            f"KISBrokerClient initialized: environment={self.environment.value}, "
            f"account={self.account_number[:4]}****"
        )
    
    async def initialize(self):
        """클라이언트를 초기화합니다."""
        self._client = httpx.AsyncClient(timeout=30.0)
        await self._refresh_token()
        logger.info("KIS API client initialized successfully")
    
    async def close(self):
        """클라이언트를 종료합니다."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def _refresh_token(self):
        """OAuth 토큰을 갱신합니다."""
        url = f"{self.base_url}/oauth2/tokenP"
        
        headers = {"Content-Type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        
        try:
            response = await self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            
            self._access_token = data["access_token"]
            # 토큰은 보통 24시간 유효, 안전하게 23시간 후 갱신
            self._token_expires_at = datetime.now() + timedelta(hours=23)
            
            logger.info("OAuth token refreshed successfully")
            
        except Exception as e:
            logger.error(f"Failed to refresh OAuth token: {e}")
            raise
    
    async def _ensure_token(self):
        """토큰이 유효한지 확인하고 필요시 갱신합니다."""
        if self._access_token is None or datetime.now() >= self._token_expires_at:
            await self._refresh_token()
    
    def _get_headers(self, tr_id: str) -> dict:
        """API 요청 헤더를 생성합니다."""
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",  # 개인
        }
    
    # ===== 시세 조회 =====
    
    async def get_current_price(self, symbol: str) -> dict:
        """
        현재가를 조회합니다.
        
        Args:
            symbol: 종목 코드 (예: "005930")
        
        Returns:
            {"price": float, "change": float, "change_rate": float, "volume": int}
        """
        await self._ensure_token()
        
        # 실거래/모의투자에 따른 TR_ID
        tr_id = "FHKST01010100" if self.environment == Environment.REAL else "FHKST01010100"
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._get_headers(tr_id)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 주식
            "FID_INPUT_ISCD": symbol,
        }
        
        try:
            response = await self._client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            output = data.get("output", {})
            
            return {
                "symbol": symbol,
                "price": float(output.get("stck_prpr", 0)),
                "change": float(output.get("prdy_vrss", 0)),
                "change_rate": float(output.get("prdy_ctrt", 0)),
                "volume": int(output.get("acml_vol", 0)),
                "high": float(output.get("stck_hgpr", 0)),
                "low": float(output.get("stck_lwpr", 0)),
                "open": float(output.get("stck_oprc", 0)),
            }
            
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            raise
    
    async def get_daily_prices(
        self,
        symbol: str,
        period_type: str = "D",  # D: 일봉, W: 주봉, M: 월봉
        count: int = 100,
        adjusted: bool = True,
    ) -> list[dict]:
        """
        일봉 데이터를 조회합니다.
        
        Args:
            symbol: 종목 코드
            period_type: D(일봉), W(주봉), M(월봉)
            count: 조회 개수 (최대 100)
            adjusted: 수정주가 여부
        
        Returns:
            OHLCV 데이터 리스트
        """
        await self._ensure_token()
        
        tr_id = "FHKST01010400" if self.environment == Environment.REAL else "FHKST01010400"
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = self._get_headers(tr_id)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": symbol,
            "FID_PERIOD_DIV_CODE": period_type,
            "FID_ORG_ADJ_PRC": "0" if adjusted else "1",
        }
        
        try:
            response = await self._client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            prices = []
            for item in data.get("output", [])[:count]:
                prices.append({
                    "date": datetime.strptime(item["stck_bsop_date"], "%Y%m%d"),
                    "open": float(item.get("stck_oprc", 0)),
                    "high": float(item.get("stck_hgpr", 0)),
                    "low": float(item.get("stck_lwpr", 0)),
                    "close": float(item.get("stck_clpr", 0)),
                    "volume": int(item.get("acml_vol", 0)),
                })
            
            return prices
            
        except Exception as e:
            logger.error(f"Failed to get daily prices for {symbol}: {e}")
            raise
    
    # ===== 주문 =====
    
    async def buy_market(self, symbol: str, quantity: int) -> dict:
        """
        시장가 매수 주문을 실행합니다.
        
        Args:
            symbol: 종목 코드
            quantity: 수량
        
        Returns:
            주문 결과
        """
        return await self._place_order(
            symbol=symbol,
            quantity=quantity,
            side="buy",
            order_type="01",  # 시장가
            price=0,
        )
    
    async def sell_market(self, symbol: str, quantity: int) -> dict:
        """시장가 매도 주문"""
        return await self._place_order(
            symbol=symbol,
            quantity=quantity,
            side="sell",
            order_type="01",
            price=0,
        )
    
    async def buy_limit(self, symbol: str, quantity: int, price: float) -> dict:
        """지정가 매수 주문"""
        return await self._place_order(
            symbol=symbol,
            quantity=quantity,
            side="buy",
            order_type="00",  # 지정가
            price=price,
        )
    
    async def sell_limit(self, symbol: str, quantity: int, price: float) -> dict:
        """지정가 매도 주문"""
        return await self._place_order(
            symbol=symbol,
            quantity=quantity,
            side="sell",
            order_type="00",
            price=price,
        )
    
    async def _place_order(
        self,
        symbol: str,
        quantity: int,
        side: str,  # "buy" or "sell"
        order_type: str,  # "00": 지정가, "01": 시장가
        price: float,
    ) -> dict:
        """주문을 실행합니다."""
        await self._ensure_token()
        
        # TR_ID 결정
        if self.environment == Environment.REAL:
            tr_id = "TTTC0802U" if side == "buy" else "TTTC0801U"
        else:
            tr_id = "VTTC0802U" if side == "buy" else "VTTC0801U"
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = self._get_headers(tr_id)
        
        # 계좌번호 분리
        acct_prefix = settings.account_prefix
        acct_suffix = settings.account_suffix
        
        body = {
            "CANO": acct_prefix,
            "ACNT_PRDT_CD": acct_suffix,
            "PDNO": symbol,
            "ORD_DVSN": order_type,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(int(price)) if price > 0 else "0",
        }
        
        try:
            logger.info(
                f"Placing order: {side.upper()} {symbol} x{quantity} "
                f"@ {'MARKET' if order_type == '01' else price}"
            )
            
            response = await self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            
            success = data.get("rt_cd") == "0"
            
            result = {
                "success": success,
                "order_id": data.get("output", {}).get("ODNO"),
                "message": data.get("msg1", ""),
                "order_time": data.get("output", {}).get("ORD_TMD"),
            }
            
            if success:
                logger.info(f"Order placed successfully: {result['order_id']}")
            else:
                logger.error(f"Order failed: {result['message']}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            return {
                "success": False,
                "message": str(e),
            }
    
    async def cancel_order(self, order_id: str, symbol: str, quantity: int) -> dict:
        """주문을 취소합니다."""
        await self._ensure_token()
        
        tr_id = "TTTC0803U" if self.environment == Environment.REAL else "VTTC0803U"
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        headers = self._get_headers(tr_id)
        
        body = {
            "CANO": settings.account_prefix,
            "ACNT_PRDT_CD": settings.account_suffix,
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "00",
            "RVSE_CNCL_DVSN_CD": "02",  # 취소
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        
        try:
            response = await self._client.post(url, headers=headers, json=body)
            response.raise_for_status()
            data = response.json()
            
            success = data.get("rt_cd") == "0"
            
            return {
                "success": success,
                "message": data.get("msg1", ""),
            }
            
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            return {
                "success": False,
                "message": str(e),
            }
    
    # ===== 계좌 조회 =====
    
    async def get_balance(self) -> dict:
        """
        계좌 잔고를 조회합니다.
        
        Returns:
            {
                "total_value": float,
                "cash": float,
                "stock_value": float,
                "positions": [...]
            }
        """
        await self._ensure_token()
        
        tr_id = "TTTC8434R" if self.environment == Environment.REAL else "VTTC8434R"
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self._get_headers(tr_id)
        params = {
            "CANO": settings.account_prefix,
            "ACNT_PRDT_CD": settings.account_suffix,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }
        
        try:
            response = await self._client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            output1 = data.get("output1", [])  # 보유 종목
            output2 = data.get("output2", [{}])[0]  # 계좌 요약
            
            positions = []
            for item in output1:
                if int(item.get("hldg_qty", 0)) > 0:
                    positions.append({
                        "symbol": item.get("pdno"),
                        "name": item.get("prdt_name"),
                        "quantity": int(item.get("hldg_qty", 0)),
                        "avg_price": float(item.get("pchs_avg_pric", 0)),
                        "current_price": float(item.get("prpr", 0)),
                        "profit_loss": float(item.get("evlu_pfls_amt", 0)),
                        "profit_loss_rate": float(item.get("evlu_pfls_rt", 0)),
                    })
            
            return {
                "total_value": float(output2.get("tot_evlu_amt", 0)),
                "cash": float(output2.get("dnca_tot_amt", 0)),
                "stock_value": float(output2.get("scts_evlu_amt", 0)),
                "profit_loss": float(output2.get("evlu_pfls_smtl_amt", 0)),
                "positions": positions,
            }
            
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise
    
    # ===== 종목 리스트 =====
    
    async def get_kospi_symbols(self) -> list[dict]:
        """KOSPI 종목 리스트를 조회합니다."""
        # 실제로는 별도 API나 파일에서 로드
        # 여기서는 예시로 빈 리스트 반환
        logger.warning("get_kospi_symbols: Not implemented - use external data source")
        return []
    
    async def get_kosdaq_symbols(self) -> list[dict]:
        """KOSDAQ 종목 리스트를 조회합니다."""
        logger.warning("get_kosdaq_symbols: Not implemented - use external data source")
        return []
