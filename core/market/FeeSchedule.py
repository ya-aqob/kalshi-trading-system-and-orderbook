import math
class KalshiFeeSchedule:
    '''
    Class representing the standard Kalshi Fee Schedule
    with associated calculators.
    '''

    taker_fee_rate: float # Fee for trades immediately filled against resting orders
    maker_fee_rate: float # Fee for trades filled after resting on the orderbook

    def __init__(self, taker_fee_rate=.07, maker_fee_rate=.0175):
        self.taker_fee_rate = taker_fee_rate
        self.maker_fee_rate = maker_fee_rate

    def _calculate_fees(self, rate: float, price: float, count: int) -> float:
        '''
        Calculates fees according to standard Kalshi equation
        with centwise round-up.
        '''
        raw_dollars = rate * count * price * (1 - price)
        return math.ceil(100 * raw_dollars) / 100

    def calculate_taker_fees(self, price: float, count: int) -> float:
        '''
        Calculates total taker fee burden for a trade executed at price with count contracts.
        '''
        return self._calculate_fees(self.taker_fee_rate, price, count)
    
    def calculate_maker_fees(self, price: float, count: int) -> float:
        '''
        Calculates total maker fee burden for a trade executed at price with count contracts.
        '''
        return self._calculate_fees(self.maker_fee_rate, price, count)
    
    def calculate_mixed_fees(self, price: float, count_made: int, count_take: int) -> float:
        '''
        Calculates total fee burden for a trade executed at price with count_made contracts
        filled after resting and count_take contracts filled against resting.
        '''
        maker_fees = self.calculate_maker_fees(price, count_made)
        taker_fees = self.calculate_taker_fees(price, count_take)
        return maker_fees + taker_fees
    
    def taker_fees_per_contract(self, price: float) -> float:
        '''
        Calculates the fee-per-contract for an order executed at price
        which is filled against a resting order.
        '''
        return math.ceil(100.0 * (.07 * price * (1 - price))) / 100
    
    def maker_fees_per_contract(self, price: float) -> float:
        '''
        Calculates the fee-per-contract for an order executed at price
        which is filled after resting.
        '''
        return math.ceil(100.0 * (.0175 * price * (1 - price))) / 100