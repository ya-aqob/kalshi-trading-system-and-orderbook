from pydantic import BaseModel, field_validator
from typing import Literal, Optional
from datetime import datetime

'''
Pydantic validation schemas for fill and orderbook messages and envelopes
'''

class OrderBookDeltaMsg(BaseModel):
    market_ticker: str
    side: Literal["yes", "no"]
    price_dollars: float
    delta: int
    ts: int # in POSIX (ns)

    @field_validator('ts', mode='before')
    @classmethod
    def parse_timestamp(cls, v):
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace('Z', '+00:00'))
            return int(dt.timestamp() * 1_000_000_000)
        return v

class OrderBookDeltaEnvelope(BaseModel):
    type: Literal["orderbook_delta"]
    sid: int
    seq: int
    msg: OrderBookDeltaMsg

class OrderBookSnapshotMsg(BaseModel):
    market_ticker: str
    yes: Optional[list]
    yes_dollars: Optional[list]
    no: Optional[list]
    no_dollars: Optional[list]

class OrderBookSnapshotEnvelope(BaseModel):
    type: Literal["orderbook_snapshot"]
    sid: int
    seq: int
    msg: OrderBookSnapshotMsg

class FillMsg(BaseModel):
    trade_id: str
    order_id: str
    market_ticker: str
    side: Literal["yes", "no"]
    purchased_side: Literal["yes", "no"]
    yes_price_dollars: float
    count: int
    action: Literal["buy", "sell"]
    post_position: int
    ts: int

class FillEnvelope(BaseModel):
    type: Literal["fill"]
    sid: int
    msg: FillMsg

class SubscribedMsg(BaseModel):
    channel: str
    sid: int