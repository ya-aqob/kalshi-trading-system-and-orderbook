from dataclasses import dataclass

class ExceptionalRiskError(Exception):
    '''
    Base class for any error that signals
    or could cause exceptional risk.
    ''' 

#
# Risk Limit Exceptions
#

class RiskLimitExceeded(ExceptionalRiskError):
    '''
    Base class for any signal that a risk limit
    has been exceeded.
    '''

class PositionLimitExceeded(RiskLimitExceeded):
    '''
    Exception raised when position limits are exceeded.
    '''

class BalanceLimitExceeded(RiskLimitExceeded):
    '''
    Exception raised when balance limits are exceeded.
    '''

#
# Data Accuracy Exceptions
#

class DataAccuracyRiskError(ExceptionalRiskError):
    '''
    Base class for any signal that data is exceptionally 
    inaccurate which could cause inaccurate trading or position
    management.
    '''

#
# Market Data Risk Management Exceptions
#

class MarketDataAccuracyRiskError(DataAccuracyRiskError):
    '''
    Base class for any signal that market data is exceptionally 
    stale or inaccurate.
    '''

class StaleOrderbookError(MarketDataAccuracyRiskError):
    '''
    Exception raised when the local orderbook is staler
    than risk tolerances permit.
    '''

#
# Portfolio Accuracy Exceptions
#

class PortfolioAccuracyRiskError(DataAccuracyRiskError):
    '''
    Base class for any signal that portfolio data is 
    exceptionally inaccurate.
    '''

@dataclass
class PositionMismatchError(PortfolioAccuracyRiskError):
    '''
    Exception raised when local position is inconsistent
    with remote position.
    '''
    remote_inventory: int
    local_inventory: int

class BalanceMismatchError(PortfolioAccuracyRiskError):
    '''
    Exception raised when local balance is inconsistent
    with remote balance.
    '''
    remote_balance: float
    local_balance: float

class OrderMismatchError(PortfolioAccuracyRiskError):
    '''
    Exception raised when local order tracking is inconsistent
    with remote orders.
    '''

#
# Execution Errors
#

class ExecutionError(ExceptionalRiskError):
    '''
    Base class for any order or execution failure.
    '''

@dataclass
class OrderRejection(ExecutionError):
    '''
    Exception raised when an order is rejected
    during placement.
    '''
    code: str
    message: str
    details: str
    service: str

class CancelFailure(ExecutionError):
    '''
    Exception raised when a cancellation request
    fails.
    '''

class MalformedFill(ExecutionError):
    '''
    Exception raised when a malformed fill is 
    received or a fill is invalid according
    to local state.
    '''