from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List
from datetime import datetime
from .OptionsExecutor import OptionsExecutor

if TYPE_CHECKING:
    from core.market import Order, OrderBookSnapshot, BinaryMarket
    from core.client import KalshiAPI, KalshiAuthentication, KalshiWebsocket
    from core.model import BSBOModel

sim_fills_logger = logging.getLogger("sim_fills")
sim_orders_logger = logging.getLogger("sim_orders")


class OptionsExecutorSimulator(OptionsExecutor):
    '''
    Simulator class for trading algorithm in "x currency above y strike at z time" markets.

    Maintains internal state for balance, inventory, and open orders. Simulates order placement
    and fills according to Kalshi's backend documented implementation. 
    
    Open orders are checked for fills on market orderbook ticks. 
    '''
    # Simulation Variables
    sim_open_orders: List[Order]

    def __init__(self, kalshi_api: KalshiAPI, market: BinaryMarket, 
                 session: KalshiAuthentication, max_inventory: int, min_edge: float, max_inventory_dev: int,
                 max_balance_dev: float, minimum_balance: float, currency: str, strike: float, 
                 expiry_datetime: str, model: BSBOModel, v_estimator, fresh_data_callback, starting_balance: float
                 ):
        
        super().__init__(kalshi_api=kalshi_api, market=market, session=session, max_inventory=max_inventory, 
                         min_edge=min_edge, currency=currency, strike=strike, expiry_datetime=expiry_datetime,
                         model=model, v_estimator=v_estimator, fresh_data_callback=fresh_data_callback, minimum_balance=minimum_balance,
                         max_balance_dev=max_balance_dev, max_inventory_dev=max_inventory_dev
                         )
        
        self.sim_open_orders = []

        self.balance = starting_balance

    #
    # OVERRIDES
    #

    def _convert_timestamp(self, timestamp: str) -> int:
        '''
        Converts ISO 8601 UTC timestamp to POSIX (ms) 
        timestamp.
        '''
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)

    def on_market_update(self):
        '''
        Market update handler.

        Triggers simulation of fill logic on new snapshot.
        '''
        self.simulate_fill_logic(self.market.snapshot())
        self.on_tick()

    async def get_balance(self):
        '''
        Returns the internally tracked balance.
        '''
        return self.balance

    async def reconcile(self):
        '''
        Reconcile overwrite to eliminate
        REST calls.
        '''
        return

    async def _place_batch_order(self, orders: List[Order]):
        '''
        Simulates placement by adding to internal order
        tracking.
        '''
        self.simulate_place_orders(orders)
    
    async def _cancel_outstanding_orders(self):
        '''
        Clears internal order tracking.
        '''
        self.sim_open_orders = []

    # 
    # SIMULATOR FUNCTIONS
    # 

    async def _close_position(self):
        '''
        Closes the position according to current
        orderbook state and internal inventory.
        '''
        if self.inventory > 0:
            sim_fills_logger.info(f"CLOSED POSITION: {self.inventory} YES @ {self.market.orderbook.best_bid}") 
            self.balance += float(self.market.orderbook.best_bid * abs(self.inventory))
            self.inventory = 0
        elif self.inventory < 0:
            sim_fills_logger.info(f"CLOSED POSITION: {self.inventory} NO @ {self.market.orderbook.best_ask.complement}")  
            self.balance += float(self.market.orderbook.best_ask.complement * abs(self.inventory))
            self.inventory = 0          

    def simulate_cancel_orders(self):
        '''
        Clears the internal resting order state.
        '''
        self.sim_open_orders = []
        return
    
    def simulate_place_orders(self, order: List[Order]):
        '''
        Simulates internal Kalshi logic for flip sales, constrains,
        and then places and logs the order in the internal state.
        '''
        orders = self.simulate_flip_sale(order)
        for o in orders:
            self.constrain_order(o)

        for o in orders:
            if o.count != 0:
                if o.side == "no" and o.action == "buy" or o.side == "yes" and o.action == "sell":
                    delta = -o.count
                    sim_orders_logger.info(f"Simulated Order Placement. {delta:+d} @ {o.yes_price_dollars}")
                if o.side == "no" and o.action == "sell" or o.side == "yes" and o.action == "buy":
                    sim_orders_logger.info(f"Simulated Order Placement. {o.count:+d} @ {o.yes_price_dollars}")
                self.sim_open_orders.append(o)

    def simulate_flip_sale(self, orders: List[Order]) -> List[Order]:
        '''
        Checks whether a "flip sale" would occur. Mutates orders
        and builds new orders to imitate the back-end translation
        for a flip sale. Returns the order batch with flipped orders
        if necessary.
        '''
        result = []
        for order in orders:
            if order.action == "sell" and order.side == "yes":
                # Selling YES (short)
                if order.count <= self.inventory:
                    # Can cover w inventory
                    result.append(order)
                elif self.inventory > 0:
                    # Can't cover, need to split
                    result.append(Order(
                        ticker=self.market.ticker,
                        type="limit",
                        action="sell",
                        side="yes",
                        count=self.inventory,
                        yes_price_dollars=order.yes_price_dollars
                    ))
                    result.append(Order(
                        ticker=self.market.ticker,
                        type="limit",
                        action="buy",
                        side="no",
                        count=order.count - self.inventory,
                        yes_price_dollars=order.yes_price_dollars
                    ))
                else:
                    # No flip, straight buy short
                    order.side = "no"
                    order.action = "buy"
                    result.append(order)

            elif order.action == "sell" and order.side == "no":
                # Selling NO (long)
                short_position = -self.inventory
                if short_position >= order.count:
                    # Can cover
                    result.append(order)
                elif short_position > 0:
                    # Can't cover, split
                    result.append(Order(
                        ticker=self.market.ticker,
                        type="limit",
                        action="sell",
                        side="no",
                        count=short_position,
                        yes_price_dollars=order.yes_price_dollars
                    ))
                    result.append(Order(
                        ticker=self.market.ticker,
                        type="limit",
                        action="buy",
                        side="yes",
                        count=order.count - short_position,
                        yes_price_dollars=order.yes_price_dollars
                    ))
                else:
                    # Straight buy
                    order.side = "yes"
                    order.action = "buy"
                    result.append(order)
            else:
                result.append(order)
        
        return result

    def simulate_fill_logic(self, snapshot: OrderBookSnapshot):
        '''
        Checks resting order list against the orderbook snapshot
        to determine whether an order would fill. Fills against
        best bid/ask and assumes no partial fills.
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
                count = order.count
                delta = count if is_long else -count
                
                if order.side == "yes":
                    cost = float(order.yes_price_dollars)
                else:
                    cost = float(order.yes_price_dollars.complement)
                
                old_inventory = self.inventory
                
                if order.action == "buy":
                    self.balance -= count * cost
                    
                    if is_long and old_inventory < 0:
                        pairs = min(count, -old_inventory)
                        self.balance += pairs * 1.0
                    elif not is_long and old_inventory > 0:
                        pairs = min(count, old_inventory)
                        self.balance += pairs * 1.0
                else:
                    self.balance += count * cost
                
                self.inventory += delta
                self.sim_open_orders.remove(order)
                sim_fills_logger.info(f"Simulated Order Filled. {delta:+d} @ {order.yes_price_dollars}. Bal/Inv: {self.balance}/{self.inventory}")