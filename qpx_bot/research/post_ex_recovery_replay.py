"""Manifest-driven causal-validation replay for Post-Ex Recovery V1.

This module produces research evidence only.  It has no economic, capital,
execution, qualification, promotion, portfolio, paper, or live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
import json
from pathlib import Path
from typing import Any

from qpx_bot.accelerators.dividend_opportunity import (
    DividendOpportunityContext,
    DividendOpportunityEvidence,
    OpportunityType,
    PostExRecoveryContext,
    PostExRecoveryObservation,
    PostExRecoveryV1,
    canonical_fingerprint,
    load_post_ex_recovery_config,
)

HARNESS_VERSION = "1.0.0"
PURPOSE = "CAUSAL_VALIDATION_ONLY"
SCHEDULE_MODE = "EXPLICIT_PER_EVENT"


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Incomplete {name}")
    return value


def _require_fingerprint(name: str, value: Any) -> str:
    value = _require_text(name, value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"Invalid {name}")
    return value


def _timestamp(name: str, value: Any) -> datetime:
    text = _require_text(name, value)
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid {name}") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return result


def _object(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Incomplete {name}")
    return value


def _list(name: str, value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"Incomplete {name}")
    return value


def _portable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_portable(item) for item in value]
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True, slots=True)
class PostExReplayResult:
    harness_version: str
    experiment_identity: str
    purpose: str
    manifest_fingerprint: str
    dataset_identity: str
    dataset_fingerprint: str
    provenance_identity: str
    reference_price_semantics: dict[str, str]
    universe: tuple[str, ...]
    interval_start: datetime
    interval_end: datetime
    evaluation_schedule: dict[str, str]
    configuration_reference: str
    configuration_fingerprint: str
    event_count: int
    evaluation_count: int
    opportunity_state_counts: dict[str, int]
    reason_code_counts: dict[str, int]
    causal_validation_pass: bool
    causal_failures: tuple[str, ...]
    decisions: tuple[dict[str, Any], ...]
    result_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return _portable(asdict(self))


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to load {name}: {path}") from exc
    return _object(name, value)


def _resolve(manifest_path: Path, reference: Any, name: str) -> Path:
    text = _require_text(name, reference)
    path = Path(text)
    return path if path.is_absolute() else manifest_path.parent / path


def run_post_ex_recovery_replay(manifest_path: Path) -> PostExReplayResult:
    """Validate inputs and replay explicit evaluation points causally."""

    manifest_path = Path(manifest_path)
    manifest = _load_json(manifest_path, "experiment manifest")
    if manifest.get("research_only") is not True or manifest.get("purpose") != PURPOSE:
        raise ValueError("Replay manifest must be research-only causal validation")
    experiment_identity = _require_text(
        "experiment_identity", manifest.get("experiment_identity")
    )

    dataset_spec = _object("dataset", manifest.get("dataset"))
    dataset_identity = _require_text("dataset.identity", dataset_spec.get("identity"))
    dataset_fingerprint = _require_fingerprint(
        "dataset.fingerprint", dataset_spec.get("fingerprint")
    )
    provenance_identity = _require_text(
        "dataset.provenance_identity", dataset_spec.get("provenance_identity")
    )
    dataset_path = _resolve(manifest_path, dataset_spec.get("path"), "dataset.path")
    dataset = _load_json(dataset_path, "replay dataset")
    if canonical_fingerprint(dataset) != dataset_fingerprint:
        raise ValueError("Replay dataset fingerprint mismatch")

    reference_spec = _object(
        "reference_price_semantics", manifest.get("reference_price_semantics")
    )
    reference_semantics = {
        "identity": _require_text(
            "reference_price_semantics.identity", reference_spec.get("identity")
        ),
        "description": _require_text(
            "reference_price_semantics.description", reference_spec.get("description")
        ),
    }

    universe_spec = _object("universe", manifest.get("universe"))
    symbols = tuple(_list("universe.symbols", universe_spec.get("symbols")))
    if any(not isinstance(item, str) or item != item.strip().upper() for item in symbols):
        raise ValueError("Universe symbols must be normalized uppercase text")
    if len(set(symbols)) != len(symbols):
        raise ValueError("Universe symbols must be unique")
    interval = _object("interval", manifest.get("interval"))
    interval_start = _timestamp("interval.start", interval.get("start"))
    interval_end = _timestamp("interval.end", interval.get("end"))
    if interval_start > interval_end:
        raise ValueError("Replay interval is reversed")

    schedule = _object("evaluation_schedule", manifest.get("evaluation_schedule"))
    if schedule.get("mode") != SCHEDULE_MODE:
        raise ValueError("Evaluation schedule must be explicit per event")
    schedule_identity = _require_text(
        "evaluation_schedule.identity", schedule.get("identity")
    )

    config_spec = _object(
        "post_ex_recovery_configuration",
        manifest.get("post_ex_recovery_configuration"),
    )
    config_path = _resolve(manifest_path, config_spec.get("path"), "configuration.path")
    expected_config_fingerprint = _require_fingerprint(
        "configuration.fingerprint", config_spec.get("fingerprint")
    )
    config = load_post_ex_recovery_config(config_path)
    if config.fingerprint != expected_config_fingerprint:
        raise ValueError("Post-Ex Recovery configuration fingerprint mismatch")

    events = _list("dataset.events", dataset.get("events"))
    engine = PostExRecoveryV1(config)
    decisions: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    seen_event_ids: set[str] = set()

    for event_index, raw_event in enumerate(events):
        event = _object(f"event[{event_index}]", raw_event)
        symbol = _require_text("event.symbol", event.get("symbol"))
        if symbol not in symbols:
            raise ValueError(f"Event symbol outside manifest universe: {symbol}")
        event_id = _require_fingerprint(
            "event.corporate_action_event_id", event.get("corporate_action_event_id")
        )
        if event_id in seen_event_ids:
            raise ValueError("Duplicate corporate action event identity")
        seen_event_ids.add(event_id)
        effective = _timestamp("event.event_effective_time", event.get("event_effective_time"))
        available = _timestamp(
            "event.information_available_time", event.get("information_available_time")
        )
        if not interval_start <= effective <= interval_end:
            raise ValueError("Corporate action event is outside manifest interval")
        evidence_spec = _object("event.evidence", event.get("evidence"))
        evidence = DividendOpportunityEvidence(
            evidence_identity=_require_text(
                "event.evidence.identity", evidence_spec.get("identity")
            ),
            source_identity=_require_text(
                "event.evidence.source_identity", evidence_spec.get("source_identity")
            ),
            source_fingerprint=_require_fingerprint(
                "event.evidence.source_fingerprint",
                evidence_spec.get("source_fingerprint"),
            ),
            provenance_identity=_require_text(
                "event.evidence.provenance_identity",
                evidence_spec.get("provenance_identity"),
            ),
            observed_at=_timestamp(
                "event.evidence.observed_at", evidence_spec.get("observed_at")
            ),
        )
        if evidence.provenance_identity != provenance_identity:
            raise ValueError("Event provenance does not match manifest provenance")
        reference_price = event.get("ex_dividend_reference_price")
        observations_raw = event.get("observations")
        if not isinstance(observations_raw, list):
            raise ValueError("Incomplete event.observations")
        observations: list[PostExRecoveryObservation] = []
        previous_observed: datetime | None = None
        for observation_index, raw_observation in enumerate(observations_raw):
            item = _object(f"observation[{observation_index}]", raw_observation)
            observation = PostExRecoveryObservation(
                observed_at=_timestamp("observation.observed_at", item.get("observed_at")),
                information_available_at=_timestamp(
                    "observation.information_available_at",
                    item.get("information_available_at"),
                ),
                price=item.get("price"),
                causal_input_fingerprint=_require_fingerprint(
                    "observation.causal_input_fingerprint",
                    item.get("causal_input_fingerprint"),
                ),
            )
            if previous_observed is not None and observation.observed_at <= previous_observed:
                raise ValueError("Dataset observations must be strictly chronological")
            previous_observed = observation.observed_at
            observations.append(observation)

        evaluations = _list(
            "event.evaluation_timestamps", event.get("evaluation_timestamps")
        )
        evaluation_times = tuple(
            _timestamp("event.evaluation_timestamp", item) for item in evaluations
        )
        if any(right <= left for left, right in zip(evaluation_times, evaluation_times[1:])):
            raise ValueError("Evaluation timestamps must be strictly chronological")

        for evaluation_time in evaluation_times:
            if not interval_start <= evaluation_time <= interval_end:
                raise ValueError("Evaluation timestamp is outside manifest interval")
            if available > evaluation_time or evidence.observed_at > evaluation_time:
                raise ValueError("Future-known dividend information at evaluation timestamp")
            causal_observations = tuple(
                item
                for item in observations
                if item.observed_at <= evaluation_time
                and item.information_available_at <= evaluation_time
            )
            base_context = DividendOpportunityContext(
                opportunity_type=OpportunityType.POST_EX_DIVIDEND_RECOVERY,
                symbol=symbol,
                corporate_action_event_id=event_id,
                event_effective_time=effective,
                information_available_time=available,
                evaluation_timestamp=evaluation_time,
                causal_input_fingerprint=_require_fingerprint(
                    "event.causal_input_fingerprint",
                    event.get("causal_input_fingerprint"),
                ),
                evidence=evidence,
            )
            decision = engine.evaluate(
                PostExRecoveryContext(
                    base_context=base_context,
                    ex_dividend_reference_price=reference_price,
                    observations=causal_observations,
                )
            )
            decision_record = _portable(asdict(decision))
            decisions.append(decision_record)
            state = decision.opportunity_state.value
            state_counts[state] = state_counts.get(state, 0) + 1
            for reason in decision.reason_codes:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1

    manifest_fingerprint = canonical_fingerprint(manifest)
    result_core = {
        "harness_version": HARNESS_VERSION,
        "experiment_identity": experiment_identity,
        "purpose": PURPOSE,
        "manifest_fingerprint": manifest_fingerprint,
        "dataset_identity": dataset_identity,
        "dataset_fingerprint": dataset_fingerprint,
        "provenance_identity": provenance_identity,
        "reference_price_semantics": reference_semantics,
        "universe": list(symbols),
        "interval_start": interval_start.isoformat(),
        "interval_end": interval_end.isoformat(),
        "evaluation_schedule": {
            "mode": SCHEDULE_MODE,
            "identity": schedule_identity,
        },
        "configuration_reference": str(config_spec.get("path")),
        "configuration_fingerprint": config.fingerprint,
        "event_count": len(events),
        "evaluation_count": len(decisions),
        "opportunity_state_counts": state_counts,
        "reason_code_counts": reason_counts,
        "causal_validation_pass": True,
        "causal_failures": [],
        "decisions": decisions,
    }
    return PostExReplayResult(
        harness_version=HARNESS_VERSION,
        experiment_identity=experiment_identity,
        purpose=PURPOSE,
        manifest_fingerprint=manifest_fingerprint,
        dataset_identity=dataset_identity,
        dataset_fingerprint=dataset_fingerprint,
        provenance_identity=provenance_identity,
        reference_price_semantics=reference_semantics,
        universe=symbols,
        interval_start=interval_start,
        interval_end=interval_end,
        evaluation_schedule={"mode": SCHEDULE_MODE, "identity": schedule_identity},
        configuration_reference=str(config_spec.get("path")),
        configuration_fingerprint=config.fingerprint,
        event_count=len(events),
        evaluation_count=len(decisions),
        opportunity_state_counts=state_counts,
        reason_code_counts=reason_counts,
        causal_validation_pass=True,
        causal_failures=(),
        decisions=tuple(decisions),
        result_fingerprint=canonical_fingerprint(result_core),
    )
