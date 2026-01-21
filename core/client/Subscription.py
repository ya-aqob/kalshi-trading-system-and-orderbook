from dataclasses import dataclass

from typing import Optional

@dataclass
class Subscription:
    '''Representation of websocket subcription information'''
    sid: int
    channel: str
    market_ticker: Optional[str]
