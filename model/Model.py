from market.OrderBookSnapshot import OrderBookSnapshot
import numpy as np
import time
from asyncio import Queue
from market.FixedPointDollars import FixedPointDollars

class Model:
    '''
    Implementation of Avellaneda-Stoikov Model on static
    data
    '''
    ### Model parameters
    T: float # Terminal time of trading session
    G: float # Risk-aversion parameter

    ### Model variables
    k: float # Decay parameter for fill-rate w.r.t. spread size
    t: float # Current time

    def __init__(self, k: float, G: float, runtime: float):
        # Tunable params
        self.k = k
        self.G = G
        
        # Time horizon
        self.T = 1.0
        self.t = 0

        # Time normalization params
        self.start_time = time.time()
        self.run_time = runtime
    
    def generate_quotes(self, snapshot: OrderBookSnapshot, inventory: int,  volatility: float):
        self.t = self.normalize_time(snapshot.timestamp)
        reserve_price = self.calc_reserve_price(snapshot, inventory, volatility)
        ask_quote = self.calc_ask_quote(reserve_price)
        bid_quote = self.calc_bid_quote(reserve_price)

        return bid_quote, ask_quote

    def calc_reserve_price(self, snapshot: OrderBookSnapshot, inventory: int, volatility: float) -> FixedPointDollars:
        '''Calculates the reserve price of the market'''
        mid_price = snapshot.mid_price
        reserve_price = mid_price - (inventory * self.G * (volatility ** 2)) * (self.T - self.t)

        return FixedPointDollars(reserve_price)

    def normalize_time(self, timestamp):
        return (timestamp - self.start_time) / self.run_time

    def calc_bid_distance(self) -> FixedPointDollars:
        '''Returns the optimal bid distance from the reserve price'''

        distance = (self.G ** -1) * np.log(1 + (self.G) * (self.k ** -1))

        return FixedPointDollars(distance)

    def calc_ask_quote(self, reservation_price: FixedPointDollars) -> FixedPointDollars:
        return FixedPointDollars((reservation_price + self.calc_bid_distance())).clamped()

    def calc_bid_quote(self, reservation_price: FixedPointDollars) -> FixedPointDollars:
        return FixedPointDollars((reservation_price - self.calc_bid_distance())).clamped()





