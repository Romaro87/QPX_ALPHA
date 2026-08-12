"""Immutable definitions, events, and audit records for Shadow Matrix V1."""

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
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
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

    @classmethod
    def from_dict(cls, payload: dict) -> "AcceleratorSnapshot":
        return cls(
            name=payload["name"], enabled=payload["enabled"],
            algorithm_version=payload["algorithm_version"],
            configuration_version=payload["configuration_version"],
            configuration_fingerprint=payload["configuration_fingerprint"],
            parameters=freeze_json(payload["parameters"]),
        )


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
            self.starting_total_equity, abs_tol=1e-9,
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
            "shadow_id": self.shadow_id, "role": self.role.value,
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

    @classmethod
    def from_dict(cls, payload: dict) -> "ShadowConfiguration":
        return cls(
            shadow_id=payload["shadow_id"], role=ShadowRole(payload["role"]),
            strategy_id=payload["strategy_id"],
            strategy_reference_commit=payload["strategy_reference_commit"],
            starting_state_profile=payload["starting_state_profile"],
            starting_qdte_value=payload["starting_qdte_value"],
            starting_swing_cash=payload["starting_swing_cash"],
            starting_total_equity=payload["starting_total_equity"],
            hard_notional_cap=payload["hard_notional_cap"],
            accelerators=tuple(
                AcceleratorSnapshot.from_dict(item) for item in payload["accelerators"]
            ),
            governance_identity=payload["governance_identity"],
        )

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
    def create(cls, *, sequence: int, timestamp: datetime, event_type: str, payload: Any) -> "MarketEvent":
        frozen = freeze_json(payload)
        canonical = {
            "sequence": sequence, "timestamp": timestamp.isoformat(),
            "event_type": event_type, "payload": thaw_json(frozen),
        }
        return cls(sequence, timestamp, event_type, frozen, canonical_hash(canonical))

    def __post_init__(self) -> None:
        if self.sequence < 1 or self.timestamp.tzinfo is None:
            raise ValueError("Events need a positive sequence and timezone-aware timestamp.")
        if not self.event_type.strip() or len(self.event_id) != 64:
            raise ValueError("Event type and deterministic event ID are required.")
        if self.payload != freeze_json(thaw_json(self.payload)):
            raise ValueError("Market event payload must be recursively immutable.")
        expected = canonical_hash({
            "sequence": self.sequence, "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type, "payload": thaw_json(self.payload),
        })
        if self.event_id != expected:
            raise ValueError("Market event ID does not match its immutable content.")


@dataclass(frozen=True, slots=True)
class PositionEntrySnapshot:
    shadow_configuration: ShadowConfiguration
    entry_event_id: str
    entry_event_sequence: int
    accelerator_decision_id: str | None = None

    def as_dict(self) -> dict:
        return {
            "shadow_configuration": self.shadow_configuration.as_dict(),
            "entry_event_id": self.entry_event_id,
            "entry_event_sequence": self.entry_event_sequence,
            "accelerator_decision_id": self.accelerator_decision_id,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PositionEntrySnapshot":
        return cls(
            ShadowConfiguration.from_dict(payload["shadow_configuration"]),
            payload["entry_event_id"], payload["entry_event_sequence"],
            payload["accelerator_decision_id"],
        )


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

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id, "event_sequence": self.event_sequence,
            "event_timestamp": self.event_timestamp.isoformat(),
            "shadow_id": self.shadow_id,
            "shadow_configuration_fingerprint": self.shadow_configuration_fingerprint,
            "before_state_hash": self.before_state_hash,
            "after_state_hash": self.after_state_hash,
            "accelerator_identities": [item.as_dict() for item in self.accelerator_identities],
            "status": self.status, "result_payload": thaw_json(self.result_payload),
            "record_id": self.record_id,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "DecisionRecord":
        return cls(
            payload["event_id"], payload["event_sequence"],
            datetime.fromisoformat(payload["event_timestamp"]), payload["shadow_id"],
            payload["shadow_configuration_fingerprint"], payload["before_state_hash"],
            payload["after_state_hash"],
            tuple(AcceleratorSnapshot.from_dict(item) for item in payload["accelerator_identities"]),
            payload["status"], freeze_json(payload["result_payload"]), payload["record_id"],
        )


@dataclass(frozen=True, slots=True)
class DivergenceRecord:
    event_id: str
    event_sequence: int
    event_timestamp: datetime
    control_shadow_id: str
    control_configuration_fingerprint: str
    comparison_shadow_id: str
    comparison_configuration_fingerprint: str
    control_status: str
    comparison_status: str
    control_before_state_hash: str
    control_after_state_hash: str
    comparison_before_state_hash: str
    comparison_after_state_hash: str
    divergence_occurred: bool
    reasons: tuple[str, ...]
    details: FrozenJSON
    divergence_id: str

    def as_dict(self) -> dict:
        return {
            "event_id": self.event_id, "event_sequence": self.event_sequence,
            "event_timestamp": self.event_timestamp.isoformat(),
            "control_shadow_id": self.control_shadow_id,
            "control_configuration_fingerprint": self.control_configuration_fingerprint,
            "comparison_shadow_id": self.comparison_shadow_id,
            "comparison_configuration_fingerprint": self.comparison_configuration_fingerprint,
            "control_status": self.control_status, "comparison_status": self.comparison_status,
            "control_before_state_hash": self.control_before_state_hash,
            "control_after_state_hash": self.control_after_state_hash,
            "comparison_before_state_hash": self.comparison_before_state_hash,
            "comparison_after_state_hash": self.comparison_after_state_hash,
            "divergence_occurred": self.divergence_occurred,
            "reasons": list(self.reasons), "details": thaw_json(self.details),
            "divergence_id": self.divergence_id,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "DivergenceRecord":
        return cls(
            payload["event_id"], payload["event_sequence"],
            datetime.fromisoformat(payload["event_timestamp"]),
            payload["control_shadow_id"], payload["control_configuration_fingerprint"],
            payload["comparison_shadow_id"], payload["comparison_configuration_fingerprint"],
            payload["control_status"], payload["comparison_status"],
            payload["control_before_state_hash"], payload["control_after_state_hash"],
            payload["comparison_before_state_hash"], payload["comparison_after_state_hash"],
            payload["divergence_occurred"], tuple(payload["reasons"]),
            freeze_json(payload["details"]), payload["divergence_id"],
        )


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    shadow_id: str
    failed_event_id: str
    failed_event_sequence: int
    failed_event_timestamp: datetime
    last_successful_sequence: int
    state_hash: str
    error_type: str
    error_message: str
    required_replay_from_sequence: int
    quarantine_id: str

    def as_dict(self) -> dict:
        return {
            "shadow_id": self.shadow_id, "failed_event_id": self.failed_event_id,
            "failed_event_sequence": self.failed_event_sequence,
            "failed_event_timestamp": self.failed_event_timestamp.isoformat(),
            "last_successful_sequence": self.last_successful_sequence,
            "state_hash": self.state_hash, "error_type": self.error_type,
            "error_message": self.error_message,
            "required_replay_from_sequence": self.required_replay_from_sequence,
            "quarantine_id": self.quarantine_id,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "QuarantineRecord":
        return cls(
            payload["shadow_id"], payload["failed_event_id"],
            payload["failed_event_sequence"],
            datetime.fromisoformat(payload["failed_event_timestamp"]),
            payload["last_successful_sequence"], payload["state_hash"],
            payload["error_type"], payload["error_message"],
            payload["required_replay_from_sequence"], payload["quarantine_id"],
        )


@dataclass(frozen=True, slots=True)
class RecoveryAuthorization:
    shadow_id: str
    quarantine_id: str
    replayed_from_sequence: int
    replayed_through_sequence: int
    recovered_state_hash: str
    last_event_id: str
    registry_fingerprint: str
    authorization_id: str

    @classmethod
    def create(
        cls, *, shadow_id: str, quarantine_id: str,
        replayed_from_sequence: int, replayed_through_sequence: int,
        recovered_state_hash: str, last_event_id: str, registry_fingerprint: str,
    ) -> "RecoveryAuthorization":
        core = {
            "shadow_id": shadow_id, "quarantine_id": quarantine_id,
            "replayed_from_sequence": replayed_from_sequence,
            "replayed_through_sequence": replayed_through_sequence,
            "recovered_state_hash": recovered_state_hash,
            "last_event_id": last_event_id,
            "registry_fingerprint": registry_fingerprint,
        }
        return cls(**core, authorization_id=canonical_hash(core))
