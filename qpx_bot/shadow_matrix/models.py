"""Immutable definitions and events for the Shadow Matrix research engine."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class FrozenObject:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class FrozenArray:
    items: tuple[Any, ...]


FrozenJSON = None | bool | int | float | str | FrozenObject | FrozenArray


def freeze_json(value: Any) -> FrozenJSON:
    """Convert a JSON-compatible value into a recursively immutable value."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite.")
        return value
    if isinstance(value, Mapping):
        return FrozenObject(tuple(
            (str(key), freeze_json(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ))
    if isinstance(value, (list, tuple)):
        return FrozenArray(tuple(freeze_json(item) for item in value))
    raise TypeError(f"Unsupported immutable JSON value: {type(value).__name__}")


def thaw_json(value: FrozenJSON) -> Any:
    if isinstance(value, FrozenObject):
        return {key: thaw_json(item) for key, item in value.items}
    if isinstance(value, FrozenArray):
        return [thaw_json(item) for item in value.items]
    return value


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ShadowRole(StrEnum):
    CONTROL = "CONTROL"
    RESEARCH = "RESEARCH"


@dataclass(frozen=True, slots=True)
class AcceleratorSnapshot:
    name: str
    enabled: bool
    algorithm_version: str
    configuration_version: str
    configuration_fingerprint: str
    parameters: FrozenJSON

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.algorithm_version.strip():
            raise ValueError("Accelerator name and algorithm version are required.")
        if not self.configuration_version.strip() or len(self.configuration_fingerprint) != 64:
            raise ValueError("Accelerator configuration identity is incomplete.")

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "algorithm_version": self.algorithm_version,
            "configuration_version": self.configuration_version,
            "configuration_fingerprint": self.configuration_fingerprint,
            "parameters": thaw_json(self.parameters),
        }


@dataclass(frozen=True, slots=True)
class ShadowConfiguration:
    shadow_id: str
    role: ShadowRole
    strategy_id: str
    strategy_reference_commit: str
    starting_state_profile: str
    starting_qdte_value: float
    starting_swing_cash: float
    starting_total_equity: float
    hard_notional_cap: float
    accelerators: tuple[AcceleratorSnapshot, ...]
    governance_identity: str

    def __post_init__(self) -> None:
        if not self.shadow_id.strip() or self.shadow_id != self.shadow_id.lower():
            raise ValueError("Shadow IDs must be non-empty lowercase identifiers.")
        if not self.strategy_id.strip() or len(self.strategy_reference_commit) != 40:
            raise ValueError("Strategy identity and full reference commit are required.")
        if not 0 < self.hard_notional_cap <= 0.90:
            raise ValueError("Hard notional cap must be in (0, 0.90].")
        if min(self.starting_qdte_value, self.starting_swing_cash) < 0:
            raise ValueError("Starting sleeve values cannot be negative.")
        if not math.isclose(
            self.starting_qdte_value + self.starting_swing_cash,
            self.starting_total_equity,
            abs_tol=1e-9,
        ):
            raise ValueError("Starting state components must equal total equity.")
        names = [item.name for item in self.accelerators]
        if len(names) != len(set(names)):
            raise ValueError("Accelerator names must be unique within a Shadow.")
        if self.shadow_id == "permanent_control":
            if self.role is not ShadowRole.CONTROL:
                raise ValueError("permanent_control must have CONTROL role.")
            if any(item.enabled for item in self.accelerators):
                raise ValueError("permanent_control must keep all accelerators disabled.")

    def as_dict(self) -> dict:
        return {
            "shadow_id": self.shadow_id,
            "role": self.role.value,
            "strategy_id": self.strategy_id,
            "strategy_reference_commit": self.strategy_reference_commit,
            "starting_state_profile": self.starting_state_profile,
            "starting_qdte_value": self.starting_qdte_value,
            "starting_swing_cash": self.starting_swing_cash,
            "starting_total_equity": self.starting_total_equity,
            "hard_notional_cap": self.hard_notional_cap,
            "accelerators": [item.as_dict() for item in self.accelerators],
            "governance_identity": self.governance_identity,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.as_dict())


@dataclass(frozen=True, slots=True)
class MarketEvent:
    sequence: int
    timestamp: datetime
    event_type: str
    payload: FrozenJSON
    event_id: str

    @classmethod
    def create(
        cls,
        *,
        sequence: int,
        timestamp: datetime,
        event_type: str,
        payload: Any,
    ) -> "MarketEvent":
        frozen = freeze_json(payload)
        canonical = {
            "sequence": sequence,
            "timestamp": timestamp.isoformat(),
            "event_type": event_type,
            "payload": thaw_json(frozen),
        }
        return cls(
            sequence=sequence,
            timestamp=timestamp,
            event_type=event_type,
            payload=frozen,
            event_id=canonical_hash(canonical),
        )

    def __post_init__(self) -> None:
        if self.sequence < 1 or self.timestamp.tzinfo is None:
            raise ValueError("Events need a positive sequence and timezone-aware timestamp.")
        if not self.event_type.strip() or len(self.event_id) != 64:
            raise ValueError("Event type and deterministic event ID are required.")
        if self.payload != freeze_json(thaw_json(self.payload)):
            raise ValueError("Market event payload must be recursively immutable.")
        expected_id = canonical_hash({
            "sequence": self.sequence,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type,
            "payload": thaw_json(self.payload),
        })
        if self.event_id != expected_id:
            raise ValueError("Market event ID does not match its immutable content.")


@dataclass(frozen=True, slots=True)
class PositionEntrySnapshot:
    shadow_configuration: ShadowConfiguration
    entry_event_id: str
    entry_event_sequence: int
    accelerator_decision_id: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    event_id: str
    event_sequence: int
    event_timestamp: datetime
    shadow_id: str
    shadow_configuration_fingerprint: str
    before_state_hash: str
    after_state_hash: str
    accelerator_identities: tuple[AcceleratorSnapshot, ...]
    status: str
    result_payload: FrozenJSON
    record_id: str
