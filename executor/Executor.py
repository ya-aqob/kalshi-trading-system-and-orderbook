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

    def __init__(self, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int, wealth: float, quote_size: int = 1):
        self.model = model
        self.market = market
        self.session = session

        self.max_inventory = max_inventory
        self.quote_size = quote_size

        self.terminal_time = time.monotonic_ns() + runtime * (1 * 10**9)

    def execute(self):
        model = self.model
        market = self.market
        session = self.session

        bid_quote = model.bid_quote
        ask_quote = model.ask_quote

        bid_size = self.quote_size
        ask_size = self.quote_size

        bid_cost = bid_size * bid_quote

        batch = []

        # Size bid to wealth constraint
        if self.wealth < bid_cost:
            bid_size = math.floor(self.wealth / bid_cost)

        # Size quote to inventory constraint
        if ask_size > model.q:
            ask_size = model.q

        if bid_size:
            order = self.construct_order(action="buy", price=bid_quote)
            batch.append(order)

        if ask_size:
            order = self.construct_order(action="sell", price=ask_quote)
            batch.append(order)
        
        if batch:
            market.make_batch_order(batch)
        
        return

    def construct_order(self, action: str, price: float):
        return Order(
            ticker = self.market.ticker,
            side = "yes",
            action = action,
            count= self.quote_size,
            type = "limit",
            yes_price = price
            )

    def run(self):
        curr_time = time.monotonic_ns()
        while curr_time < self.terminal_time:
            
            while not self.market.is_ready():
                self.market.update()
            
            self.market.update()
            self.model.update()
            self.execute()