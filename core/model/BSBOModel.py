from scipy.stats import norm
import math

class BSBOModel:
    '''
    Basic implementation of pricing for a Binary Option according to the
    Black-Scholes equation.
    '''
    
    def calc_option_price(self, spot: float, strike: float, t_terminal: float, implied_sig: float, risk_free_rt=0.0):
        '''
        Returns the price of an option with params based on Black-Scholes Binary Option.
        '''
        d2 = (math.log(spot / strike) + (risk_free_rt - 0.5 * implied_sig ** 2) * t_terminal) / (implied_sig * math.sqrt(t_terminal))
        return float(math.exp(-risk_free_rt * t_terminal) * norm.cdf(d2))

    