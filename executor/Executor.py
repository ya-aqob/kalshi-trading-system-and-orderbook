from __future__ import annotations
from typing import TYPE_CHECKING, Dict
from .ExecutorSnapshot import ExecutorSnapshot
from client.KSocket import KalshiWebsocket
from client.API import KalshiAPI, AuthError, APIError, RateLimitError
from market import Order, FixedPointDollars
from market.FixedPointDollars import MAX_PRICE, MIN_PRICE, MID_DEFAULT
from executor import Context

import asyncio
import logging
import math
import time

if TYPE_CHECKING:
    from market import BinaryMarket
    from model import Model
    from client import Session
    from client.WebsocketResponses import FillMsg



logger = logging.getLogger(__name__)

class Executor:
    '''
    Executor agent responsible for portfolio and trade decisions and execution
    '''

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
    quote_lock: asyncio.Lock     # Lock control against concurrent quote gen

    # The union of resting_orders and unregistered_fills is ALWAYS representative of total order state
    resting_orders: Dict[str, int]          # Map of resting orders outstanding, represents whole order state
                                            # before and after batch creation call
    unregistered_fills: Dict[str, int]      # Map of changed orders during async creation op
                                            # always coherent w.r.t. resting_orders

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
        self.unregistered_fills = set()

    def snapshot(self) -> ExecutorSnapshot:
        '''Capture snapshot of executor state'''
        return ExecutorSnapshot.from_executor(self)

    async def on_fill(self, fill: FillMsg):
        '''
        Updates inv on FillMsg then fire-and-forgets
        an attempt at quote execution.
        '''
        self.update_inv_on_fill(fill)

        # Guard against insufficient volatility data
        if self.should_attempt_quote():
            asyncio.create_task(self._attempt_execute_quote())

    def update_inv_on_fill(self, fill: FillMsg):
        '''
        Synchronously updates inventory after a 
        fill is made and updates resting_orders.
        '''
        if fill.action == "sell":
            self.inventory -= fill.count
            self.balance += fill.count * fill.yes_price_dollars
            
        else:
            self.inventory += fill.count
            self.balance -= fill.count * fill.yes_price_dollars
        
        order_id = fill.order_id

        if order_id in self.resting_orders:
            self.resting_orders[order_id] -= fill.count
            if self.resting_orders[order_id] <= 0:
                del self.resting_orders[order_id]

        else:
            self.unregistered_fills[order_id] = self.unregistered_fills.get(order_id, 0) + fill.count

    async def _sync_balance(self):
        '''
        Makes async REST API request to get current balance.
        Synchronizes the inventory on the response.
        Called whenever balance needs to be synced
        OR the balance is expected to be inaccurate,
        like after a malformed fill message.
        '''
        balance = await asyncio.to_thread(self.get_balance)
        self.balance = balance

    async def _sync_inventory(self):
        '''
        Makes async REST API request to get current position.
        Synchronizes the inventory on the response.
        Called whenever inventory needs to be synced
        OR the inventory is expected to be inaccurate,
        like after a malformed fill message.
        '''
        response = await asyncio.to_thread(self.api.get_positions, ticker=self.market.ticker)

        for position in response.get("market_positions", []):
            if position["ticker"] == self.market.ticker:
                contracts = position["position"]
                self.inventory = contracts
    
    async def _sync_orders(self):
        '''
        Makes async REST API request to get current orders.
        Synchronizes resting_orders and pending_fills to reflect
        resting orders at time of response. Called whenever orders
        need to be synced or are expected to be inaccurate.
        '''
        response = await asyncio.to_thread(self.api.get_orders, ticker=self.market.ticker)

        self.resting_orders.clear()
        self.unregistered_fills.clear()

        for order in response.get("orders", []):
            order_id = order["order_id"]
            if order["status"] == "resting":
                self.resting_orders[order_id] = order["remaining_count"]

    async def on_inventory_mismatch(self):
        '''Public entry point for syncing executor inventory'''
        await self._sync_inventory()
        await self._sync_balance()

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
            success = await self._cancel_outstanding_orders()
            
            # Exit on failure of cancellation, reduce open order exposure
            if not success:
                return
            
            ctx = self._capture_quote_context()
            
            # Guard against insufficient volatility data
            if not self._should_quote(ctx):
                return
            
            bid, ask = self.model.generate_quotes(ctx.orderbook_snapshot, ctx.executor_snapshot.inventory, 
                                                  ctx.volatility)

            await self._place_quote(bid, ask, ctx.executor_snapshot)

    def _should_quote(self, ctx: Context) -> bool:
        '''
        Returns whether a new quote should be made
        immediately on context. Guard against
        insufficient volatility data.
        '''
        return ctx.volatility is not None and ctx.orderbook_snapshot.best_ask <= MAX_PRICE and ctx.orderbook_snapshot.best_bid >= MIN_PRICE
    
    def should_attempt_quote(self) -> bool:
        '''
        Returns whether should attempt a new
        quote based on current information. Guard against
        insufficient volatility data.
        '''
        return self.market.get_volatility() is not None
    
    def _capture_quote_context(self) -> Context:
        '''
        Captures snapshots of orderbook and executor state
        and then construct Context.
        '''
        orderbook_snapshot = self.market.snapshot()
        executor_snapshot = self.snapshot()

        return Context(
            orderbook_snapshot=orderbook_snapshot,
            executor_snapshot=executor_snapshot,
            volatility=self.market.get_volatility(),
            seq_n=self.market.orderbook.seq_n,
            timestamp=time.time()
        )

    async def _place_quote(self, bid_quote, ask_quote, executor_snapshot: ExecutorSnapshot):
        '''
        Constructs quotes according to price bounds,
        max_inventory, balance, and other applicable constraints.
        Checks for quote validity and attempts order placement,
        updating resting_order set on success.
        '''

        batch = []
        
        bid_size = self.quote_size
        ask_size = self.quote_size

        inventory = executor_snapshot.inventory
        bal = executor_snapshot.balance

        # Enforce upper price bound
        if bid_quote > self.max_price:
            bid_size = 0

        # Enforce lower price bound
        if ask_quote < self.min_price:
            ask_size = 0

        # Enforce max inventory constraint
        if self.quote_size + inventory > self.max_inventory:
            bid_size = max(0, self.max_inventory - inventory)

        # Enforce balance constraint
        if bid_size * bid_quote > bal and bid_quote > 0:
            if bid_quote > 0:
                bid_size = min(bid_size, math.floor(bal / bid_quote))
            else:
                bid_size = 0
        
        if ask_size > inventory:
            ask_size = inventory
        
        if bid_size > 0:
            bid_order = self.construct_order(action="buy", price=bid_quote, count=bid_size)
            
            if bid_order is not None:
                batch.append(bid_order.to_dict())

        if ask_size > 0:
            ask_order = self.construct_order(action="sell", price=ask_quote, count=ask_size)
            
            if ask_order is not None:
                batch.append(ask_order.to_dict())
        
        if not batch:
            return
        
        self.unregistered_fills.clear()
        try:
            try:
                response = await asyncio.to_thread(self.api.batch_create_orders, batch)
            except:
                # Re-sync on failure to ensure accurate orders
                await self._sync_orders()
                return

            if "orders" in response:
                for order in response.get("orders"):
                    order_id = response[order_id]
                    placed_count = order["count"]

                    filled = self.unregistered_fills.pop(order_id, 0)
                    
                    net_count = placed_count - filled

                    if net_count > 0:
                        self.resting_orders[order_id] = net_count

        except Exception as e:


    async def _cancel_outstanding_orders(self):
        '''
        Makes REST API request to cancel all orders
        in resting_orders in a new thread. Clears resting
        orders.
        '''
        
        if self.resting_orders:
            try:
                response = await asyncio.to_thread(self.api.batch_cancel_orders, list(self.resting_orders))
                
                for order in response["orders"]:
                    if "error" not in order:
                        self.resting_orders.pop(order["order_id"], None)

            # Squash key errors, assumes not cleared conservatively
            except KeyError as e:
                logger.info(f"Invalid order clear response: {e}")
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
