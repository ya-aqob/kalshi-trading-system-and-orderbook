from __future__ import annotations
from typing import TYPE_CHECKING, Optional
import asyncio
import numpy as np

from .FeeSchedule import KalshiFeeSchedule
from .PriceBuffer import PriceBuffer
from .OrderBookSnapshot import OrderBookSnapshot
from .OrderBook import OrderBook

if TYPE_CHECKING:
    from client.KalshiWebsocketResponses import OrderBookDeltaEnvelope, OrderBookSnapshotEnvelope, OrderBookDeltaMsg, OrderBookSnapshotMsg

class BinaryMarket:
    '''
    Base class representing a single ticker Binary Market.

    All asset-specific fields and methods are relative to the Yes resolution.
    
    The complement invariant (No fields are complements of Yes fields) is maintained
    by the Kalshi backend, allowing for access to both sides of the orderbook.

    Updates trigger the post_update_action which can be wired to trigger
    trading, position evaluation, etc. in the executor.

    Sequence order variant is maintained and orderbook is rebuilt when
    sequence is broken.
    '''

    # Kalshi Information
    ticker: str                     # The ticker of the BinaryPrediction Market
    fee_schedule: KalshiFeeSchedule # Fee schedule specific to the market

    # State Elements
    price_window: PriceBuffer       # history of delta prices in sequence number order, [price, timestamp (POSIX (ns))] pairs
    orderbook: OrderBook            # The mutable orderbook representing the market
    volatility: float | None        # Volatility over price_window, None if price_window has fewer than two sequential
                                    # price samples


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
        

    async def update(self, update: OrderBookSnapshotEnvelope | OrderBookDeltaEnvelope) -> None:
        '''
        Updates the orderbook to represent update.
        Makes call to the post_update_action handler.
        '''
        if update.type == "orderbook_snapshot":
            self._load_snapshot(update.seq, update.msg)
        
        if update.type == "orderbook_delta":
            
            # Maintain sequence number invariant
            if self.orderbook.seq_n is not None and self.orderbook.seq_n != (update.seq - 1):

                if self.on_gap_callback:
                    await self.on_gap_callback(self.ticker)

                return

            self._apply_delta(update.seq, update.msg)
        
            self.price_window.add([self.orderbook.mid_price, update.msg.ts])
        
        self.update_volatility(self.calculate_volatility())

        self.post_update_action()

    def post_update_action(self) -> None:
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

    def _load_snapshot(self, seq_n: int, snapshot_msg: OrderBookSnapshotMsg) -> None:
        '''
        Resets the price window and updates orderbook to given snapshot
        '''
        # Clear price window, order invariant broken
        self.price_window = PriceBuffer(max_size=self.volatility_window)

        self.orderbook._apply_snapshot(seq_n, snapshot_msg)
    
    def _apply_delta(self, seq_n: int, delta_msg: OrderBookDeltaMsg) -> None:
        '''
        Updates orderbook to reflect new delta
        '''
        self.orderbook._apply_delta(seq_n, delta_msg)

    def calculate_volatility(self) -> float | None:
        '''
        Calculates the annualized, realized arithmetic volatility over the samples 
        of price window. Returns None if there are fewer than two sequential
        price samples.
        '''
        variance_values = []
    
        size = min(len(self.price_window), self.volatility_window)
        price_values = self.price_window.get_last_n(size)
        
        for i in range(1, len(price_values)):
            # in years
            delta_time = (price_values[i][1] - price_values[i - 1][1]) / (1e9 * 60 * 60 * 24 * 365.25)
            
            if delta_time <= 0:
                continue
            
            curr_price = float(price_values[i][0])
            prev_price = float(price_values[i - 1][0])
            
            price_return = curr_price - prev_price
            variance_per_unit_time = (price_return ** 2) / delta_time
            variance_values.append(variance_per_unit_time)
        
        if not variance_values:
            return None
        
        return np.sqrt(np.mean(variance_values))

    def update_volatility(self, volatility: float | None) -> float | None:
        '''
        Sets new volatility
        '''
        self.volatility = volatility

    def get_volatility(self) -> float | None:
        '''
        Returns current volatility
        '''
        return self.volatility