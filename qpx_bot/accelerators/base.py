"""Immutable scalar decision objects shared by research accelerators."""

from __future__ import annotations

from dataclasses import dataclass
import math
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DynamicSizingContext:
    decision_timestamp: datetime
    symbol: str
    risk_budget_requested_shares: int
    base_requested_shares: int
    entry_price: float
    decision_time_total_equity: float
    available_swing_cash: float
    decision_time_active_portfolio_risk: float
    maximum_active_portfolio_risk: float
    risk_per_share: float
    existing_open_position_count: int
    maximum_open_positions: int
    existing_portfolio_exposure: float

    def __post_init__(self) -> None:
        if self.decision_timestamp.tzinfo is None:
            raise ValueError("Decision timestamp must be timezone-aware.")
        normalized = self.symbol.strip().upper()
        if not normalized:
            raise ValueError("Symbol cannot be empty.")
        object.__setattr__(self, "symbol", normalized)
        integer_fields = (
            "risk_budget_requested_shares",
            "base_requested_shares",
            "existing_open_position_count",
            "maximum_open_positions",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
        numeric_fields = (
            "entry_price",
            "decision_time_total_equity",
            "available_swing_cash",
            "decision_time_active_portfolio_risk",
            "maximum_active_portfolio_risk",
            "risk_per_share",
            "existing_portfolio_exposure",
        )
        for name in numeric_fields:
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError(f"{name} must be a non-negative scalar.")
        if self.entry_price <= 0 or self.decision_time_total_equity <= 0:
            raise ValueError("Entry price and total equity must be positive.")
        if self.maximum_active_portfolio_risk <= 0 or self.risk_per_share <= 0:
            raise ValueError("Risk limits must be positive.")

    @property
    def base_requested_notional(self) -> float:
        return self.base_requested_shares * self.entry_price

    @property
    def risk_utilization(self) -> float:
        return (
            self.decision_time_active_portfolio_risk
            / self.maximum_active_portfolio_risk
        )


@dataclass(frozen=True, slots=True)
class DynamicSizingDecision:
    accelerator_name: str
    accelerator_version: str
    configuration_version: str
    enabled: bool
    decision_timestamp: datetime
    symbol: str
    risk_budget_requested_shares: int
    base_requested_shares: int
    base_requested_notional: float
    entry_price: float
    decision_time_total_equity: float
    available_swing_cash: float
    decision_time_active_portfolio_risk: float
    maximum_active_portfolio_risk: float
    existing_open_position_count: int
    existing_portfolio_exposure: float
    risk_utilization: float
    sizing_multiplier: float
    final_requested_shares: int
    final_requested_notional: float
    reason_codes: tuple[str, ...]
    decision_id: str


@dataclass(frozen=True, slots=True)
class AcceleratorEntrySnapshot:
    accelerator_name: str
    accelerator_version: str
    configuration_version: str
    sizing_decision_id: str
    sizing_multiplier: float
    base_requested_shares: int
    final_shares: int
