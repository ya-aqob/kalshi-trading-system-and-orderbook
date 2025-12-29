from dataclasses import dataclass
from typing import Tuple, List, Dict
from .OrderBook import OrderBook
from .FixedPointDollars import FixedPointDollars

@dataclass(frozen=True)
class OrderBookSnapshot:
    '''
    Immutable snapshot of an OrderBook
    '''

    # Snapshot is representative of orderbook at timestamp (in ns)
    timestamp: float

    # Lists of [price_dollars, resting_size] pairs 
    yes_side: List[Tuple[FixedPointDollars, int]] # Sorted ascending
    no_side:  List[Tuple[FixedPointDollars, int]] # Sorted ascending

    # Best bid in price_dollars
    best_bid: FixedPointDollars
    bid_size: int

    # Best ask in price_dollars (taken from complement)
    best_ask: FixedPointDollars
    ask_size: int

    # Volume-weighted Mid Price of Underlying Orderbook
    mid_price: FixedPointDollars
    # Raw best bid-ask spread
    spread: FixedPointDollars

    @classmethod
    def from_orderbook(cls, book: OrderBook) -> "OrderBookSnapshot":
        '''
        Returns snapshot of given OrderBook
        '''
        yes_side = sorted(list(book.yes_book.items()))
        no_side = sorted(list(book.no_book.items()))

        bid_size = book.bid_size
        ask_size = book.ask_size

        best_bid = book.best_bid
        best_ask = book.best_ask

        mid_price = book.mid_price
        spread = book.bid_ask_spread

        timestamp = book.timestamp
        
        return cls(
            yes_side=yes_side,
            no_side=no_side,
            best_bid=best_bid,
            bid_size=bid_size,
            best_ask=best_ask,
            ask_size=ask_size,
            mid_price=mid_price,
            spread=spread,
            timestamp=timestamp
        )

