from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple
from .ExecutorSnapshot import ExecutorSnapshot
from core.client.KalshiAPI import KalshiAPI, AuthError, APIError, RateLimitError
from core.market import Order, FixedPointDollars
from core.market.FixedPointDollars import MAX_PRICE, MIN_PRICE, MID_DEFAULT
from abc import ABC, abstractmethod
import asyncio
import logging
from live_trading.RiskExceptions import *

if TYPE_CHECKING:
    from core.market import BinaryMarket
    from core.client import KalshiAuthentication
    from core.client import FillMsg

logger = logging.getLogger("execution")

class Executor(ABC):
    '''
    Base trading execution class for portfolio state management
    and basic trading execution. Provides basic state synchronization,
    trade placement, tracking, and cancellation, and event-handling
    functionality.

    Exposes two abstract event-handlers for fill and market update
    events from the Kalshi Websocket.

    Utilizes an execution lock during trading and reconciliation
    to maintain state consistency.
    
    Maintains internal inventory state through fill tracking.
    Maintains other stateful fields through periodic reconciliation
    and reconciliation on failure/error.

    Must be reconciled before start of trading.
    '''

    # Composition Elements
    api:     KalshiAPI
    market:  BinaryMarket
    session: KalshiAuthentication

    # Risk profile
    max_inventory: int     # The maximum allowed size of inventory at any given time
    minimum_balance: float # The minimum permissible balance of the account             
    max_inventory_dev: int # The maximum allowable deviation between remote and local inventory
    max_balance_dev: float # The maximum allowable deviation between remote and local balance

    # Variables
    balance: float               # Most recent balance fetched from remote
    inventory: int               # Current position held (net long/short on YES)
    last_fill_ts: float          # Timestamp of last fill received in POSIX (ns)

    # The union of resting_orders and unregistered_fills is ALWAYS representative of total order state
    resting_orders: Dict[str, int]          # Map of resting orders outstanding, represents whole order state
                                            # before and after batch creation call
    unregistered_fills: Dict[str, int]      # Map of changed orders during async creation op
                                            # always coherent w.r.t. resting_orders

    # Synchronization
    _execution_lock: asyncio.Lock # Lock held for any state reconciliation and trading action

    def __init__(self, api: KalshiAPI, market: BinaryMarket, session: KalshiAuthentication, max_inventory: int,
                 minimum_balance: float, max_inventory_dev: int, max_balance_dev: float):
        
        self.minimum_balance = minimum_balance
        self.max_balance_dev = max_balance_dev
        self.max_inventory_dev = max_inventory_dev

        self.api = api
        self.market = market
        self.session = session

        self.inventory = 0
        self.max_inventory = max_inventory

        self.balance = 0
    
        self.resting_orders = dict()
        self.unregistered_fills = dict()

        self._execution_lock = asyncio.Lock()

    def calculate_transaction_cost(self, price: float, count_taken: int, count_made: int) -> float:
        '''
        Calculates the total transaction cost of a trade according to maker/taker fees.
        '''
        fees = self.market.fee_schedule.calculate_mixed_fees(price, count_made, count_taken)
        return fees + (price * (count_taken + count_made))

    def snapshot(self) -> ExecutorSnapshot:
        '''
        Captures snapshot of executor state
        '''
        return ExecutorSnapshot.from_executor(self)
    
    def constrain_order(self, order: Order) -> None:
        '''
        Modifies order in-place to not exceed max inventory
        constraint based on current state.
        '''
        is_long = (order.action == "buy" and order.side == "yes") or (order.action == "sell" and order.side == "no")

        if is_long:
            max_delta = self.max_inventory - self.inventory
        else:
            max_delta = self.inventory + self.max_inventory

        order.count = max(0, min(max_delta, order.count))
        
    def update_inv_on_fill(self, fill: FillMsg) -> None:
        '''
        Updates inventory according to fill message.
        Checks inventory against inventory constraint
        for violations.

        Raises PositionLimitExceeded or BalanceLimitExceeded
        if the post-fill position exceeds the respective
        limit.
        '''
        self.last_fill_ts = fill.ts  * 1e9

        pre_position = self.inventory
        self.inventory = fill.post_position

        # Handles fill before order
        order_id = fill.order_id
        if order_id in self.resting_orders:
            self.resting_orders[order_id] -= fill.count
            if self.resting_orders[order_id] <= 0:
                del self.resting_orders[order_id]
        else:
            self.unregistered_fills[order_id] = self.unregistered_fills.get(order_id, 0) + fill.count

        logger.info(f"Fill Received. Pre-fill Inv: {pre_position}. Post-fill inv: {self.inventory}.")

        if abs(self.inventory) > self.max_inventory:
            logger.error(f"Inventory Limit Exceeded. Limit: {self.max_inventory}. Inventory: {self.inventory}.")
            raise PositionLimitExceeded

    async def reconcile(self) -> None:
        '''
        Locks execution and reconciles orders,
        balance, and inventory with remote endpoints.
        '''
        async with self._execution_lock:
            await self._sync_orders()
            await self._sync_balance()
            await self._sync_inventory()
        
        logger.info(f"Reconciled: inventory={self.inventory}, balance={self.balance}, orders={len(self.resting_orders)}")
        
    async def _sync_balance(self) -> None:
        '''
        Fetches balance from REST endpoint.
        Sets balance to the response value.

        Raises BalanceLimitExceeded if the post-reconciliation
        balance is lower than permitted.

        Logs a BalanceMismatchError if reconciliation shows a
        greater deviation than permitted.
        '''
        local_balance = self.balance

        balance = await self.get_balance()
        self.balance = balance

        remote_balance = self.balance

        if self.balance < self.minimum_balance:
            logger.error(f"Balance Limit Exceeded. Limit: {self.minimum_balance}. Balance: {self.balance}.")
            raise BalanceLimitExceeded

        if abs(remote_balance - local_balance) > self.max_balance_dev:
            logger.error(f"Balance Mismatch Error. Remote: {remote_balance}. Local: {local_balance}. Difference: {abs(remote_balance - local_balance)}")

    async def _sync_inventory(self) -> None:
        '''
        Fetches position from REST endpoint.
        Sets inventory to the response value.

        Raises PositionLimitExceeded if the post-reconciliation
        inventory is higher than permitted.

        Logs a PositionMismatchError if position reconciliation
        shows a greater deviation than permitted.
        '''

        response = await self.api.get_positions(ticker=self.market.ticker)

        for position in response.get("market_positions", []):
            if position["ticker"] == self.market.ticker:
                contracts = position["position"]
                self.inventory = contracts

        if abs(self.inventory) > self.max_inventory:
            logger.error(f"Inventory Limit Exceeded. Limit: {self.max_inventory}. Inventory: {self.inventory}.")
            raise PositionLimitExceeded
        
    async def _sync_orders(self) -> None:
        '''
        Fetches resting orders from the REST endpoint.
        Clears local sets and sets resting_orders to match
        the outstanding orders.
        '''
        response = await self.api.get_orders(ticker=self.market.ticker)

        self.resting_orders.clear()
        self.unregistered_fills.clear()

        for order in response.get("orders", []):
            order_id = order["order_id"]
            if order["status"] == "resting":
                self.resting_orders[order_id] = order["remaining_count"]

    async def _cancel_outstanding_orders(self) -> None:
        '''
        Calls batch cancellation on the whole batch of 
        order_ids in resting_orders. Logs failures and triggers
        reconciliation on failure/error to prevent order tracking 
        drift.
        '''
        if self.resting_orders:
            try:
                response = await self.api.batch_cancel_orders(list(self.resting_orders))
                
                for order in response["orders"]:
                    if "error" not in order:
                        order_id = order.get("order_id")
                        self.resting_orders.pop(order_id, None)
                        logger.info(f"Order cancelled. order_id: {order_id}")

                if self.resting_orders:
                    logger.error(f"Order cancellation failed. Resting orders: {self.resting_orders}")
                    await self._sync_orders()

            # Assumes not cleared conservatively
            except KeyError as e:
                logger.error(f"Invalid order clear response: {e}")
                await self.reconcile()
                return
            except AuthError as e:
                logger.critical(f"Auth failed during order clear: {e}")
                await self.reconcile()
                return
            except RateLimitError as e :
                logger.error(f"Rate limit exceeded during order clear: {e}")
                await self.reconcile()
                return
            except APIError as e:
                logger.error(f"API error during order clear: {e}")
                await self.reconcile()
                return
            except Exception as e:
                logger.error(f"Unexpected exception during order clear: {e}")
                await self.reconcile()
                return
    
    async def _close_position(self) -> None:
        '''
        Peforms atomic closure of entire position
        by syncing orders, cancelling all resting orders,
        and placing a market order for entire
        position.
        '''
        async with self._execution_lock:
            await self._sync_orders()
            await self._cancel_outstanding_orders()
            await self._sync_inventory()

            if self.inventory > 0:
                order = {
                    "ticker": self.market.ticker,
                    "side": "yes",
                    "action": "sell",
                    "count": self.inventory,
                    "type": "market"
                }

            elif self.inventory < 0:
                order = {
                    "ticker": self.market.ticker,
                    "side": "no",
                    "action": "sell",
                    "count": abs(self.inventory),
                    "type": "market"
                }
            
            else:
                order = None

            if order:
                await self.api.batch_create_orders([order])

    async def _place_batch_order(self, orders: list[Order]) -> None:
        '''
        Attempts to place the orders list and maintains the
        correctness of the resting orders and unregistered
        fills maps. Applies order constraints before placing.
        
        Logs rejection and reconciles on order rejection to
        maintain state.
        '''
        self.unregistered_fills.clear()

        for order in orders:
            self.constrain_order(order)

        try:
            response = await self.api.batch_create_orders([o.to_dict() for o in orders])
        except OrderRejection as e:
            logger.error(f"Order rejected. Rejection Data: {e}")
            await self.reconcile()
            return
        except Exception:
            return

        received_orders = response.get("orders", [])
        for order in received_orders:
            order_data = order.get("order", {})
            order_id = order_data.get("order_id")
            
            logger.info(f"Order placed.  {order_data.get("action")} {order_data.get("side")}: {order_data.get("count")}@{order_data.get("yes_price_dollars")}")

            remaining = order_data.get("remaining_count", 0)
            unregistered = self.unregistered_fills.pop(order_id, 0)
            net_count = remaining - unregistered
            
            if net_count > 0:
                self.resting_orders[order_id] = net_count

    async def get_balance(self) -> float:
        '''
        Returns balance, in dollars, from
        REST API balance endpoint.
        '''

        response = await self.api.get_balance()
        bal_dollars = (response.get("balance", 0)) / 100

        return bal_dollars

    def construct_order(self, action: str, price: FixedPointDollars, count: int) -> Order | None:
        '''
        Constructs order object based on params and executor
        configuration.

        Order is always placed in terms of the yes side.
        Action field controls how order is interpreted.

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
        raise NotImplementedError
    
    @abstractmethod
    def on_market_update(self):
        '''
        Event-handler for market updates.   
        Override to implement post-update
        logic.
        '''
        raise NotImplementedError

        