from __future__ import annotations
from client.WebsocketResponses import FillMsg
from .Executor import Executor
from typing import TYPE_CHECKING, List
import asyncio
from asyncio import Lock, Event
from derivatives_pipeline.DeribitAPI import DeribitREST, DeribitSocket
from datetime import datetime
import pytz
import time
import math
import logging

order_logger = logging.getLogger("orders")
fill_logger = logging.getLogger("fills")

if TYPE_CHECKING:
    from derivatives_pipeline.DeribitResponse import OptionTick
    from client.API import KalshiAPI
    from market.BinaryMarket import BinaryMarket
    from client.Session import Session
    from market.OrderBookSnapshot import OrderBookSnapshot
    from market.Order import Order
    from derivatives_pipeline.DeribitResponse import Instrument
    from model.BSBOModel import BSBOModel
    from .ExecutorSnapshot import ExecutorSnapshot


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
    prediction_expiry: float # Expiry time of the binary market in ms since unix epoch
    currency: str            # Currency name in Deribit format

    # Syncronization
    _tick_event:          asyncio.Event       # Event representing pending ticks
    _tick_processor_task: asyncio.Task | None # Prevents repetitive tick tasks
    _fresh_tick:          OptionTick | None   # Freshest tick yet received


    # Deribit API
    deri_rest: DeribitREST
    deri_ws: DeribitSocket

    def __init__(self, kalshi_api: KalshiAPI, market: BinaryMarket, 
                 session: Session, max_inventory: int, deri_ws: DeribitSocket, 
                 deri_rest: DeribitREST, currency: str, strike: float, expiry_datetime: str,
                 model: BSBOModel
                 ):
        
        super().__init__(kalshi_api, market, session, max_inventory)

        self.currency = currency
        self.prediction_expiry = self._convert_est_to_timestamp(expiry_datetime)
        self.prediction_strike = strike

        self.model = model

        self._tick_event = asyncio.Event()
        self._fresh_tick = None
        self._tick_processor_task = None

        self.deri_ws = deri_ws
        self.deri_rest = deri_rest

        self.sim_open_orders = []

    def _convert_est_to_timestamp(self, est_time: str):
        '''
        Converts HH:MM MM/DD/YYYY (EST) time to milliseconds-since-Unix-epoch 
        timestamp.
        '''
        est = pytz.timezone('America/New_York')
        dt = est.localize(datetime.strptime(est_time, "%H:%M %m/%d/%Y"))
        unix_timestamp = int(dt.timestamp())
        return unix_timestamp * 1000

    def on_market_update(self):
        '''
        Event handler for market updates.
        Does nothing.
        '''
        return

    def on_fill(self, fill: FillMsg):
        '''
        Event handler for fill messages.
        Updates inv, balance, and order
        set according to fill that is received.
        '''
        self.update_inv_on_fill(fill)

    def on_tick(self, tick: OptionTick):
        '''
        Event handler for ticks in the option instrument.
        Dispatches new tick processing task if one is not running.
        Updates freshest tick to this tick.
        '''
        self._fresh_tick = tick
        self._tick_event.set()

        if self._tick_processor_task is None or self._tick_processor_task.done():
            self._tick_processor_task = asyncio.create_task(self._tick_processor())

    async def _tick_processor(self):
        while True:
            try:
                await asyncio.wait_for(self._tick_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                if self._fresh_tick is None:
                    return
                continue
            
            tick = self._fresh_tick
            self._fresh_tick = None
            self._tick_event.clear()
        
            if tick is not None:
                await self.on_tick_action(tick)

    async def on_tick_action(self, tick: OptionTick):
        '''
        Requires execution lock.
        Cancels all outstanding orders, captures states, and generates 
        appropriate order for tick, market, and executor state data.
        '''

        async with self._execution_lock:
            await self._cancel_outstanding_orders()

            market_state = self.market.snapshot()
            executor_state = self.snapshot()
            true_price = self._generate_price_of_market(tick)

            order_logger.info(f"True Price: {true_price}. Market ask: {market_state.best_ask}. Market bid: {market_state.best_bid}")

            inv_size = executor_state.inventory
            
            kelly_size = self._generate_size(market_state, true_price, executor_state)
            
            kelly_size = max(-self.max_inventory, min(self.max_inventory, kelly_size))
            
            pos_delta = kelly_size - inv_size

            if kelly_size == 0 and pos_delta != 0:
                return

            if pos_delta < 0:
                order = self.construct_order(
                    action="sell",
                    price=market_state.best_bid,
                    count=-int(pos_delta)
                )
            elif pos_delta > 0:
                order = self.construct_order(
                    action="buy",
                    price=market_state.best_ask,
                    count=int(pos_delta)
                )
            else:
                order = None
            
            if order:
                await self._place_batch_order([order])
            
    def _generate_size(self, market_state: OrderBookSnapshot, true_price: float, executor_state: ExecutorSnapshot):
        '''
        Generates ideal position according to Kelly Criterion
        based on best bid/ask prices of the orderbook.
        
        Returns:
            Ideal Kelly Position
        '''
        k_float = self._generate_kelly_float(market_state, true_price)
        
        if k_float == 0:
            return 0
        
        position_val = k_float * executor_state.balance

        if market_state.best_bid > true_price:
            cost = market_state.best_bid.complement
            pos_size = math.floor(position_val / float(cost))
            return -pos_size
        elif market_state.best_ask < true_price:
            cost = market_state.best_ask
            position_size = math.floor(position_val / float(cost))
            return position_size
        else:
            return 0

    def _generate_kelly_float(self, market_state: OrderBookSnapshot, true_price: float) -> float:
        '''
        Generates ratio of bankroll to have in portfolio
        based on Kelly Criterion. Approximates fee cost
        in for profits.
        Returns:
            Ideal bankroll ratio
        '''

        if float(market_state.best_bid) > true_price:
            price = market_state.best_bid
            net_profit = price * (1 - self.market.fee_schedule.taker_fee_rate * (1 - price))
            risk = 1 - price
            b_adj = net_profit / risk

            p = 1 - true_price
            q = true_price
        elif float(market_state.best_ask) < true_price:
            price = market_state.best_ask
            net_profit = (1 - price) * (1 - self.market.fee_schedule.taker_fee_rate * price)
            risk = price
            b_adj = net_profit / risk
            p = true_price
            q = 1 - true_price
        else:
            return 0.0
        
        kelly_ratio = (float(b_adj) * p - q) / b_adj

        return max(0.0, float(kelly_ratio))

    def _generate_price_of_market(self, tick: OptionTick):
        '''
        Generates the true price of the prediction market
        according to the Black-Scholes Binary Option
        price model based on market strike and expiry,
        and approximate option instrument implied volatility.

        Returns:
            True price of the prediction market
        '''
        instrument_iv = tick.mark_iv

        market_price = self.model.calc_option_price(
            spot=tick.underlying_price,
            strike=self.prediction_strike,
            t_terminal=(self.prediction_expiry - (time.time() * 1000)) / (3.156e+10),
            implied_sig=(instrument_iv/100)
        )

        return market_price
    
    async def configure(self):
        '''
        Matches best instrument and subscribes if a match is made.
        
        Throws error if no match is made.
        '''
        best_match_instrument = await self.match_instrument_market()
        
        if not best_match_instrument:
            raise ValueError
        
        await self.deri_ws.subscribe([best_match_instrument.instrument_name])

        return

    def calc_option_distance(self, instrument: Instrument, sigma=0.6) -> float:
        '''
        Calculates approximation of probability estimation error of using
        instrument to price prediction market.

        Strike distance is normalized by width of lognormal distribution
        at expiry.

        Time error is normalized by target expiry.
        '''
        instr_strike = instrument.strike

        # in years
        instr_time_to_exp = (instrument.expiration_timestamp - (time.time() * 1000)) / (3.156e+10)
        pred_time_to_exp = (self.prediction_expiry - (time.time() * 1000)) / (3.156e+10)

        width = self.prediction_strike * sigma * math.sqrt(pred_time_to_exp)

        strik_dis = abs(instr_strike - self.prediction_strike) / width
        time_dis = abs(instr_time_to_exp - pred_time_to_exp) / pred_time_to_exp

        total_d = strik_dis + time_dis
        
        return total_d

    async def match_instrument_market(self) -> Instrument | None:
        '''
        Returns the instrument that matches closest to the parameters
        of the prediction market.
        
        None if there are no instruments.
        '''
        instruments = await asyncio.to_thread(self.deri_rest.get_instruments, currency=self.currency, kind="option")
        
        if not instruments:
            return None

        return min(instruments, key=lambda x: self.calc_option_distance(x))