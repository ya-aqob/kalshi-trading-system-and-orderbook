from __future__ import annotations
from typing import List, TYPE_CHECKING
from decimal import Decimal
from dataclasses import dataclass
from .FixedPointDollars import FixedPointDollars, ZERO, ONE, MID_DEFAULT
from sortedcontainers.sorteddict import SortedDict

if TYPE_CHECKING:
    from client.WebsocketResponses import OrderBookDeltaMsg, OrderBookSnapshotMsg

class OrderBook:
    '''
    Mutable orderbook updated by delta messages.
    Orderbook is only valid AFTER a snapshot has been
    applied.

    Snapshots apply in O(N) time.
    '''

    # Time where orderbook obj represents market orderbook
    timestamp: float
    
    # bid and ask are init to min and max values respectively
    best_bid: FixedPointDollars # Best bid price for given orderbook    
    bid_size: int   # Size of contract at best bid price

    best_ask: FixedPointDollars # Best ask for a given orderbook (calculated through complement)
    ask_size: int   # Size of contract at best ask price

    yes_book: SortedDict[FixedPointDollars, int] # Yes side of the orderbook in [price, resting_contract] key-value pairs
    no_book: SortedDict[FixedPointDollars, int]  # No side of the order book in [price, resting_contracts] key-value pairs.

    mid_price: FixedPointDollars      # Volume-weighted mid price
    bid_ask_spread: FixedPointDollars # Best bid-ask spread

    seq_n: int # Sequence number of message that spawns orderbook, ensures no gaps

    def __init__(self):
        self.timestamp = -1.0
        self.best_bid = ZERO
        self.bid_size = 0

        self.best_ask = ONE # Init to >max value for min logic
        self.ask_size = 0
        self.yes_book = SortedDict()
        self.no_book = SortedDict()

        self.mid_price = MID_DEFAULT
        self.bid_ask_spread = ZERO

        self.seq_n = None
    
    def _apply_snapshot(self, timestamp: float, sequence_number: int, snapshot_msg: OrderBookSnapshotMsg) -> None:
        '''
        Updates all fields of OrderBook to match snapshot.

        Builds batch for each side of orderbook and then
        batch updates the sorted dicts.

        Returns None.
        '''
        self.seq_n = sequence_number
    
        yes_dict = {}
        for price, size in (snapshot_msg.yes_dollars or []):
            price = FixedPointDollars(price)
            yes_dict[price] = yes_dict.get(price, 0) + size

        no_dict = {}
        for no_bid, size in (snapshot_msg.no_dollars or []):
            no_bid = FixedPointDollars(no_bid)
            no_dict[no_bid] = no_dict.get(no_bid, 0) + size

        # Batch insert w/ order invariant
        self.yes_book = SortedDict(yes_dict)
        self.no_book = SortedDict(no_dict)

        if self.yes_book:
            self.best_bid = self.yes_book.keys()[-1]
            self.bid_size = self.yes_book[self.best_bid]
        else:
            self.best_bid = ZERO
            self.bid_size = 0

        if self.no_book:
            highest_no_bid = self.no_book.keys()[-1]
            self.best_ask = highest_no_bid.complement
            self.ask_size = self.no_book[highest_no_bid]
        else:
            self.best_ask = ONE
            self.ask_size = 0

        self.timestamp = timestamp
        self.mid_price = self.calc_mid_price()
        self.bid_ask_spread = self.spread() 

    def _apply_delta(self, timestamp: float, sequence_number: int, delta_msg: OrderBookDeltaMsg) -> None:
        '''
        Accepts timestamp (in ns) of receipt of delta and delta message.

        Updates all fields to represent post-delta OrderBook.

        Returns None.
        '''
    
        self.seq_n = sequence_number

        delta = delta_msg.delta
        price = FixedPointDollars(delta_msg.price_dollars)

        if delta_msg.side == "yes":
            if price in self.yes_book:
                self.yes_book[price] += delta

                if self.yes_book[price] <= 0:
                    del self.yes_book[price]
                    if price == self.best_bid:
                        self._find_new_best_bid()
                elif price == self.best_bid:
                    self.bid_size = self.yes_book[price]
            else:
                if delta > 0:
                    self.yes_book[price] = delta
                    if price > self.best_bid:
                        self.best_bid = price
                        self.bid_size = delta

        if delta_msg.side == "no":
            if price in self.no_book:
                self.no_book[price] += delta

                if self.no_book[price] <= 0:
                    del self.no_book[price]
                    if price.complement == self.best_ask:
                        self._find_new_best_ask()
                elif price.complement == self.best_ask:
                    self.ask_size = self.no_book[price]
            else:
                if delta > 0:
                    self.no_book[price] = delta
                    if price.complement < self.best_ask:
                        self.best_ask = price.complement
                        self.ask_size = delta

        self.timestamp = timestamp
        self.mid_price = self.calc_mid_price()
        self.bid_ask_spread = self.spread()

    def _find_new_best_ask(self):
        '''Sets best_ask and ask_size based on book'''
        if not self.no_book:
            self.best_ask = ONE
            self.ask_size = 0
            return
        
        highest_no_bid, ask_size = self.no_book.items()[-1]

        self.best_ask = highest_no_bid.complement
        self.ask_size = ask_size

    def _find_new_best_bid(self):
        '''Sets best_bid and bid_size based on book'''
        if not self.yes_book:
            self.best_bid = ZERO
            self.bid_size = 0
            return
        
        best_bid, bid_size = self.yes_book.items()[-1]
        
        self.best_bid = best_bid
        self.bid_size = bid_size

    def calc_mid_price(self) -> FixedPointDollars:
        '''
        Returns the mid price of the orderbook.
        Returns default mid price if one or more of 
        the ask and bid are invalid.
        '''
        has_ask = self.best_ask < ONE
        has_bid = self.best_bid > ZERO

        if has_ask and has_bid:
            return (self.best_bid + self.best_ask) / 2
        elif has_ask:
            return self.best_ask
        elif has_bid:
            return self.best_bid
        else:
            return MID_DEFAULT
    
    def spread(self) -> FixedPointDollars:
        '''Returns the bid-ask spread of the orderbook'''
        return (self.best_ask - self.best_bid)
    