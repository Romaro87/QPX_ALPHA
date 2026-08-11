"""
QPX_ALPHA Portfolio Domain Models

These classes represent the core financial objects used
throughout the platform.

They intentionally contain minimal business logic.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradeSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(slots=True)
class Position:
    """
    Represents a single security held by the portfolio.
    """

    symbol: str
    quantity: float
    average_cost: float

    current_price: float = 0.0
    dividend_income: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.average_cost

    @property
    def unrealized_gain(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_gain_percent(self) -> float:

        if self.cost_basis == 0:
            return 0.0

        return (self.unrealized_gain / self.cost_basis) * 100.0


@dataclass(slots=True)
class CashAccount:
    """
    Tracks all cash balances.
    """

    operating_cash: float = 0.0
    dividend_cash: float = 0.0
    tax_reserve_cash: float = 0.0

    @property
    def total_cash(self) -> float:
        return (
            self.operating_cash
            + self.dividend_cash
            + self.tax_reserve_cash
        )


@dataclass(slots=True)
class Trade:
    """
    Represents an executed trade.
    """

    symbol: str
    quantity: float
    price: float

    side: TradeSide

    timestamp: datetime = field(default_factory=datetime.utcnow)

    commission: float = 0.0

    fees: float = 0.0

    notes: Optional[str] = None

    @property
    def gross_value(self) -> float:
        return self.quantity * self.price

    @property
    def total_cost(self) -> float:
        return self.gross_value + self.commission + self.fees


@dataclass(slots=True)
class DividendPayment:
    """
    Represents one dividend payment.
    """

    symbol: str

    amount: float

    payment_date: datetime

    shares_owned: float

    dividend_per_share: float


@dataclass(slots=True)
class PortfolioSnapshot:
    """
    Historical portfolio state.
    """

    timestamp: datetime

    total_value: float

    total_cash: float

    invested_value: float

    unrealized_gain: float

    realized_gain: float

    dividend_income: float