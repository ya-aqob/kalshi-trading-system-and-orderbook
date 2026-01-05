import websockets
import json
import asyncio
from typing import Callable
from .DeribitResponse import OptionTick, Instrument
import requests
import logging

logger = logging.getLogger("der_websocket")

class DeribitSocket:
    '''
    Basic class for getting instrument information
    from Deribit public websocket.

    Provides on_tick event-handler for event-driven
    trading.
    '''

    # State management
    uri: str
    on_tick: Callable[[OptionTick], None] | None
    subscriptions: set
    state: dict
    _running: bool
    _msg_id: int

    # Retry logic
    retries: int
    max_retries: int
    base_delay: float
    max_delay: float

    def __init__(self, on_tick = None, max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0):

        self.uri = "wss://www.deribit.com/ws/api/v2"
        self.ws = None
        self.on_tick = on_tick
        self.subscriptions = set()
        self.state = {}
        self._running = False
        self._msg_id = 0

        self.retries = 0
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def _next_id(self) -> int:
        '''
        Increments _msg_id and returns new field.
        '''
        self._msg_id += 1
        return self._msg_id

    async def connect(self):
        '''
        Connects to websocket with retry logic.
        '''
        self._running = True
        delay = self.base_delay

        while self._running:
            while self.retries < self.max_retries:

                try:
                    async with websockets.connect(self.uri) as ws:
                        self.retries = 0
                        delay = self.base_delay
                        self.ws = ws

                        if self.subscriptions:
                            await self._subscribe(list(self.subscriptions))
                        
                        asyncio.create_task(self._heartbeat())

                        async for msg in ws:
                            self._handle_message(json.loads(msg))
                
                except websockets.ConnectionClosed as e:
                    self.retries += 1
                    delay = min(delay * 2, self.max_delay)
                    await asyncio.sleep(delay)
                except Exception as e:
                    self.retries += 1
                    delay = min(delay * 2, self.max_delay)
                    await asyncio.sleep(delay)
    
    async def _heartbeat(self):
        '''
        Keeps connection alive
        '''
        while self.ws and self._running:
            try:
                msg = {
                    "jsonrpc": "2.0",
                    "id": self._next_id(),
                    "method": "public/set_heartbeat",
                    "params": {"interval": 30}
                }
                await self.ws.send(json.dumps(msg))
                await asyncio.sleep(30)
            except:
                break
    
    async def subscribe(self, instruments: list[str]):
        '''Subscribe to ticker channels for instruments'''
        self.subscriptions.update(instruments)
        if self.ws:
            await self._subscribe(instruments)
    
    async def _subscribe(self, instruments: list[str]):
        '''
        Subscribes to instruments.
        '''
        channels = [f"ticker.{inst}.100ms" for inst in instruments]
        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "public/subscribe",
            "params": {"channels": channels}
        }
        response = await self.ws.send(json.dumps(msg))
        logger.info(f"Subscribed.")

    def _handle_message(self, data: dict):
        '''
        Handles ticks and heartbeats.
        '''
        if "params" in data and data.get("method") == "subscription":
            self._handle_tick(data["params"]["data"])
            logger.info(f"Tick received.")

        elif data.get("method") == "heartbeat":
            if data["params"]["type"] == "test_request":
                asyncio.create_task(self._pong())
    
    async def _pong(self):
        '''
        Sends pong frame.
        '''
        msg = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "public/test"
        }
        await self.ws.send(json.dumps(msg))
    
    def _handle_tick(self, data: dict):
        '''
        Captures tick information into tick object,
        saves to field, and then calls tick post-action.
        '''
        tick = OptionTick.model_validate(data)
        self.state[tick.instrument_name] = tick
        self.on_tick(tick)
    
    def stop(self):
        '''
        Sets _running to false to stop
        connection.
        '''
        self._running = False

class DeribitREST:
    '''
    Basic class for the public Deribit REST API.

    All methods are synchronous and have to be 
    put to threads for async operation.
    '''
    
    def get_instruments(self, currency: str, kind: str) -> list[Instrument]:
        '''
        Returns the current instruments of kind in currency.

        Generates HTTP and Decode errors.
        '''
        resp = requests.get(
                url="https://www.deribit.com/api/v2/public/get_instruments",
                params={
                    "currency": currency,
                    "kind": kind,
                    "expired": "false"
                }
            )
        
        resp.raise_for_status()
        data = resp.json()
    
        return [Instrument.model_validate(i) for i in data["result"]]