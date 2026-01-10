from __future__ import annotations

from market import Order
from .OptionsExecutor import OptionsExecutor
import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from market.Order import Order
    from market.OrderBookSnapshot import OrderBookSnapshot
    from client.API import KalshiAPI
    from client.KSocket import KalshiWebsocket
    from client.Session import Session
    from derivatives_pipeline.DeribitAPI  import DeribitREST, DeribitSocket
    from market.BinaryMarket import BinaryMarket
    from model.BSBOModel import BSBOModel

fill_logger = logging.getLogger("fills")
order_logger = logging.getLogger("orders")


class OptionsExecutorSimulator(OptionsExecutor):

    # Simulation Variables
    sim_open_orders: List[Order]

    def __init__(self, kalshi_api: KalshiAPI, market: BinaryMarket, 
                 session: Session, max_inventory: int, min_edge: float, deri_ws: DeribitSocket, 
                 deri_rest: DeribitREST, currency: str, strike: float, expiry_datetime: str,
                 model: BSBOModel, vol_est
                 ):
        super().__init__(kalshi_api, market, session, max_inventory, min_edge, deri_ws, deri_rest, currency, strike, expiry_datetime,
                         model, vol_est)
        
        self.sim_open_orders = []

        self.balance = 50

    #
    # OVERRIDES
    #

    def on_market_update(self):
        self.simulate_fill_logic(self.market.snapshot())

    async def get_balance(self):
        return self.balance

    async def reconcile(self):
        return

    async def _place_batch_order(self, orders: List[Order]):
        self.simulate_place_orders(orders)
    
    async def _cancel_outstanding_orders(self):
        self.sim_open_orders = []

    # 
    # SIMULATOR FUNCTIONS
    # 

    def simulate_cancel_orders(self):
        self.sim_open_orders = []
        return
    
    def simulate_place_orders(self, order: List[Order]):
        orders = self.simulate_flip_sale(order)
        for o in orders:
            self.constrain_order(o)

        for o in orders:
            if o.count != 0:
                if o.side == "no" and o.action == "buy" or o.side == "yes" and o.action == "sell":
                    delta = -o.count
                    order_logger.info(f"{delta:+d} @ {o.yes_price_dollars}")
                if o.side == "no" and o.action == "sell" or o.side == "yes" and o.action == "buy":
                    order_logger.info(f"{o.count:+d} @ {o.yes_price_dollars}")
                self.sim_open_orders.append(o)

    def simulate_flip_sale(self, orders: List[Order]) -> List[Order]:
        '''
        Flips orders if necessary to represent
        the likely fill order/implementation for a 
        live trading flip sale.
        '''
        result = []
        for order in orders:
            if order.action == "sell" and order.side == "yes":
                # Selling YES (going short / closing long)
                if order.count <= self.inventory:
                    # Have enough long YES to sell
                    result.append(order)
                elif self.inventory > 0:
                    # Split: sell existing YES, buy NO for remainder
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
                    # No YES inventory, flip entirely to buying NO
                    order.side = "no"
                    order.action = "buy"
                    result.append(order)

            elif order.action == "sell" and order.side == "no":
                # Selling NO (going long / closing short)
                short_position = -self.inventory  # NO contracts held when short
                if short_position >= order.count:
                    # Have enough short position to sell NO
                    result.append(order)
                elif short_position > 0:
                    # Split: sell existing NO (close short), buy YES for remainder
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
                    # No short position, flip entirely to buying YES
                    order.side = "yes"
                    order.action = "buy"
                    result.append(order)

            else:
                result.append(order)
        
        return result

    def simulate_fill_logic(self, snapshot: OrderBookSnapshot):
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
                fill_logger.info(f"{delta:+d} @ {order.yes_price_dollars}. Bal/Inv: {self.balance}/{self.inventory}")