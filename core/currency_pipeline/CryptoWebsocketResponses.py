import pydantic
from pydantic import BaseModel
from typing import Literal

'''
Pydantic validation schemas for Crypto.com Websocket Messages
'''

class TickEnvelope(BaseModel):
    id: int
    method: Literal["subscribe"]
    
class TickerUpdate(BaseModel):
    
    model_config = {"extra": "ignore"}

    h: str
    l: str
    a: str
    c: str
    b: str
    bs: str
    k: str
    ks: str
    i: str
    v: str
    vv: str
    oi: str
    t: int

class IndexTick(BaseModel):
    v: str
    t: int