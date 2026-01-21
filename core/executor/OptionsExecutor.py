from __future__ import annotations
from core.client import FillMsg
from .Executor import Executor
from typing import TYPE_CHECKING, Callable
import asyncio
from asyncio import Lock, Event
from datetime import datetime
import pytz
import time
import math
import logging
from core.currency_pipeline import TickerUpdate, IndexTick

logger = logging.getLogger("pricing_decisions")

if TYPE_CHECKING:
    from core.currency_pipeline import TickerUpdate, IndexTick
    from core.client import KalshiAPI
    from core.market import BinaryMarket
    from core.client import KalshiAuthentication
    from core.market import OrderBookSnapshot
    from core.market import Order
    from core.derivatives_pipeline import Instrument
    from core.model import BSBOModel
    from .ExecutorSnapshot import ExecutorSnapshot
    from core.currency_pipeline import VolatilityEstimator


class OptionsExecutor(Executor):
    '''
    Executor specialized for trading in "x currency above y strike at z time".
    
    Trades on edge between true price of the market (approximated as a digital option)
    and the actual price of the bid-ask spread of the market.

    Jtilizes event-conflation on high-frequency websocket ticks
    to generate trades on fresh edges.
    '''
    
    model: BSBOModel

    # Binary Market Metadata
    prediction_strike: float # Strike price of binary market in dollars
    prediction_expiry: float # Expiry time of the binary market in POSIX (ms)
    currency: str            # Currency name in Deribit format

    # Syncronization
    _tick_event:          asyncio.Event            # Event representing pending ticks
    _tick_processor_task: asyncio.Task | None      # Prevents repetitive tick tasks
    fresh_data_callback: Callable                  # Returns the freshest tick data in
                                                   # the WS pipeline

    def __init__(self, kalshi_api: KalshiAPI, market: BinaryMarket, 
                 session: KalshiAuthentication, max_inventory: int, min_edge: float,
                 currency: str, strike: float, expiry_datetime: str,
                 model: BSBOModel, v_estimator: VolatilityEstimator,
                 fresh_data_callback: Callable, max_inventory_dev, max_balance_dev,
                 minimum_balance
                 ):
        
        super().__init__(kalshi_api, market, session, max_inventory, minimum_balance, max_inventory_dev, max_balance_dev)

        self.fresh_data_callback = fresh_data_callback

        self.min_edge = min_edge
        self.currency = currency
        self.prediction_expiry = self._convert_timestamp(expiry_datetime)
        self.prediction_strike = strike

        self.model = model

        self._tick_event = asyncio.Event()
        self._fresh_tick = None
        self._tick_processor_task = None

        self.v_estimator = v_estimator

        self.sim_open_orders = []

    def _convert_timestamp(self, est_time: str) -> int:
        '''
        Converts HH:MM MM/DD/YYYY (EST) time to POSIX (ms) 
        timestamp.
        '''
        est = pytz.timezone('America/New_York')
        dt = est.localize(datetime.strptime(est_time, "%H:%M %m/%d/%Y"))
        unix_timestamp = int(dt.timestamp())
        return unix_timestamp * 1000

    def on_market_update(self) -> None:
        '''
        Event handler for market updates.
        Does nothing.
        '''
        return

    def on_fill(self, fill: FillMsg) -> None:
        '''
        Updates inv and order tracking
        according to the fill received.
        '''
        self.update_inv_on_fill(fill)

    def on_tick(self) -> None:
        '''
        Event handler for ticks in the underlying currency.
        Dispatches new tick processing task if one is not running.
        Updates freshest tick to this tick.
        '''
        self._tick_event.set()

        if self._tick_processor_task is None or self._tick_processor_task.done():
            self._tick_processor_task = asyncio.create_task(self._tick_processor())

    def parse_tick(self, tick: TickerUpdate | IndexTick) -> float:
        '''
        Returns the estimated price of the underlying asset
        based on mid price for orderbook ticks and index
        value for index ticks.
        '''
        if isinstance(tick, TickerUpdate):
            mid_price = .5 * (float(tick.k) + float(tick.b))
        else:
            mid_price = float(tick.v)

        return mid_price
    
    async def _tick_processor(self) -> None:
        '''
        Waits for tick event flag (1s timeout to return). Clears tick event flag
        and starts action iff tick event flag is set in window.
        '''
        while True:
            try:
                await asyncio.wait_for(self._tick_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                return
            
            self._tick_event.clear()

            await self.on_tick_action()

    async def on_tick_action(self) -> None:
        '''
        Acquires execution lock and begins pricing and trading logic.

        Cancels all outstanding orders, captures states, and generates 
        appropriate order for tick, market, and executor state data.
        '''

        async with self._execution_lock:
            await self._cancel_outstanding_orders()
            if (time.time() - self.v_estimator.timestamp) >= 300:
                await self.v_estimator.add_candle()

            # Grab freshest states for action
            market_state = self.market.snapshot()
            executor_state = self.snapshot()

            recent_tick = self.fresh_data_callback()
            
            if not recent_tick:
                return
            
            signal_price = self.parse_tick(recent_tick)
            volatility = self.v_estimator.rogers_vol_estimate()

            true_price = self._generate_price_of_market(signal_price, volatility)

            logger.info(f"Price Decision. True Price: {true_price}. Market ask: {market_state.best_ask}. Market bid: {market_state.best_bid}")
            
            if true_price > market_state.best_ask + self.min_edge:
                space = max(0, self.max_inventory - executor_state.inventory)
                count = min(10, space)
                order = self.construct_order(
                    action="buy",
                    price=market_state.best_ask,
                    count=count
                )
            elif true_price < market_state.best_bid - self.min_edge:
                space = max(0, executor_state.inventory + self.max_inventory)
                count = min(10, space)
                order = self.construct_order(
                    action="sell",
                    price=market_state.best_bid,
                    count=count
                )
            else:
                order = None
            
            if order:
                await self._place_batch_order([order])

    def _generate_price_of_market(self, spot: float, volatility: float) -> float:
        '''
        Generates the true price of the prediction market
        according to the Black-Scholes Binary Option
        price model based on market strike and expiry,
        and approximate option instrument implied volatility.

        Returns:
            True price of the prediction market
        '''

        market_price = self.model.calc_option_price(
            spot=spot,
            strike=self.prediction_strike,
            t_terminal=(self.prediction_expiry - (time.time() * 1000)) / (3.156e+10),
            implied_sig=(volatility)
        )

        return market_price

        