"""Experimental deterministic causal logistic-regression baseline.

This is explicitly unqualified research plumbing.  It has no promotion, live,
broker, or capital authority and does not alter historical qualification state.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping

from qpx_bot.ml_historical_acquisition import (
    DEFAULT_ROOT,
    fingerprint,
    load_provider_population,
)
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


SEMANTIC_VERSION = "QPX_ML_EXPERIMENTAL_CAUSAL_BASELINE_V1"
TRAINING_MODE = "EXPERIMENTAL_UNQUALIFIED_TRAINING"
SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 1
MODEL_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1
LEARNING_RATE = 0.01
FEATURE_NAMES = (
    "ret_1", "ret_2", "ret_4", "ret_8", "body", "range",
    "volume_log_change",
)
FEATURE_DEFINITIONS = {
    "ret_1": "close_t / close_t-1 - 1",
    "ret_2": "close_t / close_t-2 - 1",
    "ret_4": "close_t / close_t-4 - 1",
    "ret_8": "close_t / close_t-8 - 1",
    "body": "(close_t - open_t) / open_t",
    "range": "(high_t - low_t) / close_t",
    "volume_log_change": "log1p(volume_t) - log1p(volume_t-1)",
}
SPLITS = {
    "TRAIN": (date(2016, 9, 6), date(2024, 12, 31)),
    "VALIDATION": (date(2025, 1, 1), date(2025, 12, 31)),
    "TEST": (date(2026, 1, 1), date(2026, 9, 3)),
}
EXPECTED_STRICT_STATUS = "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE"
EXPECTED_UNBOUNDED = 22_498
EXPECTED_RESIDUAL_CLASSES = {
    "NO_CUSIP_OR_ISIN_SUPPLIED": 16_626,
    "NO_PROVIDER_ASSET_LOOKUP_RESULT": 5_625,
    "MIXED_MATCH_AND_NOT_FOUND_IDENTITY_EVIDENCE": 247,
}


class ExperimentalTrainingError(RuntimeError):
    """The experimental run cannot be proven safe or reproducible."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _process_command() -> list[str]:
    try:
        values = Path("/proc/self/cmdline").read_bytes().split(b"\0")
        return [value.decode("utf-8") for value in values if value]
    except (OSError, UnicodeDecodeError):
        return [sys.executable, *sys.argv]


def _write_checksummed_json(path: Path, value: Mapping[str, Any]) -> None:
    encoded = json.dumps(
        value, sort_keys=True, indent=2, allow_nan=False,
    ).encode("utf-8") + b"\n"
    write_checksummed_state(path, path.with_suffix(".sha256"), encoded)


def _read_checksummed_json(path: Path, label: str) -> dict[str, Any]:
    try:
        encoded = read_checksummed_state(
            path, path.with_suffix(".sha256"), label=label,
        )
        value = json.loads(encoded)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        raise ExperimentalTrainingError(f"{label} is missing or corrupt.") from exc
    if not isinstance(value, dict):
        raise ExperimentalTrainingError(f"{label} is malformed.")
    return value


def stable_transform(value: float) -> float:
    if not math.isfinite(value):
        raise ExperimentalTrainingError("Feature value is non-finite.")
    return value / (1.0 + abs(value))


def feature_vector(history: list[Mapping[str, Any]]) -> tuple[float, ...] | None:
    """Build features for the completed last bar; no successor is accepted."""
    if len(history) < 9:
        return None
    current = history[-1]
    closes = [float(item["close"]) for item in history]
    current_close = closes[-1]
    current_open = float(current["open"])
    current_high = float(current["high"])
    current_low = float(current["low"])
    current_volume = int(current["volume"])
    previous_volume = int(history[-2]["volume"])
    if current_close <= 0 or current_open <= 0:
        raise ExperimentalTrainingError("Feature price must be positive.")
    raw = (
        current_close / closes[-2] - 1.0,
        current_close / closes[-3] - 1.0,
        current_close / closes[-5] - 1.0,
        current_close / closes[-9] - 1.0,
        (current_close - current_open) / current_open,
        (current_high - current_low) / current_close,
        math.log1p(current_volume) - math.log1p(previous_volume),
    )
    return tuple(stable_transform(value) for value in raw)


def sigmoid(value: float) -> float:
    if value >= 0:
        return 1.0 / (1.0 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1.0 + exp_value)


def sgd_update(
    intercept: float, weights: list[float], features: tuple[float, ...], target: int,
    learning_rate: float = LEARNING_RATE,
) -> tuple[float, list[float], float]:
    probability = sigmoid(intercept + sum(w * x for w, x in zip(weights, features)))
    error = probability - target
    return (
        intercept - learning_rate * error,
        [weight - learning_rate * error * value for weight, value in zip(weights, features)],
        probability,
    )


def _empty_metrics() -> dict[str, Any]:
    return {
        "samples": 0, "positives": 0, "negatives": 0,
        "skipped_flat": 0, "skipped_gap_nonconsecutive": 0,
        "loss_sum": 0.0, "brier_sum": 0.0, "correct": 0,
    }


def _metric_report(value: Mapping[str, Any]) -> dict[str, Any]:
    samples = int(value["samples"])
    positives = int(value["positives"])
    negatives = int(value["negatives"])
    return {
        "samples": samples,
        "positives": positives,
        "negatives": negatives,
        "skipped_flat": int(value["skipped_flat"]),
        "skipped_gap_nonconsecutive": int(value["skipped_gap_nonconsecutive"]),
        "binary_cross_entropy": value["loss_sum"] / samples if samples else None,
        "accuracy": value["correct"] / samples if samples else None,
        "baseline_majority_class_accuracy": max(positives, negatives) / samples if samples else None,
        "brier_score": value["brier_sum"] / samples if samples else None,
    }


def _part_key(part_id: str) -> tuple[int, int]:
    try:
        year_text, batch_text = part_id.split("/")
        return int(year_text.split("=", 1)[1]), int(batch_text.split("=", 1)[1])
    except (ValueError, IndexError) as exc:
        raise ExperimentalTrainingError(f"Invalid partition identity: {part_id}") from exc


def canonical_partition_order(part_ids: Iterable[str]) -> list[str]:
    values = list(part_ids)
    if len(values) != len(set(values)):
        raise ExperimentalTrainingError("Input partition inventory contains duplicates.")
    return sorted(values, key=_part_key)


def _split_for_year(year: int) -> str:
    for name, (start, end) in SPLITS.items():
        if start.year <= year <= end.year:
            return name
    raise ExperimentalTrainingError(f"Partition year {year} is outside configured splits.")


def _manifest_entry(root: Path, part_id: str) -> dict[str, Any]:
    data_path = root / "bars_15m" / f"{part_id}.csv.gz"
    manifest_path = data_path.with_suffix(data_path.suffix + ".manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentalTrainingError(f"Partition manifest is missing or corrupt: {part_id}") from exc
    excluded = {"manifest_fingerprint"}
    if manifest.get("schema_version") == 3:
        excluded.add("completed_at_utc")
    core = {key: value for key, value in manifest.items() if key not in excluded}
    if (
        manifest.get("partition") != part_id
        or manifest.get("manifest_fingerprint") != fingerprint(core)
        or not data_path.is_file()
    ):
        raise ExperimentalTrainingError(f"Partition manifest identity is invalid: {part_id}")
    accepted_sha = manifest.get("accepted_partition_sha256") or manifest.get("sha256")
    if not isinstance(accepted_sha, str) or len(accepted_sha) != 64:
        raise ExperimentalTrainingError(f"Partition checksum identity is invalid: {part_id}")
    row_count = manifest.get("accepted_row_count", manifest.get("row_count"))
    if type(row_count) is not int or row_count < 0:
        raise ExperimentalTrainingError(f"Partition row count is invalid: {part_id}")
    year, batch = _part_key(part_id)
    return {
        "partition": part_id,
        "year": year,
        "batch": batch,
        "phase": _split_for_year(year),
        "data_path": str(data_path.relative_to(root)),
        "manifest_path": str(manifest_path.relative_to(root)),
        "schema_version": manifest.get("schema_version"),
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "accepted_partition_sha256": accepted_sha,
        "row_count": row_count,
    }


def build_input_snapshot(root: Path) -> dict[str, Any]:
    state = _read_checksummed_json(root / "acquisition_state/state.json", "acquisition state")
    completed = canonical_partition_order(state.get("completed", ()))
    if (
        state.get("partitions_total") != 7370
        or state.get("partitions_complete") != 7370
        or state.get("rows_15m") != 383_082_447
        or len(completed) != 7370
        or state.get("corporate_action_status") != "COMPLETE"
        or state.get("training_eligibility") != EXPECTED_STRICT_STATUS
    ):
        raise ExperimentalTrainingError("Historical acquisition snapshot does not match the authorized baseline.")
    entries = [_manifest_entry(root, part_id) for part_id in completed]
    population = load_provider_population(root)
    resolution_path = root / str(state["corporate_action_identity_resolution_path"])
    enrichment_path = root / str(state["corporate_action_identity_enrichment_path"])
    try:
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentalTrainingError("Corporate-action identity evidence is missing or corrupt.") from exc
    unresolved_unbounded = sum(
        item.get("outcome") == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
        and (not item.get("excluded_provider_asset_ids") or not item.get("bounded_dates"))
        for item in resolution.get("records", ())
    )
    if (
        enrichment.get("identity_enrichment_fingerprint")
        != state.get("corporate_action_identity_enrichment_fingerprint")
        or resolution.get("identity_resolution_fingerprint")
        != state.get("corporate_action_identity_resolution_fingerprint")
        or unresolved_unbounded != EXPECTED_UNBOUNDED
    ):
        raise ExperimentalTrainingError("Corporate-action limitation evidence is inconsistent.")
    partition_inventory_fingerprint = fingerprint(entries)
    core = {
        "schema_version": SCHEMA_VERSION,
        "provider": state.get("provider"),
        "feed": state.get("feed"),
        "adjustment": state.get("adjustment"),
        "timeframe": "15Min",
        "partitions_total": len(entries),
        "rows_15m": state["rows_15m"],
        "partition_inventory_fingerprint": partition_inventory_fingerprint,
        "partitions": entries,
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "corporate_action_identity_enrichment_fingerprint": enrichment["identity_enrichment_fingerprint"],
        "corporate_action_identity_resolution_fingerprint": resolution["identity_resolution_fingerprint"],
        "unresolved_unbounded_corporate_action_count": unresolved_unbounded,
        "unresolved_unbounded_residual_classes": EXPECTED_RESIDUAL_CLASSES,
        "calendar_repair_status": "NOT_RUN",
        "strict_dataset_eligibility_status": state["training_eligibility"],
    }
    return {**core, "input_snapshot_fingerprint": fingerprint(core)}


def _configuration() -> dict[str, Any]:
    core = {
        "schema_version": SCHEMA_VERSION,
        "semantic_version": SEMANTIC_VERSION,
        "training_mode": TRAINING_MODE,
        "feature_names": list(FEATURE_NAMES),
        "feature_definitions": FEATURE_DEFINITIONS,
        "feature_transform": "x/(1+abs(x))",
        "target": "next_same_session_15m_close_direction_skip_equal",
        "model": "binary_logistic_regression_intercept_plus_7",
        "numeric_type": "float64",
        "initial_intercept": 0.0,
        "initial_weights": [0.0] * 7,
        "algorithm": "chronological_online_sgd_no_shuffle_one_pass",
        "learning_rate": LEARNING_RATE,
        "momentum": False,
        "regularization": None,
        "splits": {name: [start.isoformat(), end.isoformat()] for name, (start, end) in SPLITS.items()},
        "promotion_authority": "NONE",
        "live_authority": "NONE",
        "capital_authority": "NONE",
    }
    return {**core, "configuration_fingerprint": fingerprint(core)}


def _parse_row(row: Mapping[str, str]) -> dict[str, Any]:
    try:
        stamp = datetime.fromisoformat(row["market_timestamp"])
        if stamp.tzinfo is None:
            raise ValueError
        return {
            "provider_asset_id": row["provider_asset_id"],
            "market_timestamp": stamp.isoformat(),
            "session_date": row.get("session_date") or stamp.date().isoformat(),
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": int(row["volume"]),
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ExperimentalTrainingError("Accepted training row is malformed.") from exc


class _HashingReader(io.RawIOBase):
    def __init__(self, handle: Any) -> None:
        self.handle = handle
        self.digest = hashlib.sha256()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: bytearray) -> int:
        chunk = self.handle.read(len(buffer))
        size = len(chunk)
        buffer[:size] = chunk
        self.digest.update(chunk)
        return size


def _rows(path: Path, expected_sha256: str | None = None) -> Iterator[dict[str, Any]]:
    with path.open("rb") as raw:
        hashing = _HashingReader(raw)
        with gzip.open(hashing, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                yield _parse_row(row)
        if expected_sha256 is not None and hashing.digest.hexdigest() != expected_sha256:
            raise ExperimentalTrainingError(f"Partition checksum mismatch: {path}")


@dataclass
class ExperimentalTrainer:
    root: Path
    output_root: Path | None = None
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    source_commit: str | None = None

    def __post_init__(self) -> None:
        self.root = self.root.resolve()
        self.output_root = (self.output_root or self.root / "experimental_training").resolve()
        self.source_commit = self.source_commit or _git_commit()
        self.code_fingerprint = _sha256(Path(__file__).resolve())
        self.config = _configuration()
        self.snapshot = build_input_snapshot(self.root)
        run_core = {
            "semantic_version": SEMANTIC_VERSION,
            "training_mode": TRAINING_MODE,
            "configuration_fingerprint": self.config["configuration_fingerprint"],
            "input_snapshot_fingerprint": self.snapshot["input_snapshot_fingerprint"],
            "trainer_code_fingerprint": self.code_fingerprint,
            "source_commit": self.source_commit,
        }
        self.run_id = fingerprint(run_core)
        self.run_dir = self.output_root / self.run_id

    def _initial_checkpoint(self) -> dict[str, Any]:
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "semantic_version": SEMANTIC_VERSION,
            "training_mode": TRAINING_MODE,
            "configuration_fingerprint": self.config["configuration_fingerprint"],
            "input_snapshot_fingerprint": self.snapshot["input_snapshot_fingerprint"],
            "trainer_code_fingerprint": self.code_fingerprint,
            "source_commit": self.source_commit,
            "last_completed_partition": None,
            "completed_partition_count": 0,
            "model_intercept": 0.0,
            "model_weights": [0.0] * 7,
            "metrics": {name: _empty_metrics() for name in SPLITS},
            "feature_state_fingerprints": {},
            "checkpoint_sequence": 0,
        }

    def _validate_checkpoint(self, value: Mapping[str, Any]) -> dict[str, Any]:
        core = {key: item for key, item in value.items() if key != "checkpoint_fingerprint"}
        expected = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "semantic_version": SEMANTIC_VERSION,
            "training_mode": TRAINING_MODE,
            "configuration_fingerprint": self.config["configuration_fingerprint"],
            "input_snapshot_fingerprint": self.snapshot["input_snapshot_fingerprint"],
            "trainer_code_fingerprint": self.code_fingerprint,
            "source_commit": self.source_commit,
        }
        if value.get("checkpoint_fingerprint") != fingerprint(core) or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise ExperimentalTrainingError("Training checkpoint identity is invalid.")
        return dict(value)

    def _write_checkpoint(self, value: dict[str, Any]) -> None:
        core = {key: item for key, item in value.items() if key != "checkpoint_fingerprint"}
        output = {**core, "checkpoint_fingerprint": fingerprint(core)}
        _write_checksummed_json(self.run_dir / "checkpoint.json", output)

    def _feature_state_path(self, batch: int, state_fingerprint: str) -> Path:
        return self.run_dir / "feature_state" / f"batch-{batch:05d}" / f"{state_fingerprint}.json"

    def _load_feature_state(self, checkpoint: Mapping[str, Any], batch: int) -> dict[str, Any]:
        expected = checkpoint["feature_state_fingerprints"].get(str(batch))
        if expected is None:
            return {"histories": {}, "pending": {}}
        path = self._feature_state_path(batch, expected)
        value = _read_checksummed_json(path, "feature state")
        core = {key: item for key, item in value.items() if key != "feature_state_fingerprint"}
        if value.get("batch") != batch or value.get("feature_state_fingerprint") != fingerprint(core) or value.get("feature_state_fingerprint") != expected:
            raise ExperimentalTrainingError("Feature-state identity is invalid.")
        return {"histories": value["histories"], "pending": value["pending"]}

    def _save_feature_state(self, batch: int, value: Mapping[str, Any]) -> str:
        core = {"schema_version": 1, "batch": batch, "histories": value["histories"], "pending": value["pending"]}
        state_fingerprint = fingerprint(core)
        output = {**core, "feature_state_fingerprint": state_fingerprint}
        path = self._feature_state_path(batch, state_fingerprint)
        if not path.exists():
            _write_checksummed_json(path, output)
        return state_fingerprint

    def _record_sample(self, checkpoint: dict[str, Any], phase: str, features: tuple[float, ...], target: int) -> None:
        intercept = float(checkpoint["model_intercept"])
        weights = [float(value) for value in checkpoint["model_weights"]]
        probability = sigmoid(intercept + sum(w * x for w, x in zip(weights, features)))
        if phase == "TRAIN":
            intercept, weights, probability = sgd_update(intercept, weights, features, target)
            checkpoint["model_intercept"] = intercept
            checkpoint["model_weights"] = weights
        metric = checkpoint["metrics"][phase]
        bounded_probability = min(max(probability, 1e-15), 1.0 - 1e-15)
        metric["samples"] += 1
        metric["positives" if target else "negatives"] += 1
        metric["loss_sum"] += -(target * math.log(bounded_probability) + (1 - target) * math.log(1.0 - bounded_probability))
        metric["brier_sum"] += (probability - target) ** 2
        metric["correct"] += int((probability >= 0.5) == bool(target))

    def process_partition(
        self, checkpoint: dict[str, Any], entry: Mapping[str, Any],
        rows: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        batch = int(entry["batch"])
        phase = str(entry["phase"])
        feature_state = self._load_feature_state(checkpoint, batch)
        histories = feature_state["histories"]
        pending = feature_state["pending"]
        source = rows if rows is not None else _rows(
            self.root / str(entry["data_path"]), entry.get("accepted_partition_sha256"),
        )
        source_row_count = 0
        for raw in source:
            source_row_count += 1
            row = dict(raw) if isinstance(raw.get("market_timestamp"), str) and isinstance(raw.get("close"), (int, float)) else _parse_row(raw)
            asset_id = row["provider_asset_id"]
            prior = pending.pop(asset_id, None)
            if prior is not None:
                previous_time = datetime.fromisoformat(prior["market_timestamp"])
                current_time = datetime.fromisoformat(row["market_timestamp"])
                prior_phase = prior["phase"]
                if row["session_date"] == prior["session_date"] and current_time - previous_time == timedelta(minutes=15):
                    if row["close"] == prior["close"]:
                        checkpoint["metrics"][prior_phase]["skipped_flat"] += 1
                    else:
                        self._record_sample(checkpoint, prior_phase, tuple(prior["features"]), int(row["close"] > prior["close"]))
                else:
                    checkpoint["metrics"][prior_phase]["skipped_gap_nonconsecutive"] += 1
            history = histories.setdefault(asset_id, [])
            history.append(row)
            del history[:-9]
            features = feature_vector(history)
            if features is not None:
                pending[asset_id] = {
                    "market_timestamp": row["market_timestamp"],
                    "session_date": row["session_date"],
                    "close": row["close"],
                    "features": list(features),
                    "phase": phase,
                }
        if entry.get("row_count") is not None and source_row_count != entry["row_count"]:
            raise ExperimentalTrainingError(
                f"Partition row count mismatch: {entry['partition']}"
            )
        state_fingerprint = self._save_feature_state(batch, feature_state)
        checkpoint["feature_state_fingerprints"][str(batch)] = state_fingerprint
        checkpoint["last_completed_partition"] = entry["partition"]
        checkpoint["completed_partition_count"] += 1
        checkpoint["checkpoint_sequence"] += 1
        self._write_checkpoint(checkpoint)

    def run(self, *, entries: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self.run_dir / "run_manifest.json"
        if manifest_path.exists():
            manifest = _read_checksummed_json(manifest_path, "run manifest")
            manifest_core = {
                key: item for key, item in manifest.items()
                if key != "run_manifest_fingerprint"
            }
            if (
                manifest.get("run_manifest_fingerprint") != fingerprint(manifest_core)
                or manifest.get("run_id") != self.run_id
                or manifest.get("configuration", {}).get("configuration_fingerprint")
                != self.config["configuration_fingerprint"]
                or manifest.get("input_snapshot", {}).get("input_snapshot_fingerprint")
                != self.snapshot["input_snapshot_fingerprint"]
            ):
                raise ExperimentalTrainingError("Run manifest identity is invalid.")
        else:
            manifest_core = {
                "schema_version": SCHEMA_VERSION,
                "semantic_version": SEMANTIC_VERSION,
                "training_mode": TRAINING_MODE,
                "run_id": self.run_id,
                "pid": os.getpid(),
                "command": _process_command(),
                "started_at_utc": self.now().astimezone(timezone.utc).isoformat(),
                "source_commit": self.source_commit,
                "trainer_code_fingerprint": self.code_fingerprint,
                "configuration": self.config,
                "input_snapshot": self.snapshot,
                "training_log_path": str(self.run_dir / "training.log"),
                "promotion_authority": "NONE",
                "live_authority": "NONE",
                "capital_authority": "NONE",
            }
            manifest = {**manifest_core, "run_manifest_fingerprint": fingerprint(manifest_core)}
            _write_checksummed_json(manifest_path, manifest)
        checkpoint_path = self.run_dir / "checkpoint.json"
        if checkpoint_path.exists():
            checkpoint = self._validate_checkpoint(_read_checksummed_json(checkpoint_path, "training checkpoint"))
        else:
            checkpoint = self._initial_checkpoint()
        inventory = entries or self.snapshot["partitions"]
        start = int(checkpoint["completed_partition_count"])
        if checkpoint["last_completed_partition"] is not None and inventory[start - 1]["partition"] != checkpoint["last_completed_partition"]:
            raise ExperimentalTrainingError("Checkpoint partition position is invalid.")
        for entry in inventory[start:]:
            self.process_partition(checkpoint, entry)
        model_core = {
            "schema_version": MODEL_SCHEMA_VERSION,
            "semantic_version": SEMANTIC_VERSION,
            "training_mode": TRAINING_MODE,
            "run_id": self.run_id,
            "feature_names": list(FEATURE_NAMES),
            "feature_definitions": FEATURE_DEFINITIONS,
            "intercept": checkpoint["model_intercept"],
            "weights": checkpoint["model_weights"],
            "algorithm": self.config["algorithm"],
            "learning_rate": LEARNING_RATE,
            "configuration_fingerprint": self.config["configuration_fingerprint"],
            "input_snapshot_fingerprint": self.snapshot["input_snapshot_fingerprint"],
            "trainer_code_fingerprint": self.code_fingerprint,
            "source_commit": self.source_commit,
            "promotion_authority": "NONE", "live_authority": "NONE", "capital_authority": "NONE",
        }
        model = {**model_core, "model_fingerprint": fingerprint(model_core)}
        _write_checksummed_json(self.run_dir / "final_model.json", model)
        report_core = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "semantic_version": SEMANTIC_VERSION,
            "training_mode": TRAINING_MODE,
            "run_id": self.run_id,
            "model_fingerprint": model["model_fingerprint"],
            "metrics": {name: _metric_report(checkpoint["metrics"][name]) for name in SPLITS},
            "splits": self.config["splits"],
            "input_snapshot_fingerprint": self.snapshot["input_snapshot_fingerprint"],
            "partition_inventory_fingerprint": self.snapshot["partition_inventory_fingerprint"],
            "provider_population_fingerprint": self.snapshot["provider_population_fingerprint"],
            "corporate_action_identity_enrichment_fingerprint": self.snapshot["corporate_action_identity_enrichment_fingerprint"],
            "corporate_action_identity_resolution_fingerprint": self.snapshot["corporate_action_identity_resolution_fingerprint"],
            "strict_dataset_eligibility_status": self.snapshot["strict_dataset_eligibility_status"],
            "unresolved_unbounded_corporate_action_count": self.snapshot["unresolved_unbounded_corporate_action_count"],
            "unresolved_unbounded_residual_classes": self.snapshot["unresolved_unbounded_residual_classes"],
            "calendar_repair_status": self.snapshot["calendar_repair_status"],
            "trainer_code_fingerprint": self.code_fingerprint,
            "source_commit": self.source_commit,
            "configuration_fingerprint": self.config["configuration_fingerprint"],
            "started_at_utc": manifest["started_at_utc"],
            "ended_at_utc": self.now().astimezone(timezone.utc).isoformat(),
            "restart_checkpoint_sequence": checkpoint["checkpoint_sequence"],
            "promotion_authority": "NONE", "live_authority": "NONE", "capital_authority": "NONE",
        }
        report = {**report_core, "report_fingerprint": fingerprint(report_core)}
        _write_checksummed_json(self.run_dir / "final_report.json", report)
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output-root", type=Path)
    args = parser.parse_args(argv)
    trainer: ExperimentalTrainer | None = None
    try:
        trainer = ExperimentalTrainer(args.root, args.output_root)
        report = trainer.run()
        status = {"status": "COMPLETE", "run_id": trainer.run_id, "report_fingerprint": report["report_fingerprint"], "ended_at_utc": datetime.now(timezone.utc).isoformat()}
        _write_checksummed_json(trainer.run_dir / "exit_status.json", status)
        print(json.dumps(status, sort_keys=True), flush=True)
        return 0
    except Exception as exc:
        if trainer is not None:
            status = {"status": "FAILED", "run_id": trainer.run_id, "exception_type": type(exc).__name__, "message": str(exc), "ended_at_utc": datetime.now(timezone.utc).isoformat()}
            _write_checksummed_json(trainer.run_dir / "exit_status.json", status)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
