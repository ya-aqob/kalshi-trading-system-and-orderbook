import uuid

class Order:
    ticker: str 
    side: str            # 'yes' or 'no'
    action: str          # 'buy' or 'sell'
    count: int
    type: str            # 'limit' or 'market'
    client_order_id: str # De-duplication ID
    yes_price: str

    def __init__(self, ticker, side, action, count, type, yes_price_dollars):
        self.ticker = ticker
        self.side = side
        self.action = action
        self.count = count
        self.type = type
        self.yes_price_dollars = yes_price_dollars

        self.client_order_id = str(uuid.uuid4())
    
    def to_dict(self):
        return {
            "ticker": self.ticker,
            "action": self.action,
            "side": self.side,
            "count": self.count,
            "type": self.type,
            "yes_price_dollars": self.yes_price_dollars,
            "client_order_id": self.client_order_id
        }
