from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Union

_PRECISION = Decimal('0.0001')
_MIN = Decimal('0.01')
_MAX = Decimal('0.99')
_ONE = Decimal('1')
_ZERO = Decimal('0')


class FixedPointDollars(Decimal):
    """
    Fixed-point dollar amount with 4 decimal precision (0.xxxx).
    Compatible with subpenny pricing on Kalshi.
    """
    
    def __new__(cls, value: Union[float, str, Decimal, 'FixedPointDollars'] = 0):
        if isinstance(value, FixedPointDollars):
            return value
        quantized = Decimal(str(value)).quantize(_PRECISION, rounding=ROUND_DOWN)
        return super().__new__(cls, quantized)

    def __add__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__add__(self, Decimal(str(other))))

    def __radd__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__add__(Decimal(str(other)), self))

    def __sub__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__sub__(self, Decimal(str(other))))

    def __rsub__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__sub__(Decimal(str(other)), self))

    def __mul__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__mul__(self, Decimal(str(other))))

    def __rmul__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__mul__(Decimal(str(other)), self))

    def __truediv__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__truediv__(self, Decimal(str(other))))

    def __rtruediv__(self, other) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__truediv__(Decimal(str(other)), self))

    def __neg__(self) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__neg__(self))

    def __abs__(self) -> 'FixedPointDollars':
        return FixedPointDollars(Decimal.__abs__(self))

    def __repr__(self) -> str:
        return f"FixedPointDollars('{Decimal.__str__(self)}')"

    def __str__(self) -> str:
        return Decimal.__str__(self)

    def __hash__(self) -> int:
        return Decimal.__hash__(self)

    @property
    def complement(self) -> 'FixedPointDollars':
        """No-side complement (1 - price)."""
        return FixedPointDollars(_ONE - self)

    @property
    def is_valid(self) -> bool:
        """Check if within valid price range [0.01, 0.99]."""
        return _MIN <= self <= _MAX

    def clamped(self) -> 'FixedPointDollars':
        """Return value clamped to valid range."""
        return FixedPointDollars(max(_MIN, min(_MAX, self)))

    def to_float(self) -> float:
        """Convert to float for API calls."""
        return float(self)

ZERO = FixedPointDollars('0')
ONE = FixedPointDollars('1')
MIN_PRICE = FixedPointDollars('0.01')
MAX_PRICE = FixedPointDollars('0.99')
MID_DEFAULT = FixedPointDollars('0.50')