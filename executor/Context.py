from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from market.OrderBookSnapshot import OrderBookSnapshot 
    from .ExecutorSnapshot import ExecutorSnapshot

@dataclass(frozen=True)
class Context:
    '''Dataclass capturing key context for quoting decision'''
    orderbook_snapshot: OrderBookSnapshot
    executor_snapshot: ExecutorSnapshot
    volatility: float | None
    seq_n: int
    timestamp: float

