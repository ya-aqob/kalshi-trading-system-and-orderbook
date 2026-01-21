import websockets
import json
import asyncio
from typing import Callable
from .CryptoWebsocketResponses import TickerUpdate, IndexTick
import logging

logger = logging.getLogger("crypto_websocket")

class CryptoWebsocket:
    '''
    Basic websocket class for the Crypto.com API
    that supports streaming ticker and index data
    for cryptocurrency instruments.
    '''
    
    # State management
    uri: str
    on_tick: Callable[[], None] | None
    subscriptions: set
    tick_state: TickerUpdate
    _running: bool
    _msg_id: int

    # Retry logic
    retries: int
    max_retries: int
    base_delay: float
    max_delay: float

    def __init__(self, channels: list[str], on_ticker_tick: Callable[[], None] | None = None, 
                 on_index_tick = Callable[[], None], max_retries: int = 5, base_delay: float = 1.0, 
                 max_delay: float = 60.0):
        
        self.uri = "wss://stream.crypto.com/exchange/v1/market"
        self.ws = None

        self.on_ticker_tick = on_ticker_tick
        self.on_index_tick = on_index_tick

        self.subscriptions = set(channels)
        self.ticker_state = None
        self.index_state = None

        self._running = False
        self._msg_id = 0
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def _next_id(self) -> int:
        '''
        Increments message id and 
        returns the next id.
        '''
        self._msg_id += 1
        return self._msg_id

    async def run(self) -> None:
        '''
        Running loop with retry logic and exponential backup.
        Subscribes to channels and handles messages.
        '''
        self._running = True
        retries = 0
        delay = self.base_delay

        while self._running and retries < self.max_retries:
            try:
                async with websockets.connect(self.uri) as ws:
                    self.ws = ws
                    retries = 0
                    delay = self.base_delay
                    
                    if self.subscriptions:
                        await self._send_subscribe(list(self.subscriptions))

                    async for message in ws:
                        if not self._running:
                            break
                        data = json.loads(message)
                        self._handle_message(data)
                        
            except websockets.ConnectionClosed:
                retries += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay)
            except Exception as e:
                retries += 1
                await asyncio.sleep(delay)
                delay = min(delay * 2, self.max_delay)
        
        self._running = False
        self.ws = None

    async def _send_subscribe(self, channels: list[str]) -> None:
        '''
        Builds channel payload and dispatches subscription
        request.
        '''
        if not self.ws:
            raise RuntimeError("Crypto websocket not configured")
        
        self.subscriptions.update(channels)
        msg = {"method": "subscribe", "params": {"channels": channels}}
        
        response = await self.ws.send(json.dumps(msg))

        logger.info(f"Attempt subscribe to channels: {channels}.")

    async def subscribe(self, channels: list[str]) -> None:
        '''
        Subscribes to channel list.
        '''        
        if self.ws:
            await self._send_subscribe(channels)

    def _handle_message(self, data: dict) -> None:
        '''
        Parses message data and dispatches message
        to respective handler.
        '''
        logger.info(f"Data received: {data}")

        type = data.get("result", {}).get("channel", None)
        if type == "index":
            result = data.get("result", {}).get("data", [])
            if result:
                self._handle_index_tick(result[0])
        if type == "ticker":
            result = data.get("result", {}).get("data", [])
            if result:
                self._handle_ticker_update(result[0])

        return

    def _handle_index_tick(self, data: dict) -> None:
        '''
        Validates index update and calls the on-index-tick
        callback.
        '''
        index_tick = IndexTick.model_validate(data)
        self.index_state = index_tick
        if self.on_index_tick:
            self.on_index_tick()        

    def _handle_ticker_update(self, data: dict) -> None:
        '''
        Validates ticker update and calls the on-ticker-tick
        callback.
        '''
        tick = TickerUpdate.model_validate(data)
        self.ticker_state = tick
        if self.on_ticker_tick:
            self.on_ticker_tick()

    def get_tick(self) -> TickerUpdate | IndexTick | None:
        '''
        Returns the most recent tick of the channel that is
        subscribed to. Defaults to the ticker stream if subscribed
        to both ticker and index channels.
        '''
        if self.ticker_state:
            return self.ticker_state
        elif self.index_state:
            return self.index_state
        else:
            return

    async def stop(self) -> None:
        '''
        Closes the websocket and terminates
        the listen loop.
        '''
        self._running = False
        if self.ws:
            try:
                logger.info(f"Closing connection...")
                await self.ws.close()
            except Exception:
                pass