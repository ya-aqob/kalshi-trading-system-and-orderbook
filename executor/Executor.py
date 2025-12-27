from model.Model import Model
from market.BinaryMarket import BinaryMarket
from client.Session import Session
from client.KSocket import KalshiWebsocket
from client.API import KalshiAPI
from asyncio import Queue, Task
import asyncio
import time
from market.Order import Order
import math

class Executor:

    api:     KalshiAPI
    ws:      KalshiWebsocket
    model:   Model
    market:  BinaryMarket
    session: Session

    # Parameters
    quote_size: int              # The standard sizing for a quote in # of contracts, default = 1
    max_inventory: int           # The maximum allowed size of inventory at any given time
    min_price: float = 0.01      # The lowest allowed price of any quote
    max_price: float = 0.99      # The highest allowed price of any quote

    # Variables
    wealth: float                # Current wealth of account
    inventory: int               # Current position held
    fresh: bool                  # Fresh if current quote reflects state
    quoting_task: Task | None    # Running quote task 

    def __init__(self, api: KalshiAPI, ws: KalshiWebsocket, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int, quote_size: int = 1):
        self.api = api
        self.ws = ws
        
        self.model = model
        self.market = market
        self.session = session

        self.max_inventory = max_inventory
        self.quote_size = quote_size

        self.wealth = self.get_balance()
        self.terminal_time = time.time() + runtime
        self.runtime = runtime
        self.quoting_task = None
        
        self.fresh = True

    def update_on_fill(self, fill: dict):
        '''
        Takes fill message.
        Updates inventory to reflect fill.
        Unsets fresh flag.
        '''
        
        if "count" in fill:
            if fill["action"] == "sell":
                self.inventory -= fill["count"]
                if "yes_price_dollars" in fill:
                    self.wealth += fill["count"] * fill["yes_price_dollars"]
                self.fresh = False
            else:
                self.inventory += fill["count"]
                if "yes_price_dollars" in fill:
                    self.wealth -= fill["count"] * fill["yes_price_dollars"]
                self.fresh = False

            if not self.quoting_task or self.quoting_task.done():
                self.quoting_task = asyncio.create_task(self._execute_quote())

    async def _execute_quote(self):
        while not self.fresh:
            self.fresh = True

            orderbook_snapshot = self.market.snapshot()
            inventory = self.inventory
            volatility = self.market.get_volatility()

            bid_quote, ask_quote = self.model.generate_bid_quote(orderbook_snapshot, inventory, volatility)

            if self.fresh:
                await self._place_quote(bid_quote, ask_quote)
                return
    
    async def _place_quote(self, bid_quote, ask_quote):
        bid_order = self.construct_order(action="buy", price=bid_quote, count=self.quote_size).to_dict()
        ask_order = self.construct_order(action="sell", price=ask_quote, count=self.quote_size).to_dict()

        await asyncio.to_thread(self.api.batch_create_orders([ask_order, bid_order]))
    
    def get_balance(self) -> float:
        return self.api.get_balance()["balance"] / 100

    def construct_order(self, action: str, price: float, count):
        return Order(
            ticker = self.market.ticker,
            side = "yes",
            action = action,
            count= count,
            type = "limit",
            yes_price_dollars = price
            )
