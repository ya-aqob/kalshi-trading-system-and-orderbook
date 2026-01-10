import httpx

class BinanceAPI:
    def __init__(self):
        self.base_url = "https://api.binance.us"
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
        url = self.base_url + "/api/v3/klines"

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }

        response = await self.client.request(method="GET", url=url, params=params)

        return response.json()