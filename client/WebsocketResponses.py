from pydantic import BaseModel
from typing import Literal, Optional

'''
Pydantic validation schemas for fill and orderbook messages and envelopes
'''

class OrderBookDeltaMsg(BaseModel):
    market_ticker: str
    side: Literal["yes", "no"]
    price_dollars: float
    delta: int

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

class FillEnvelope(BaseModel):
    type: Literal["fill"]
    sid: int
    msg: FillMsg

class SubscribedMsg(BaseModel):
    channel: str
    sid: int