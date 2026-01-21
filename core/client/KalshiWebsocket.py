from __future__ import annotations
from typing import TYPE_CHECKING
from .KalshiAuthentication import KalshiAuthentication
from .KalshiWebsocketResponses import FillEnvelope, OrderBookDeltaEnvelope, OrderBookSnapshotEnvelope
import websockets
import json
import logging
import asyncio
import time
from pydantic import BaseModel, ValidationError
from typing import Literal
from live_trading.RiskExceptions import *

if TYPE_CHECKING:
    from market import BinaryMarket
    from executor import Executor
    from websockets import ClientConnection

logger = logging.getLogger("kalshi_websocket")

class KalshiWebsocket:
    '''
    Websocket class for KalshiAPI.

    Executor and market must be injected for 
    on-message event handling.
    '''

    # Composed Objects
    session: KalshiAuthentication
    market: BinaryMarket # None on init, injected dependancy
    executor: Executor   # None on init, injected dependancy
    
    # Retry logic parameters
    max_retries: int  # The maximum number of retries attempted before exiting
    base_delay: float # Base delay of retry loop
    max_delay: float  # Max retry loop delay
    retries: int      # Current number of retries attempted

    # Websocket management
    ws: ClientConnection  # None on init. MUST be set before any other method calls.
    ws_url: str           # Base URL for websocket
    message_id: int       # Unique ID for next message to be sent
    is_running: bool      # Retry connect iff is_running

    # Channel, sid, ticker mappings
    ticker_to_sid: dict    # [ticker, sid] map
    sid_to_ticker: dict    # [sid, ticker] map
    pending_requests: dict # [message_id, ticker] map

    # Orderbook rebuild flag
    pending_snapshot: bool

    def __init__(self, session: KalshiAuthentication, max_retries: int = 5, 
                 base_delay: float = 1.0, max_delay: float = 60.0):
        self.session = session
        self.market = None
        self.executor = None

        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

        self.ws_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        self.ws = None
        self.message_id = 1

        self.retries = 0

        self.ticker_to_sid = {} # [str, int]
        self.sid_to_ticker = {} # [int, str]

        self.pending_requests = {} # [int, str]

        self.pending_snapshot = False
        self.is_running = False

    def set_executor(self, executor: Executor) -> None:
        '''
        Injects executor dependency
        '''
        self.executor = executor    

    def set_market(self, market: BinaryMarket) -> None:
        '''
        Injects market dependency
        '''
        self.market = market

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
    
    async def connect(self) -> None:
        '''
        Establishes connection to websocket with retry logic
        and exponential back-off.
        Raises exception after retry logic fails.
        '''
        while self.retries < self.max_retries:
            try:
                headers = self._gen_headers("GET", "/trade-api/ws/v2")
                self.ws = await websockets.connect(self.ws_url, 
                                                   additional_headers=headers, 
                                                   ping_interval=10, 
                                                   ping_timeout=10)
                self.retries = 0
                logger.info("Websocket connected successfully")
                return
            except Exception as e:
                self.retries += 1
                delay = min(self.base_delay * (2 ** (self.retries - 1)), self.max_delay)
                logger.error(f"Connection failed: {e}. Retrying in {delay}s... (attempt {self.retries})")
                await asyncio.sleep(delay)
        
        raise Exception(f"Failed to connect after {self.retries} attempts.")

    async def _restore_subs(self):
        '''
        Restores existing orderbook subscriptions.
        Clears and rebuilds ticker-sid maps.
        '''
        tickers = list(self.ticker_to_sid.keys())

        if not tickers:
            logger.info("No subscriptions to restore")
            return

        logger.info(f"Restoring {len(tickers)} orderbook subscriptions...")

        self.ticker_to_sid.clear()
        self.sid_to_ticker.clear()
        
        for ticker in tickers:
            await self.subscribe_orderbook(ticker)

    async def subscribe_orderbook(self, ticker: str) -> None:
        '''
        Subscribes to orderbook feed, adds to pending request
        map and increments message_id.

        Raises RuntimeError if websocket is not connected.
        '''
        subscription = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_ticker": ticker
            }
        }

        self.pending_requests[self.message_id] = ticker

        if self.ws is None:
            raise RuntimeError("Websocket not connected")
        
        await self.ws.send(json.dumps(subscription))
        self.message_id += 1
    
    async def unsubscribe_orderbook(self, ticker: str) -> None:
        '''
        Attempts to unsubscribe from ticker's orderbook feed and increments message_id.
        Maintains ticker-sid maps.

        Raises RuntimeError if websocket is not connected.
        '''
        if ticker not in self.ticker_to_sid:
            logger.warning(f"Cannot unsubscribe from {ticker} - not subscribed")
            return
        
        sid = self.ticker_to_sid[ticker]
        unsubscription = {
            "id": self.message_id,
            "cmd": 'unsubscribe',
            "params": {
                "sids": [sid]
            }
        }

        if self.ws is None:
            raise RuntimeError("Websocket not connected")
        
        await self.ws.send(json.dumps(unsubscription))
        self.message_id += 1

        # Atomic deletion sequence to ensure sync between mappings
        if ticker in self.ticker_to_sid:
            del self.ticker_to_sid[ticker]
            del self.sid_to_ticker[sid]

    async def subscribe_fills(self) -> None:
        '''
        Subscribes to fill feed and increments message_id.

        Raises RuntimeError if websocket is not connected.
        '''
        subscription = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["fill"]
            }
        }

        if self.ws is None:
            raise RuntimeError("Websocket not connected")
    
        await self.ws.send(json.dumps(subscription))
        self.message_id += 1
    
    async def subscribe_trades(self, ticker: str) -> None:
        '''
        Subscribes to trade feed and increments message_id.
        
        Raises RuntimeError if websocket is not connected.
        '''
        subscription = {
            "id": self.message_id,
            "cmd": "subscribe",
            "params": {
                "channels": ["trades"],
                "market_ticker": ticker
            }
        }
        if self.ws is None:
            raise RuntimeError("Websocket not connected")
        
        await self.ws.send(json.dumps(subscription))
        self.message_id += 1

    async def _rebuild_on_gap(self, ticker: str) -> None:
        '''
        Sets pending_snapshot flag to ignore deltas and cycles 
        orderbooks to rebuild on snapshot.

        Called from market when sequence mismatch is identified.
        '''

        # Set flag to ignore deltas until orderbook repaired
        self.pending_snapshot = True

        await self.unsubscribe_orderbook(ticker)
        await self.subscribe_orderbook(ticker)

    async def handle_gap(self, ticker: str) -> None:
        '''
        Starts rebuild of orderbook.
        Called when sequence invariant is broken or questionable.
        '''
        await self._rebuild_on_gap(ticker)

    async def handle_msg(self, message) -> None:
        '''
        Handles and routes all messages for supported channels: orderbook_delta and fill.
        Validates all messages for supported channels against response models and schemas.

        Calls callbacks for respective channel message handling.
        Rebuilds orderbook on malformed orderbook message.

        Parses some errors for logging.

        Raises exception for authentication failures and logs all others.
        '''
        data = json.loads(message)
        timestamp = time.time()
        msg_type = data.get("type")

        if msg_type == "subscribed":
            id = data['id']
            channel = data['msg']["channel"]
            sid = data['msg']['sid']

            if channel == "orderbook_delta":
                ticker = self.pending_requests.pop(id, None)
                self.sid_to_ticker[sid] = ticker
                self.ticker_to_sid[ticker] = sid
            
                logger.info(f"Subscribed to {channel} for ticker {ticker} (sid={sid}).")
            else:
                logger.info(f"Subscribed to channel {channel} (sid={sid})")

        try:
            if msg_type == "orderbook_snapshot":
                envelope = OrderBookSnapshotEnvelope.model_validate(data)
                self.pending_snapshot = False
                logger.info("Orderbook snapshot received")
                await self.market.update(envelope)

            elif msg_type == "orderbook_delta":
                envelope = OrderBookDeltaEnvelope.model_validate(data)
                # ignore deltas if sequence chain broken
                if self.pending_snapshot:
                    logger.debug("Ignoring delta while rebuilding orderbook...")
                    return
                await self.market.update(envelope)
        
        except ValidationError as e:
            logger.error(f"Invalid orderbook received: {e}")
            await self.handle_gap(self.market.ticker)   

        try:
            if msg_type == "fill":
                envelope = FillEnvelope.model_validate(data)
                logger.info(f"Fill received: {envelope.msg.trade_id}")
                self.executor.on_fill(envelope.msg)

        except ValidationError as e:
            await self.executor.reconcile()
        
        if msg_type == "error":
            code = data.get('msg', {}).get('code')
            msg = data.get('msg', {}).get('msg')
            id = data.get('id')

            logger.error(f"Server error {code}: {msg} (msg_id={id})")

            if code == 6:
                pass
            elif code == 401:
                logger.critical("Websocket Auth failed")
                raise Exception("Websocket Auth failed")
            else:
                logger.warning(f"Unhandled error code: {code}")
        
        else:
            pass

        return
        
    async def close(self) -> None:
        '''
        Close websocket connection and unset running flag.
        Swallows all exceptions.
        '''
        logger.info("Closing Websocket connection...")

        self.is_running = False
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.error(f"Error closing Websocket: {e}")
        
        logger.info("Websocket closed")


    async def run(self) -> None:
        '''
        Initializes websocket if not started, then runs
        listen-handle loop. Exits on is_running flag and 
        swallows all other exceptions.
        '''
        self.is_running = True

        while self.is_running:
            try:
                if self.ws is None:
                    await self.connect()
                    if self.ticker_to_sid:
                        await self._restore_subs()
                
                async for message in self.ws:
                    try:
                        await self.handle_msg(message)
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse message: {e}")
                    except Exception as e:
                        logger.error(f"Failed to handle message: {e}", exc_info=True)
            
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: code={e.code}, reason={e.reason}")
                
                if self.is_running:
                    logger.info("Reconnecting")
                    await asyncio.sleep(.1)
                else:
                    break
            
            except Exception as e:
                logger.error(f"Unexpected error in run loop: {e}", exc_info=True)
            
            if not self.is_running:
                break
