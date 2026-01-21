from .KalshiAuthentication import KalshiAuthentication
from typing import List
import httpx
from json import JSONDecodeError
import logging
import asyncio
from live_trading.RiskExceptions import *

logger = logging.getLogger("ks_rest")

class APIError(Exception):
    pass

class RateLimitError(Exception):
    pass

class AuthError(Exception):
    pass

class KalshiAPI:
    '''
    Async (httpx) class for Kalshi's REST API with retry logic.

    All methods return JSON obj of response with no type or
    response validation.
    '''
    def __init__(self, session: KalshiAuthentication, max_retries: int = 3, retry_delay: float = .1, time_out: int = 5):
        self.session = session
        self.base_url = "https://api.elections.kalshi.com"
        self.client = None

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.time_out = time_out

    async def connect(self):
        '''
        Init the client if applicable
        '''
        if self.client is None:
            self.client = httpx.AsyncClient()

    async def close(self):
        '''
        Close the client if applicable
        '''
        if self.client:
            await self.client.aclose()
            self.client = None

    def _gen_headers(self, method: str, path: str) -> dict:
        '''
        Generates signature and timestamp string for request authentication. Formats into Kalshi
        API header format.
        Returns headers.
        '''
        timestampt_str = self.session.gen_timestampstr()

        path_without_query = path.split('?')[0]
        msg_string = timestampt_str + method + path_without_query

        sig = self.session.sign_pss_text(msg_string)

        headers = {
            'KALSHI-ACCESS-KEY': self.session.access_key,
            'KALSHI-ACCESS-SIGNATURE': sig,
            'KALSHI-ACCESS-TIMESTAMP': timestampt_str
        }

        return headers
    
    async def _request(self, method: str, path: str, params=None, json=None):
        '''
        Base request helper method with retry logic.
        Generates HTTP errors and retries on decode errors.
        Returns JSON serialization of response.      
        '''
        if self.client is None:
            raise RuntimeError("Client not initialized. Must be connected first.")

        url = self.base_url + path
        for attempt in range(self.max_retries):
            try:
                headers = self._gen_headers(method=method, path=path)

                logger.info(f"Method: {method}. URL: {url}. Params: {params}. JSON: {json}")

                response = await self.client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=self.time_out
                )

                response.raise_for_status()
                try:
                    return response.json()
                except JSONDecodeError as e:
                    logger.error(f"Response decode error: {e}")
                    continue

            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                    continue
                raise APIError("Request timed out")
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                if status_code == 401:
                    raise AuthError("Authentication failed") from e
                elif status_code == 429:
                    raise RateLimitError("Rate limit exceeded") from e
                elif status_code >= 500 and attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))
                    continue
                else:
                    logger.error(f"API error ({status_code})")
            except httpx.RequestError as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)
                    continue
                raise APIError(f"Network error: {e}") from e

        raise APIError("Max retries exceeded")

    async def get_orders(self, ticker: str | None = None, event_ticker:str | None = None, min_ts: int | None = None, max_ts: int| None = None, status: str | None = None, limit: int=100, cursor: str | None = None):
        '''
        Makes GET request to get_orders endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/orders'

        payload = {
            "ticker":  ticker,
            "event_ticker": event_ticker,
            "min_ts": min_ts,
            "max_ts": max_ts,
            "status": status,
            "limit": limit,
            "cursor": cursor
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        response = await self._request(method="GET", path=path, params=payload)
        
        return response

    async def get_positions(self, cursor: str| None =None, limit: int  = 100, count_filter: str | None = None, ticker: str | None = None, event_ticker: str | None = None):
        '''
        Makes GET request to get_positions endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/positions'

        payload = {
            "ticker":  ticker,
            "event_ticker": event_ticker,
            "limit": limit,
            "cursor": cursor,
            "count_filter": count_filter
        }

        payload = {k: v for k, v in payload.items() if v is not None}
        response = await self._request(method="GET", path=path, params=payload)

        return response

    async def get_balance(self):
        '''
        Makes GET request to get_balance endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/balance'

        response = await self._request(method="GET", path=path)

        return response
    
    async def get_market_orderbook(self, ticker: str, depth: int = 0):
        '''
        Makes GET request to get_market_orderbook endpoint.
        Generates HTTP status error.
        Returns:
            Response JSON
        '''
        path = f'/trade-api/v2/markets/{ticker}/orderbook'
        params = {"depth": depth}

        response = await self._request(method="GET", path=path, params=params)

        return response
    
    async def batch_create_orders(self, orders: List[dict]):
        '''
        Makes POST request to batch_create_orders endpoint.
        Generates HTTP status errors.

        Raises OrderRejection if an order error is received
        in the response.
        
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/orders/batched'

        payload = {"orders": orders}

        response = await self._request(method="POST", path=path, json=payload)

        for order_obj in response.get("orders", []):
            order = order_obj.get("order", {})
            if (error := order.get("error")) is not None:
                logger.error(f"Order Creation Error. {error}")  

        return response

    async def batch_cancel_orders(self, orders: List[str]):
        '''
        Makes DELETE request to batch_delete_orders endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/orders/batched'

        payload = {"ids": orders}

        response = await self._request(method="DELETE", path=path, json=payload)

        return response

    async def get_event(self, event_ticker: str):
        '''
        Makes GET request to get_event endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = f'/trade-api/v2/events/{event_ticker}'

        response = await self._request(method="GET", path=path)

        return response
    
    async def get_market(self, market_ticker: str):
        '''
        Makes GET request to markets endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''

        path = f'/trade-api/v2/markets/{market_ticker}'

        response = await self._request(method="GET", path=path)
        
        return response

    async def get_user_data_timestamp(self):
        '''
        Makes GET request to get_user_data_timestamp endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/exchange/user_data_timestamp'

        response = await self._request(method="GET", path=path)

        return response
