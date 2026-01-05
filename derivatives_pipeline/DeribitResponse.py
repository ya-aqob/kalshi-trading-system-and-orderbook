from pydantic import BaseModel, Field  
from typing import Optional

class Greeks(BaseModel):
    model_config = {"extra": "ignore"}
    delta: float = 0
    gamma: float = 0
    vega: float = 0
    theta: float = 0
    rho: float = 0

class OptionTick(BaseModel):
    model_config = {"extra": "ignore"}
    instrument_name: str
    timestamp: int
    mark_iv: float = 0
    bid_iv: Optional[float] = None
    ask_iv: Optional[float] = None
    greeks: Greeks = Field(default_factory=Greeks)
    underlying_price: float = 0
    mark_price: float = 0
    underlying_index: str = ""

class Instrument(BaseModel):
    model_config = {"extra": "ignore"}
    instrument_name: str
    expiration_timestamp: int
    strike: float
    option_type: Optional[str] = None