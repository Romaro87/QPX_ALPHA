"""Research-only Top-100 dividend actions to Post-Ex staged inputs.

The output is intentionally not a runnable replay dataset. Historical
information availability is unknown, and this adapter never invents it.
"""

from __future__ import annotations

from datetime import date, datetime, time
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from qpx_bot.accelerators.dividend_opportunity import canonical_fingerprint


ADAPTER_VERSION = "top100-post-ex-event-adapter-v1"
PURPOSE = "POST_EX_RECOVERY_RESEARCH_INPUT_STAGING_ONLY"
EVENT_EFFECTIVENESS_CONVENTION = "EX_DATE_09_30_AMERICA_NEW_YORK"
NEW_YORK = ZoneInfo("America/New_York")
SUPPORTED_ORDINARY_SUBTYPES = frozenset({None, "", "cash", "ordinary"})


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unable to read required JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Required JSON must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_fingerprint(name: str, value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ValueError(f"Invalid {name}")
    return value


def _require_date(name: str, value: Any) -> date:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing {name}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {name}") from exc


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"Unable to read normalized events: {path}") from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed event JSON on line {number}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Event line {number} must be an object")
        events.append(value)
    return events


def _classification(event: dict[str, Any]) -> tuple[str, bool, str]:
    provider = event.get("provider_fields")
    if not isinstance(provider, dict):
        raise ValueError("Missing provider_fields")
    subtype = _optional_text(provider.get("sub_type"))
    normalized_subtype = subtype.lower() if subtype is not None else None
    special = provider.get("special")
    if not isinstance(special, bool):
        raise ValueError("Missing or invalid special flag")
    if normalized_subtype == "return_of_capital":
        return "RETURN_OF_CAPITAL", False, "NON_ORDINARY_RETURN_OF_CAPITAL"
    if normalized_subtype not in SUPPORTED_ORDINARY_SUBTYPES:
        return "UNSUPPORTED_NON_ORDINARY_SUBTYPE", False, "UNSUPPORTED_SUBTYPE"
    if special:
        return "SPECIAL_CASH_DIVIDEND", False, "NON_ORDINARY_SPECIAL_DIVIDEND"
    if event.get("action_type") != "cash_dividend":
        return "NON_CASH_DIVIDEND", False, "NON_ORDINARY_ACTION_TYPE"
    return "ORDINARY_CASH_DIVIDEND", True, "STRUCTURALLY_ELIGIBLE"


def validate_causal_boundary(
    *,
    information_available_time: datetime | None,
    evidence_observed_at: datetime | None,
    evaluation_timestamps: Iterable[datetime],
) -> None:
    """Fail closed before a staged event can enter a causal replay path."""
    if information_available_time is None:
        raise ValueError("Historical information availability is UNKNOWN")
    if evidence_observed_at is None:
        raise ValueError("Historical evidence observation time is UNKNOWN")
    if information_available_time.tzinfo is None or evidence_observed_at.tzinfo is None:
        raise ValueError("Causal timestamps must be timezone-aware")
    if evidence_observed_at < information_available_time:
        raise ValueError("Evidence predates information availability")
    evaluations = tuple(evaluation_timestamps)
    if not evaluations:
        raise ValueError("Explicit evaluation timestamps are required")
    for evaluation in evaluations:
        if evaluation.tzinfo is None:
            raise ValueError("Evaluation timestamps must be timezone-aware")
        if information_available_time > evaluation or evidence_observed_at > evaluation:
            raise ValueError("Future information would be introduced")


def build_adapter_dataset(source_root: Path) -> dict[str, Any]:
    source_root = Path(source_root)
    manifest_path = source_root / "dataset_manifest.json"
    provenance_path = source_root / "provenance.json"
    events_path = source_root / "dividend_actions.jsonl"
    manifest = _read_json(manifest_path)
    provenance = _read_json(provenance_path)
    events = _load_events(events_path)

    source_dataset_fingerprint = _require_fingerprint(
        "source dataset fingerprint", manifest.get("dataset_fingerprint")
    )
    manifest_core = {
        key: value for key, value in manifest.items()
        if key != "dataset_fingerprint"
    }
    if canonical_fingerprint(manifest_core) != source_dataset_fingerprint:
        raise ValueError("Source dataset fingerprint mismatch")
    if manifest.get("normalized_sha256") != _sha256(events_path):
        raise ValueError("Normalized dividend dataset hash mismatch")
    if manifest.get("provenance_sha256") != _sha256(provenance_path):
        raise ValueError("Dividend provenance hash mismatch")
    if manifest.get("normalized_event_count") != len(events):
        raise ValueError("Dividend event count does not match manifest")
    if manifest.get("status") != "COMPLETE" or manifest.get("failed_symbol_type_queries") != 0:
        raise ValueError("Dividend source dataset is incomplete")

    source_identity = _require_fingerprint(
        "source identity", manifest.get("source_identity")
    )
    expected_source_identity = canonical_fingerprint({
        "symbols": provenance.get("symbols"),
        "start": provenance.get("start"),
        "end": provenance.get("end"),
        "selection_fingerprint": provenance.get("selection_fingerprint"),
        "frozen_top100_fingerprint": provenance.get("frozen_top100_fingerprint"),
        "historical_dataset_fingerprint": provenance.get(
            "historical_dataset_fingerprint"
        ),
    })
    if source_identity != expected_source_identity:
        raise ValueError("Source/dataset identity does not match provenance")
    symbols = provenance.get("symbols")
    if not isinstance(symbols, list) or len(symbols) != 100 or len(set(symbols)) != 100:
        raise ValueError("Frozen Top-100 universe identity is invalid")
    symbol_set = set(symbols)
    interval_start = _require_date("provenance start", provenance.get("start"))
    interval_end = _require_date("provenance end", provenance.get("end"))

    adapted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        event_fingerprint = _require_fingerprint(
            "event fingerprint", event.get("event_fingerprint")
        )
        event_core = {
            key: value for key, value in event.items()
            if key != "event_fingerprint"
        }
        if canonical_fingerprint(event_core) != event_fingerprint:
            raise ValueError("Source event fingerprint mismatch")
        if event_fingerprint in seen:
            raise ValueError("Duplicate event identity")
        seen.add(event_fingerprint)
        alpaca_event_id = _optional_text(event.get("provider_event_id"))
        if alpaca_event_id is None:
            raise ValueError("Required Alpaca event identity is missing")
        symbol = _optional_text(event.get("symbol"))
        if symbol not in symbol_set:
            raise ValueError("Event symbol is outside the frozen Top-100 universe")
        ex_date = _require_date("ex-date", event.get("ex_date"))
        if not interval_start <= ex_date <= interval_end:
            raise ValueError("Event ex-date is outside the frozen replay interval")
        rate = event.get("rate")
        if not isinstance(rate, (int, float)) or not math.isfinite(rate) or rate <= 0:
            raise ValueError("Missing or invalid dividend amount/rate")
        provider = event.get("provider_fields")
        if not isinstance(provider, dict):
            raise ValueError("Missing provider event fields")
        foreign = provider.get("foreign")
        if not isinstance(foreign, bool):
            raise ValueError("Missing or invalid foreign flag")
        classification, eligible, eligibility_reason = _classification(event)
        if eligible and classification != "ORDINARY_CASH_DIVIDEND":
            raise ValueError("Unsupported subtype entered ordinary-dividend path")
        effective = datetime.combine(ex_date, time(9, 30), tzinfo=NEW_YORK)
        core = {
            "adapter_version": ADAPTER_VERSION,
            "alpaca_event_id": alpaca_event_id,
            "event_fingerprint": event_fingerprint,
            "corporate_action_event_id": event_fingerprint,
            "symbol": symbol,
            "action_type": event.get("action_type"),
            "classification": classification,
            "ordinary_post_ex_eligible": eligible,
            "eligibility_reason": eligibility_reason,
            "subtype": _optional_text(provider.get("sub_type")),
            "special": provider.get("special"),
            "foreign": foreign,
            "due_bill_on_date": provider.get("due_bill_on_date"),
            "due_bill_off_date": provider.get("due_bill_off_date"),
            "ex_date": ex_date.isoformat(),
            "record_date": event.get("record_date"),
            "payable_date": event.get("payable_date"),
            "process_date": event.get("process_date"),
            "rate": rate,
            "event_effective_time": effective.isoformat(),
            "event_effectiveness_convention": EVENT_EFFECTIVENESS_CONVENTION,
            "event_effectiveness_is_experiment_assumption": True,
            "information_available_time": None,
            "information_availability_status": "UNKNOWN_NOT_IN_SOURCE",
            "historical_replay_ready": False,
            "noncausal_metadata_not_assumed_known_at_event_time": [
                "record_date", "payable_date", "process_date", "rate",
                "subtype", "special", "foreign", "due_bill_on_date",
                "due_bill_off_date",
            ],
            "source_dataset_fingerprint": source_dataset_fingerprint,
            "source_identity": source_identity,
            "source_provenance_sha256": manifest["provenance_sha256"],
        }
        adapted.append({
            **core,
            "adapter_record_fingerprint": canonical_fingerprint(core),
        })

    adapted.sort(key=lambda item: (
        item["symbol"], item["ex_date"], item["event_fingerprint"]
    ))
    ordinary_count = sum(item["ordinary_post_ex_eligible"] for item in adapted)
    classifications: dict[str, int] = {}
    for item in adapted:
        key = item["classification"]
        classifications[key] = classifications.get(key, 0) + 1
    result_core = {
        "schema_version": 1,
        "adapter_version": ADAPTER_VERSION,
        "purpose": PURPOSE,
        "research_only": True,
        "price_data_joined": False,
        "economic_replay_run": False,
        "capital_authority": False,
        "execution_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "source_dataset_fingerprint": source_dataset_fingerprint,
        "source_identity": source_identity,
        "source_provenance_sha256": manifest["provenance_sha256"],
        "selection_fingerprint": provenance.get("selection_fingerprint"),
        "frozen_top100_fingerprint": provenance.get("frozen_top100_fingerprint"),
        "historical_dataset_fingerprint": provenance.get(
            "historical_dataset_fingerprint"
        ),
        "universe": symbols,
        "interval": {
            "start": interval_start.isoformat(),
            "end": interval_end.isoformat(),
        },
        "event_effectiveness_convention": {
            "identity": EVENT_EFFECTIVENESS_CONVENTION,
            "description": (
                "Experiment convention: the corporate action becomes effective "
                "at 09:30 America/New_York on its ex-date. This does not assert "
                "when the dividend was announced or historically knowable."
            ),
            "source_claims_historical_information_availability": False,
        },
        "causal_assumptions": {
            "historical_information_availability": "UNKNOWN",
            "declaration_or_announcement_time_invented": False,
            "events_historically_replay_ready": False,
            "future_metadata_permitted_as_causal_input": False,
        },
        "source_event_count": len(adapted),
        "ordinary_post_ex_structurally_eligible_count": ordinary_count,
        "separately_classified_count": len(adapted) - ordinary_count,
        "classification_counts": dict(sorted(classifications.items())),
        "events": adapted,
    }
    return {
        **result_core,
        "adapter_output_fingerprint": canonical_fingerprint(result_core),
    }


def write_adapter_dataset(source_root: Path, output_path: Path) -> dict[str, Any]:
    result = build_adapter_dataset(source_root)
    _atomic_json(Path(output_path), result)
    return result
