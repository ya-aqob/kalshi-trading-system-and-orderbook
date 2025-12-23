import typing
from decimal import Decimal
from dataclasses import dataclass

@dataclass
class OneSidedOrderBook:
    '''
    Data class representing key information from an orderbook
    '''

    # Best bid price for given orderbook
    best_bid: float
    # Size of contract at best bid price
    bid_size: int

    # Best ask for a given orderbook (calculated through complement)
    best_ask: float
    # Size of contract at best ask price
    ask_size: int

    @property
    def volume_weight_mid_price(self):
        '''Returns the volume-weighted mid price of the orderbook'''
        return ((self.best_bid * self.ask_size) + (self.best_ask * self.bid_size)) / (self.bid_size + self.ask_size)
    
    @property
    def spread(self):
        '''Returns the bid-ask spread of the orderbook'''
        return (self.best_ask - self.best_bid)
    