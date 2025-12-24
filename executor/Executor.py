from model.Model import Model
from market.BinaryMarket import BinaryMarket
from session.Session import Session
import time
from market.Order import Order
import math

class Executor:

    quote_size: int         # The standard sizing for a quote in # of contracts, default = 1
    max_inventory: int      # The maximum allowed size of inventory at any given time
    wealth: float           # Current wealth of account
    min_price: float = 0.01 # The lowest allowed price of any quote
    max_price: float = 0.99 # The highest allowed price of any quote

    def __init__(self, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int, quote_size: int = 1):
        self.model = model
        self.market = market
        self.session = session

        self.max_inventory = max_inventory
        self.quote_size = quote_size

        self.wealth = market.get_balance()["balance"]
        self.terminal_time = time.time() + runtime

    def execute(self):
        self.clear_open_orders() # Clear previous orders
        self.order_quote_batch() # Make new quote orders

    def construct_order(self, action: str, price: float, count):
        return Order(
            ticker = self.market.ticker,
            side = "yes",
            action = action,
            count= count,
            type = "limit",
            yes_price_dollars = price
            )

    def clear_open_orders(self):
        orders = self.market.get_orders()["orders"]
        batch = []

        for order in orders:
            batch.append(order["order_id"])

        self.market.cancel_batch_order(batch)

        return
    
    def order_quote_batch(self):
        model = self.model
        market = self.market

        bid_quote = model.bid_quote
        ask_quote = model.ask_quote

        bid_size = self.quote_size
        ask_size = self.quote_size

        bid_cost = bid_size * bid_quote

        self.wealth = market.get_balance()["balance"]
        batch = []

        # Valid iff quotes are in min and max bounds
        valid_quotes = bid_quote >= self.min_price and bid_quote <= self.max_price and ask_quote >= self.min_price and  ask_quote <= self.max_price

        if not valid_quotes:
            return
        
        # Size bid to wealth constraint
        if self.wealth < bid_cost:
            bid_size = math.floor(self.wealth / bid_quote)

        # Size quote to inventory constraint
        if ask_size > model.q:
            ask_size = model.q

        if bid_size > 0:
            bid_size = min(bid_size, self.max_inventory - model.q)
            order = self.construct_order(action="buy", price=bid_quote, count=bid_size)
            batch.append(order.to_dict())

        if ask_size > 0:
            order = self.construct_order(action="sell", price=ask_quote, count=ask_size)
            batch.append(order.to_dict())
        
        if batch:
            market.make_batch_order(batch)
        
        return

    def run(self):
        curr_time = time.time()
        while curr_time < self.terminal_time:
            
            while not self.market.is_ready():
                self.clear_open_orders()
                self.market.update()
            
            self.market.update()
            self.model.update(curr_time)
            self.execute()

            curr_time = time.time()
        
        self.clear_open_orders()