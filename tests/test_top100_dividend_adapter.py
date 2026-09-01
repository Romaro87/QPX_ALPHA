from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from qpx_bot.accelerators.dividend_opportunity import canonical_fingerprint
from qpx_bot.research.top100_dividend_adapter import (
    build_adapter_dataset,
    validate_causal_boundary,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research_data" / "qpx_top100_dividend_actions_v1"


class Top100DividendAdapterTests(unittest.TestCase):
    @unittest.skipUnless(
        (SOURCE / "dataset_manifest.json").is_file(),
        "requires the local governed Top-100 dividend-action dataset",
    )
    def test_real_source_is_deterministic_and_fail_closed_on_availability(self):
        first = build_adapter_dataset(SOURCE)
        second = build_adapter_dataset(SOURCE)
        self.assertEqual(first, second)
        self.assertEqual(first["source_event_count"], 142)
        self.assertEqual(first["ordinary_post_ex_structurally_eligible_count"], 124)
        self.assertEqual(first["classification_counts"], {
            "ORDINARY_CASH_DIVIDEND": 124,
            "RETURN_OF_CAPITAL": 1,
            "SPECIAL_CASH_DIVIDEND": 17,
        })
        self.assertFalse(first["price_data_joined"])
        self.assertFalse(first["economic_replay_run"])
        self.assertTrue(all(
            event["information_available_time"] is None
            and not event["historical_replay_ready"]
            for event in first["events"]
        ))
        visn = next(event for event in first["events"] if event["symbol"] == "VISN")
        self.assertEqual(visn["classification"], "RETURN_OF_CAPITAL")
        self.assertFalse(visn["ordinary_post_ex_eligible"])

    @unittest.skipUnless(
        (SOURCE / "dataset_manifest.json").is_file(),
        "requires the local governed Top-100 dividend-action dataset",
    )
    def test_ex_date_convention_is_new_york_session_open(self):
        result = build_adapter_dataset(SOURCE)
        winter = next(event for event in result["events"] if event["ex_date"] == "2024-03-14")
        self.assertEqual(winter["event_effective_time"], "2024-03-14T09:30:00-04:00")
        self.assertTrue(winter["event_effectiveness_is_experiment_assumption"])

    @unittest.skipUnless(
        (SOURCE / "dataset_manifest.json").is_file(),
        "requires the local governed Top-100 dividend-action dataset",
    )
    def test_missing_identity_and_unsupported_subtype_fail_closed(self):
        with TemporaryDirectory() as directory:
            target = Path(directory)
            for name in ("dataset_manifest.json", "provenance.json", "dividend_actions.jsonl"):
                (target / name).write_bytes((SOURCE / name).read_bytes())
            events = [json.loads(line) for line in (target / "dividend_actions.jsonl").read_text().splitlines()]
            events[0]["provider_event_id"] = None
            event_core = {
                key: value for key, value in events[0].items()
                if key != "event_fingerprint"
            }
            events[0]["event_fingerprint"] = canonical_fingerprint(event_core)
            text = "\n".join(json.dumps(item, sort_keys=True, separators=(",", ":")) for item in events) + "\n"
            (target / "dividend_actions.jsonl").write_text(text, encoding="utf-8")
            manifest = json.loads((target / "dataset_manifest.json").read_text())
            manifest["normalized_sha256"] = hashlib.sha256(text.encode()).hexdigest()
            manifest_core = {
                key: value for key, value in manifest.items()
                if key != "dataset_fingerprint"
            }
            manifest["dataset_fingerprint"] = canonical_fingerprint(manifest_core)
            (target / "dataset_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Alpaca event identity"):
                build_adapter_dataset(target)

    def test_future_information_is_rejected(self):
        evaluation = datetime(2025, 1, 2, 15, tzinfo=timezone.utc)
        with self.assertRaisesRegex(ValueError, "UNKNOWN"):
            validate_causal_boundary(
                information_available_time=None,
                evidence_observed_at=None,
                evaluation_timestamps=(evaluation,),
            )
        with self.assertRaisesRegex(ValueError, "Future information"):
            validate_causal_boundary(
                information_available_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
                evidence_observed_at=datetime(2025, 1, 3, tzinfo=timezone.utc),
                evaluation_timestamps=(evaluation,),
            )


if __name__ == "__main__":
    unittest.main()
