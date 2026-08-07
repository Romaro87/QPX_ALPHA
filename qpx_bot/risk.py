"""Position sizing, Kelly sizing, risk caps, and slippage."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Sequence

from qpx_bot.config import BotConfig


@dataclass(frozen=True, slots=True)
class PositionSize:
    """A fully specified, risk-controlled trade plan."""

    shares: int
    entry_fill: float
    stop_price: float
    target_price: float
    risk_per_share: float
    planned_risk: float
    risk_fraction: float
    blocked_reason: str | None = None

    @property
    def is_tradeable(self) -> bool:
        return self.shares > 0 and self.blocked_reason is None


def buy_fill(price: float, slippage_rate: float) -> float:
    """Apply adverse slippage to a buy."""
    if price <= 0:
        raise ValueError("Buy price must be positive.")
    if slippage_rate < 0:
        raise ValueError("Slippage cannot be negative.")
    return price * (1.0 + slippage_rate)


def sell_fill(price: float, slippage_rate: float) -> float:
    """Apply adverse slippage to a sell."""
    if price <= 0:
        raise ValueError("Sell price must be positive.")
    if slippage_rate < 0:
        raise ValueError("Slippage cannot be negative.")
    return price * (1.0 - slippage_rate)


def quarter_kelly_fraction(
    trade_results_r: Sequence[float],
    config: BotConfig,
) -> float:
    """
    Return the configured fraction of full Kelly.

    Results are expressed in R multiples. Until enough completed
    trades exist, the configured base risk is used.
    """
    config.validate()

    if len(trade_results_r) < config.minimum_kelly_trades:
        return config.risk_per_trade

    wins = [value for value in trade_results_r if value > 0]
    losses = [-value for value in trade_results_r if value < 0]

    if not wins or not losses:
        return config.risk_per_trade if wins else 0.0

    win_probability = len(wins) / len(trade_results_r)
    average_win = sum(wins) / len(wins)
    average_loss = sum(losses) / len(losses)
    payoff_ratio = average_win / average_loss

    if payoff_ratio <= 0:
        return 0.0

    full_kelly = (
        win_probability
        - ((1.0 - win_probability) / payoff_ratio)
    )
    fractional_kelly = max(0.0, full_kelly) * config.kelly_fraction

    return min(config.risk_per_trade, fractional_kelly)


def calculate_position_size(
    *,
    account_equity: float,
    available_cash: float,
    entry_price: float,
    atr: float,
    active_risk: float,
    config: BotConfig,
    trade_results_r: Sequence[float] = (),
) -> PositionSize:
    """Calculate an integer share quantity under every risk limit."""
    config.validate()

    numeric_values = {
        "account equity": account_equity,
        "available cash": available_cash,
        "entry price": entry_price,
        "ATR": atr,
        "active risk": active_risk,
    }

    for name, value in numeric_values.items():
        if value < 0:
            raise ValueError(f"{name.capitalize()} cannot be negative.")

    if account_equity == 0 or available_cash == 0:
        return PositionSize(
            shares=0,
            entry_fill=0.0,
            stop_price=0.0,
            target_price=0.0,
            risk_per_share=0.0,
            planned_risk=0.0,
            risk_fraction=0.0,
            blocked_reason="No available capital.",
        )

    if entry_price <= 0:
        raise ValueError("Entry price must be positive.")

    if atr <= 0:
        raise ValueError("ATR must be positive.")

    risk_fraction = quarter_kelly_fraction(
        trade_results_r,
        config,
    )

    if risk_fraction <= 0:
        return PositionSize(
            shares=0,
            entry_fill=0.0,
            stop_price=0.0,
            target_price=0.0,
            risk_per_share=0.0,
            planned_risk=0.0,
            risk_fraction=0.0,
            blocked_reason="Kelly sizing blocked the trade.",
        )

    maximum_total_risk = (
        account_equity
        * config.maximum_active_portfolio_risk
    )
    remaining_risk_capacity = max(
        0.0,
        maximum_total_risk - active_risk,
    )

    if remaining_risk_capacity <= 0:
        return PositionSize(
            shares=0,
            entry_fill=0.0,
            stop_price=0.0,
            target_price=0.0,
            risk_per_share=0.0,
            planned_risk=0.0,
            risk_fraction=risk_fraction,
            blocked_reason=(
                f"The {config.maximum_active_portfolio_risk:.0%} "
                "active-risk cap is full."
            ),
        )

    entry_fill = buy_fill(
        entry_price,
        config.slippage_rate,
    )
    risk_per_share = atr * config.stop_atr_multiple
    requested_risk = account_equity * risk_fraction
    risk_budget = min(
        requested_risk,
        remaining_risk_capacity,
    )

    shares_by_risk = floor(risk_budget / risk_per_share)
    shares_by_cash = floor(available_cash / entry_fill)
    shares = max(0, min(shares_by_risk, shares_by_cash))

    if shares == 0:
        return PositionSize(
            shares=0,
            entry_fill=entry_fill,
            stop_price=entry_fill - risk_per_share,
            target_price=(
                entry_fill
                + (atr * config.target_atr_multiple)
            ),
            risk_per_share=risk_per_share,
            planned_risk=0.0,
            risk_fraction=risk_fraction,
            blocked_reason=(
                "Risk budget or cash is too small for one share."
            ),
        )

    return PositionSize(
        shares=shares,
        entry_fill=entry_fill,
        stop_price=entry_fill - risk_per_share,
        target_price=(
            entry_fill
            + (atr * config.target_atr_multiple)
        ),
        risk_per_share=risk_per_share,
        planned_risk=shares * risk_per_share,
        risk_fraction=risk_fraction,
    )
