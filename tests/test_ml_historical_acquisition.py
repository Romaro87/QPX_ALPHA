from __future__ import annotations

import gzip
import errno
import json
import socket
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qpx_bot.ml_historical_acquisition import (
    ACQUISITION_PROVENANCE_VERSION, ADJUSTMENT, BAR_COLUMNS, BARS_URL,
    CHECKPOINT_SCHEMA_VERSION, DEFAULT_ROOT, FEED, PAGE_LIMIT,
    PROVIDER_INPUT_SEMANTIC_VERSION, QUALIFIED_FROZEN_ROOT, TIMEFRAME,
    Acquisition, ProviderError, RateGovernor, aggregate_bars, atomic_bytes,
    atomic_json, batch_descriptor, build_security_master, calculate_range,
    canonical_provider_asset_id, encode_gzip_csv, fingerprint, initial_estimate,
    classify_transport_error, normalize_corporate_action, page_evidence, read_gzip_csv, sha256_path,
    status, validate_bar,
)


NOW = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)


def asset(identity="id-a", symbol="AAA", state="active"):
    return {"id": identity, "symbol": symbol, "class": "us_equity", "exchange": "NYSE", "status": state, "tradable": state == "active", "fractionable": False, "marginable": True, "shortable": True, "easy_to_borrow": False, "attributes": []}


def raw_bar(stamp="2026-09-03T13:30:00Z"):
    return {"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}


class FakeClient:
    def __init__(self, pages=None):
        self.pages = list(pages or []); self.request_count = 0; self.retry_count = 0; self.calls = []
    def assets(self, state):
        self.request_count += 1
        return [asset("active-id", "AAA", "active")] if state == "active" else [asset("inactive-id", "OLD", "inactive")]
    def request(self, url, params):
        self.request_count += 1; self.calls.append((url, dict(params)))
        if url == BARS_URL:
            return self.pages.pop(0) if self.pages else {"bars": {}, "next_page_token": None}
        return {"corporate_actions": {}, "next_page_token": None}


class ScriptedAcquisition(Acquisition):
    def __init__(self, root, state, outcomes, *, now=lambda: NOW, sleep=lambda _seconds: None):
        super().__init__(root, FakeClient(), now=now, sleep=sleep, monotonic=lambda: 0.0)
        self.test_state = state; self.outcomes = list(outcomes); self.snapshots = []; self.calls = 0

    def load_state(self):
        return self.test_state

    def save_state(self, state):
        self.snapshots.append(json.loads(json.dumps(state)))

    def acquire_partition(self, state, item):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        part_id = f"year={item['year']}/batch={int(item['batch']):05d}"
        state["completed"].append(part_id); state["partitions_complete"] += 1


def run_state():
    return {
        "status": "PARTIAL", "requested_range": {}, "completed": [],
        "partitions": [{"year": 2017, "batch": 458}], "partitions_complete": 0,
        "partitions_total": 1, "rows_15m": 0, "bytes_stored": 0,
        "api_request_count": 0, "retry_count": 0, "failure_count": 0,
        "unqueryable_symbols": [], "started_at_utc": NOW.isoformat(),
    }


class InvalidThenValidClient(FakeClient):
    def request(self, url, params):
        self.request_count += 1
        if "BAD" in params.get("symbols", ""):
            raise ProviderError('Alpaca HTTP 400: {"message":"invalid symbol: BAD"}', status=400)
        return {"bars": {}, "next_page_token": None}


class RejectedTokenClient(FakeClient):
    def request(self, url, params):
        self.request_count += 1; self.calls.append((url, dict(params)))
        if params.get("page_token"):
            raise ProviderError("expired page token", status=400)
        return {"bars": {}, "next_page_token": None}


def resume_identity(symbols=("AAA",), asset_ids=("a",)):
    start, end = date(2026, 9, 1), date(2026, 9, 3)
    descriptor = batch_descriptor(year=2026, start=start, end=end, symbols=symbols, asset_ids=asset_ids)
    request = {"symbols": ",".join(symbols), "timeframe": TIMEFRAME, "start": "2026-09-01T00:00:00Z", "end": "2026-09-04T00:00:00Z", "limit": str(PAGE_LIMIT), "feed": FEED, "adjustment": ADJUSTMENT, "sort": "asc"}
    request_fp = fingerprint({"provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION, "batch_fingerprint": descriptor["batch_fingerprint"], "request": request})
    return descriptor, request_fp


def write_v2_resume(root: Path, *, token="resume", request_fp=None, batch_fp=None, corrupt=False):
    descriptor, expected_request = resume_identity()
    request_fp = request_fp or expected_request; batch_fp = batch_fp or descriptor["batch_fingerprint"]
    page_root = root / "acquisition_state/pages/year=2026/batch=00000"; page_root.mkdir(parents=True)
    fragment = page_root / "page-000001.csv.gz"
    row = validate_bar(raw_bar(), "AAA", "a", request_fp, date(2026, 9, 1), date(2026, 9, 3), NOW)
    atomic_bytes(fragment, encode_gzip_csv([row], BAR_COLUMNS))
    evidence = page_evidence(fragment, page=1, row_count=1, request_fingerprint=request_fp, batch_fingerprint=batch_fp)
    if corrupt: evidence["sha256"] = "0" * 64
    atomic_json(fragment.with_suffix(fragment.suffix + ".manifest.json"), evidence)
    checkpoint = {"schema_version": CHECKPOINT_SCHEMA_VERSION, "year": 2026, "batch": 0, "batch_fingerprint": batch_fp, "requested_start": "2026-09-01", "requested_end": "2026-09-03", "page": 1, "next_page_token": token, "last_completed_boundary": ["a", row["market_timestamp"]], "invalid_rows": 0, "request_fingerprint": request_fp, "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION}
    checkpoint["checkpoint_fingerprint"] = fingerprint(checkpoint)
    atomic_json(page_root / "checkpoint.json", checkpoint)
    return page_root


class MLHistoricalAcquisitionTests(unittest.TestCase):
    @staticmethod
    def partition_state():
        return {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "unqueryable_symbols": [], "rows_15m": 0, "api_request_count": 0, "retry_count": 0}

    def test_enumeration_order_does_not_change_batch_membership(self):
        values = [asset("00000000-0000-0000-0000-000000000002", "BBB"), asset("00000000-0000-0000-0000-000000000001", "AAA")]
        first = build_security_master(values, [], NOW)
        second = build_security_master(reversed(values), [], NOW)
        self.assertEqual(first, second)

    def test_uuid_provider_identity_is_canonical(self):
        self.assertEqual(canonical_provider_asset_id("00000000-0000-0000-0000-00000000000A"), "00000000-0000-0000-0000-00000000000a")
        self.assertEqual(canonical_provider_asset_id("provider:CaseSensitive"), "provider:CaseSensitive")

    def test_batch_fingerprint_is_deterministic_and_order_independent(self):
        a = batch_descriptor(year=2026, start=date(2026, 1, 1), end=date(2026, 9, 3), symbols=["B", "A"], asset_ids=["b", "a"])
        b = batch_descriptor(year=2026, start=date(2026, 1, 1), end=date(2026, 9, 3), symbols=["A", "B"], asset_ids=["a", "b"])
        self.assertEqual(a["batch_fingerprint"], b["batch_fingerprint"])

    def test_membership_change_changes_batch_fingerprint(self):
        a = batch_descriptor(year=2026, start=date(2026, 1, 1), end=date(2026, 9, 3), symbols=["A"], asset_ids=["a"])
        b = batch_descriptor(year=2026, start=date(2026, 1, 1), end=date(2026, 9, 3), symbols=["B"], asset_ids=["b"])
        self.assertNotEqual(a["batch_fingerprint"], b["batch_fingerprint"])

    def test_exact_ten_year_range_and_valid_start(self):
        result = calculate_range(NOW)
        self.assertEqual(result["requested_start"], "2016-09-03")
        self.assertEqual(result["actual_first_requested_session"], "2016-09-06")
        self.assertEqual(result["requested_end"], "2026-09-03")

    def test_latest_completed_endpoint_excludes_incomplete_session(self):
        result = calculate_range(datetime(2026, 9, 3, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(result["requested_end"], "2026-09-02")

    def test_security_master_preserves_active_and_inactive(self):
        master = build_security_master([asset()], [asset("id-z", "ZZZ", "inactive")], NOW)
        self.assertEqual(len(master), 2); self.assertEqual(sum(not x["active"] for x in master), 1)

    def test_provider_identity_deduplicates_symbol_records(self):
        master = build_security_master([asset("same", "NEW")], [asset("same", "OLD", "inactive")], NOW)
        self.assertEqual([(x["provider_asset_id"], x["canonical_current_symbol"]) for x in master], [("same", "NEW")])

    def test_master_does_not_invent_listing_dates(self):
        item = build_security_master([asset()], [], NOW)[0]
        self.assertIsNone(item["authoritative_listing_date"]); self.assertIsNone(item["authoritative_delisting_date"])

    def test_valid_regular_15m_bar(self):
        row = validate_bar(raw_bar(), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW)
        self.assertEqual(row["provider_asset_id"], "id-a"); self.assertEqual(row["feed"], FEED)

    def test_incomplete_future_bar_rejected(self):
        self.assertIsNone(validate_bar(raw_bar("2026-09-03T22:15:00Z"), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW))

    def test_off_grid_bar_rejected(self):
        self.assertIsNone(validate_bar(raw_bar("2026-09-03T13:31:00Z"), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW))

    def test_outside_regular_session_rejected(self):
        self.assertIsNone(validate_bar(raw_bar("2026-09-03T12:00:00Z"), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW))

    def test_no_synthetic_or_fill_code_in_row(self):
        row = validate_bar(raw_bar(), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW)
        self.assertNotIn("synthetic", row); self.assertNotIn("filled", row)

    def test_deterministic_gzip_partition(self):
        row = validate_bar(raw_bar(), "AAA", "id-a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW)
        self.assertEqual(encode_gzip_csv([row], tuple(row)), encode_gzip_csv([row], tuple(row)))

    def test_atomic_partition_write(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "x" / "p.gz"; atomic_bytes(path, b"abc")
            self.assertEqual(path.read_bytes(), b"abc"); self.assertFalse(path.with_suffix(".tmp").exists())

    def test_partition_checksum(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "p"; path.write_bytes(b"abc")
            self.assertEqual(sha256_path(path), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_duplicate_prevention_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient([{"bars": {"AAA": [raw_bar(), raw_bar()]}, "next_page_token": None}])
            acquisition = Acquisition(Path(folder), client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            with self.assertRaisesRegex(RuntimeError, "Duplicate"):
                acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["id-a"]})

    def test_provider_batch_is_single_symbol_list_request(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(Path(folder), client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA", "BBB"], "asset_ids": ["a", "b"]})
            self.assertEqual(client.request_count, 1)

    def test_final_manifest_contains_exact_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); client = FakeClient([{"bars": {"AAA": [raw_bar()]}, "next_page_token": None}])
            acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            manifest = json.loads((root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json").read_text())
            self.assertEqual(manifest["ordered_provider_asset_ids"], ["a"])
            self.assertEqual(manifest["ordered_symbol_mapping"], [{"provider_asset_id": "a", "canonical_symbol": "AAA"}])
            self.assertEqual(manifest["requested_start"], "2026-09-01")

    def test_matching_checkpoint_fingerprint_resumes_with_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root)
            client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(client.calls[0][1]["page_token"], "resume")

    def test_mismatched_request_fingerprint_rebuilds_without_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root, request_fp="f" * 64)
            client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertNotIn("page_token", client.calls[0][1]); self.assertTrue(list((root / "acquisition_state/rebuild_evidence").iterdir()))

    def test_missing_token_finalizes_valid_pages_without_provider_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root, token=None)
            client = FakeClient(); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(client.request_count, 0)

    def test_rejected_token_rebuilds_only_current_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root)
            client = RejectedTokenClient(); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertIn("page_token", client.calls[0][1]); self.assertNotIn("page_token", client.calls[1][1])

    def test_completed_partition_is_not_redownloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); destination = root / "bars_15m/year=2026/batch=00000.csv.gz"; atomic_bytes(destination, b"done")
            atomic_json(destination.with_suffix(destination.suffix + ".manifest.json"), {"sha256": sha256_path(destination)})
            client = FakeClient(); acquisition = Acquisition(root, client, now=lambda: NOW)
            state = self.partition_state(); acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(client.request_count, 0); self.assertEqual(destination.read_bytes(), b"done")

    def test_corrupt_page_fragment_is_rejected_and_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root, corrupt=True)
            client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertNotIn("page_token", client.calls[0][1])

    def test_valid_page_fragment_checksum_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_v2_resume(root, token=None); acquisition = Acquisition(root, FakeClient(), now=lambda: NOW)
            descriptor, request_fp = resume_identity()
            page, token = acquisition._validated_resume(root / "acquisition_state/pages/year=2026/batch=00000", expected_request_fingerprint=request_fp, expected_batch_fingerprint=descriptor["batch_fingerprint"], descriptor=descriptor)
            self.assertEqual((page, token), (1, None))

    def test_pages_from_different_requests_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); page_root = write_v2_resume(root)
            manifest = next(page_root.glob("*.csv.gz.manifest.json")); evidence = json.loads(manifest.read_text()); evidence["request_fingerprint"] = "0" * 64; atomic_json(manifest, evidence)
            client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW); acquisition.disk_gate = lambda: 900_000_000_000
            acquisition.acquire_partition(self.partition_state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertNotIn("page_token", client.calls[0][1])

    def test_provider_rejected_symbol_is_bounded_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            client = InvalidThenValidClient(); acquisition = Acquisition(Path(folder), client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "unqueryable_symbols": [], "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["BAD", "AAA"], "asset_ids": ["bad-id", "good-id"]})
            self.assertEqual(state["unqueryable_symbols"][0]["provider_asset_id"], "bad-id")
            self.assertEqual(client.request_count, 2)

    def test_legacy_checkpoint_is_explicitly_rebuilt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"; page_root.mkdir(parents=True)
            (page_root / "checkpoint.json").write_text(json.dumps({"page": 1, "next_page_token": "resume", "invalid_rows": 0, "request_fingerprint": "x"}))
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            evidence = list((root / "acquisition_state/rebuild_evidence").rglob("rebuild_reason.json"))
            self.assertEqual(client.request_count, 1); self.assertEqual(json.loads(evidence[0].read_text())["reason"], "LEGACY_CHECKPOINT_SCHEMA_REBUILD")

    def test_rate_governor_waits_globally(self):
        values = iter([0.0, 0.0, 0.1, 0.5]); sleeps=[]
        governor = RateGovernor(60, clock=lambda: next(values), sleep=sleeps.append); governor.wait(); governor.wait()
        self.assertTrue(sleeps and sleeps[0] > 0)

    def test_systemic_provider_failure_is_explicit(self):
        error = ProviderError("auth", status=401, systemic=True)
        self.assertTrue(error.systemic); self.assertEqual(error.status, 401)

    def test_dns_outage_waits_then_resumes_without_permanent_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            sleeps = []
            transient = ProviderError("temporary lookup", transient=True, failure_class="DNS_RESOLUTION_FAILURE")
            acquisition = ScriptedAcquisition(Path(folder), run_state(), [transient, transient, None], sleep=sleeps.append)
            result = acquisition.run(max_partitions=1)
            self.assertEqual(acquisition.calls, 3)
            self.assertEqual(sleeps, [60, 120])
            self.assertEqual(result["partitions_complete"], 1)
            self.assertEqual(result["failure_count"], 0)
            self.assertTrue(any(item["status"] == "WAITING_FOR_NETWORK" for item in acquisition.snapshots))

    def test_network_unreachable_is_transient_and_unknown_transport_is_hard(self):
        transient, kind = classify_transport_error(OSError(errno.ENETUNREACH, "unreachable"))
        self.assertTrue(transient); self.assertEqual(kind, "NETWORK_UNREACHABLE")
        transient, kind = classify_transport_error(OSError(None, "unknown"))
        self.assertFalse(transient); self.assertEqual(kind, "UNCLASSIFIED_TRANSPORT_FAILURE")

    def test_dns_resolution_classification(self):
        transient, kind = classify_transport_error(urllib.error.URLError(socket.gaierror(-3, "temporary failure")))
        self.assertTrue(transient); self.assertEqual(kind, "DNS_RESOLUTION_FAILURE")

    def test_transient_http_statuses_resume_and_auth_statuses_fail_closed(self):
        for status_code in (429, 500, 502, 503, 504):
            with self.subTest(status=status_code), tempfile.TemporaryDirectory() as folder:
                error = ProviderError("gateway", status=status_code, transient=True, failure_class=f"HTTP_{status_code}")
                acquisition = ScriptedAcquisition(Path(folder), run_state(), [error, None])
                self.assertEqual(acquisition.run(max_partitions=1)["partitions_complete"], 1)
        for status_code in (401, 403):
            with self.subTest(status=status_code), tempfile.TemporaryDirectory() as folder:
                error = ProviderError("denied", status=status_code, systemic=True, failure_class=f"HTTP_{status_code}")
                acquisition = ScriptedAcquisition(Path(folder), run_state(), [error])
                with self.assertRaises(ProviderError): acquisition.run(max_partitions=1)
                self.assertEqual(acquisition.test_state["status"], "HARD_FAILED")

    def test_morning_cutoff_during_outage_exits_cleanly(self):
        cutoff = datetime(2026, 9, 4, 12, 45, tzinfo=timezone.utc)
        error = ProviderError("dns", transient=True, failure_class="DNS_RESOLUTION_FAILURE")
        with tempfile.TemporaryDirectory() as folder:
            acquisition = ScriptedAcquisition(Path(folder), run_state(), [error], now=lambda: cutoff)
            result = acquisition.run()
            self.assertEqual(result["status"], "STOPPED_FOR_MARKET_WINDOW")
            self.assertEqual(acquisition.calls, 0)

    def test_status_tracks_active_and_wall_clock_rates_separately(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state = run_state()
            state.update({"rows_15m": 1000, "bytes_stored": 1_000_000, "active_acquisition_seconds": 10,
                          "active_measurement_rows_baseline": 0, "active_measurement_bytes_baseline": 0})
            acquisition = Acquisition(root, FakeClient()); acquisition.save_state(state)
            report = status(root)
            self.assertEqual(report["active_rows_per_second"], 100.0)
            self.assertIn("wall_clock_rows_per_second", report)

    def test_systemd_unit_recovers_unexpected_failure(self):
        unit = (Path(__file__).parents[1] / "deploy/qpx-ml-historical-acquisition.service").read_text()
        self.assertIn("Restart=on-failure", unit)
        self.assertIn("RestartSec=60", unit)
        self.assertIn("RestartPreventExitStatus=78", unit)

    def test_disk_capacity_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW)
            with patch("qpx_bot.ml_historical_acquisition.shutil.disk_usage") as usage:
                usage.return_value.free = 1
                with self.assertRaisesRegex(RuntimeError, "Disk safety"):
                    acquisition.disk_gate()

    def test_corporate_action_dates_preserved(self):
        action = normalize_corporate_action({"id": "e", "symbol": "AAA", "ex_date": "2020-01-02", "record_date": "2020-01-03", "payable_date": "2020-01-04", "process_date": "2020-01-05"}, "cash_dividend", NOW)
        self.assertEqual(action["ex_or_effective_date"], "2020-01-02"); self.assertEqual(action["process_date"], "2020-01-05")

    def test_daily_aggregation_is_deterministic(self):
        rows = [{"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:30:00-04:00", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "4"}, {"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:45:00-04:00", "open": "11", "high": "13", "low": "10", "close": "12", "volume": "6"}]
        result = aggregate_bars(rows, "daily")[0]
        self.assertEqual((result["open"], result["close"], result["volume"]), ("10", "12", "10"))

    def test_hourly_aggregation_is_deterministic(self):
        rows = [{"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:30:00-04:00", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "4"}]
        self.assertEqual(aggregate_bars(rows, "hourly")[0]["bucket"], "2026-09-03T09:00:00-04:00")

    def test_morning_boundary(self):
        acquisition = Acquisition(Path(tempfile.gettempdir()) / "qpx-test", FakeClient(), now=lambda: datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc))
        self.assertTrue(acquisition._deadline_reached())

    def test_read_only_status_does_not_create_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "missing"; result = status(root)
            self.assertFalse(root.exists()); self.assertFalse(result["state_exists"])

    def test_reservoir_isolated_from_forward_and_broker_state(self):
        self.assertNotIn("runtime", DEFAULT_ROOT.parts); self.assertNotIn("operator_state", DEFAULT_ROOT.parts)

    def test_qualified_frozen_root_is_distinct(self):
        self.assertNotEqual(DEFAULT_ROOT, QUALIFIED_FROZEN_ROOT)

    def test_partial_state_not_training_eligible(self):
        estimate = initial_estimate(10, calculate_range(NOW), 900_000_000_000)
        self.assertGreater(estimate["upper_bound_rows"], 0)
        self.assertGreater(estimate["safety_reserve_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
