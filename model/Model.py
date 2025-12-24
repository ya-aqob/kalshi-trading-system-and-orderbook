from market.BinaryMarket import BinaryMarket
import numpy as np
import time
class Model:

    market: BinaryMarket # The market that the model is based on
    
    ### Model parameters
    T: float # Terminal time of trading session
    G: float # Risk-aversion parameter

    ### Model variables
    k: float # Decay parameter for fill-rate w.r.t. spread size
    q: int   # Size of inventory of position
    t: float # Current time

    ### Model Outputs
    reservation_price: float # Most recent indifference price
    bid_quote: float         # Most recent bid quote
    ask_quote: float         # Most recent ask quote
    spread:    float         # Most recent quote spread

    def __init__(self, market: BinaryMarket, k: float, q: int, T: float, G: float):
        self.k = k
        self.q = q
        self.T = T
        self.t = time.time()
        self.G = G

        self.market = market
    
    def calc_reserve_price(self) -> float:
        '''Calculates the reserve price of the market'''
        volatility = self.market.get_volatility()
        mid_price = self.market.get_mid_price()

        reserve_price = mid_price - (self.q * self.G * (volatility ** 2)) * (self.T - self.t)

        return reserve_price

    def calc_bid_distance(self) -> float:
        '''Returns the optimal bid distance from the reserve price'''
        volatility = self.market.get_volatility()

        distance = (self.G ** -1) * np.log(1 + (self.G) * (self.k ** -1))

        return distance

    def calc_ask_quote(self) -> float:
        return self.reservation_price + self.calc_bid_distance()

    def calc_bid_quote(self) -> float:
        return self.reservation_price - self.calc_bid_distance()
    
    def update(self, curr_time: float) -> None:
        self.t = curr_time
        self.q = self.market.get_position()["market_positions"]["position"]
        self.reservation_price = self.calc_reserve_price()
        self.ask_quote = self.calc_ask_quote()
        self.bid_quote = self.calc_bid_quote()
        self.spread = 2 * self.calc_bid_distance()

        return None





