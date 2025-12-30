from dataclasses import dataclass
from typing import TYPE_CHECKING
import time

if TYPE_CHECKING:
    from .Executor import Executor

@dataclass(frozen=True)
class ExecutorSnapshot:
    '''
    Class representing executor state at timestamp
    '''
    timestamp: float

    balance: float
    inventory: int
    resting_orders: frozenset

    @classmethod
    def from_executor(cls, executor: Executor) -> "ExecutorSnapshot":
        return cls(
            timestamp = time.time(),
            balance=executor.balance,
            inventory=executor.inventory,
            resting_orders=frozenset(executor.resting_orders)
        )
