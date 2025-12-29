from __future__ import annotations
from typing import TYPE_CHECKING
import asyncio
import numpy as np

from .PriceBuffer import PriceBuffer
from .OrderBookSnapshot import OrderBookSnapshot
from .OrderBook import OrderBook

if TYPE_CHECKING:
    from executor import Executor
    from client import KalshiWebsocket

class BinaryMarket:
    '''
    Class representing a single ticker in a single BinaryMarket
    '''
    executor: Executor         # None on init. MUST be injected before any method calls.

    ticker: str                # The ticker of the BinaryPrediction Market

    price_window: PriceBuffer  # history of prices in sequence number order, [price, timestamp] pairs
    orderbook: OrderBook       # The mutable orderbook representing the market

    volatility: float | None   # Volatility over price_window, None if price_window is not full

    def __init__(self, ticker: str, volatility_window: int, on_gap_callback=None):
        
        self.price_window = PriceBuffer(max_size=volatility_window)
        self.volatility_window = volatility_window
        self.ticker = ticker

        self.executor = None
        self.on_gap_callback = on_gap_callback
        self.orderbook = OrderBook()

        self.volatility = None
        self.fresh = True

    def set_executor(self, executor: Executor):
        self.executor = executor
    
    def set_websocket(self, websocket: KalshiWebsocket):
        self.ws = websocket

    async def update(self, timestamp: float, update: dict) -> None:
        '''
        Takes orderbook update channel message and updates the orderbook.
        Fire-and-forgets an attempt at quote placement/execution.
        Returns none.
        '''
        if self.executor is None:
            raise RuntimeError("Executor not configured")

        update_type = update["type"]
        data = update["msg"]
        seq_n = update["seq"]

        if update_type == "orderbook_snapshot":
            self._load_snapshot(timestamp, seq_n, data)
        elif update_type == "orderbook_delta":
            
            # Maintain sequence number invariant
            if self.orderbook.seq_n is not None and self.orderbook.seq_n != (seq_n - 1):

                if self.on_gap_callback:
                    self.on_gap_callback(self.ticker)

                return

            self._apply_delta(timestamp, seq_n, data)
        
        self.price_window.add([self.orderbook.mid_price, timestamp])
        
        self.update_volatility(self.calculate_volatility())

        if self.executor.should_attempt_quote():
            asyncio.create_task(self.executor.on_market_update())
        
    def snapshot(self) -> OrderBookSnapshot:
        '''
        Returns a snapshot of the current orderbook.
        '''
        return OrderBookSnapshot.from_orderbook(self.orderbook)

    def _load_snapshot(self, timestamp: float, seq_n: int, snapshot_msg: dict) -> None:
        # Clear price window, order invariant broken
        self.price_window = PriceBuffer(max_size=self.volatility_window)

        self.orderbook._apply_snapshot(timestamp, seq_n, snapshot_msg)
    
    def _apply_delta(self, timestamp: float, seq_n: int, delta_msg: dict) -> None:
        self.orderbook._apply_delta(timestamp, seq_n, delta_msg)

    def calculate_volatility(self) -> float | None:
        '''
        Returns volatility based on logit-transformed returns over the price_window
        array. 
        Returns:
               None if no computation can be done.
               volatility else
        '''

        variance_values = []
    
        size = min(len(self.price_window), self.volatility_window)
        price_values = self.price_window.get_last_n(size)
        
        for i in range(1, len(price_values)):
            delta_time = price_values[i][1] - price_values[i - 1][1]
            if delta_time <= 0:
                continue
            
            curr_price = float(price_values[i][0])
            prev_price = float(price_values[i - 1][0])
            
            # Simple price return (not logit)
            price_return = curr_price - prev_price
            variance_per_unit_time = (price_return ** 2) / delta_time
            variance_values.append(variance_per_unit_time)
        
        if not variance_values:
            return None
        
        return np.sqrt(np.mean(variance_values))

    def update_volatility(self, volatility: float) -> float | None:
        self.volatility = volatility

    def get_volatility(self) -> float | None:
        return self.volatility

    def is_fresh(self) -> bool:
        return self.fresh