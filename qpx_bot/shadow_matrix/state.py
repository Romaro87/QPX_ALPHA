"""Independent mutable portfolio state owned by one Shadow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from qpx_bot.shadow_matrix.models import PositionEntrySnapshot, ShadowConfiguration, canonical_hash


@dataclass(slots=True)
class ShadowPosition:
    symbol: str
    shares: int
    entry_price: float
    entry_snapshot: PositionEntrySnapshot
    management_state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ShadowState:
    configuration: ShadowConfiguration
    swing_cash: float
    qdte_state: dict[str, Any]
    tax_reserve: float = 0.0
    positions: dict[str, ShadowPosition] = field(default_factory=dict)
    pending_orders: dict[str, dict[str, Any]] = field(default_factory=dict)
    accelerator_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    performance_metrics: dict[str, float] = field(default_factory=dict)
    event_sequence: int = 0
    last_event_id: str | None = None
    checkpoint_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def initial(cls, configuration: ShadowConfiguration) -> "ShadowState":
        return cls(
            configuration=configuration,
            swing_cash=float(configuration.starting_swing_cash),
            qdte_state={
                "market_value": float(configuration.starting_qdte_value),
                "shares": None,
                "entitlements": {},
                "settlements": {},
            },
            accelerator_state={
                item.name: {
                    "enabled": item.enabled,
                    "configuration_version": item.configuration_version,
                    "decision_count": 0,
                }
                for item in configuration.accelerators
            },
            performance_metrics={
                "starting_total_equity": configuration.starting_total_equity,
                "event_count": 0.0,
            },
            checkpoint_state={"resume_authorized": False},
        )

    def canonical_dict(self) -> dict:
        return {
            "configuration_fingerprint": self.configuration.fingerprint,
            "swing_cash": self.swing_cash,
            "qdte_state": self.qdte_state,
            "tax_reserve": self.tax_reserve,
            "positions": {
                symbol: {
                    "shares": position.shares,
                    "entry_price": position.entry_price,
                    "entry_configuration_fingerprint": (
                        position.entry_snapshot.shadow_configuration.fingerprint
                    ),
                    "entry_event_id": position.entry_snapshot.entry_event_id,
                    "entry_event_sequence": position.entry_snapshot.entry_event_sequence,
                    "accelerator_decision_id": position.entry_snapshot.accelerator_decision_id,
                    "management_state": position.management_state,
                }
                for symbol, position in sorted(self.positions.items())
            },
            "pending_orders": self.pending_orders,
            "accelerator_state": self.accelerator_state,
            "performance_metrics": self.performance_metrics,
            "event_sequence": self.event_sequence,
            "last_event_id": self.last_event_id,
            "checkpoint_state": self.checkpoint_state,
        }

    @property
    def state_hash(self) -> str:
        return canonical_hash(self.canonical_dict())
