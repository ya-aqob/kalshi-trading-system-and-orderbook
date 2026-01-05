from __future__ import annotations
from client.WebsocketResponses import FillMsg
from .Executor import Executor
from typing import TYPE_CHECKING, List
import asyncio
from asyncio import Lock
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

    Trade decisions are triggered on Deribit websocket ticks.
    '''
    model: BSBOModel

    # Binary Market Metadata
    prediction_strike: float # Strike price of binary market in dollars
    prediction_expiry: float # Expiry time of the binary market in ms since unix epoch
    currency: str            # Currency name in Deribit format

    _tick_lock: asyncio.Lock # Prevents repetitive tick tasks

    # Deribit API
    deri_rest: DeribitREST
    deri_ws: DeribitSocket

    # Simulation Variables
    sim_open_orders: List[Order]

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

        self._tick_lock = asyncio.Lock()

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
        Dispatches new tick task if one is not fired.
        '''
        if self._tick_lock.locked():
            return

        asyncio.create_task(self.on_tick_action(tick))

    async def on_tick_action(self, tick: OptionTick):
        '''
        Locked action on each tick. Cancels all outstanding
        orders, captures states, and generates appropriate
        order for tick, market, and executor state data.
        '''
        async with self._tick_lock:
            await self._cancel_outstanding_orders()

            market_state = self.market.snapshot()
            executor_state = self.snapshot()
            true_price = self._generate_price_of_market(tick, market_state)

            order_logger.info(f"True Price: {true_price}. Market ask: {market_state.best_ask}. Market bid: {market_state.best_bid}")

            inv_size = executor_state.inventory
            
            kelly_size = self._generate_size(market_state, true_price, executor_state)
            
            kelly_size = max(-self.max_inventory, min(self.max_inventory, kelly_size))
            
            pos_delta = kelly_size - inv_size

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
                order_dict = order.to_dict()
                await asyncio.to_thread(self.api.batch_create_orders, [order_dict])
            
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
        based on Kelly Criterion.
        Returns:
            Ideal bankroll ratio
        '''
        if market_state.best_bid > true_price:
            edge = market_state.best_bid - true_price
            ratio = edge / market_state.best_bid
        elif market_state.best_ask < true_price:
            edge = true_price - market_state.best_ask
            ratio = edge / (1 - market_state.best_ask)
        else:
            ratio = 0.0
        
        return float(ratio)

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

    ###
    ### Simulation Functions
    ###

    def simulate_cancel_orders(self):
        self.sim_open_orders = []
        return
    
    def simulate_place_orders(self, order: List[Order]):
        orders = self.simulate_flip_sale(order)
        
        for o in orders:
            if o.side == "no" and o.action == "buy" or o.side == "yes" and o.action == "sell":
                delta = -o.count
                order_logger.info(f"{delta:+d} @ {o.yes_price_dollars}")
            if o.side == "no" and o.action == "sell" or o.side == "yes" and o.action == "buy":
                order_logger.info(f"{o.count:+d} @ {o.yes_price_dollars}")
            self.sim_open_orders.append(o)

    def simulate_flip_sale(self, orders: List[Order]):
        result = []
        for order in orders:
            if order.action == "sell" and order.side == "yes":
                if order.count <= self.inventory:
                    result.append(order)
                elif self.inventory > 0:
                    # Split
                    result.append(Order(ticker=self.market.ticker, type="limit", action="sell", side="yes", count=self.inventory, yes_price_dollars=order.yes_price_dollars))
                    result.append(Order(ticker=self.market.ticker, type="limit", action="buy", side="no", count=order.count - self.inventory, yes_price_dollars=order.yes_price_dollars))
                else:
                    # Full flip
                    order.side = "no"
                    order.action = "buy"
                    result.append(order)
            else:
                result.append(order)
        return result

    def simulate_fill_logic(self, snapshot: OrderBookSnapshot):
        '''
        Simulates open order fill logic.
        '''
        for order in self.sim_open_orders[:]:
            is_long = (order.side == "yes") == (order.action == "buy")
            
            if is_long and snapshot.best_ask <= order.yes_price_dollars:
                filled = True
            elif not is_long and snapshot.best_bid >= order.yes_price_dollars:
                filled = True
            else:
                filled = False
            
            if filled:
                cost = float(order.yes_price_dollars if order.side == "yes" else order.yes_price_dollars.complement)
                count = order.count
                delta = count if is_long else -count
                
                if order.action == "buy":
                    self.balance -= count * cost
                    if is_long and self.inventory < 0:
                        pairs = min(count, -self.inventory)
                        self.balance += pairs * 1.0
                    elif not is_long and self.inventory > 0:
                        pairs = min(count, self.inventory)
                        self.balance += pairs * 1.0
                else:
                    self.balance += count * cost
                
                self.inventory += delta
                self.sim_open_orders.remove(order)
                fill_logger.info(f"{delta:+d} @ {order.yes_price_dollars}. Bal/Inv: {self.balance}/{self.inventory}")