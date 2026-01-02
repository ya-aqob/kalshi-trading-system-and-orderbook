from __future__ import annotations
from typing import TYPE_CHECKING, Dict
from .ExecutorSnapshot import ExecutorSnapshot
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
    Base class for Executor agent that manages portfolio state,
    synchronization, order creation, and snapshotting.

    Provides two event-handlers for fill and market update
    message handling.
    '''

    api:     KalshiAPI
    model:   Model
    market:  BinaryMarket
    session: Session

    # Parameters
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

    def __init__(self, api: KalshiAPI, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int):
        
        self.api = api
        self.model = model
        self.market = market
        self.session = session

        self.inventory = 0
        self.max_inventory = max_inventory

        self.balance = self.get_balance()
        self.terminal_time = time.time() + runtime
        self.runtime = runtime
        self.quote_lock = asyncio.Lock()

        self.resting_orders = dict()
        self.unregistered_fills = dict()

    def snapshot(self) -> ExecutorSnapshot:
        '''Capture snapshot of executor state'''
        return ExecutorSnapshot.from_executor(self)

    async def on_fill(self, fill: FillMsg):
        '''
        Event-handler for fill messages.
        Override to implement post-fill logic.
        '''
        return
    
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
                
                return self.resting_orders == {}

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
        else:
            return True
    
    async def on_market_update(self):
        '''
        Event-handler for market updates.
        Override to implement post-update
        logic.
        '''
        return

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
