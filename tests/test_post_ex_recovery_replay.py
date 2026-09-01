from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qpx_bot.accelerators.dividend_opportunity import canonical_fingerprint
from qpx_bot.research.post_ex_recovery_replay import run_post_ex_recovery_replay


HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


class PostExRecoveryReplayTests(unittest.TestCase):
    def dataset(self):
        return {
            "events": [{
                "symbol": "TEST",
                "corporate_action_event_id": HEX_A,
                "event_effective_time": "2026-01-02T14:30:00+00:00",
                "information_available_time": "2025-12-30T12:00:00+00:00",
                "causal_input_fingerprint": HEX_B,
                "ex_dividend_reference_price": 100.0,
                "evidence": {
                    "identity": "event-evidence-v1",
                    "source_identity": "corporate-action-source-v1",
                    "source_fingerprint": HEX_C,
                    "provenance_identity": "test-provenance-v1",
                    "observed_at": "2025-12-30T12:00:00+00:00",
                },
                "observations": [
                    {
                        "observed_at": "2026-01-02T15:00:00+00:00",
                        "information_available_at": "2026-01-02T15:00:01+00:00",
                        "price": 101.0,
                        "causal_input_fingerprint": HEX_A,
                    },
                    {
                        "observed_at": "2026-01-02T16:00:00+00:00",
                        "information_available_at": "2026-01-02T16:00:01+00:00",
                        "price": 105.0,
                        "causal_input_fingerprint": HEX_B,
                    },
                ],
                "evaluation_timestamps": [
                    "2026-01-02T15:30:00+00:00",
                    "2026-01-02T16:30:00+00:00",
                ],
            }]
        }

    def config(self):
        return {
            "enabled": True,
            "accelerator_version": "1.0.0",
            "configuration_version": "focused-replay-test-v1",
            "recovery_threshold": 0.05,
            "evaluation_window_seconds": 2592000.0,
            "lookback_window_seconds": 2592000.0,
            "research_only": True,
            "capital_authority": False,
            "execution_authority": False,
            "qualification_authority": False,
            "promotion_authority": False,
        }

    def manifest(self, dataset, config):
        return {
            "experiment_identity": "post-ex-causal-validation-test-v1",
            "research_only": True,
            "purpose": "CAUSAL_VALIDATION_ONLY",
            "dataset": {
                "identity": "synthetic-focused-test-data-v1",
                "path": "dataset.json",
                "fingerprint": canonical_fingerprint(dataset),
                "provenance_identity": "test-provenance-v1",
            },
            "reference_price_semantics": {
                "identity": "synthetic-explicit-reference-v1",
                "description": "Explicit synthetic reference used only by focused tests.",
            },
            "universe": {"symbols": ["TEST"]},
            "interval": {
                "start": "2026-01-01T00:00:00+00:00",
                "end": "2026-02-01T00:00:00+00:00",
            },
            "evaluation_schedule": {
                "mode": "EXPLICIT_PER_EVENT",
                "identity": "synthetic-explicit-evaluations-v1",
            },
            "post_ex_recovery_configuration": {
                "path": "config.json",
                "fingerprint": canonical_fingerprint(config),
            },
        }

    def write_case(self, root: Path, dataset=None, config=None, manifest=None):
        dataset = dataset if dataset is not None else self.dataset()
        config = config if config is not None else self.config()
        manifest = manifest if manifest is not None else self.manifest(dataset, config)
        (root / "dataset.json").write_text(json.dumps(dataset), encoding="utf-8")
        (root / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return root / "manifest.json"

    def test_manifest_replay_is_deterministic_and_prefix_causal(self):
        with TemporaryDirectory() as directory:
            path = self.write_case(Path(directory))
            first = run_post_ex_recovery_replay(path)
            second = run_post_ex_recovery_replay(path)
        self.assertEqual(first, second)
        self.assertTrue(first.causal_validation_pass)
        self.assertEqual(first.evaluation_count, 2)
        self.assertEqual(
            [item["opportunity_state"] for item in first.decisions],
            ["NO_OPPORTUNITY", "OPPORTUNITY_IDENTIFIED"],
        )
        self.assertEqual(first.decisions[0]["latest_observation_price"], 101.0)
        self.assertEqual(first.decisions[1]["latest_observation_price"], 105.0)
        self.assertEqual(len(first.result_fingerprint), 64)

    def test_manifest_requires_complete_experiment_identity_and_semantics(self):
        dataset = self.dataset()
        config = self.config()
        manifest = self.manifest(dataset, config)
        del manifest["reference_price_semantics"]
        with TemporaryDirectory() as directory:
            path = self.write_case(Path(directory), dataset, config, manifest)
            with self.assertRaisesRegex(ValueError, "reference_price_semantics"):
                run_post_ex_recovery_replay(path)

    def test_dataset_and_configuration_fingerprints_fail_closed(self):
        dataset = self.dataset()
        config = self.config()
        manifest = self.manifest(dataset, config)
        manifest["dataset"]["fingerprint"] = HEX_A
        with TemporaryDirectory() as directory:
            path = self.write_case(Path(directory), dataset, config, manifest)
            with self.assertRaisesRegex(ValueError, "dataset fingerprint mismatch"):
                run_post_ex_recovery_replay(path)

    def test_future_known_dividend_information_fails_closed(self):
        dataset = self.dataset()
        dataset["events"][0]["information_available_time"] = "2026-01-03T00:00:00+00:00"
        config = self.config()
        with TemporaryDirectory() as directory:
            path = self.write_case(Path(directory), dataset, config)
            with self.assertRaisesRegex(ValueError, "Future-known dividend information"):
                run_post_ex_recovery_replay(path)

    def test_nonchronological_observations_fail_closed(self):
        dataset = self.dataset()
        dataset["events"][0]["observations"] = list(
            reversed(dataset["events"][0]["observations"])
        )
        config = self.config()
        with TemporaryDirectory() as directory:
            path = self.write_case(Path(directory), dataset, config)
            with self.assertRaisesRegex(ValueError, "strictly chronological"):
                run_post_ex_recovery_replay(path)

    def test_result_has_no_authority_or_action(self):
        with TemporaryDirectory() as directory:
            result = run_post_ex_recovery_replay(self.write_case(Path(directory)))
        for decision in result.decisions:
            self.assertEqual(decision["proposed_action"], "NO_ACTION")
            self.assertIsNone(decision["proposed_capital"])
            for field in (
                "capital_authority", "execution_authority",
                "qualification_authority", "promotion_authority",
            ):
                self.assertFalse(decision[field])


if __name__ == "__main__":
    unittest.main()
