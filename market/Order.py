import uuid
from .FixedPointDollars import FixedPointDollars, MAX_PRICE, MIN_PRICE

class Order:
    '''
    Representation of a KalshiAPI Order obj
    Enforced input validation
    '''
    ticker: str                          # Ticker where order will be executed
    side: str                            # 'yes' or 'no'
    action: str                          # 'buy' or 'sell'
    count: int                           # size of order in # of contracts
    type: str                            # 'limit' or 'market'
    client_order_id: str                 # Unique de-duplication ID
    yes_price_dollars: FixedPointDollars # Price in penny dollars

    def __init__(self, ticker: str, side: str, action: str, count: int, type: str, 
                 yes_price_dollars: FixedPointDollars):
        
        if side not in ('yes', 'no', 'YES', 'NO'):
            raise ValueError(f"Invalid side provided: {side}")
        if action not in ('buy', 'sell', "BUY", "SELL"):
            raise ValueError(f"Invalid action provided: {action}")
        if type not in ("limit", "market", "LIMIT", "MARKET"):
            raise ValueError(f"Invalid type: {type}")
        if count <= 0:
            raise ValueError(f"Invalid order count: {count}")
        if not (MIN_PRICE <= yes_price_dollars <= MAX_PRICE):
            raise ValueError(f"Price out of range: {yes_price_dollars}")
        
        self.ticker = ticker
        self.side = side
        self.action = action
        self.count = count
        self.type = type
        self.yes_price_dollars = yes_price_dollars

        self.client_order_id = str(uuid.uuid4())
    
    def __hash__(self):
        return hash(self.client_order_id)

    def __eq__(self, other):
        if not isinstance(other, Order):
            return False
        return self.client_order_id == other.client_order_id

    def to_dict(self):
        return {
            "ticker": self.ticker,
            "action": self.action,
            "side": self.side,
            "count": self.count,
            "type": self.type,
            "yes_price_dollars": self.yes_price_dollars.to_float(),
            "client_order_id": self.client_order_id
        }
