"""Bounded, append-only evidence storage for V3 historical replays."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from qpx_bot.historical_paper_replay import ReplayConfigurationError
from qpx_bot.historical_paper_replay_runner import _write_evidence
from qpx_bot.paper_state import read_checksummed_state


EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_SEMANTIC_VERSION = "QPX_V3_BOUNDED_EVIDENCE_BATCH_V1"
EVIDENCE_DIRECTORY = "evidence_batches"


def empty_rolling_totals() -> dict[str, Any]:
    return {
        "capacity": {
            "decision_count": 0,
            "qualifying": 0,
            "selected": 0,
            "deferred": 0,
        },
        "entry_outcomes": {
            "terminal_count": 0,
            "filled": 0,
            "rejected": 0,
            "sizing_rejection_reasons": {},
        },
        "profit_recycling": {
            "decision_count": 0,
            "dollars_made_available": 0.0,
        },
        "dynamic_sizing": {
            "decision_count": 0,
            "multiplier_counts": {"1.0": 0, "0.85": 0, "0.7": 0, "0.5": 0},
        },
        "pyramiding": {"decision_count": 0, "accepted_count": 0},
        "regime_allocation": {"decision_count": 0},
    }


def initial_archive_state() -> dict[str, Any]:
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "semantic_version": EVIDENCE_SEMANTIC_VERSION,
        "identity": None,
        "batches": [],
        "last_persisted_boundary": None,
        "rolling_totals": empty_rolling_totals(),
    }


def _encoded(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def _increment(mapping: dict[str, int], key: str, amount: int = 1) -> None:
    mapping[key] = mapping.get(key, 0) + amount


def _updated_totals(
    previous: Mapping[str, Any], events: Mapping[str, Any],
) -> dict[str, Any]:
    totals = json.loads(json.dumps(previous))
    capacity = totals["capacity"]
    for decision in events["capacity_decisions"]:
        capacity["decision_count"] += 1
        capacity["qualifying"] += len(decision["qualifying_asset_ids"])
        capacity["selected"] += len(decision["selected_asset_ids"])
        capacity["deferred"] += len(decision["deferred_asset_ids"])

    outcomes = totals["entry_outcomes"]
    reasons = outcomes["sizing_rejection_reasons"]
    for item in events["entry_outcomes"]:
        status = str(item["status"])
        if status not in {"FILLED", "REJECTED"}:
            raise ReplayConfigurationError(
                "Only terminal entry outcomes may be archived."
            )
        outcomes["terminal_count"] += 1
        outcomes[status.lower()] += 1
        if status == "REJECTED":
            _increment(reasons, str(item.get("reason") or "UNSPECIFIED"))
    outcomes["sizing_rejection_reasons"] = dict(sorted(reasons.items()))

    profit = totals["profit_recycling"]
    for item in events["profit_recycling"]:
        profit["decision_count"] += 1
        profit["dollars_made_available"] += float(
            item["amount_proposed_for_recycling"]
        )

    dynamic = totals["dynamic_sizing"]
    for item in events["dynamic_sizing"]:
        dynamic["decision_count"] += 1
        key = str(item["sizing_multiplier"])
        if key not in dynamic["multiplier_counts"]:
            raise ReplayConfigurationError(
                "Dynamic-sizing evidence contains an unsupported multiplier."
            )
        dynamic["multiplier_counts"][key] += 1

    pyramid = totals["pyramiding"]
    for item in events["pyramiding"]:
        pyramid["decision_count"] += 1
        if float(item["accepted_shares"]) > 0:
            pyramid["accepted_count"] += 1

    totals["regime_allocation"]["decision_count"] += len(
        events["regime_allocation"]
    )
    return totals


def _runtime_events(state: Mapping[str, Any]) -> dict[str, Any]:
    terminal_outcomes = []
    for signal_id, outcome in state["entry_outcomes"].items():
        status = str(outcome["status"])
        if status == "PENDING":
            continue
        terminal_outcomes.append({"signal_id": signal_id, **outcome})
    terminal_outcomes.sort(key=lambda item: item["signal_id"])
    accelerators = state.get("accelerators")
    return {
        "capacity_decisions": state["capacity_decisions"],
        "entry_outcomes": terminal_outcomes,
        "profit_recycling": (
            accelerators["profit_recycling"]["decisions"] if accelerators else []
        ),
        "dynamic_sizing": (
            accelerators["dynamic_sizing"]["decisions"] if accelerators else []
        ),
        "pyramiding": (
            accelerators["pyramiding"]["decisions"] if accelerators else []
        ),
        "regime_allocation": (
            accelerators["regime_allocation"]["decisions"] if accelerators else []
        ),
    }


def _compact_state(
    state: Mapping[str, Any], next_archive: Mapping[str, Any], terminal_ids: set[str],
) -> dict[str, Any]:
    compact = {**state, "capacity_decisions": [], "evidence_archive": next_archive}
    compact["entry_outcomes"] = {
        signal_id: outcome
        for signal_id, outcome in state["entry_outcomes"].items()
        if signal_id not in terminal_ids
    }
    accelerators = state.get("accelerators")
    if accelerators is not None:
        compact_accelerators = {**accelerators}
        for key in (
            "profit_recycling", "dynamic_sizing", "pyramiding", "regime_allocation",
        ):
            compact_accelerators[key] = {**accelerators[key], "decisions": []}
        compact["accelerators"] = compact_accelerators
    return compact


@dataclass(frozen=True)
class EvidenceFlush:
    payload: Mapping[str, Any]
    reference: Mapping[str, Any]
    next_archive: Mapping[str, Any]
    compact_state: Mapping[str, Any]
    terminal_outcome_ids: frozenset[str]


class V3EvidenceArchive:
    """Own the batch/checkpoint transaction without owning strategy state."""

    def __init__(
        self, run_dir: Path, identity: Mapping[str, Any], runtime: Any,
    ) -> None:
        self.run_dir = run_dir
        self.identity = dict(identity)
        archive = runtime.state.get("evidence_archive")
        if not isinstance(archive, Mapping):
            raise ReplayConfigurationError(
                "V3 bounded-evidence runtime state is missing."
            )
        if archive.get("identity") is None:
            archive["identity"] = self.identity
        elif archive.get("identity") != self.identity:
            raise ReplayConfigurationError("V3 evidence archive identity mismatch.")
        self.validate(archive)

    def _batch_path(self, sequence: int) -> Path:
        return self.run_dir / EVIDENCE_DIRECTORY / f"batch-{sequence:08d}.json"

    def _read_reference(self, reference: Mapping[str, Any]) -> Mapping[str, Any]:
        sequence = int(reference["sequence"])
        expected_relative = f"{EVIDENCE_DIRECTORY}/batch-{sequence:08d}.json"
        if reference.get("path") != expected_relative:
            raise ReplayConfigurationError("V3 evidence batch path is invalid.")
        path = self.run_dir / expected_relative
        try:
            raw = read_checksummed_state(
                path, path.with_suffix(path.suffix + ".sha256"),
                label="V3 replay evidence batch",
            )
        except (FileNotFoundError, RuntimeError) as exc:
            raise ReplayConfigurationError(str(exc)) from exc
        actual = hashlib.sha256(raw).hexdigest()
        if (
            actual != reference.get("sha256")
            or len(raw) != reference.get("byte_length")
        ):
            raise ReplayConfigurationError(
                "V3 evidence batch checkpoint reference mismatch."
            )
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ReplayConfigurationError("V3 evidence batch is malformed.") from exc
        return payload

    def validate(self, archive: Mapping[str, Any]) -> None:
        if (
            archive.get("schema_version") != EVIDENCE_SCHEMA_VERSION
            or archive.get("semantic_version") != EVIDENCE_SEMANTIC_VERSION
            or archive.get("identity") != self.identity
            or not isinstance(archive.get("batches"), list)
        ):
            raise ReplayConfigurationError("V3 evidence archive contract mismatch.")
        previous_checksum = None
        last_payload = None
        for expected_sequence, reference in enumerate(archive["batches"], 1):
            if reference.get("sequence") != expected_sequence:
                raise ReplayConfigurationError("V3 evidence batch sequence has a gap.")
            payload = self._read_reference(reference)
            if (
                payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION
                or payload.get("semantic_version") != EVIDENCE_SEMANTIC_VERSION
                or payload.get("identity") != self.identity
                or payload.get("sequence") != expected_sequence
                or payload.get("previous_batch_sha256") != previous_checksum
                or payload.get("completed_through_boundary")
                != reference.get("completed_through_boundary")
            ):
                raise ReplayConfigurationError("V3 evidence batch chain is invalid.")
            previous_checksum = reference["sha256"]
            last_payload = payload
        expected_totals = (
            last_payload["rolling_totals"] if last_payload else empty_rolling_totals()
        )
        expected_boundary = (
            last_payload["completed_through_boundary"] if last_payload else None
        )
        if (
            archive.get("rolling_totals") != expected_totals
            or archive.get("last_persisted_boundary") != expected_boundary
        ):
            raise ReplayConfigurationError(
                "V3 evidence archive rolling state does not match its durable prefix."
            )
        self._validated_batch_count = len(archive["batches"])
        self._validated_last_checksum = previous_checksum

    def _validate_live_head(self, archive: Mapping[str, Any]) -> None:
        batches = archive.get("batches")
        if not isinstance(batches, list):
            raise ReplayConfigurationError(
                "V3 in-memory evidence archive changed after validation."
            )
        last_checksum = batches[-1]["sha256"] if batches else None
        if (
            archive.get("schema_version") != EVIDENCE_SCHEMA_VERSION
            or archive.get("semantic_version") != EVIDENCE_SEMANTIC_VERSION
            or archive.get("identity") != self.identity
            or len(batches) != self._validated_batch_count
            or last_checksum != self._validated_last_checksum
        ):
            raise ReplayConfigurationError(
                "V3 in-memory evidence archive changed after validation."
            )

    def prepare_flush(self, runtime: Any) -> EvidenceFlush:
        state = runtime.persistence_state()
        archive = state["evidence_archive"]
        self._validate_live_head(archive)
        events = _runtime_events(state)
        sequence = len(archive["batches"]) + 1
        totals = _updated_totals(archive["rolling_totals"], events)
        payload = {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "semantic_version": EVIDENCE_SEMANTIC_VERSION,
            "identity": self.identity,
            "sequence": sequence,
            "previous_batch_sha256": (
                archive["batches"][-1]["sha256"] if archive["batches"] else None
            ),
            "previous_persisted_boundary": archive["last_persisted_boundary"],
            "completed_through_boundary": state["last_completed_boundary"],
            "events": events,
            "rolling_totals": totals,
        }
        encoded = _encoded(payload)
        reference = {
            "sequence": sequence,
            "path": f"{EVIDENCE_DIRECTORY}/batch-{sequence:08d}.json",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "byte_length": len(encoded),
            "completed_through_boundary": state["last_completed_boundary"],
        }
        next_archive = {
            **archive,
            "batches": [*archive["batches"], reference],
            "last_persisted_boundary": state["last_completed_boundary"],
            "rolling_totals": totals,
        }
        terminal_ids = frozenset(item["signal_id"] for item in events["entry_outcomes"])
        return EvidenceFlush(
            payload=payload,
            reference=reference,
            next_archive=next_archive,
            compact_state=_compact_state(state, next_archive, set(terminal_ids)),
            terminal_outcome_ids=terminal_ids,
        )

    def persist_and_verify_batch(self, flush: EvidenceFlush) -> None:
        path = self._batch_path(int(flush.reference["sequence"]))
        checksum_path = path.with_suffix(path.suffix + ".sha256")
        if path.exists() or checksum_path.exists():
            if not path.exists() or not checksum_path.exists():
                raise ReplayConfigurationError(
                    "Incomplete orphan V3 evidence batch cannot be reused."
                )
            raw = read_checksummed_state(
                path, checksum_path, label="Orphan V3 replay evidence batch",
            )
            if raw != _encoded(flush.payload):
                raise ReplayConfigurationError(
                    "Orphan V3 evidence batch differs from replayed evidence."
                )
        else:
            _write_evidence(path, flush.payload)
        payload = self._read_reference(flush.reference)
        if _encoded(payload) != _encoded(flush.payload):
            raise ReplayConfigurationError(
                "V3 evidence batch verification changed its payload."
            )

    def commit_flush(self, runtime: Any, flush: EvidenceFlush) -> None:
        state = runtime.state
        state["evidence_archive"] = flush.next_archive
        self._validated_batch_count = len(flush.next_archive["batches"])
        self._validated_last_checksum = flush.reference["sha256"]
        state["capacity_decisions"] = []
        for signal_id in flush.terminal_outcome_ids:
            outcome = state["entry_outcomes"].get(signal_id)
            if outcome is None or outcome.get("status") == "PENDING":
                raise ReplayConfigurationError(
                    "Terminal entry outcome changed during evidence commit."
                )
            del state["entry_outcomes"][signal_id]
        accelerators = state.get("accelerators")
        if accelerators is not None:
            for key in (
                "profit_recycling", "dynamic_sizing", "pyramiding",
                "regime_allocation",
            ):
                accelerators[key]["decisions"] = []

    def write_progress_report(self, runtime: Any, *, status: str = "RUNNING") -> None:
        state = runtime.state
        archive = state["evidence_archive"]
        _write_evidence(self.run_dir / "progress_report.json", {
            "schema_version": EVIDENCE_SCHEMA_VERSION,
            "semantic_version": EVIDENCE_SEMANTIC_VERSION,
            "identity": self.identity,
            "status": status,
            "last_completed_boundary": state["last_completed_boundary"],
            "completed_15m_boundaries": state["boundaries"],
            "evidence_batch_count": len(archive["batches"]),
            "evidence_batch_sha256": (
                archive["batches"][-1]["sha256"] if archive["batches"] else None
            ),
            "rolling_totals": archive["rolling_totals"],
            "signals": state["signals"],
            "fills": state["fills"],
            "pending_entries": len(state["pending"]),
            "outcome_reconciliation": state["outcome_reconciliation"],
        })

    def report_evidence(self, state: Mapping[str, Any]) -> dict[str, Any]:
        archive = state["evidence_archive"]
        self._validate_live_head(archive)
        capacity_decisions: list[Mapping[str, Any]] = []
        profit_ids: list[str] = []
        dynamic_ids: list[str] = []
        accepted_additions: list[Mapping[str, Any]] = []
        affected_assets: set[str] = set()
        regime_decisions: list[Mapping[str, Any]] = []
        previous_checksum = None
        last_payload = None
        for expected_sequence, reference in enumerate(archive["batches"], 1):
            payload = self._read_reference(reference)
            if (
                reference.get("sequence") != expected_sequence
                or payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION
                or payload.get("semantic_version") != EVIDENCE_SEMANTIC_VERSION
                or payload.get("identity") != self.identity
                or payload.get("sequence") != expected_sequence
                or payload.get("previous_batch_sha256") != previous_checksum
                or payload.get("completed_through_boundary")
                != reference.get("completed_through_boundary")
            ):
                raise ReplayConfigurationError("V3 evidence batch chain is invalid.")
            events = payload["events"]
            capacity_decisions.extend(events["capacity_decisions"])
            profit_ids.extend(item["decision_id"] for item in events["profit_recycling"])
            dynamic_ids.extend(item["decision_id"] for item in events["dynamic_sizing"])
            for item in events["pyramiding"]:
                if float(item["accepted_shares"]) > 0:
                    accepted_additions.append(item)
                    affected_assets.add(str(item["symbol"]))
            regime_decisions.extend(events["regime_allocation"])
            previous_checksum = reference["sha256"]
            last_payload = payload
        expected_totals = (
            last_payload["rolling_totals"] if last_payload else empty_rolling_totals()
        )
        expected_boundary = (
            last_payload["completed_through_boundary"] if last_payload else None
        )
        if (
            archive["rolling_totals"] != expected_totals
            or archive["last_persisted_boundary"] != expected_boundary
        ):
            raise ReplayConfigurationError(
                "V3 evidence archive rolling state does not match its durable prefix."
            )
        totals = archive["rolling_totals"]
        return {
            "capacity_decisions": capacity_decisions,
            "profit_recycling": {
                **totals["profit_recycling"], "decision_ids": profit_ids,
            },
            "dynamic_sizing": {
                **totals["dynamic_sizing"], "decision_ids": dynamic_ids,
            },
            "pyramiding": {
                **totals["pyramiding"],
                "affected_provider_asset_ids": sorted(affected_assets),
                "accepted_additions": accepted_additions,
            },
            "regime_allocation": {
                **totals["regime_allocation"], "decisions": regime_decisions,
            },
        }
