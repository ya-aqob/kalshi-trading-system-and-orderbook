from dataclasses import dataclass
from typing import Tuple, List, Dict
from OrderBook import OrderBook

@dataclass(frozen=True)
class OrderBookSnapshot:
    '''
    Immutable snapshot of an OrderBook
    '''
    # Snapshot is representative of orderbook at timestamp (in ns)
    timestamp: float

    # Lists of [price_dollars, resting_size] pairs 
    yes_side: List[Tuple[float, int]] # Sorted ascending
    no_side:  List[Tuple[float, int]] # Sorted ascending

    # Best bid in price_dollars
    best_bid: float | None
    # Best ask in price_dollars (taken from complement)
    best_ask: float | None

    # Volume-weighted Mid Price of Underlying Orderbook
    mid_price: float | None
    # Raw best bid-ask spread
    spread: float | None

    @classmethod
    def from_orderbook(cls, book: OrderBook) -> "OrderBookSnapshot":
        '''
        Returns snapshot of given OrderBook
        '''
        yes_side = sorted(list(book.yes_book.items()))
        no_side = sorted(list(book.no_book.items()))

        best_bid = book.best_bid
        best_ask = book.best_ask

        mid_price = book.mid_price
        spread = book.bid_ask_spread

        timestamp = book.timestamp
        
        return cls(
            yes_side=yes_side,
            no_side=no_side,
            best_bid=best_bid,
            best_ask=best_ask,
            mid_price=mid_price,
            spread=spread,
            timestamp=timestamp
        )

