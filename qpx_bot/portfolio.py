"""Cash, positions, realized gains, taxes, and portfolio equity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
import math
from typing import Mapping

from qpx_bot.config import BotConfig
from qpx_bot.risk import PositionSize, sell_fill


def reconcile_net_realized_tax_reserve_balances(
    *,
    cash: float,
    tax_reserve_cash: float,
    realized_pnl: float,
    reserve_rate: float,
) -> tuple[float, float, float]:
    """Return cash, required reserve, and released excess for net realized P&L."""
    target = max(0.0, realized_pnl) * reserve_rate
    if target > tax_reserve_cash + 1e-8:
        raise RuntimeError(
            "Net-realized tax target exceeded the gross trade reserve."
        )
    released = max(0.0, tax_reserve_cash - target)
    return cash + released, target, released


@dataclass(slots=True)
class Position:
    symbol: str
    # Entries remain integer-sized.  A governed corporate action may later
    # create an exact fractional share quantity without a synthetic cash-out.
    shares: float
    entry_date: date
    entry_price: float
    entry_atr: float
    stop_price: float
    target_price: float
    highest_price: float

    # Exit/execution policy captured when this trade opened.
    # None means legacy state created before policy snapshots existed.
    entry_stop_atr_multiple: float | None = None
    entry_target_atr_multiple: float | None = None
    entry_trailing_activation_atr: float | None = None
    exit_slippage_rate: float | None = None
    entry_semantic_snapshot: dict | None = None

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares

    @property
    def active_risk(self) -> float:
        return (
            max(0.0, self.entry_price - self.stop_price)
            * self.shares
        )

    def initial_risk_per_share(self, config: BotConfig) -> float:
        """Return the immutable entry risk under the captured entry semantics."""
        semantics = self.entry_semantic_snapshot or {}
        if semantics.get("initial_stop_mode") == "ENTRY_PRICE_FRACTION":
            fraction = float(semantics["initial_stop_fraction"])
            return self.entry_price * fraction
        multiple = (
            self.entry_stop_atr_multiple
            if self.entry_stop_atr_multiple is not None
            else config.stop_atr_multiple
        )
        return self.entry_atr * multiple


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    symbol: str
    entry_date: date
    exit_date: date
    shares: float
    entry_price: float
    exit_price: float
    pnl: float
    tax_reserved: float
    reason: str
    result_r: float


@dataclass(slots=True)
class Portfolio:
    starting_cash: float
    preserve_identity: bool = False
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

    def _identity_key(self, value: str) -> str:
        """Return an exact provider identity or the legacy symbol key."""
        key = value.strip()
        if not key:
            raise ValueError("Position identity cannot be empty.")
        return key if self.preserve_identity else key.upper()

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

    def apply_split(
        self, *, symbol: str, share_multiplier: float,
    ) -> dict[str, float | str]:
        """Apply one value-preserving corporate-action split to an open position."""
        normalized_symbol = self._identity_key(symbol)
        if (
            isinstance(share_multiplier, bool)
            or not isinstance(share_multiplier, (int, float))
            or not math.isfinite(float(share_multiplier))
            or float(share_multiplier) <= 0
        ):
            raise ValueError("Split share multiplier must be finite and positive.")
        position = self.positions[normalized_symbol]
        multiplier = float(share_multiplier)
        inverse = 1.0 / multiplier
        before_value = position.shares * position.entry_price
        before_risk = position.active_risk
        before = {
            "shares": position.shares,
            "entry_price": position.entry_price,
            "entry_atr": position.entry_atr,
            "stop_price": position.stop_price,
            "target_price": position.target_price,
            "highest_price": position.highest_price,
            "cost_basis": before_value,
            "dollar_risk": before_risk,
        }
        position.shares *= multiplier
        position.entry_price *= inverse
        position.entry_atr *= inverse
        position.stop_price *= inverse
        position.target_price *= inverse
        position.highest_price *= inverse
        after_value = position.shares * position.entry_price
        after_risk = position.active_risk
        if not math.isclose(before_value, after_value, rel_tol=1e-12, abs_tol=1e-9):
            raise RuntimeError("Split transformation changed position cost basis.")
        if not math.isclose(before_risk, after_risk, rel_tol=1e-12, abs_tol=1e-9):
            raise RuntimeError("Split transformation changed position dollar risk.")
        return {
            "provider_asset_id": normalized_symbol,
            **{f"pre_{key}": value for key, value in before.items()},
            "post_shares": position.shares,
            "post_entry_price": position.entry_price,
            "post_entry_atr": position.entry_atr,
            "post_stop_price": position.stop_price,
            "post_target_price": position.target_price,
            "post_highest_price": position.highest_price,
            "post_cost_basis": after_value,
            "post_dollar_risk": after_risk,
        }

    def open_position(
        self,
        *,
        symbol: str,
        sizing: PositionSize,
        entry_date: date,
        entry_atr: float,
        config: BotConfig | None = None,
    ) -> Position:
        """Open one risk-sized position and deduct its full cost."""
        normalized_symbol = self._identity_key(symbol)

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
            entry_stop_atr_multiple=(
                config.stop_atr_multiple
                if config is not None
                else None
            ),
            entry_target_atr_multiple=(
                config.target_atr_multiple
                if config is not None
                else None
            ),
            entry_trailing_activation_atr=(
                config.trailing_activation_atr
                if config is not None
                else None
            ),
            exit_slippage_rate=(
                config.slippage_rate
                if config is not None
                else None
            ),
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
        normalized_symbol = self._identity_key(symbol)
        position = self.positions[normalized_symbol]

        if current_high <= 0 or current_atr <= 0:
            raise ValueError(
                "Current high and ATR must be positive."
            )

        position.highest_price = max(
            position.highest_price,
            current_high,
        )

        trailing_activation = (
            position.entry_trailing_activation_atr
            if position.entry_trailing_activation_atr
            is not None
            else config.trailing_activation_atr
        )

        trailing_stop_multiple = (
            position.entry_stop_atr_multiple
            if position.entry_stop_atr_multiple
            is not None
            else config.stop_atr_multiple
        )

        activation_price = (
            position.entry_price
            + (
                position.entry_atr
                * trailing_activation
            )
        )

        if position.highest_price >= activation_price:
            candidate = (
                position.highest_price
                - (
                    current_atr
                    * trailing_stop_multiple
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
        normalized_symbol = self._identity_key(symbol)
        position = self.positions.pop(normalized_symbol)
        exit_slippage_rate = (
            position.exit_slippage_rate
            if position.exit_slippage_rate
            is not None
            else config.slippage_rate
        )

        fill = sell_fill(
            exit_price,
            exit_slippage_rate,
        )
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

        initial_risk = position.initial_risk_per_share(config) * position.shares
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
