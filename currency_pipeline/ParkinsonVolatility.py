import numpy as np
from collections import deque
from .BinanceAPI import BinanceAPI
import time
import math

class VolatilityEstimator:

    def __init__(self, api: BinanceAPI):
        self.candles_5m = deque(maxlen=24)
        self.api = api
        self.timestamp = time.time()

    async def add_candle(self):
        new_candles = await self.api.get_klines("ETHUSDC", "5m")
    
        if not self.candles_5m:
            self.candles_5m.append(new_candles[-1])
        else:
            # Find candles newer than our last one
            last_time = self.candles_5m[-1][0]
            for candle in new_candles:
                if candle[0] > last_time:
                    self.candles_5m.append(candle)
        
        self.timestamp = time.time()
    
    async def init_candles(self):
        new_candles = await self.api.get_klines("ETHUSDC", "5m")
        self.candles_5m = deque(new_candles[-24:], maxlen=24)
        self.timestamp = time.time()

    def estimate_vol(self):
        candles = list(self.candles_5m)
        
        if len(candles) < 12:
            return 0.60
        
        return self._rogers(candles)
    
    def _estimate_vol_parkinson(self):
        candles = list(self.candles_5m)
        
        if len(candles) < 12:
            return 0.60
        
        short = self._parkinson(candles[-24:])
        
        long = self._parkinson(candles)
        
        vol = .7 * short + .3 * long

        return vol
        

    def _parkinson(self, candles):
        highs = np.array([float(c[2]) for c in candles])
        lows = np.array([float(c[3]) for c in candles])
        log_hl = np.log(highs / lows)
        var = np.mean(log_hl ** 2) / (4 * np.log(2))
        return np.sqrt(var * 12 * 24 * 365)

    def _rogers(self, candles):
        n = len(candles)
        if n == 0:
            return 0.60
        
        rs_sum = 0
        valid = 0
        
        for c in candles:
            o, h, l, close = float(c[1]), float(c[2]), float(c[3]), float(c[4])
            
            if h <= l or min(o, h, l, close) <= 0:
                continue
            
            rs_sum += math.log(h/close) * math.log(h/o) + math.log(l/close) * math.log(l/o)
            valid += 1
        
        if valid == 0:
            return 0.60
        
        variance = rs_sum / valid
        vol = math.sqrt(max(0, variance) * 105120)
        
        # Floor at reasonable minimum
        return max(0.10, vol)