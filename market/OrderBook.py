from typing import List
from decimal import Decimal
from dataclasses import dataclass

class OrderBook:
    '''
    Mutable orderbook updated by delta messages
    '''

    # Time where orderbook obj represents market orderbook
    timestamp: float

    best_bid: float # Best bid price for given orderbook    
    bid_size: int   # Size of contract at best bid price

    best_ask: float # Best ask for a given orderbook (calculated through complement)
    ask_size: int   # Size of contract at best ask price

    yes_book: dict[float, int] # Yes side of the orderbook in [price, resting_contract] key-value pairs
    no_book: dict[float, int]  # No side of the order book in [price, resting_contracts] key-value pairs.

    mid_price: float      # Volume-weighted mid price
    bid_ask_spread: float # Best bid-ask spread

    seq_n: int | None     # Sequence number of message that spawns orderbook, ensures no gaps

    def __init__(self):
        self.timestamp = -1
        self.best_bid = 0.0
        self.bid_size = 0

        self.best_ask = 100.0 # Init to >max value for min logic
        self.ask_size = 0
        self.yes_book = {}
        self.no_book = {}

        self.mid_price = 0.0
        self.bid_ask_spread = 0.0

        self.seq_n = None
    
    def _apply_snapshot(self, timestamp: float, sequence_number: int, snapshot_msg: dict) -> None:
        '''
        Accepts timestamp (in ns) of receipt of snapshot and snapshot message.

        Updates all fields of OrderBook to match snapshot.

        Returns None.
        '''
        # Re-init
        self.best_bid = 0.0
        self.best_ask = 100.0

        self.seq_n = sequence_number

        if "yes_dollars" in snapshot_msg:
            yes_book = snapshot_msg["yes_dollars"]
        else:
            no_book = []

        if "no_dollars" in snapshot_msg:
            no_book = snapshot_msg["no_dollars"]
        else:
            no_book = []

        for bid in yes_book:
            price, size = bid
            
            self.best_bid = max(self.best_bid, price)

            if price in yes_book:
                self.yes_book[price] += size
            else:
                self.yes_book[price] = size
            
        for bid in no_book:
            no_bid, size = bid
            price = 1 - no_bid
            
            self.best_ask = min(self.best_ask, price)

            if price in no_book:
                self.no_book[price] += size
            else:
                self.no_book[price] = size

        self.timestamp = timestamp
        self.mid_price = self.calc_mid_price()
        self.bid_ask_spread = self.spread()  

    def _apply_delta(self, timestamp: float, sequence_number: int, delta_msg: dict) -> None:
        '''
        Accepts timestamp (in ns) of receipt of delta and delta message.

        Updates all fields to represent post-delta OrderBook.

        Returns None.
        '''
        self.seq_n = sequence_number

        if "side" in delta_msg:
            side = delta_msg["side"]

        if side == "yes":
            if "price_dollars" in delta_msg and "delta" in delta_msg:
                price = delta_msg["price_dollars"]
                delta = delta_msg["delta"]
                if price in self.yes_book:
                    self.yes_book[price] += delta
                else:
                    self.yes_book[price] = delta
                self.best_bid = max(price, self.best_bid)

        if side == "no":
            if "price_dollars" in delta_msg and "delta" in delta_msg:
                price = delta_msg["price_dollars"]
                delta = delta_msg["delta"]
                if price in self.yes_book:
                    self.yes_book[price] += delta
                else:
                    self.yes_book = delta
                self.best_ask= max(price, 1 - self.best_bid)
        
        self.timestamp = timestamp
                    
    def calc_mid_price(self):
        '''Returns the mid price of the orderbook'''
        return (self.best_bid + self.best_ask) / 2
    
    def spread(self):
        '''Returns the bid-ask spread of the orderbook'''
        return (self.best_ask - self.best_bid)
    