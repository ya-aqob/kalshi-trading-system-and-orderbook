from .Session import Session
import requests
from typing import Tuple, List
import time

class APIError(Exception):
    pass

class RateLimitError(Exception):
    pass

class AuthError(Exception):
    pass

class KalshiAPI:
    '''
    Class for Kalshi's REST API with retry logic.
    All methods are synchronous and need to be passed to threads
    to prevent slow blocking.
    '''
    def __init__(self, session: Session, max_retries: int = 3, retry_delay: float = .1, time_out: int = 5):
        self.session = session
        self.base_url = "https://api.elections.kalshi.com"

        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.time_out = time_out

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
    
    def _request(self, method: str, path: str, params=None, json=None):
        url = self.base_url + path
        for attempt in range(self.max_retries):
            try:
                headers = self._gen_headers(method=method, path=path)
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json,
                    timeout=self.time_out
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                raise APIError("Request timed out")
            except requests.exceptions.HTTPError as e:
                status_code = response.status_code

                if status_code == 401:
                    raise AuthError("Authentication failed") from e
                elif status_code == 429:
                    raise RateLimitError("Rate limit exceeded") from e
                elif status_code >= 500 and attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    continue
                else:
                    raise APIError(f"API error ({status_code}): {e}") from e
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    continue
                raise APIError(f"Network error: {e}") from e

        raise APIError("Max retries exceeded")

    def get_orders(self, ticker: str | None = None, event_ticker:str | None = None, min_ts: int | None = None, max_ts: int| None = None, status: str | None = None, limit: int=100, cursor: str | None = None):
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
        response = self._request(method="GET", path=path, params=payload)
        
        return response

    def get_positions(self, cursor: str| None =None, limit: int  = 100, count_filter: str | None = None, ticker: str | None = None, event_ticker: str | None = None):
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
        response = self._request(method="GET", path=path, params=payload)

        return response

    def get_balance(self):
        '''
        Makes GET request to get_balance endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/balance'

        response = self._request(method="GET", path=path)

        return response
    
    def get_market_orderbook(self, ticker: str, depth: int = 0):
        '''
        Makes GET request to get_market_orderbook endpoint.
        Generates HTTP status error.
        Returns:
            Response JSON
        '''
        path = f'/trade-api/v2/markets/{ticker}/orderbook'
        params = {"depth": depth}

        response = self._request(method="GET", path=path, params=params)

        return response
    
    def batch_create_orders(self, orders: List[dict]):
        '''
        Makes POST request to batch_create_orders endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/orders/batched'

        payload = {"orders": orders}

        response = self._request(method="POST", path=path, json=payload)

        
        return response

    def batch_cancel_orders(self, orders: List[str]):
        '''
        Makes DELETE request to batch_delete_orders endpoint.
        Generates HTTP status errors.
        Returns:
            Response JSON
        '''
        path = '/trade-api/v2/portfolio/orders/batched'

        payload = {"ids": orders}

        response = self._request(method="DELETE", path=path, json=payload)

        return response