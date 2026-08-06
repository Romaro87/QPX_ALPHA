"""Cash, positions, realized gains, taxes, and portfolio equity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Mapping

from qpx_bot.config import BotConfig
from qpx_bot.risk import PositionSize, sell_fill


@dataclass(slots=True)
class Position:
    symbol: str
    shares: int
    entry_date: date
    entry_price: float
    entry_atr: float
    stop_price: float
    target_price: float
    highest_price: float

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares

    @property
    def active_risk(self) -> float:
        return (
            max(0.0, self.entry_price - self.stop_price)
            * self.shares
        )


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: str
    entry_date: date
    exit_date: date
    shares: int
    entry_price: float
    exit_price: float
    pnl: float
    tax_reserved: float
    reason: str
    result_r: float


@dataclass(slots=True)
class Portfolio:
    starting_cash: float
    cash: float = field(init=False)
    tax_reserve_cash: float = 0.0
    total_contributions: float = field(init=False)
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    closed_trades: list[ClosedTrade] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.starting_cash < 0:
            raise ValueError("Starting cash cannot be negative.")
        self.cash = float(self.starting_cash)
        self.total_contributions = float(self.starting_cash)

    def deposit(self, amount: float) -> None:
        """Add external capital to the investable cash balance."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")
        self.cash += amount
        self.total_contributions += amount

    def active_risk(self) -> float:
        return sum(
            position.active_risk
            for position in self.positions.values()
        )

    def open_position(
        self,
        *,
        symbol: str,
        sizing: PositionSize,
        entry_date: date,
        entry_atr: float,
    ) -> Position:
        """Open one risk-sized position and deduct its full cost."""
        normalized_symbol = symbol.strip().upper()

        if not normalized_symbol:
            raise ValueError("Symbol cannot be empty.")

        if normalized_symbol in self.positions:
            raise ValueError(
                f"A position in {normalized_symbol} is already open."
            )

        if not sizing.is_tradeable:
            raise ValueError(
                sizing.blocked_reason
                or "The position size is not tradeable."
            )

        total_cost = sizing.entry_fill * sizing.shares

        if total_cost > self.cash + 1e-9:
            raise ValueError("Insufficient cash for this position.")

        position = Position(
            symbol=normalized_symbol,
            shares=sizing.shares,
            entry_date=entry_date,
            entry_price=sizing.entry_fill,
            entry_atr=entry_atr,
            stop_price=sizing.stop_price,
            target_price=sizing.target_price,
            highest_price=sizing.entry_fill,
        )

        self.cash -= total_cost
        self.positions[normalized_symbol] = position
        return position

    def update_trailing_stop(
        self,
        *,
        symbol: str,
        current_high: float,
        current_atr: float,
        config: BotConfig,
    ) -> float:
        """Activate and raise the ATR trailing stop; never lower it."""
        normalized_symbol = symbol.strip().upper()
        position = self.positions[normalized_symbol]

        if current_high <= 0 or current_atr <= 0:
            raise ValueError(
                "Current high and ATR must be positive."
            )

        position.highest_price = max(
            position.highest_price,
            current_high,
        )

        activation_price = (
            position.entry_price
            + (
                position.entry_atr
                * config.trailing_activation_atr
            )
        )

        if position.highest_price >= activation_price:
            candidate = (
                position.highest_price
                - (
                    current_atr
                    * config.stop_atr_multiple
                )
            )
            position.stop_price = max(
                position.stop_price,
                candidate,
            )

        return position.stop_price

    def close_position(
        self,
        *,
        symbol: str,
        exit_price: float,
        exit_date: date,
        reason: str,
        config: BotConfig,
    ) -> ClosedTrade:
        """Close a position, apply slippage, and reserve gain taxes."""
        normalized_symbol = symbol.strip().upper()
        position = self.positions.pop(normalized_symbol)
        fill = sell_fill(exit_price, config.slippage_rate)
        proceeds = fill * position.shares
        pnl = (
            (fill - position.entry_price)
            * position.shares
        )
        tax_reserved = (
            max(0.0, pnl)
            * config.annual_tax_reserve_rate
        )

        self.cash += proceeds - tax_reserved
        self.tax_reserve_cash += tax_reserved
        self.realized_pnl += pnl

        initial_risk = (
            position.entry_atr
            * config.stop_atr_multiple
            * position.shares
        )
        result_r = (
            pnl / initial_risk
            if initial_risk > 0
            else 0.0
        )

        trade = ClosedTrade(
            symbol=normalized_symbol,
            entry_date=position.entry_date,
            exit_date=exit_date,
            shares=position.shares,
            entry_price=position.entry_price,
            exit_price=fill,
            pnl=pnl,
            tax_reserved=tax_reserved,
            reason=reason,
            result_r=result_r,
        )
        self.closed_trades.append(trade)
        return trade

    def market_value(
        self,
        prices: Mapping[str, float],
    ) -> float:
        value = 0.0

        for symbol, position in self.positions.items():
            if symbol not in prices:
                raise KeyError(
                    f"Missing market price for {symbol}."
                )
            value += prices[symbol] * position.shares

        return value

    def equity(
        self,
        prices: Mapping[str, float],
    ) -> float:
        """Return investable cash, tax reserve, and open positions."""
        return (
            self.cash
            + self.tax_reserve_cash
            + self.market_value(prices)
        )


def contribution_allocation(
    elapsed_years: int,
    config: BotConfig,
) -> tuple[float, float]:
    """Return dividend and swing allocation weights."""
    if elapsed_years < 0:
        raise ValueError("Elapsed years cannot be negative.")

    if elapsed_years < 2:
        return (
            config.dividend_allocation_years_1_2,
            config.swing_allocation_years_1_2,
        )

    return (
        config.dividend_allocation_later,
        config.swing_allocation_later,
    )
