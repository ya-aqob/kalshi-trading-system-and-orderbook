from typing import List
from collections import deque
from decimal import Decimal
from .OrderBook import OrderBook
from .OrderBookSnapshot import OrderBookSnapshot
from client.API import KalshiAPI
from client.KSocket import KalshiWebsocket
from client.Session import Session
import numpy as np
from asyncio import Queue
import logging
from .Order import Order
from model.Model import Model
from executor.Executor import Executor
import asyncio
from sortedcontainers import SortedList
from .PriceBuffer import PriceBuffer
import time

class BinaryMarket:
    
    executor: Executor | None                # Executor responsible for executing trades in market

    ticker: str                              # The ticker of the BinaryPrediction Market

    price_window: PriceBuffer                # history of prices in sequence number order, [price, timestamp] pairs
    orderbook: OrderBook                     # The mutable orderbook representing the market

    volatility: float | None                 # Volatility over price_window

    fresh: bool                              # Stale when update has been received and quote does not reflect post-delta state


    def __init__(self, ticker: str, volatility_window: int, on_gap_callback=None):
        
        self.price_window = PriceBuffer(max_size=volatility_window)
        self.volatility_window = volatility_window
        self.ticker = ticker

        self.executor = None
        self.on_gap_callback = on_gap_callback
        self.orderbook = OrderBook()

        self.last_mid_price = None
        self.volatility = None

    def set_executor(self, executor: Executor):
        self.executor = executor
    
    def set_websocket(self, websocket: KalshiWebsocket)
        self.ws = websocket

    def update(self, timestamp: float, update: dict) -> None:
        '''
        Takes orderbook update channel message.
        Applies update to orderbook and unsets fresh flag.
        Returns none.
        '''
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

        self.fresh = False

        if not self.executor.quoting_task or self.executor.quoting_task.done():
            self.executor.quoting_task = asyncio.create_task(self.executor._execute_quote())

    def on_sequence_mismatch(self) -> None:
        '''
        Handles sequence mismatch by triggering a subscription cycle.
        Returns None.
        '''
        asyncio.create_task(self.ws.rebuild_on_gap(self.ticker))
        return
        

    def snapshot(self) -> OrderBookSnapshot:
        '''
        Returns a snapshot of the current orderbook.
        '''
        return OrderBookSnapshot.from_orderbook(self.orderbook)

    def _load_snapshot(self, timestamp: float, seq_n: int | None, snapshot_msg: dict) -> None:
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
               0.0 if no computation can be done.
               volatility else
        Returns:
            None if price history is shorter than 60 seconds
            calculated volatility otherwise
        '''

        variance_values = []

        # Sample volatility_window number of events
        start_idx = max(1, 1 + (len(self.price_window) - self.volatility_window))
        
        price_values = self.price_window.get_last_n(self.volatility_window)

        for i in range(start_idx, len(self.price_window)):
            delta_time = price_values[i][1] - price_values[i - 1][1]

            # Don't sample same time twice
            if delta_time == 0:
                continue 

            curr_price = np.clip(price_values[i][0], 1e-6, 1 - 1e-6)
            prev_price = np.clip(price_values[i - 1][0], 1e-6, 1 - 1e-6)

            # Logit transformed returns
            logit_return = np.log(curr_price / (1 - curr_price)) - np.log(prev_price / (1 - prev_price))

            variance_per_unit_time = (logit_return ** 2) / delta_time
            variance_values.append(variance_per_unit_time)
        
        return np.sqrt(np.mean(variance_values)) if variance_values else 0.0 

    def update_volatility(self, volatility: float) -> None:
        self.volatility = volatility

    def get_volatility(self) -> float | None:
        return self.volatility
    
    def get_mid_price(self) -> float | None:
        return self.last_mid_price

    def is_fresh(self) -> bool:
        return self.fresh