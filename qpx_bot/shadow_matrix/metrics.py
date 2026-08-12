"""Deterministic, checkpointable per-Shadow metrics foundation."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ShadowMetrics:
    starting_equity: float
    current_equity: float | None = None
    ending_equity: float | None = None
    total_return: float | None = None
    eod_peak_equity: float | None = None
    eod_maximum_drawdown: float | None = None
    intraday_peak_equity: float | None = None
    intraday_maximum_drawdown: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    profit_factor: float | None = None
    trades: int = 0
    wins: int = 0
    win_rate: float | None = None
    concentration: float | None = None
    largest_trade_loss: float | None = None
    overnight_gap_loss_count: int = 0
    overnight_gap_loss_total: float = 0.0
    largest_overnight_gap_loss: float | None = None
    cash_starvation_rejections: int = 0
    risk_rejections: int = 0
    capacity_deferrals: int = 0
    accelerator_interventions: int = 0
    divergence_from_permanent_control: int = 0
    pyramid_opportunities_considered: int = 0
    pyramid_additions_accepted: int = 0
    pyramid_additions_rejected: int = 0
    pyramid_shares_added: int = 0
    pyramid_notional_added: float = 0.0
    pyramid_rejection_reason_counts: dict[str, int] = field(default_factory=dict)
    pyramid_attributable_pnl: float = 0.0
    maximum_pyramid_additions_reached_count: int = 0
    event_count: int = 0
    lifetime_start_sequence: int | None = None
    rolling_observations: list[dict[str, Any]] = field(default_factory=list)

    def record_event(self, sequence: int) -> None:
        if self.lifetime_start_sequence is None:
            self.lifetime_start_sequence = sequence
        self.event_count += 1

    def record_equity(self, equity: float, *, phase: str) -> None:
        if not math.isfinite(equity) or equity < 0:
            raise ValueError("Equity must be finite and non-negative.")
        self.current_equity = equity
        self.ending_equity = equity
        self.total_return = equity / self.starting_equity - 1.0
        if phase == "EOD":
            self.eod_peak_equity = max(self.eod_peak_equity or equity, equity)
            drawdown = (
                (self.eod_peak_equity - equity) / self.eod_peak_equity
                if self.eod_peak_equity > 0 else 0.0
            )
            self.eod_maximum_drawdown = max(self.eod_maximum_drawdown or 0.0, drawdown)
        elif phase == "INTRADAY":
            self.intraday_peak_equity = max(self.intraday_peak_equity or equity, equity)
            drawdown = (
                (self.intraday_peak_equity - equity) / self.intraday_peak_equity
                if self.intraday_peak_equity > 0 else 0.0
            )
            self.intraday_maximum_drawdown = max(
                self.intraday_maximum_drawdown or 0.0, drawdown
            )
        else:
            raise ValueError("Equity phase must be EOD or INTRADAY.")

    def record_trade(self, pnl: float, *, overnight_gap: bool = False) -> None:
        if not math.isfinite(pnl):
            raise ValueError("Trade P&L must be finite.")
        self.trades += 1
        if pnl > 0:
            self.wins += 1
            self.gross_profit += pnl
        elif pnl < 0:
            self.gross_loss += abs(pnl)
            self.largest_trade_loss = min(self.largest_trade_loss or pnl, pnl)
            if overnight_gap:
                self.overnight_gap_loss_count += 1
                self.overnight_gap_loss_total += pnl
                self.largest_overnight_gap_loss = min(
                    self.largest_overnight_gap_loss or pnl, pnl
                )
        self.win_rate = self.wins / self.trades
        self.profit_factor = (
            self.gross_profit / self.gross_loss if self.gross_loss > 0 else None
        )

    def set_risk_adjusted(self, *, sharpe: float | None, sortino: float | None) -> None:
        for name, value in (("sharpe", sharpe), ("sortino", sortino)):
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite when populated.")
        self.sharpe = sharpe
        self.sortino = sortino

    def set_concentration(self, fraction: float) -> None:
        if not math.isfinite(fraction) or fraction < 0:
            raise ValueError("Concentration must be finite and non-negative.")
        self.concentration = fraction

    def record_rejection(self, category: str, count: int = 1) -> None:
        if count < 1:
            raise ValueError("Rejection count must be positive.")
        fields = {
            "CASH_STARVATION": "cash_starvation_rejections",
            "RISK": "risk_rejections",
            "CAPACITY": "capacity_deferrals",
        }
        if category not in fields:
            raise ValueError(f"Unsupported rejection category: {category}")
        field_name = fields[category]
        setattr(self, field_name, getattr(self, field_name) + count)

    def record_accelerator_intervention(self, count: int = 1) -> None:
        if count < 1:
            raise ValueError("Intervention count must be positive.")
        self.accelerator_interventions += count

    def record_pyramid_decision(self, *, accepted_shares: int, notional: float, reasons: tuple[str, ...]) -> None:
        self.pyramid_opportunities_considered += 1
        if accepted_shares > 0:
            self.pyramid_additions_accepted += 1
            self.pyramid_shares_added += accepted_shares
            self.pyramid_notional_added += notional
        else:
            self.pyramid_additions_rejected += 1
        for reason in reasons:
            if reason != "PYRAMID_ADDITION_ACCEPTED":
                self.pyramid_rejection_reason_counts[reason] = self.pyramid_rejection_reason_counts.get(reason, 0) + 1

    def record_pyramid_pnl(self, pnl: float) -> None:
        if not math.isfinite(pnl):
            raise ValueError("Pyramid P&L must be finite.")
        self.pyramid_attributable_pnl += pnl

    def record_divergence(self) -> None:
        self.divergence_from_permanent_control += 1

    def record_rolling_observation(self, *, sequence: int, values: dict[str, Any]) -> None:
        self.rolling_observations.append({"sequence": sequence, "values": values.copy()})

    def as_dict(self) -> dict[str, Any]:
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ShadowMetrics":
        expected = set(cls.__dataclass_fields__)
        if set(payload) != expected:
            raise ValueError("Shadow metrics schema differs from checkpoint schema.")
        return cls(**payload)

    def comparison_dict(self) -> dict[str, Any]:
        payload = self.as_dict()
        payload.pop("divergence_from_permanent_control")
        payload.pop("event_count")
        payload.pop("lifetime_start_sequence")
        payload.pop("rolling_observations")
        return payload
