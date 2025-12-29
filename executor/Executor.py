from __future__ import annotations
from typing import TYPE_CHECKING

from client.KSocket import KalshiWebsocket
from client.API import KalshiAPI, AuthError, APIError, RateLimitError
from market import Order, FixedPointDollars
from market.FixedPointDollars import MAX_PRICE, MIN_PRICE
from executor import Context

import asyncio
import logging
import math
import time

if TYPE_CHECKING:
    from market import BinaryMarket
    from model import Model
    from client import Session



logger = logging.getLogger(__name__)

class Executor:

    api:     KalshiAPI
    model:   Model
    market:  BinaryMarket
    session: Session

    # Parameters
    quote_size: int                          # The standard sizing for a quote in # of contracts, default = 1
    max_inventory: int                       # The maximum allowed size of inventory at any given time
    min_price: FixedPointDollars = MIN_PRICE # The lowest allowed price of any quote
    max_price: FixedPointDollars = MAX_PRICE # The highest allowed price of any quote

    # Variables
    balance: float               # Current balance of account
    inventory: int               # Current position held
    resting_orders: set          # Set of resting orders outstanding 
    quote_lock: asyncio.Lock     # Lock control against concurrent quote gen

    def __init__(self, api: KalshiAPI, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int, quote_size: int = 1):
        
        self.api = api
        self.model = model
        self.market = market
        self.session = session

        self.inventory = 0
        self.max_inventory = max_inventory
        self.quote_size = quote_size

        self.balance = self.get_balance()
        self.terminal_time = time.time() + runtime
        self.runtime = runtime
        self.quote_lock = asyncio.Lock()
        self.resting_orders = set()

    async def on_fill(self, fill: dict):
        '''
        Sync updates inv on fill msg payload then
        fire-and-forgets an attempt at quote execution.
        '''
        self.update_inv_on_fill(fill)

        # Guard against insufficient volatility data
        if self.should_attempt_quote():
            asyncio.create_task(self._attempt_execute_quote())

    def update_inv_on_fill(self, fill: dict):
        '''
        Synchronously updates inventory after a 
        fill is made. Takes fill msg payload.
        '''
        if "count" in fill:
            if fill["action"] == "sell":
                self.inventory -= fill["count"]
                if "yes_price_dollars" in fill:
                    self.balance += fill["count"] * fill["yes_price_dollars"]
            else:
                self.inventory += fill["count"]
                if "yes_price_dollars" in fill:
                    self.balance -= fill["count"] * fill["yes_price_dollars"]
        
        if "post_position" in fill:
            order_id = fill["order_id"]
            if fill['post_position'] == 0:
                self.resting_orders.discard(order_id)


    async def _attempt_execute_quote(self):
        '''
        Attempts to execute quotes. Does nothing if can't acquire lock.
        Makes REST API call to cancel outstanding orders and yields.
        Captures context AFTER call returns and checks _should_quote
        conditions. Places quote IFF should quote.
        '''
        if self.quote_lock.locked():
            return

        async with self.quote_lock:
            await self._cancel_outstanding_orders()

            ctx = self._capture_quote_context()
            bid, ask = self.model.generate_quotes(ctx.snapshot, ctx.inventory, ctx.volatility)

            # Guard against insufficient volatility data
            if not self._should_quote(ctx):
                return

            await self._place_quote(bid, ask)

    def _should_quote(self, ctx) -> bool:
        '''
        Returns whether a new quote should be made
        immediately on context. Guard against
        insufficient volatility data.
        '''
        return self.market.get_volatility() is not None

    def should_attempt_quote(self) -> bool:
        '''
        Returns whether should attempt a new
        quote based on current information. Guard against
        insufficient volatility data.
        '''
        return self.market.get_volatility() is not None
    
    def _capture_quote_context(self) -> Context:
        '''
        Captures key context of orderbook from
        snapshot and returns Context obj.
        '''
        snapshot = self.market.snapshot()
        
        return Context(
            snapshot=snapshot,
            inventory=self.inventory,
            volatility=self.market.get_volatility(),
            seq_n=self.market.orderbook.seq_n,
            timestamp=time.time()
        )

    async def _place_quote(self, bid_quote, ask_quote):
        '''
        Constructs quotes according to constraints and
        creates batch order task.
        '''

        batch = []
        
        bid_size = self.quote_size
        ask_size = self.quote_size

        # Enforce upper price bound
        if bid_quote > self.max_price:
            bid_size = 0

        # Enforce lower price bound
        if ask_quote < self.min_price:
            ask_size = 0

        # Enforce max inventory constraint
        if self.quote_size + self.inventory > self.max_inventory:
            bid_size = max(0, self.max_inventory - self.inventory)

        # Enforce balance constraint
        if bid_size * bid_quote > self.balance and bid_quote > 0:
            bid_size = min(bid_size, math.floor(self.balance / bid_quote))
        
        if ask_size > self.inventory:
            ask_size = self.inventory
        
        if bid_size:
            bid_order = self.construct_order(action="buy", price=bid_quote, count=bid_size)
            
            if bid_order is not None:
                batch.append(bid_order.to_dict())

        if ask_size:
            ask_order = self.construct_order(action="sell", price=ask_quote, count=ask_size)
            
            if ask_order is not None:
                batch.append(ask_order.to_dict())
        
        if not batch:
            return
        
        response = await asyncio.to_thread(self.api.batch_create_orders, batch)

        for order in response["orders"]:
            self.resting_orders.add(order["order_id"])

    async def _cancel_outstanding_orders(self):
        '''
        Makes REST API request to cancel all orders
        in resting_orders in a new thread. Clears resting
        orders.
        '''
        
        if self.resting_orders:
            try:
                await asyncio.to_thread(self.api.batch_cancel_orders, list(self.resting_orders))
                self.resting_orders.clear()
            except AuthError as e:
                logger.critical(f"Auth failed during order clear: {e}")
            except RateLimitError as e :
                logger.error(f"Rate limit exceeded during order clear: {e}")
            except APIError as e:
                logger.error(f"API error during order clear: {e}")
            except Exception as e:
                logger.error(f"Unexpected exception during order clear: {e}")
    
    async def on_market_update(self):
        '''Public entry point for update-triggered quoting'''
        await self._attempt_execute_quote()

    def get_balance(self) -> float:
        '''
        Returns balance, in dollars, from
        REST API balance endpoint.
        '''
        return self.api.get_balance()["balance"] / 100

    def construct_order(self, action: str, price: FixedPointDollars, count: int) -> Order | None:
        '''
        Constructs order object based on params and executor
        configuration.
        Swallows ValueErrors and returns None if invalid
        order.
        '''
        try:
            return Order(
                ticker = self.market.ticker,
                side = "yes",
                action = action,
                count= count,
                type = "limit",
                yes_price_dollars = price
                )
        
        except ValueError as e:
            return None
