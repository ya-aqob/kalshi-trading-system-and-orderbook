from executor import Executor
import math
import logging

quote_logger = logging.getLogger("quotes")
fill_logger = logging.getLogger("fills")

class SimulatorExecutor(Executor):
    '''
    Simulates Executor actions on live market data fed by same
    websocket pipeline.

    Mimics same quoting and action logic on orderbook deltas as live executor,
    but does not currently start the quoting chain on fills.

    Maintains inventory, trade history, and resting orders for simulated
    order filling and model calculations. Logs quotes and fills for model
    tuning and evaluation.
    '''

    resting_orders: set       # Resting orders between updates
    inventory: int            # Contracts held between updates
    trade_history: list[dict] # List of transactions in
                              # {"order_id": order_id, "fill_size": fill_size, "price": yes_price_dollars}
                              # format
    start_balance: float


    def __init__(self, api, model, market, session, runtime, max_inventory, start_balance):
        
        self.start_balance = start_balance
        super().__init__(api, model, market, session, runtime, max_inventory)

        self.resting_orders = set() 
        self.trade_history = []
        self.start_balance = start_balance

    async def on_market_update(self):
        '''
        Simulates changes in portfolio between updates (order fills)
        and starts quote logic chain.

        Simulates fills by checking order set against new orderbook snapshot, 
        filling asks when best bid >= ask and filling bids when best ask <= bid.
        Estimates partial fills by depth at single best price in either direction.
        '''
        snapshot = self.market.snapshot()
        filled = set()
        for order in self.resting_orders:
            if order.action == "sell":
                if snapshot.best_bid >= order.yes_price_dollars:
                    fill_size = min(order.count, snapshot.bid_size, self.inventory)
                    self.balance += fill_size * order.yes_price_dollars
                    if fill_size == order.count:
                        filled.add(order)
                    else:
                        order.count -= fill_size
                    self.inventory -= fill_size
                    self.trade_history.append({"order_id": order.client_order_id, "fill_size": fill_size, "price": order.yes_price_dollars})
                    fill_logger.info(f"FILL {order.action} {fill_size}@{order.yes_price_dollars} | inv={self.inventory} bal={self.balance:.2f}")
            elif order.action == "buy":
                if snapshot.best_ask <= order.yes_price_dollars:
                    fill_size = min(order.count, snapshot.ask_size)
                    self.balance -= fill_size * order.yes_price_dollars
                    if fill_size == order.count:
                        filled.add(order)
                    else:
                        order.count -= fill_size
                    self.inventory += fill_size
                    self.trade_history.append({"order_id": order.client_order_id, "fill_size": fill_size, "price": order.yes_price_dollars})
                    fill_logger.info(f"FILL {order.action} {fill_size}@{order.yes_price_dollars} | inv={self.inventory} bal={self.balance:.2f}")
        
        self.resting_orders = self.resting_orders - filled
        await self._attempt_execute_quote()


    async def _attempt_execute_quote(self):
        '''
        Attempts to place quote and checks should_quote
        conditions. Captures the context for quoting.
        '''
        if self.quote_lock.locked():
            return

        async with self.quote_lock:
            self._cancel_outstanding_orders()

            ctx = self._capture_quote_context()
            bid, ask = self.model.generate_quotes(ctx.snapshot, ctx.inventory, ctx.volatility)

            if not self._should_quote(ctx):
                return

            self._place_quote(bid, ask)

    def _cancel_outstanding_orders(self):
        '''Re-init resting orders'''
        self.resting_orders = set()

    def _place_quote(self, bid_quote, ask_quote):
        '''
        Simulates order placement with normal constraints.
        Adds valid orders to resting orders set.
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
            quote_logger.info(f"BID {bid_size}@{bid_quote}")
            bid_order = self.construct_order(action="buy", price=bid_quote, count=bid_size)

            if bid_order is not None:
                batch.append(bid_order)

        if ask_size:
            quote_logger.info(f"ASK {ask_size}@{ask_quote}")
            ask_order = self.construct_order(action="sell", price=ask_quote, count=ask_size)

            if ask_order is not None:
                batch.append(ask_order)
        
        if not batch:
            return
        
        for order in batch:
            self.resting_orders.add(order)

    def get_balance(self):
        '''
        Returns the static starting balance
        '''
        return self.start_balance
        