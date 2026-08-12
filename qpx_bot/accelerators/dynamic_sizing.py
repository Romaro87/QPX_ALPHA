"""Deterministic, reduction-only Dynamic Sizing V1 accelerator."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from qpx_bot.accelerators.base import DynamicSizingContext, DynamicSizingDecision


ACCELERATOR_NAME = "dynamic_sizing"


@dataclass(frozen=True, slots=True)
class RiskTier:
    upper_bound: float | None
    multiplier: float

    def validate(self) -> None:
        if self.upper_bound is not None:
            if type(self.upper_bound) not in (int, float):
                raise ValueError("Risk-tier thresholds must be numeric.")
            if not 0 < float(self.upper_bound) <= 1:
                raise ValueError("Risk-tier thresholds must be in (0, 1].")
        if type(self.multiplier) not in (int, float):
            raise ValueError("Sizing multipliers must be numeric.")
        if not 0 < float(self.multiplier) <= 1:
            raise ValueError("Sizing multipliers must be in (0, 1].")


@dataclass(frozen=True, slots=True)
class DynamicSizingConfig:
    enabled: bool
    accelerator_version: str
    configuration_version: str
    risk_tiers: tuple[RiskTier, ...]
    maximum_position_notional_fraction: float

    def validate(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be boolean.")
        if not self.accelerator_version.strip() or not self.configuration_version.strip():
            raise ValueError("Accelerator and configuration versions are required.")
        if not self.risk_tiers:
            raise ValueError("At least one risk tier is required.")
        for tier in self.risk_tiers:
            tier.validate()
        finite = [tier.upper_bound for tier in self.risk_tiers[:-1]]
        if self.risk_tiers[-1].upper_bound is not None:
            raise ValueError("The final risk tier must be open-ended.")
        if any(value is None for value in finite):
            raise ValueError("Only the final risk tier may be open-ended.")
        if list(finite) != sorted(set(finite)):
            raise ValueError("Risk-tier thresholds must be strictly increasing.")
        if type(self.maximum_position_notional_fraction) not in (int, float):
            raise ValueError("Maximum notional fraction must be numeric.")
        if not 0 < self.maximum_position_notional_fraction <= 0.90:
            raise ValueError("Maximum notional fraction must be in (0, 0.90].")

    @property
    def fingerprint(self) -> str:
        payload = {
            "enabled": self.enabled,
            "accelerator_version": self.accelerator_version,
            "configuration_version": self.configuration_version,
            "risk_tiers": [asdict(tier) for tier in self.risk_tiers],
            "maximum_position_notional_fraction": self.maximum_position_notional_fraction,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def load_dynamic_sizing_config(path: Path, *, enabled: bool | None = None) -> DynamicSizingConfig:
    payload = json.loads(path.read_text(encoding="utf-8"))
    tiers = tuple(
        RiskTier(item.get("upper_bound"), item["multiplier"])
        for item in payload["risk_tiers"]
    )
    config = DynamicSizingConfig(
        enabled=payload["enabled"] if enabled is None else enabled,
        accelerator_version=payload["accelerator_version"],
        configuration_version=payload["configuration_version"],
        risk_tiers=tiers,
        maximum_position_notional_fraction=payload["maximum_position_notional_fraction"],
    )
    config.validate()
    return config


class DynamicSizingV1:
    def __init__(self, config: DynamicSizingConfig):
        config.validate()
        self.config = config

    def _multiplier(self, utilization: float) -> float:
        if not math.isfinite(utilization) or utilization < 0:
            raise ValueError("Risk utilization must be finite and non-negative.")
        for tier in self.config.risk_tiers:
            if tier.upper_bound is None or utilization < tier.upper_bound:
                return tier.multiplier
        raise RuntimeError("Validated risk tiers did not cover utilization.")

    def decide(self, context: DynamicSizingContext) -> DynamicSizingDecision:
        utilization = context.risk_utilization
        multiplier = 1.0 if not self.config.enabled else self._multiplier(utilization)
        position_slots = context.maximum_open_positions - context.existing_open_position_count
        if not self.config.enabled:
            final_shares = context.base_requested_shares
        else:
            adjusted = math.floor(context.base_requested_shares * multiplier)
            hard_cap = math.floor(
                context.decision_time_total_equity
                * self.config.maximum_position_notional_fraction
                / context.entry_price
            )
            cash_cap = math.floor(context.available_swing_cash / context.entry_price)
            remaining_risk = max(
                0.0,
                context.maximum_active_portfolio_risk
                - context.decision_time_active_portfolio_risk,
            )
            risk_cap = math.floor(remaining_risk / context.risk_per_share)
            final_shares = min(
                context.base_requested_shares, adjusted, hard_cap, cash_cap, risk_cap
            )
        reasons: list[str] = []
        if not self.config.enabled:
            reasons.append("ACCELERATOR_DISABLED_NO_OP")
        elif multiplier < 1:
            reasons.append("REDUCED_BY_ACTIVE_RISK_TIER")
        else:
            reasons.append("UNCHANGED_LOW_ACTIVE_RISK")
        if self.config.enabled and position_slots <= 0:
            final_shares = 0
            reasons.append("BLOCKED_POSITION_CAPACITY")
        if final_shares < 1:
            final_shares = 0
            reasons.append("BLOCKED_BELOW_ONE_SHARE")
        canonical = {
            "accelerator_name": ACCELERATOR_NAME,
            "accelerator_version": self.config.accelerator_version,
            "configuration_version": self.config.configuration_version,
            "configuration_fingerprint": self.config.fingerprint,
            "enabled": self.config.enabled,
            "context": {
                key: (value.isoformat() if key == "decision_timestamp" else value)
                for key, value in asdict(context).items()
            },
            "risk_utilization": utilization,
            "sizing_multiplier": multiplier,
            "final_requested_shares": final_shares,
            "reason_codes": reasons,
        }
        decision_id = hashlib.sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return DynamicSizingDecision(
            accelerator_name=ACCELERATOR_NAME,
            accelerator_version=self.config.accelerator_version,
            configuration_version=self.config.configuration_version,
            enabled=self.config.enabled,
            decision_timestamp=context.decision_timestamp,
            symbol=context.symbol,
            risk_budget_requested_shares=context.risk_budget_requested_shares,
            base_requested_shares=context.base_requested_shares,
            base_requested_notional=context.base_requested_notional,
            entry_price=context.entry_price,
            decision_time_total_equity=context.decision_time_total_equity,
            available_swing_cash=context.available_swing_cash,
            decision_time_active_portfolio_risk=context.decision_time_active_portfolio_risk,
            maximum_active_portfolio_risk=context.maximum_active_portfolio_risk,
            existing_open_position_count=context.existing_open_position_count,
            existing_portfolio_exposure=context.existing_portfolio_exposure,
            risk_utilization=utilization,
            sizing_multiplier=multiplier,
            final_requested_shares=final_shares,
            final_requested_notional=final_shares * context.entry_price,
            reason_codes=tuple(reasons),
            decision_id=decision_id,
        )
