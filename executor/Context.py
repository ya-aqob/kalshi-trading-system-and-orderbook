from dataclasses import dataclass
from market.OrderBookSnapshot import OrderBookSnapshot 
@dataclass(frozen=True)
class Context:
    '''Dataclass capturing key context for quoting decision'''
    snapshot: OrderBookSnapshot
    inventory: int
    volatility: float | None
    seq_n: int
    timestamp: float

