from dataclasses import dataclass

from typing import Optional

@dataclass
class Subscription:
    sid: int
    channel: str
    market_ticker: Optional[str]
