import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qpx_bot.ml_experimental_causal_baseline import (
    ExperimentalTrainer,
    ExperimentalTrainingError,
    _configuration,
    canonical_partition_order,
    feature_vector,
    sgd_update,
    stable_transform,
)


NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def bar(index, *, asset="a", day="2024-01-02", close=None, minute=None):
    value = float(close if close is not None else 100 + index)
    minute = index * 15 if minute is None else minute
    hour, minute = divmod(9 * 60 + 30 + minute, 60)
    return {
        "provider_asset_id": asset,
        "market_timestamp": f"{day}T{hour:02d}:{minute:02d}:00+00:00",
        "session_date": day,
        "open": value - 0.5,
        "high": value + 1.0,
        "low": value - 1.0,
        "close": value,
        "volume": 1000 + index,
    }


def snapshot(entries):
    return {
        "input_snapshot_fingerprint": "i" * 64,
        "partition_inventory_fingerprint": "p" * 64,
        "provider_population_fingerprint": "o" * 64,
        "corporate_action_identity_enrichment_fingerprint": "e" * 64,
        "corporate_action_identity_resolution_fingerprint": "r" * 64,
        "strict_dataset_eligibility_status": "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE",
        "unresolved_unbounded_corporate_action_count": 22498,
        "unresolved_unbounded_residual_classes": {
            "NO_CUSIP_OR_ISIN_SUPPLIED": 16626,
            "NO_PROVIDER_ASSET_LOOKUP_RESULT": 5625,
            "MIXED_MATCH_AND_NOT_FOUND_IDENTITY_EVIDENCE": 247,
        },
        "calendar_repair_status": "NOT_RUN",
        "partitions": entries,
    }


def entry(partition, phase="TRAIN"):
    year = int(partition[5:9])
    batch = int(partition.rsplit("=", 1)[1])
    return {
        "partition": partition, "year": year, "batch": batch,
        "phase": phase, "data_path": f"bars_15m/{partition}.csv.gz",
    }


def write_rows(root, item, rows):
    path = root / item["data_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "provider_asset_id", "market_timestamp", "session_date",
            "open", "high", "low", "close", "volume",
        ))
        writer.writeheader()
        writer.writerows(rows)


class ExperimentalCausalBaselineTests(unittest.TestCase):
    def trainer(self, root, entries, output=None):
        with patch(
            "qpx_bot.ml_experimental_causal_baseline.build_input_snapshot",
            return_value=snapshot(entries),
        ):
            return ExperimentalTrainer(
                root, output_root=output, now=lambda: NOW,
                source_commit="1" * 40,
            )

    def test_feature_causality_and_transform_are_deterministic(self):
        history = [bar(index) for index in range(9)]
        expected = feature_vector(history)
        self.assertEqual(expected, feature_vector(history))
        successor = bar(9, close=9999)
        self.assertEqual(expected, feature_vector(history))
        self.assertNotIn(successor["close"], expected)
        self.assertEqual(stable_transform(2.0), 2.0 / 3.0)
        self.assertEqual(stable_transform(-2.0), -2.0 / 3.0)

    def test_known_sgd_update_is_deterministic(self):
        result = sgd_update(0.0, [0.0] * 7, (1.0, 0, 0, 0, 0, 0, 0), 1)
        self.assertEqual(result, (0.005, [0.005, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 0.5))

    def test_session_gap_missing_successor_and_equal_close_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = entry("year=2024/batch=00000")
            trainer = self.trainer(root, [item]); checkpoint = trainer._initial_checkpoint()
            rows = [bar(index) for index in range(9)]
            rows += [bar(0, day="2024-01-03", close=108), bar(1, day="2024-01-03", close=108)]
            trainer.process_partition(checkpoint, item, rows)
            metric = checkpoint["metrics"]["TRAIN"]
            self.assertEqual(metric["skipped_gap_nonconsecutive"], 1)
            self.assertEqual(metric["skipped_flat"], 1)
            self.assertEqual(metric["samples"], 0)

    def test_missing_same_session_15m_successor_is_not_fabricated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = entry("year=2024/batch=00000")
            trainer = self.trainer(root, [item]); checkpoint = trainer._initial_checkpoint()
            rows = [bar(index) for index in range(9)]
            rows.append(bar(10))
            trainer.process_partition(checkpoint, item, rows)
            metric = checkpoint["metrics"]["TRAIN"]
            self.assertEqual(metric["skipped_gap_nonconsecutive"], 1)
            self.assertEqual(metric["samples"], 0)

    def test_validation_and_test_never_update_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            validation = entry("year=2025/batch=00000", "VALIDATION")
            test = entry("year=2026/batch=00000", "TEST")
            trainer = self.trainer(root, [validation, test]); checkpoint = trainer._initial_checkpoint()
            trainer.process_partition(checkpoint, validation, [bar(i, day="2025-01-02") for i in range(10)])
            trainer.process_partition(checkpoint, test, [bar(i, day="2026-01-02") for i in range(10)])
            self.assertEqual(checkpoint["model_intercept"], 0.0)
            self.assertEqual(checkpoint["model_weights"], [0.0] * 7)
            self.assertEqual(checkpoint["metrics"]["VALIDATION"]["samples"], 1)
            self.assertGreater(checkpoint["metrics"]["TEST"]["samples"], 0)

    def test_canonical_partition_order(self):
        values = ["year=2026/batch=00001", "year=2016/batch=00001", "year=2016/batch=00000"]
        self.assertEqual(canonical_partition_order(values), [
            "year=2016/batch=00000", "year=2016/batch=00001", "year=2026/batch=00001",
        ])

    def test_checkpoint_only_after_partition_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = entry("year=2024/batch=00000")
            trainer = self.trainer(root, [item]); checkpoint = trainer._initial_checkpoint()

            def interrupted():
                yield bar(0)
                raise RuntimeError("interrupted")

            with self.assertRaisesRegex(RuntimeError, "interrupted"):
                trainer.process_partition(checkpoint, item, interrupted())
            self.assertFalse((trainer.run_dir / "checkpoint.json").exists())
            self.assertEqual(checkpoint["completed_partition_count"], 0)

    def test_restart_resumes_after_last_completed_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = entry("year=2024/batch=00000")
            second = entry("year=2024/batch=00001")
            write_rows(root, first, [bar(i, asset="a") for i in range(10)])
            write_rows(root, second, [bar(i, asset="b") for i in range(10)])
            trainer = self.trainer(root, [first, second]); checkpoint = trainer._initial_checkpoint()
            trainer.process_partition(checkpoint, first)
            resumed = self.trainer(root, [first, second])
            report = resumed.run(entries=[first, second])
            self.assertEqual(report["restart_checkpoint_sequence"], 2)
            saved = json.loads((resumed.run_dir / "checkpoint.json").read_text())
            self.assertEqual(saved["completed_partition_count"], 2)

    def test_checkpoint_fingerprint_or_config_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = entry("year=2024/batch=00000")
            write_rows(root, item, [bar(i) for i in range(10)])
            trainer = self.trainer(root, [item]); trainer.run(entries=[item])
            path = trainer.run_dir / "checkpoint.json"
            value = json.loads(path.read_text()); value["configuration_fingerprint"] = "x" * 64
            path.write_text(json.dumps(value))
            resumed = self.trainer(root, [item])
            with self.assertRaisesRegex(ExperimentalTrainingError, "corrupt|identity"):
                resumed.run(entries=[item])

    def test_same_inputs_produce_same_model_and_zero_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = entry("year=2024/batch=00000")
            write_rows(root, item, [bar(i) for i in range(10)])
            first = self.trainer(root, [item], root / "one"); first.run(entries=[item])
            second = self.trainer(root, [item], root / "two"); second.run(entries=[item])
            a = json.loads((first.run_dir / "final_model.json").read_text())
            b = json.loads((second.run_dir / "final_model.json").read_text())
            self.assertEqual(a["model_fingerprint"], b["model_fingerprint"])
            self.assertEqual(a["weights"], b["weights"])
            self.assertEqual(a["promotion_authority"], "NONE")
            self.assertEqual(a["live_authority"], "NONE")
            self.assertEqual(a["capital_authority"], "NONE")
            self.assertEqual(first.snapshot["strict_dataset_eligibility_status"], "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE")

    def test_configuration_is_explicit_experimental_contract(self):
        config = _configuration()
        self.assertEqual(config["training_mode"], "EXPERIMENTAL_UNQUALIFIED_TRAINING")
        self.assertEqual(config["learning_rate"], 0.01)
        self.assertEqual(config["initial_weights"], [0.0] * 7)
        self.assertEqual(config["promotion_authority"], "NONE")


if __name__ == "__main__":
    unittest.main()
