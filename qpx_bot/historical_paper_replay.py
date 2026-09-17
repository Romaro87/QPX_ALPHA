"""Configuration and causal boundaries for historical paper replay.

This module deliberately contains no strategy rules and no archive reader.  It
binds a complete immutable experiment configuration to provider adapters, the
existing Candidate V1 scalar causal interface, and restart evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from qpx_bot.candidate_v1_causal import (
    CandidateV1CausalEvaluation,
    CandidateV1CausalInputs,
    evaluate_candidate_v1_causal,
)
from qpx_bot.candidate_v1_config import CandidateV1ConfigSnapshot
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


CONFIG_SCHEMA_VERSION = 1
CONFIG_SEMANTIC_VERSION = "QPX_CAUSAL_HISTORICAL_PAPER_REPLAY_CONFIG_V1"
ACCELERATED_CONFIG_SCHEMA_VERSION = 2
ACCELERATED_CONFIG_SEMANTIC_VERSION = "QPX_CAUSAL_HISTORICAL_PAPER_REPLAY_CONFIG_V2"
CHECKPOINT_SCHEMA_VERSION = 1
CHECKPOINT_SEMANTIC_VERSION = "QPX_CAUSAL_HISTORICAL_PAPER_REPLAY_CHECKPOINT_V1"

_IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BAR_INTERVAL = re.compile(r"^[1-9][0-9]*[mhd]$")

ADJUSTMENT_MODES = frozenset({"RAW", "SPLIT_ADJUSTED", "CAUSAL_SPLIT_ADJUSTED"})
EXECUTION_MODELS = frozenset({"NEXT_ELIGIBLE_1M", "NEXT_ELIGIBLE_15M_OPEN"})
INCOME_BOOTSTRAP_MODES = frozenset(
    {"CANONICAL_IMMEDIATE", "CASH_UNTIL_INCOME_IMPLEMENTATION_AVAILABLE"}
)
UNIVERSE_MODES = frozenset({"STATIC_FROZEN", "CAUSALLY_RESELECTED"})
AUTHORITY_FIELDS = frozenset({"training", "promotion", "live", "broker", "capital"})

_ROOT_FIELDS = {
    "schema_version", "semantic_version", "experiment_id", "market_data",
    "execution", "income", "volatility", "universe", "starting_account",
    "contributions", "strategy", "capacity_arbitration", "runtime", "dataset", "authority",
}
_ACCELERATOR_FIELDS = {
    "enabled", "configuration_path", "configuration_fingerprint",
    "source_file_sha256",
}
_RECONSTITUTED_FIELDS = {
    "eligibility_source", "selection_rule", "membership_count", "lookback",
    "reselection_cadence", "evidence_cutoff", "effective_time_boundary",
    "entry_removal_treatment",
}


class ReplayConfigurationError(RuntimeError):
    """The complete governed replay configuration is absent or invalid."""


def _authority_none() -> dict[str, str]:
    return {field: "NONE" for field in sorted(AUTHORITY_FIELDS)}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayConfigurationError(f"Duplicate configuration field: {key}.")
        result[key] = value
    return result


def _object(value: Any, label: str, fields: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayConfigurationError(f"{label} must be a JSON object.")
    actual = set(value)
    if actual != fields:
        raise ReplayConfigurationError(
            f"{label} fields are invalid; missing={sorted(fields - actual)}; "
            f"unknown={sorted(actual - fields)}."
        )
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReplayConfigurationError(f"{label} must be nonempty text.")
    return value.strip()


def _identifier(value: Any, label: str) -> str:
    result = _text(value, label)
    if not _IDENTIFIER.fullmatch(result):
        raise ReplayConfigurationError(f"{label} is not a governed identifier.")
    return result


def _fingerprint(value: Any, label: str) -> str:
    result = _text(value, label)
    if not _SHA256.fullmatch(result):
        raise ReplayConfigurationError(f"{label} is not a SHA-256 fingerprint.")
    return result


def _number(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReplayConfigurationError(f"{label} must be a JSON number.")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ReplayConfigurationError(f"{label} is outside its governed range.")
    return result


def canonical_replay_configuration(payload: Mapping[str, Any]) -> bytes:
    """Return deterministic configuration bytes without supplying defaults."""
    try:
        return json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ReplayConfigurationError(
            "Replay configuration is not canonically serializable."
        ) from exc


@dataclass(frozen=True, slots=True)
class ReplayExperimentConfiguration:
    canonical_json: str
    fingerprint: str

    @property
    def payload(self) -> Mapping[str, Any]:
        """Return a detached view so callers cannot mutate the frozen identity."""
        return json.loads(self.canonical_json)

    @property
    def experiment_id(self) -> str:
        return str(self.payload["experiment_id"])

    @property
    def universe_mode(self) -> str:
        return str(self.payload["universe"]["mode"])

    def as_dict(self) -> dict[str, Any]:
        return json.loads(self.canonical_json)


def replay_configuration_from_mapping(
    raw: Mapping[str, Any],
) -> ReplayExperimentConfiguration:
    if not isinstance(raw, Mapping):
        raise ReplayConfigurationError("Replay configuration must be a JSON object.")
    schema_version = raw.get("schema_version")
    semantic_version = raw.get("semantic_version")
    accelerated = (
        schema_version == ACCELERATED_CONFIG_SCHEMA_VERSION
        and semantic_version == ACCELERATED_CONFIG_SEMANTIC_VERSION
    )
    fields = _ROOT_FIELDS | ({"accelerators"} if accelerated else set())
    root = _object(raw, "Replay configuration", fields)
    if type(root["schema_version"]) is not int or root["schema_version"] not in {
        CONFIG_SCHEMA_VERSION, ACCELERATED_CONFIG_SCHEMA_VERSION,
    }:
        raise ReplayConfigurationError("Unsupported replay configuration schema.")
    expected_semantic = (
        ACCELERATED_CONFIG_SEMANTIC_VERSION if accelerated
        else CONFIG_SEMANTIC_VERSION
    )
    if root["semantic_version"] != expected_semantic:
        raise ReplayConfigurationError("Unsupported replay configuration semantics.")
    _identifier(root["experiment_id"], "experiment_id")

    market = _object(root["market_data"], "market_data", {
        "provider", "feed", "decision_bar_interval", "adjustment_mode",
        "adapter_identity",
    })
    _identifier(market["provider"], "market_data.provider")
    _identifier(market["feed"], "market_data.feed")
    interval = _text(market["decision_bar_interval"], "market_data.decision_bar_interval")
    if not _BAR_INTERVAL.fullmatch(interval):
        raise ReplayConfigurationError("market_data.decision_bar_interval is invalid.")
    if market["adjustment_mode"] not in ADJUSTMENT_MODES:
        raise ReplayConfigurationError("market_data.adjustment_mode is unsupported.")
    _identifier(market["adapter_identity"], "market_data.adapter_identity")

    execution = _object(root["execution"], "execution", {
        "model", "adapter_identity", "semantic_version",
    })
    if execution["model"] not in EXECUTION_MODELS:
        raise ReplayConfigurationError("execution.model is unsupported.")
    _identifier(execution["adapter_identity"], "execution.adapter_identity")
    _identifier(execution["semantic_version"], "execution.semantic_version")

    income = _object(root["income"], "income", {
        "implementation_identity", "bootstrap_mode", "availability_source",
    })
    _identifier(income["implementation_identity"], "income.implementation_identity")
    if income["bootstrap_mode"] not in INCOME_BOOTSTRAP_MODES:
        raise ReplayConfigurationError("income.bootstrap_mode is unsupported.")
    _identifier(income["availability_source"], "income.availability_source")

    volatility = _object(root["volatility"], "volatility", {
        "source", "adapter_identity", "evidence_fingerprint",
    })
    _identifier(volatility["source"], "volatility.source")
    _identifier(volatility["adapter_identity"], "volatility.adapter_identity")
    _fingerprint(volatility["evidence_fingerprint"], "volatility.evidence_fingerprint")

    universe = _object(root["universe"], "universe", {
        "mode", "identity", "manifest_reference", "manifest_fingerprint",
        "retrospective_selection", "policy",
    })
    if universe["mode"] not in UNIVERSE_MODES:
        raise ReplayConfigurationError("universe.mode is unsupported.")
    _identifier(universe["identity"], "universe.identity")
    if type(universe["retrospective_selection"]) is not bool:
        raise ReplayConfigurationError("universe.retrospective_selection must be boolean.")
    if universe["mode"] == "STATIC_FROZEN":
        _text(universe["manifest_reference"], "universe.manifest_reference")
        _fingerprint(universe["manifest_fingerprint"], "universe.manifest_fingerprint")
        if universe["policy"] is not None:
            raise ReplayConfigurationError("Static universe policy must be null.")
    else:
        if universe["manifest_reference"] is not None or universe["manifest_fingerprint"] is not None:
            raise ReplayConfigurationError("Reconstituted universe cannot masquerade as static evidence.")
        policy = _object(universe["policy"], "universe.policy", _RECONSTITUTED_FIELDS)
        for field in _RECONSTITUTED_FIELDS - {"membership_count"}:
            _identifier(policy[field], f"universe.policy.{field}")
        if type(policy["membership_count"]) is not int or policy["membership_count"] < 1:
            raise ReplayConfigurationError("universe.policy.membership_count is invalid.")
        if universe["retrospective_selection"]:
            raise ReplayConfigurationError("Causal reconstitution cannot be retrospective.")

    account = _object(root["starting_account"], "starting_account", {
        "configuration_identity", "currency", "starting_cash",
    })
    _identifier(account["configuration_identity"], "starting_account.configuration_identity")
    _identifier(account["currency"], "starting_account.currency")
    _number(account["starting_cash"], "starting_account.starting_cash")

    contributions = _object(root["contributions"], "contributions", {
        "schedule_identity", "currency", "amount",
    })
    _identifier(contributions["schedule_identity"], "contributions.schedule_identity")
    _identifier(contributions["currency"], "contributions.currency")
    _number(contributions["amount"], "contributions.amount")

    strategy = _object(root["strategy"], "strategy", {
        "identity", "configuration_fingerprint", "entry_semantics_fingerprint",
    })
    _identifier(strategy["identity"], "strategy.identity")
    _fingerprint(strategy["configuration_fingerprint"], "strategy.configuration_fingerprint")
    _fingerprint(strategy["entry_semantics_fingerprint"], "strategy.entry_semantics_fingerprint")

    arbitration = _object(root["capacity_arbitration"], "capacity_arbitration", {
        "enabled", "policy", "policy_version", "configuration_fingerprint",
    })
    if type(arbitration["enabled"]) is not bool or not arbitration["enabled"]:
        raise ReplayConfigurationError("capacity_arbitration must be explicitly enabled.")
    _text(arbitration["policy"], "capacity_arbitration.policy")
    _text(arbitration["policy_version"], "capacity_arbitration.policy_version")
    _fingerprint(
        arbitration["configuration_fingerprint"],
        "capacity_arbitration.configuration_fingerprint",
    )

    if accelerated:
        accelerators = _object(root["accelerators"], "accelerators", {
            "profit_recycling", "dynamic_sizing", "pyramiding",
            "regime_allocation",
        })
        for name in ("profit_recycling", "pyramiding", "regime_allocation"):
            item = _object(
                accelerators[name], f"accelerators.{name}", _ACCELERATOR_FIELDS,
            )
            if item["enabled"] is not True:
                raise ReplayConfigurationError(f"accelerators.{name} must be enabled.")
            _text(item["configuration_path"], f"accelerators.{name}.configuration_path")
            _fingerprint(item["configuration_fingerprint"], f"accelerators.{name}.configuration_fingerprint")
            _fingerprint(item["source_file_sha256"], f"accelerators.{name}.source_file_sha256")
        dynamic = _object(
            accelerators["dynamic_sizing"], "accelerators.dynamic_sizing",
            _ACCELERATOR_FIELDS | {
                "paired_caps_path", "paired_caps_file_sha256", "paired_cap",
            },
        )
        if dynamic["enabled"] is not True or dynamic["paired_cap"] != "90":
            raise ReplayConfigurationError(
                "Accelerated replay requires the enabled governed 90% Dynamic Sizing pair."
            )
        _text(dynamic["configuration_path"], "accelerators.dynamic_sizing.configuration_path")
        _text(dynamic["paired_caps_path"], "accelerators.dynamic_sizing.paired_caps_path")
        for field in (
            "configuration_fingerprint", "source_file_sha256",
            "paired_caps_file_sha256",
        ):
            _fingerprint(dynamic[field], f"accelerators.dynamic_sizing.{field}")

    runtime = _object(root["runtime"], "runtime", {
        "causal_driver_version", "accounting_version", "execution_version",
    })
    for field in runtime:
        _identifier(runtime[field], f"runtime.{field}")

    dataset = _object(root["dataset"], "dataset", {
        "root_identity", "snapshot_fingerprint", "qualification_status",
    })
    _text(dataset["root_identity"], "dataset.root_identity")
    _fingerprint(dataset["snapshot_fingerprint"], "dataset.snapshot_fingerprint")
    _identifier(dataset["qualification_status"], "dataset.qualification_status")

    authority = _object(root["authority"], "authority", set(AUTHORITY_FIELDS))
    if dict(authority) != _authority_none():
        raise ReplayConfigurationError("Historical replay authority must remain NONE.")

    canonical = canonical_replay_configuration(root)
    return ReplayExperimentConfiguration(
        canonical_json=canonical.decode("utf-8"),
        fingerprint=hashlib.sha256(canonical).hexdigest(),
    )


def load_replay_configuration(path: Path) -> ReplayExperimentConfiguration:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReplayConfigurationError(f"Cannot load replay configuration: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ReplayConfigurationError("Replay configuration root must be an object.")
    return replay_configuration_from_mapping(payload)


@dataclass(frozen=True, slots=True)
class ReplayAdapterBindings:
    market_data_adapter_identity: str
    execution_adapter_identity: str
    volatility_adapter_identity: str
    universe_policy_identity: str
    broker_authority: str = "NONE"

    def validate(self, config: ReplayExperimentConfiguration) -> None:
        expected = (
            config.payload["market_data"]["adapter_identity"],
            config.payload["execution"]["adapter_identity"],
            config.payload["volatility"]["adapter_identity"],
            config.payload["universe"]["identity"],
        )
        actual = (
            self.market_data_adapter_identity, self.execution_adapter_identity,
            self.volatility_adapter_identity, self.universe_policy_identity,
        )
        if actual != expected:
            raise ReplayConfigurationError("Replay adapter identity differs from configuration.")
        if self.broker_authority != "NONE":
            raise ReplayConfigurationError("Historical replay cannot bind broker authority.")


class CandidateV1ReplayPort:
    """Thin port to the canonical Candidate V1 evaluator; owns no universe/archive."""

    __slots__ = ("_snapshot",)

    def __init__(self, snapshot: CandidateV1ConfigSnapshot) -> None:
        self._snapshot = snapshot

    @property
    def configuration_fingerprint(self) -> str:
        return self._snapshot.fingerprint

    def evaluate(self, inputs: CandidateV1CausalInputs) -> CandidateV1CausalEvaluation:
        return evaluate_candidate_v1_causal(
            inputs=inputs,
            config=self._snapshot.bot_config,
            momentum_persistence_level=self._snapshot.momentum_persistence_level,
            vix_exclusion_low=self._snapshot.vix_exclusion_low,
            vix_exclusion_high=self._snapshot.vix_exclusion_high,
        )


@dataclass(frozen=True, slots=True)
class CausalEvidenceEvent:
    """One detached fact released by an archive-owning external driver."""

    event_id: str
    event_type: str
    effective_time: datetime
    available_time: datetime
    payload: Mapping[str, Any]


class CausalEvidenceGateway:
    """Forward-only evidence boundary with no archive navigation capability."""

    __slots__ = ("_last_available_time", "_released", "_sequence")

    def __init__(self) -> None:
        self._last_available_time: datetime | None = None
        self._released: list[CausalEvidenceEvent] = []
        self._sequence = 0

    @property
    def causal_sequence(self) -> int:
        return self._sequence

    def release(
        self, event: CausalEvidenceEvent, *, current_boundary: datetime,
    ) -> CausalEvidenceEvent:
        if current_boundary.tzinfo is None or event.effective_time.tzinfo is None or event.available_time.tzinfo is None:
            raise ReplayConfigurationError("Causal replay times must be timezone-aware.")
        if event.available_time < event.effective_time:
            raise ReplayConfigurationError("Evidence cannot be available before it is effective.")
        if event.available_time > current_boundary:
            raise ReplayConfigurationError("Future evidence is not causally available.")
        if self._last_available_time is not None and event.available_time < self._last_available_time:
            raise ReplayConfigurationError("Causal evidence cannot move backward in time.")
        event_id = _text(event.event_id, "event_id")
        event_type = _identifier(event.event_type, "event_type")
        if not isinstance(event.payload, Mapping):
            raise ReplayConfigurationError("Causal event payload must be an object.")
        detached = CausalEvidenceEvent(
            event_id=event_id,
            event_type=event_type,
            effective_time=event.effective_time,
            available_time=event.available_time,
            payload=json.loads(canonical_replay_configuration(event.payload)),
        )
        self._released.append(detached)
        self._last_available_time = event.available_time
        self._sequence += 1
        return detached

    def released(self, *, event_type: str | None = None) -> tuple[CausalEvidenceEvent, ...]:
        if event_type is None:
            return tuple(self._released)
        governed_type = _identifier(event_type, "event_type")
        return tuple(event for event in self._released if event.event_type == governed_type)


@dataclass(frozen=True, slots=True)
class ReplayCheckpoint:
    run_id: str
    configuration_fingerprint: str
    last_completed_boundary_id: str | None
    causal_sequence: int
    paper_state_fingerprint: str


def write_replay_checkpoint(
    directory: Path, checkpoint: ReplayCheckpoint,
    config: ReplayExperimentConfiguration,
) -> str:
    if checkpoint.configuration_fingerprint != config.fingerprint:
        raise ReplayConfigurationError("Checkpoint configuration does not match the run.")
    if checkpoint.causal_sequence < 0:
        raise ReplayConfigurationError("Checkpoint causal sequence cannot be negative.")
    if checkpoint.last_completed_boundary_id is not None:
        _text(checkpoint.last_completed_boundary_id, "last_completed_boundary_id")
    _fingerprint(checkpoint.paper_state_fingerprint, "paper_state_fingerprint")
    core = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "semantic_version": CHECKPOINT_SEMANTIC_VERSION,
        "run_id": _identifier(checkpoint.run_id, "run_id"),
        "configuration_fingerprint": config.fingerprint,
        "last_completed_boundary_id": checkpoint.last_completed_boundary_id,
        "causal_sequence": checkpoint.causal_sequence,
        "paper_state_fingerprint": checkpoint.paper_state_fingerprint,
        "authority": _authority_none(),
    }
    encoded_core = canonical_replay_configuration(core)
    result = hashlib.sha256(encoded_core).hexdigest()
    payload = canonical_replay_configuration({**core, "checkpoint_fingerprint": result})
    write_checksummed_state(
        Path(directory) / "checkpoint.json", Path(directory) / "checkpoint.sha256", payload,
    )
    return result


def read_replay_checkpoint(
    directory: Path, config: ReplayExperimentConfiguration,
) -> ReplayCheckpoint:
    encoded = read_checksummed_state(
        Path(directory) / "checkpoint.json", Path(directory) / "checkpoint.sha256",
        label="Historical replay checkpoint",
    )
    try:
        payload = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ReplayConfigurationError("Replay checkpoint is invalid JSON.") from exc
    fields = {
        "schema_version", "semantic_version", "run_id", "configuration_fingerprint",
        "last_completed_boundary_id", "causal_sequence", "paper_state_fingerprint",
        "authority", "checkpoint_fingerprint",
    }
    root = _object(payload, "Replay checkpoint", fields)
    if root["schema_version"] != CHECKPOINT_SCHEMA_VERSION or root["semantic_version"] != CHECKPOINT_SEMANTIC_VERSION:
        raise ReplayConfigurationError("Replay checkpoint semantics are incompatible.")
    if root["configuration_fingerprint"] != config.fingerprint:
        raise ReplayConfigurationError("Replay checkpoint configuration mismatch.")
    if root["authority"] != _authority_none():
        raise ReplayConfigurationError("Replay checkpoint contains forbidden authority.")
    fingerprint_value = root["checkpoint_fingerprint"]
    core = {key: value for key, value in root.items() if key != "checkpoint_fingerprint"}
    if hashlib.sha256(canonical_replay_configuration(core)).hexdigest() != fingerprint_value:
        raise ReplayConfigurationError("Replay checkpoint fingerprint mismatch.")
    if type(root["causal_sequence"]) is not int or root["causal_sequence"] < 0:
        raise ReplayConfigurationError("Replay checkpoint causal sequence is invalid.")
    if root["last_completed_boundary_id"] is not None:
        _text(root["last_completed_boundary_id"], "last_completed_boundary_id")
    _fingerprint(root["paper_state_fingerprint"], "paper_state_fingerprint")
    return ReplayCheckpoint(
        run_id=_identifier(root["run_id"], "run_id"),
        configuration_fingerprint=config.fingerprint,
        last_completed_boundary_id=root["last_completed_boundary_id"],
        causal_sequence=root["causal_sequence"],
        paper_state_fingerprint=root["paper_state_fingerprint"],
    )
