from __future__ import annotations
from typing import TYPE_CHECKING
from .ExecutorSnapshot import ExecutorSnapshot
from .Executor import Executor
from client.API import KalshiAPI
from market.FixedPointDollars import MAX_PRICE, MIN_PRICE
from executor import Context
import asyncio
import math
import time
import logging

if TYPE_CHECKING:
    from market import BinaryMarket
    from model import Model
    from client import Session
    from client.WebsocketResponses import FillMsg


class MarketMakingExecutor(Executor):
    '''
    Executor specialized for market-making in 
    binary prediction markets that is compatible with
    any market-making model that subclasses Model.

    Utilizes event-conflation pattern for high-frequency
    fills and updates to debounce quote generation and
    ensure fresh quotes.
    '''
    
    quote_size: int                             # Standard size of each quote (in number of contracts)
    _update_event: asyncio.Event                # Event representing a pending update
    _update_processor_task: asyncio.Task | None # Task for processing ticks


    def __init__(self, api: KalshiAPI, model: Model, market: BinaryMarket, session: Session, runtime: int, max_inventory: int, quote_size: int = 1):
        
        super().__init__(api, market, session, max_inventory)
        
        self.quote_size = quote_size
        self.model = model
        
        self._update_event = asyncio.Event()
        self._update_processor_task = None

        self.terminal_time = time.time() + runtime
        self.runtime = runtime
    
    async def _attempt_execute_quote(self):
        '''
        Requires execution lock.
        Makes REST API call to cancel outstanding orders and yields.
        Captures context AFTER call returns and checks _should_quote
        conditions. Places quote IFF should quote.
        '''
        async with self._execution_lock:
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
            bid_size = min(bid_size, math.floor(bal / bid_quote))
        
        if ask_size > inventory:
            ask_size = inventory
        
        if bid_size > 0 and bid_quote:
            bid_order = self.construct_order(action="buy", price=bid_quote, count=bid_size)
            
            if bid_order is not None:
                batch.append(bid_order.to_dict())

        if ask_size > 0 and ask_quote:
            ask_order = self.construct_order(action="sell", price=ask_quote, count=ask_size)
            
            if ask_order is not None:
                batch.append(ask_order)
        
        if not batch:
            return
        
        await self._place_batch_order(batch)
    
    def on_fill(self, fill: FillMsg):
        '''
        Updates inv on FillMsg then triggers
        quote process.
        '''
        self.update_inv_on_fill(fill)
        self.trigger_process()

    def on_market_update(self):
        '''
        Public entrypoint for post-market-update logic.
        Initiates quote trigger process.
        '''
        self.trigger_process()
    
    def trigger_process(self):
        '''
        Checks quote conditions, sets event flag,
        and spawns processing task if one is not running.
        '''
        if not self.should_attempt_quote():
            return

        self._update_event.set()

        if self._update_processor_task is None or self._update_processor_task.done():
            self._update_processor_task = asyncio.create_task(self._update_processor()) 

    async def _update_processor(self):
        '''
        Update processor that triggers quote execution.
        Expects event flag within 1 second else exits.
        '''
        while True:
            try:
                await asyncio.wait_for(self._update_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                return
            
            self._update_event.clear()
            await self._attempt_execute_quote()