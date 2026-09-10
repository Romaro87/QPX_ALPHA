from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qpx_bot.ml_historical_acquisition import (
    BAR_COLUMNS,
    Acquisition,
    atomic_bytes,
    atomic_json,
    build_security_master,
    batch_descriptor,
    encode_gzip_csv,
    fingerprint,
    LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION,
    sha256_path,
)
from qpx_bot.ml_historical_calendar_repair import HistoricalCalendarRepair
from qpx_bot.ml_historical_qualification import (
    MISSINGNESS_ATTESTATION,
    SOURCE_LEGACY,
    SOURCE_REPAIR,
    HistoricalQualificationError,
    audit_legacy_partition,
    qualify_historical_dataset,
    verify_training_eligibility_attestation,
)


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _asset(identity: str, symbol: str) -> dict[str, object]:
    return {
        "id": identity, "symbol": symbol, "class": "us_equity",
        "exchange": "NYSE", "status": "active", "tradable": True,
        "fractionable": False, "marginable": True, "shortable": True,
        "easy_to_borrow": False, "attributes": [],
    }


class FixtureClient:
    retry_count = 0

    def __init__(self, corporate_actions: dict[str, list[dict[str, object]]] | None = None) -> None:
        self.request_count = 0
        self.corporate_actions = corporate_actions or {}

    def request(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.request_count += 1
        if "bars" in url:
            stamp = (
                "2021-06-18T13:30:00Z"
                if params["start"].startswith("2021-06-18")
                else "2021-12-31T14:30:00Z"
            )
            return {"bars": {"AAA": [{"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]}, "next_page_token": None}
        return {"corporate_actions": self.corporate_actions, "next_page_token": None}


class V3FixtureClient(FixtureClient):
    def request(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.request_count += 1
        if "bars" in url:
            return {"bars": {"AAA": [{"t": "2026-09-01T13:30:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]}, "next_page_token": None}
        return {"corporate_actions": {}, "next_page_token": None}


class HistoricalQualificationTests(unittest.TestCase):
    def fixture(
        self, root: Path, *, base_rows: list[dict[str, str]] | None = None,
        corporate_actions: dict[str, list[dict[str, object]]] | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        assets = build_security_master(
            [_asset("a", "AAA"), _asset("d1", "DUP"), _asset("d2", "DUP")], [], NOW,
        )
        master = {"schema_version": 1, "provider": "alpaca", "assets": assets}
        master["manifest_fingerprint"] = fingerprint(master)
        master_path = root / "security_master/alpaca_us_equity_assets.json.gz"
        atomic_bytes(master_path, gzip.compress(json.dumps(master, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
        atomic_json(master_path.with_suffix(master_path.suffix + ".manifest.json"), {
            "sha256": sha256_path(master_path), "security_count": 3,
            "active_count": 3, "inactive_count": 0,
            "provenance_fingerprint": master["manifest_fingerprint"],
        })
        rows = list(base_rows or [])
        path = root / "bars_15m/year=2021/batch=00000.csv.gz"
        atomic_bytes(path, encode_gzip_csv(rows, BAR_COLUMNS))
        manifest: dict[str, object] = {
            "schema_version": 1, "partition": "year=2021/batch=00000",
            "provider": "alpaca", "feed": "sip", "adjustment": "raw",
            "resolution": "15Min", "row_count": len(rows),
            "security_count": len({row["provider_asset_id"] for row in rows}),
            "sha256": sha256_path(path), "request_fingerprint": "a" * 64,
            "first_observed_bar": min((row["market_timestamp"] for row in rows), default=None),
            "last_observed_bar": max((row["market_timestamp"] for row in rows), default=None),
            "first_session": min((row["session_date"] for row in rows), default=None),
            "last_session": max((row["session_date"] for row in rows), default=None),
            "synthetic_bars": False, "forward_fill": False,
            "timestamp_substitution": False, "completed_at_utc": NOW.isoformat(),
        }
        manifest["manifest_fingerprint"] = fingerprint(manifest)
        atomic_json(path.with_suffix(path.suffix + ".manifest.json"), manifest)
        item: dict[str, object] = {
            "year": 2021, "batch": 0,
            "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"],
        }
        state: dict[str, object] = {
            "schema_version": 1,
            "requested_range": {
                "requested_start": "2021-01-01",
                "actual_first_requested_session": "2021-01-04",
                "requested_end": "2021-12-31",
                "actual_last_completed_session": "2021-12-31",
            },
            "partitions": [item], "completed": ["year=2021/batch=00000"],
            "partitions_total": 1, "partitions_complete": 1,
            "rows_15m": len(rows), "bytes_stored": 0,
            "observed_ranges": {}, "unqueryable_symbols": [],
            "api_request_count": 0, "retry_count": 0, "failure_count": 0,
            "corporate_action_status": "PENDING",
            "training_eligibility": "ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE",
            "status": "PARTIAL", "stage": "BARS_15M",
            "started_at_utc": NOW.isoformat(),
        }
        client = FixtureClient(corporate_actions)
        HistoricalCalendarRepair(
            root, client, now=lambda: NOW,
            capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
        ).repair_partition(state, item)
        acquisition = Acquisition(
            root, client, now=lambda: NOW,
            capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False},
        )
        acquisition._state_defaults(state)
        acquisition.acquire_corporate_actions(state)
        acquisition.finalize(state)
        acquisition.save_state(state)
        return state, item

    @staticmethod
    def row(
        asset_id: str = "a", symbol: str = "AAA", *, close: str = "11",
        stamp: str = "2021-06-17T09:30:00-04:00",
    ) -> dict[str, str]:
        return {
            "provider_asset_id": asset_id, "observation_symbol": symbol,
            "market_timestamp": stamp,
            "session_date": stamp[:10], "open": "10", "high": "12",
            "low": "9", "close": close, "volume": "100", "provider": "alpaca",
            "feed": "sip", "adjustment": "raw", "request_fingerprint": "a" * 64,
        }

    def test_end_to_end_fixture_emits_deterministic_training_eligible_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            original = root / "bars_15m/year=2021/batch=00000.csv.gz"
            original_bytes = original.read_bytes()
            original_manifest_bytes = original.with_suffix(original.suffix + ".manifest.json").read_bytes()
            first = qualify_historical_dataset(root, observed_at=NOW)
            second = qualify_historical_dataset(root, observed_at=datetime(2026, 9, 5, tzinfo=timezone.utc))
            self.assertEqual(first["content"]["result"], "TRAINING_ELIGIBLE")
            self.assertEqual(first["qualification_fingerprint"], second["qualification_fingerprint"])
            self.assertEqual(
                {item["source_type"] for item in first["content"]["effective_dataset_inventory"]},
                {SOURCE_LEGACY, SOURCE_REPAIR},
            )
            self.assertEqual(first["content"]["missingness_attestation"], MISSINGNESS_ATTESTATION)
            self.assertFalse(first["content"]["synthetic_or_forward_filled_observations_permitted"])
            path = root / "qualification_evidence/attestations" / f"{first['qualification_fingerprint']}.json"
            self.assertEqual(
                verify_training_eligibility_attestation(root, path)["qualification_fingerprint"],
                first["qualification_fingerprint"],
            )
            self.assertFalse(any("train" in path.name.lower() for path in root.rglob("*") if path.is_file() and path.parent.name != "attestations"))
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(
                original.with_suffix(original.suffix + ".manifest.json").read_bytes(),
                original_manifest_bytes,
            )

    def test_incomplete_acquisition_is_not_training_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, _item = self.fixture(root)
            state["status"] = "PARTIAL"
            state["completed"] = []
            Acquisition(root, FixtureClient(), now=lambda: NOW).save_state(state)
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "NOT_TRAINING_ELIGIBLE")
            self.assertIn("ACQUISITION_INCOMPLETE", result["content"]["reasons"])

    def test_ambiguous_legacy_rows_are_explicitly_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ambiguous = self.row("d1", "DUP")
            state, item = self.fixture(root, base_rows=[ambiguous])
            from qpx_bot.historical_market_calendar import load_frozen_historical_calendar
            from qpx_bot.ml_historical_acquisition import load_provider_population
            audit, keys = audit_legacy_partition(
                root, state, item, load_provider_population(root),
                load_frozen_historical_calendar(), write=False,
            )
            self.assertEqual(audit["ambiguous_identity_excluded_row_count"], 1)
            self.assertEqual(keys, set())

    def test_invalid_legacy_accepted_row_creates_bounded_ineligible_scope(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, item = self.fixture(root, base_rows=[self.row(close="20")])
            from qpx_bot.historical_market_calendar import load_frozen_historical_calendar
            from qpx_bot.ml_historical_acquisition import load_provider_population
            audit, _keys = audit_legacy_partition(
                root, state, item, load_provider_population(root),
                load_frozen_historical_calendar(), write=False,
            )
            self.assertEqual(audit["result"], "BOUNDED_INELIGIBLE_SCOPE")
            self.assertEqual(audit["invalid_accepted_scopes"][0]["reason"], "INVALID_OHLC")

    def test_changed_bound_input_invalidates_prior_pass(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, _item = self.fixture(root)
            passed = qualify_historical_dataset(root, observed_at=NOW)
            path = root / "qualification_evidence/attestations" / f"{passed['qualification_fingerprint']}.json"
            state["observational_coverage_fingerprint"] = "0" * 64
            Acquisition(root, FixtureClient(), now=lambda: NOW).save_state(state)
            with self.assertRaisesRegex(HistoricalQualificationError, "inputs changed"):
                verify_training_eligibility_attestation(root, path)

    def test_duplicate_effective_observation_across_base_and_repair_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, base_rows=[self.row(stamp="2021-06-18T09:30:00-04:00")])
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "NOT_TRAINING_ELIGIBLE")
            self.assertIn(
                "DUPLICATE_EFFECTIVE_OBSERVATION:year=2021/batch=00000",
                result["content"]["reasons"],
            )

    def test_corrupt_provider_population_fails_closed_as_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "security_master/alpaca_us_equity_assets.json.gz.manifest.json").unlink()
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "NOT_TRAINING_ELIGIBLE")
            self.assertTrue(result["content"]["reasons"][0].startswith("EVIDENCE_VALIDATION_FAILED"))

    def test_corrupt_frozen_calendar_fails_closed_as_not_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with patch(
                "qpx_bot.ml_historical_qualification.load_frozen_historical_calendar",
                side_effect=RuntimeError("corrupt calendar"),
            ):
                result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "NOT_TRAINING_ELIGIBLE")
            self.assertTrue(result["content"]["reasons"][0].startswith("EVIDENCE_VALIDATION_FAILED"))

    def test_unbounded_unresolved_corporate_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, corporate_actions={
                "reorganizations": [{"id": "unknown-event", "symbol": "UNKNOWN"}],
            })
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "NOT_TRAINING_ELIGIBLE")
            self.assertIn("CORPORATE_ACTION_EVIDENCE_INVALID", result["content"]["reasons"])

    def test_ambiguous_corporate_identity_is_excluded_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root, corporate_actions={
                "name_changes": [{
                    "id": "conflicting-event", "symbol": "AAA",
                    "new_symbol": "DUP", "effective_date": "2021-01-04",
                }],
            })
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "TRAINING_ELIGIBLE")
            self.assertEqual(
                sum(item["eligible_row_count"] for item in result["content"]["effective_dataset_inventory"]),
                0,
            )

    def test_not_eligible_attestation_cannot_authorize_startup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, _item = self.fixture(root)
            state["status"] = "PARTIAL"
            Acquisition(root, FixtureClient(), now=lambda: NOW).save_state(state)
            result = qualify_historical_dataset(root, observed_at=NOW)
            path = root / "qualification_evidence/attestations" / f"{result['qualification_fingerprint']}.json"
            with self.assertRaisesRegex(HistoricalQualificationError, "does not prove"):
                verify_training_eligibility_attestation(root, path)

    def test_schema_v2_membership_enrichment_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state, item = self.fixture(root, base_rows=[self.row()])
            path = root / "bars_15m/year=2021/batch=00000.csv.gz"
            manifest_path = path.with_suffix(path.suffix + ".manifest.json")
            manifest = json.loads(manifest_path.read_text())
            descriptor = batch_descriptor(
                year=2021, start=datetime(2021, 1, 4).date(), end=datetime(2021, 12, 31).date(),
                symbols=item["symbols"], asset_ids=item["asset_ids"],
                provider_input_semantic_version=LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION,
            )
            manifest.update({
                "schema_version": 2,
                "year": 2021,
                "batch": 0,
                "requested_start": "2021-01-04",
                "requested_end": "2021-12-31",
                "timeframe": "15Min",
                "requested_security_count": 3,
                "ordered_provider_asset_ids": [member["provider_asset_id"] for member in descriptor["members"]],
                "ordered_symbol_mapping": descriptor["members"],
                "batch_fingerprint": descriptor["batch_fingerprint"],
                "acquisition_provenance_version": "QPX_ML_HISTORICAL_15M_V2",
                "provider_input_semantic_version": LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION,
                "actual_first_observation": self.row()["market_timestamp"],
                "actual_last_observation": self.row()["market_timestamp"],
                "page_count": 1,
            })
            manifest["manifest_fingerprint"] = fingerprint({
                key: value for key, value in manifest.items() if key != "manifest_fingerprint"
            })
            atomic_json(manifest_path, manifest)
            from qpx_bot.historical_market_calendar import load_frozen_historical_calendar
            from qpx_bot.ml_historical_acquisition import load_provider_population
            first, _ = audit_legacy_partition(
                root, state, item, load_provider_population(root),
                load_frozen_historical_calendar(), write=False,
            )
            second, _ = audit_legacy_partition(
                root, state, item, load_provider_population(root),
                load_frozen_historical_calendar(), write=False,
            )
            self.assertEqual(first, second)
            self.assertEqual(first["source_manifest_schema_version"], 2)

    def test_v3_partition_can_enter_effective_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets = build_security_master([_asset("a", "AAA")], [], NOW)
            master = {"schema_version": 1, "provider": "alpaca", "assets": assets}
            master["manifest_fingerprint"] = fingerprint(master)
            master_path = root / "security_master/alpaca_us_equity_assets.json.gz"
            atomic_bytes(master_path, gzip.compress(json.dumps(master, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
            atomic_json(master_path.with_suffix(master_path.suffix + ".manifest.json"), {
                "sha256": sha256_path(master_path), "security_count": 1,
                "active_count": 1, "inactive_count": 0,
                "provenance_fingerprint": master["manifest_fingerprint"],
            })
            item = {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}
            state = {
                "schema_version": 1, "requested_range": {
                    "requested_start": "2026-09-01", "actual_first_requested_session": "2026-09-01",
                    "requested_end": "2026-09-03", "actual_last_completed_session": "2026-09-03",
                },
                "partitions": [item], "completed": [], "partitions_total": 1,
                "partitions_complete": 0, "rows_15m": 0, "bytes_stored": 0,
                "observed_ranges": {}, "unqueryable_symbols": [], "api_request_count": 0,
                "retry_count": 0, "failure_count": 0, "corporate_action_status": "PENDING",
                "training_eligibility": "ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE",
                "status": "PARTIAL", "stage": "BARS_15M", "started_at_utc": NOW.isoformat(),
            }
            client = V3FixtureClient()
            acquisition = Acquisition(
                root, client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False},
            )
            acquisition._state_defaults(state)
            acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(state, item)
            acquisition.acquire_corporate_actions(state)
            acquisition.finalize(state)
            acquisition.save_state(state)
            result = qualify_historical_dataset(root, observed_at=NOW)
            self.assertEqual(result["content"]["result"], "TRAINING_ELIGIBLE")
            self.assertEqual(
                result["content"]["effective_dataset_inventory"][0]["source_type"],
                "V3_ACCEPTED_DATA",
            )


if __name__ == "__main__":
    unittest.main()
