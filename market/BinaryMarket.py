from __future__ import annotations
from typing import TYPE_CHECKING, Optional
import asyncio
import numpy as np

from .FeeSchedule import KalshiFeeSchedule
from .PriceBuffer import PriceBuffer
from .OrderBookSnapshot import OrderBookSnapshot
from .OrderBook import OrderBook

if TYPE_CHECKING:
    from client.WebsocketResponses import OrderBookDeltaEnvelope, OrderBookSnapshotEnvelope, OrderBookDeltaMsg, OrderBookSnapshotMsg

class BinaryMarket:
    '''
    Base class representing a single ticker in a Binary Market (yes/no).
    All asset-specific fields and methods are based on the YES resolution
    in the given ticker's market.

    Provides on_update_callback to allow for connection executor update logic.
    '''
    ticker: str                     # The ticker of the BinaryPrediction Market

    price_window: PriceBuffer       # history of prices in sequence number order, [price, timestamp] pairs
    orderbook: OrderBook            # The mutable orderbook representing the market

    volatility: float | None        # Volatility over price_window, None if price_window is not full
    
    fee_schedule: KalshiFeeSchedule # Fee schedule specific to the market

    def __init__(self, ticker: str, volatility_window: int, on_gap_callback=None, on_update_callback=None,
                 taker_fee_rate=.07, maker_fee_rate=.0175):
        
        self.orderbook = OrderBook()
        self.fee_schedule = KalshiFeeSchedule(taker_fee_rate=taker_fee_rate, maker_fee_rate=maker_fee_rate)
        self.price_window = PriceBuffer(max_size=volatility_window)

        self.volatility_window = volatility_window
        self.volatility = None
        self.ticker = ticker

        self.on_gap_callback = on_gap_callback
        self.on_update_callback = on_update_callback
        

    async def update(self, timestamp: float, update: OrderBookSnapshotEnvelope | OrderBookDeltaEnvelope) -> None:
        '''
        Updates the orderbook to match update.
        Makes call to on-update callback.
        Returns none.
        '''
        if update.type == "orderbook_snapshot":
            self._load_snapshot(timestamp, update.seq, update.msg)
        
        if update.type == "orderbook_delta":
            
            # Maintain sequence number invariant
            if self.orderbook.seq_n is not None and self.orderbook.seq_n != (update.seq - 1):

                if self.on_gap_callback:
                    self.on_gap_callback(self.ticker)

                return

            self._apply_delta(timestamp, update.seq, update.msg)
        
        self.price_window.add([self.orderbook.mid_price, timestamp])
        
        self.update_volatility(self.calculate_volatility())

        self.post_update_action()

    def post_update_action(self):
        '''
        Calls on-update callback if it exists.
        '''
        if self.on_update_callback:
            self.on_update_callback()

    def snapshot(self) -> OrderBookSnapshot:
        '''
        Returns a snapshot of the current orderbook.
        '''
        return OrderBookSnapshot.from_orderbook(self.orderbook)

    def _load_snapshot(self, timestamp: float, seq_n: int, snapshot_msg: OrderBookSnapshotMsg) -> None:
        '''Resets the price window and updates orderbook to given snapshot'''
        # Clear price window, order invariant broken
        self.price_window = PriceBuffer(max_size=self.volatility_window)

        self.orderbook._apply_snapshot(timestamp, seq_n, snapshot_msg)
    
    def _apply_delta(self, timestamp: float, seq_n: int, delta_msg: OrderBookDeltaMsg) -> None:
        '''Updates orderbook to reflect new delta'''
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
        '''Sets new volatility'''
        self.volatility = volatility

    def get_volatility(self) -> float | None:
        '''Returns current volatility'''
        return self.volatility