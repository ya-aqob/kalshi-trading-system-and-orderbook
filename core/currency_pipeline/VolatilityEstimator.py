import numpy as np
from collections import deque
from .BinanceAPI import BinanceAPI
import time
import math
import logging

class VolatilityEstimator:
    '''
    Base class for volatility estimation calculators based on candlestick
    data on 5m intervals (2-hour rolling window).

    Suports Roger-Satchell and Parkinson realized volatility
    functions.

    Data freshness must be maintained by the runner/orchestrator.
    '''

    def __init__(self, api: BinanceAPI):
        self.candles_5m = deque(maxlen=24)
        self.api = api
        self.timestamp = time.time()

        self.periods_per_year = 12 * 24 * 365

    async def add_candle(self):
        '''
        Adds newest candle to the backing data struct.
        '''
        response = await self.api.get_klines("ETH_USD", "5m")
        new_candles = response.get("result", {}).get("data", [])
    
        if not self.candles_5m:
            self.candles_5m.append(new_candles[-1])
        else:
            last_time = self.candles_5m[-1]["t"]
            for candle in new_candles:
                if candle["t"] > last_time:
                    self.candles_5m.append(candle)
        
        self.timestamp = time.time()
    
    async def init_candles(self):
        '''
        Overwrites and re-populates backing data struct
        on response.
        '''
        response = await self.api.get_klines("ETH_USD", "5m")
        new_candles = response.get("result", {}).get("data", [])
        self.candles_5m = deque(new_candles[-24:], maxlen=24)
        self.timestamp = time.time()
    
    def parkinson_vol_estimate(self):
        '''
        Returns the realized volatility according to
        Parkinson's volatility Estimator weighted by
        time-to-present and annualized. 
        Logs warnings for low volatility.
        '''

        candles = list(self.candles_5m)
        
        if len(candles) < 12:
            raise RuntimeError("Insufficient price data for volatility estimation")
        
        short = self._parkinson(candles[-24:])
        
        long = self._parkinson(candles)
        
        vol = .7 * short + .3 * long

        if vol < .05:
            logging.warning(f"Low volatility estimate: {vol}")

        return vol
        
    def rogers_vol_estimate(self):
        '''
        Returns the realized volatility (annualized) 
        according to Rogers-Satchell volatility estimator. 
        '''
        candles = list(self.candles_5m)
        
        if len(candles) < 12:
            raise RuntimeError("Insufficient price data for volatility estimation")
        
        vol = self._rogers(candles)

        if vol < .05:
            logging.warning(f"Low volatility estimate: {vol}")

        return vol

    def _parkinson(self, candles):
        '''
        Returns annualized volatility according to Parkinson
        volatility estimator.
        '''
        highs = np.array([float(c["h"]) for c in candles])
        lows = np.array([float(c["l"]) for c in candles])
        log_hl = np.log(highs / lows)
        var = np.mean(log_hl ** 2) / (4 * np.log(2))
        vol = np.sqrt(var * self.periods_per_year)

        return vol

    def _rogers(self, candles):
        '''
        Returns annualized volatility according to Rogers-Satchell
        volatility estimator.
        '''        
        rs_sum = 0
        valid = 0
        
        for c in candles:
            o, h, l, close = float(c["o"]), float(c["h"]), float(c["l"]), float(c["c"])
            
            if h <= l or min(o, h, l, close) <= 0:
                continue
            
            rs_sum += math.log(h/close) * math.log(h/o) + math.log(l/close) * math.log(l/o)
            valid += 1
        
        if valid == 0:
            raise RuntimeError("Insufficient data for volatility estimnation")
        
        variance = rs_sum / valid
        vol = math.sqrt(max(0, variance) * self.periods_per_year)
        
        return vol