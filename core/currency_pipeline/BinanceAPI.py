import httpx
import logging

logger = logging.getLogger("binance_rest")

class BinanceAPI:
    '''
    Basic client for accessing Binance's REST API.
    '''
    def __init__(self):
        self.base_url = "https://api.crypto.com/exchange/v1/"
        self.client = None

    async def connect(self):
        '''Init the client'''
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.base_url)

    async def close(self):
        '''Close the client'''
        if self.client:
            await self.client.aclose()
            self.client = None
    
    async def get_klines(self, symbol: str, interval: str, limit: int = 500):
        '''
        Returns response json from get_klines endpoint with params.
        '''
        url = self.base_url + "public/get-candlestick"

        params = {
            "instrument_name": symbol,
            "timeframe": interval,
            "count": limit
        }

        response = await self.client.request(method="GET", url=url, params=params)

        return response.json()