"""
QPX_ALPHA Portfolio Engine

The Portfolio class is the authoritative source of portfolio
state within QPX_ALPHA.
"""

from __future__ import annotations

from typing import Dict

from .models import CashAccount, DividendPayment, Position


class Portfolio:
    """
    Represents an investment portfolio.

    Responsibilities
    ----------------
    * Maintain cash balances
    * Maintain positions
    * Track dividends
    * Calculate portfolio value
    """

    def __init__(self) -> None:

        self.cash = CashAccount()

        self.positions: Dict[str, Position] = {}

        self.total_dividend_income = 0.0

    # --------------------------------------------------
    # Cash Management
    # --------------------------------------------------

    def deposit(self, amount: float) -> None:

        if amount <= 0:
            raise ValueError("Deposit must be positive.")

        self.cash.operating_cash += amount

    def withdraw(self, amount: float) -> None:

        if amount <= 0:
            raise ValueError("Withdrawal must be positive.")

        if amount > self.cash.operating_cash:
            raise ValueError("Insufficient cash.")

        self.cash.operating_cash -= amount

    # --------------------------------------------------
    # Position Management
    # --------------------------------------------------

    def add_position(self, position: Position) -> None:

        self.positions[position.symbol] = position

    def remove_position(self, symbol: str) -> None:

        self.positions.pop(symbol, None)

    def get_position(self, symbol: str) -> Position | None:

        return self.positions.get(symbol)

    # --------------------------------------------------
    # Market Updates
    # --------------------------------------------------

    def update_price(self, symbol: str, price: float) -> None:

        if symbol not in self.positions:
            raise KeyError(symbol)

        self.positions[symbol].current_price = price

    # --------------------------------------------------
    # Dividends
    # --------------------------------------------------

    def record_dividend(self, dividend: DividendPayment) -> None:

        self.cash.dividend_cash += dividend.amount

        self.total_dividend_income += dividend.amount

        if dividend.symbol in self.positions:
            self.positions[
                dividend.symbol
            ].dividend_income += dividend.amount

    # --------------------------------------------------
    # Portfolio Statistics
    # --------------------------------------------------

    @property
    def invested_value(self) -> float:

        return sum(
            position.market_value
            for position in self.positions.values()
        )

    @property
    def total_value(self) -> float:

        return self.cash.total_cash + self.invested_value

    @property
    def total_unrealized_gain(self) -> float:

        return sum(
            position.unrealized_gain
            for position in self.positions.values()
        )

    @property
    def buying_power(self) -> float:

        return self.cash.operating_cash