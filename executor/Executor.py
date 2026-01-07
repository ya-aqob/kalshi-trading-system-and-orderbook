from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
from .ExecutorSnapshot import ExecutorSnapshot
from client.API import KalshiAPI, AuthError, APIError, RateLimitError
from market import Order, FixedPointDollars
from market.FixedPointDollars import MAX_PRICE, MIN_PRICE, MID_DEFAULT
from executor import Context
from abc import ABC, abstractmethod

import asyncio
import logging

if TYPE_CHECKING:
    from market import BinaryMarket
    from model import Model
    from client import Session
    from client.WebsocketResponses import FillMsg

fill_logger = logging.getLogger("fills")
logger = logging.getLogger(__name__)

class Executor(ABC):
    '''
    Base class for Executor agent that manages portfolio state,
    synchronization, order creation, and snapshotting.

    Provides two event-handlers for fill and market update
    message handling.

    Provides an execution lock that should be utilized
    in subclasses to prevent trading during state reconciliation.

    Reconcile must be called during Executor state initialization.
    '''

    # Composition Elements
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
    inventory: int               # Current position held (net long/short on YES)

    # The union of resting_orders and unregistered_fills is ALWAYS representative of total order state
    resting_orders: Dict[str, int]          # Map of resting orders outstanding, represents whole order state
                                            # before and after batch creation call
    unregistered_fills: Dict[str, int]      # Map of changed orders during async creation op
                                            # always coherent w.r.t. resting_orders

    # Synchronization
    _execution_lock: asyncio.Lock # Held during reconciliation to pause trading

    def __init__(self, api: KalshiAPI, market: BinaryMarket, session: Session, max_inventory: int):
        
        self.api = api
        self.market = market
        self.session = session

        self.inventory = 0
        self.max_inventory = max_inventory

        self.balance = 0

        self.resting_orders = dict()
        self.unregistered_fills = dict()

        self._execution_lock = asyncio.Lock()
    
    def calculate_transaction_cost(self, price: float, count_taken: int, count_made: int):
        '''
        Calculates the total transaction cost of a trade.
        '''
        fees = self.market.fee_schedule.calculate_mixed_fees(price, count_made, count_taken)
        return fees + (price * (count_taken + count_made))

    def snapshot(self) -> ExecutorSnapshot:
        '''Capture snapshot of executor state'''
        return ExecutorSnapshot.from_executor(self)
    
    def _calculate_post_position(self, order: Order) -> Tuple[int, FixedPointDollars]:
        '''
        Calculates the post-position of the portfolio
        if the order was filled in its entirety.

        Returns (post_inventory, post_balance) tuple.
        '''
        is_long = (order.side == "yes" and order.action == "buy") or (order.side == "no" and order.action == "sell")
        
        if is_long:
            post_inventory = self.inventory + order.count
            if self.inventory > 0:
                # Long++
                post_balance = self.balance - order.count * order.yes_price_dollars
            else:
                # Short--
                pairs = 1 * min(abs(self.inventory), order.count)
                post_balance = self.balance + pairs - order.count * (order.yes_price_dollars)
        else:
            post_inventory = self.inventory - order.count
            if self.inventory > 0:
                # Long--
                pairs = 1 * min(abs(self.inventory), order.count)
                post_balance = self.balance + pairs - order.count * order.yes_price_dollars.complement
            else:
                # Short++
                post_balance = self.balance - (order.count) * order.yes_price_dollars.complement

        return post_inventory, post_balance

    def constrain_order(self, order: Order):
        '''
        Constrains an order to the max inventory constraints.
        '''
        is_long = (order.side == "yes" and order.action == "buy") or (order.side == "no" and order.action == "sell")
        
        post_inventory, post_balance = self._calculate_post_position(order)
        
        inventory_constraint = order.count

        if is_long:
            if post_inventory > self.max_inventory:
                inventory_constraint = max(0, self.max_inventory - self.inventory)
        else:
            if post_inventory < -self.max_inventory:
                inventory_constraint = max(0, self.inventory + self.max_inventory)
        
        order.count = inventory_constraint
        
    async def reconcile(self):
        '''
        Performs whole reconciliation on order set, balance,
        and inventory while holding the execution lock.
        '''
        async with self._execution_lock:
            await self._sync_orders()
            await self._sync_balance()
            await self._sync_inventory()
        
        logger.info(f"Reconciled: inventory={self.inventory}, balance={self.balance}, orders={len(self.resting_orders)}")

    def update_inv_on_fill(self, fill: FillMsg):
        '''
        Updates inventory and balance according
        to fill message. Supports fills on both
        sides of the market.
        '''
        
        yes_price_dollars = fill.yes_price_dollars

        if fill.side == "yes":
            price = yes_price_dollars

            if fill.action == "buy":

                if self.inventory < 0:
                    pairs = min(fill.count, -self.inventory)
                    self.balance += pairs * 1.0

                self.inventory += fill.count
                self.balance -= fill.count * price
                fill_logger.info(f"Long {fill.count} @ {yes_price_dollars}")
            else:
                self.inventory -= fill.count
                self.balance += fill.count * price
                fill_logger.info(f"Short {fill.count} @ {yes_price_dollars}")

        if fill.side == "no":
            price = 1 - yes_price_dollars
            if fill.action == "buy":
                if self.inventory > 0:
                    pairs = min(fill.count, self.inventory)
                    self.balance += pairs * 1.0
                self.inventory -= fill.count
                self.balance -= fill.count * price
                fill_logger.info(f"Short {fill.count} @ {yes_price_dollars}")
            else:
                self.inventory += fill.count
                self.balance += fill.count * price
                fill_logger.info(f"Long {fill.count} @ {yes_price_dollars}")
        
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
        balance = await self.get_balance()
        self.balance = balance

    async def _sync_inventory(self):
        '''
        Makes async REST API request to get current position.
        Synchronizes the inventory on the response.
        Called whenever inventory needs to be synced
        OR the inventory is expected to be inaccurate,
        like after a malformed fill message.
        '''
        response = await self.api.get_positions(ticker=self.market.ticker)

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
        response = await self.api.get_orders(ticker=self.market.ticker)

        self.resting_orders.clear()
        self.unregistered_fills.clear()

        for order in response.get("orders", []):
            order_id = order["order_id"]
            if order["status"] == "resting":
                self.resting_orders[order_id] = order["remaining_count"]

    async def _cancel_outstanding_orders(self):
        '''
        Makes REST API request to cancel all orders
        in resting_orders in a new thread. Ensures
        resting_orders is accurate to the response.
        Reconciles on error.
        '''
        
        if self.resting_orders:
            try:
                response = await self.api.batch_cancel_orders(list(self.resting_orders))
                
                for order in response["orders"]:
                    if "error" not in order:
                        self.resting_orders.pop(order["order_id"], None)
                
                return not self.resting_orders

            # Assumes not cleared conservatively
            except KeyError as e:
                logger.info(f"Invalid order clear response: {e}")
                await self.reconcile()
                return False
            except AuthError as e:
                logger.critical(f"Auth failed during order clear: {e}")
                await self.reconcile()
                return False
            except RateLimitError as e :
                logger.error(f"Rate limit exceeded during order clear: {e}")
                await self.reconcile()
                return False
            except APIError as e:
                logger.error(f"API error during order clear: {e}")
                await self.reconcile()
                return False
            except Exception as e:
                logger.error(f"Unexpected exception during order clear: {e}")
                await self.reconcile()
                return False
        else:
            return True
    
    async def _place_batch_order(self, orders: list[Order]):
        '''
        Attempts to place the orders list and maintains the
        correctness of the resting orders and unregistered
        fills maps. Applies order constraints before placing.
        Triggers reconciliation on any errors during creation.
        '''
        self.unregistered_fills.clear()

        for order in orders:
            self.constrain_order(order)

        try:
            response = await self.api.batch_create_orders(orders)
        except Exception:
            # Reconcile on failure to ensure accurate orders
            await self.reconcile()
            return

        if "orders" in response:
            for order in response.get("orders"):
                order_id = order["order_id"]
                placed_count = order["count"]

                filled = self.unregistered_fills.pop(order_id, 0)
                
                net_count = placed_count - filled

                if net_count > 0:
                    self.resting_orders[order_id] = net_count

    async def get_balance(self) -> float:
        '''
        Returns balance, in dollars, from
        REST API balance endpoint.
        '''
        response = await self.api.get_balance()
        return response["balance"] / 100

    def construct_order(self, action: str, price: FixedPointDollars, count: int) -> Order | None:
        '''
        Constructs order object based on params and executor
        configuration.

        Order is always on the yes side, so
        action controls the implementation of the
        order.

        Returns None if args are invalid.
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
    
    @abstractmethod
    def on_fill(self, fill: FillMsg):
        '''
        Event-handler for fill messages.
        Override to implement post-fill logic.
        '''
        pass
    
    @abstractmethod
    def on_market_update(self):
        '''
        Event-handler for market updates.
        Override to implement post-update
        logic.
        '''
        return
        