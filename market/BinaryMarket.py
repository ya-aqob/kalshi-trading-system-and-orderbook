import typing
from collections import deque
from decimal import Decimal
from .OrderBook import OneSidedOrderBook
from session.Session import Session
from session.request import send_request
import numpy as np
import logging

class BinaryMarket:
    
    session: Session                         # Authentication session for API requests

    ticker: str                              # The ticker of the BinaryPrediction Market
    base_url: str                            # The base url of the market
    path: str                                # The path of the market
    
    price_history: deque                     # Stores last 60 seconds of prices at given polling rate
    last_orderbook: OneSidedOrderBook | None # The most recent orderbook associated with the market
    polling_rate: int                        # Updates per second for orderbook

    last_mid_price: float | None             # The most recently calculated mid price of the BinaryMarket
    volatility: float | None                 # Volatility over previous 60 seconds of market history


    def __init__(self, session: Session, polling_rate: int, ticker: str, base_url: str, path: str):
        self.ticker = ticker
        self.base_url = base_url
        self.path = path
        self.session = session

        self.polling_rate = polling_rate
        self.price_history = deque(maxlen=(polling_rate)*60)
        self.last_orderbook = None
        self.last_mid_price = None

        self.volatility = None

    def update(self) -> None:
        '''
        Fetches and constructs new orderbook, calculates price, updates price history
        and calculates and updates volatility.
        '''
        orderbook = self.constructOrderbook()

        mid_price = orderbook.volume_weight_mid_price
        self.update_mid_price(mid_price)
        self.update_price_history(mid_price)
        
        volatility = self.calculate_volatility()
        
        if volatility:
            self.update_volatility(volatility)
        
        return None

    def constructOrderbook(self) -> OneSidedOrderBook:
        '''Fetches orderbook and constructs OneSidedOrderBook obj'''
        orderbook_json = self.fetch_orderbook()["orderbook"]
        
        yes_book = orderbook_json["yes_dollars"]
        no_book = orderbook_json["no_dollars"]

        best_bid, bid_volume = yes_book[-1]
        no_bid, ask_volume = no_book[-1]
        best_ask = 1 - float(no_bid)
        best_bid = float(best_bid)

        orderbook = OneSidedOrderBook(best_bid=best_bid, bid_size = bid_volume, 
                                      best_ask=best_ask, ask_size=ask_volume)
        
        return orderbook

    def fetch_orderbook(self) -> dict:
        '''Returns JSON object of response from orderbook endpoint 
           of given ticker at base_url/path/ticker'''
        
        response = send_request(
                        session=self.session,
                        method="GET",
                        base_url=self.base_url,
                        path=f"{self.path}/{self.ticker}/orderbook"
                        ).json()

        return response
    
    def calculate_volatility(self) -> float | None:
        '''
        Calculates volatility by sampling previous prices at 1 second intervals over a 
        60 second window. Utilizes the standard deviation formula.

        Returns:
            None if price history is shorter than 60 seconds
            calculated volatility otherwise
        '''

        if not self.is_ready():
            return None
        
        subsampled_prices = list(self.price_history)[::int(self.polling_rate)]
        
        returns = np.diff(subsampled_prices)

        volatility = np.std(returns, ddof=1)

        return float(volatility)

    def update_mid_price(self, price: float) -> None:
        '''Updates last_mid_price to price'''
        self.last_mid_price = price
    
    def update_price_history(self, price: float) -> None:
        '''Adds price to price_history'''
        self.price_history.append(price)

    def update_volatility(self, volatility: float) -> None:
        self.volatility = volatility

    def get_volatility(self) -> float | None:
        return self.volatility
    
    def get_mid_price(self) -> float | None:
        return self.last_mid_price

    def is_ready(self) -> bool:
        '''
        Determines whether 
        Returns True iff price_history has at least 60 seconds of history
        Else False
        '''
        return len(self.price_history) >= self.polling_rate * 60