from market.BinaryMarket import BinaryMarket
import numpy as np

class Model:

    market: BinaryMarket # The market that the model is based on

    ### Model Limits
    max_inventory: int # The maximum allowed size of the position
    
    ### Model parameters
    T: float # Terminal time of trading session
    G: float # Risk-aversion parameter
    W: float # Wealth

    ### Model variables
    k: float # Decay parameter for fill-rate w.r.t. spread size
    q: int   # Size of inventory of position
    t: float # Current time

    ### Model Outputs
    reservation_price: float # Most recent indifference price
    bid_quote: float         # Most recent bid quote
    ask_quote: float         # Most recent ask quote
    spread:    float         # Most recent quote spread

    def __init__(self, market: BinaryMarket, max_inventory: int, k: float, q: int, T: float, t: float, G: float):
        self.k = k
        self.q = q
        self.T = T
        self.t = t
        self.G = G

        self.max_inventory = max_inventory
    
    def calc_reserve_price(self) -> float:
        '''Calculates the reserve price of the market'''
        volatility = self.market.get_volatility()
        mid_price = self.market.get_mid_price()

        reserve_price = mid_price - (self.q * self.G * (volatility ** 2)) * (self.T - self.t)

        return reserve_price

    def calc_bid_distance(self) -> float:
        '''Returns the optimal bid distance from the reserve price'''
        volatility = self.market.get_volatility()

        spread = (self.G * self.q * (volatility ** 2) * (self.T - self.t)) + (self.G ** -1) * np.log(1 + (self.G) * (self.k ** -1))

        return spread

    def calc_ask_quote(self) -> float:
        return self.reservation_price - self.calc_bid_distance()

    def calc_bid_quote(self) -> float:
        return self.reservation_price + self.calc_bid_distance()
    
    def update(self) -> None:
        self.reservation_price = self.calc_reserve_price()
        self.ask_quote = self.calc_ask_quote()
        self.bid_quote = self.calc_bid_quote()
        self.spread = 2 * self.calc_bid_distance()

        return None




