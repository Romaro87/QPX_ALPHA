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
    ACQUISITION_PROVENANCE_VERSION, ADJUSTMENT, BAR_COLUMNS, BAR_OUTCOMES, BARS_URL,
    CHECKPOINT_SCHEMA_VERSION, DEFAULT_ROOT, FEED, LIVE_REQUESTS_PER_MINUTE, PAGE_LIMIT,
    LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION, PROVIDER_INPUT_SEMANTIC_VERSION,
    QUALIFIED_FROZEN_ROOT, TIMEFRAME,
    Acquisition, AlpacaHistoricalClient, CooperativeStop, ProviderError, RateGovernor, aggregate_bars, atomic_bytes,
    atomic_json, batch_descriptor, build_security_master, calculate_range,
    canonical_provider_asset_id, classify_bar, encode_gzip_csv, fingerprint, initial_estimate,
    classify_transport_error, corporate_action_identity_resolution,
    load_provider_population, normalize_corporate_action, observational_coverage_evidence,
    page_evidence, partition_population_disposition, read_gzip_csv, request_identity, sha256_path,
    coexistence_capacity, status, validate_bar,
)
from qpx_bot.historical_market_calendar import FROZEN_CALENDAR_CONTENT_FINGERPRINT, load_frozen_historical_calendar


NOW = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)


def asset(identity="id-a", symbol="AAA", state="active"):
    return {"id": identity, "symbol": symbol, "class": "us_equity", "exchange": "NYSE", "status": state, "tradable": state == "active", "fractionable": False, "marginable": True, "shortable": True, "easy_to_borrow": False, "attributes": []}


def raw_bar(stamp="2026-09-03T13:30:00Z"):
    return {"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}


def write_security_master(root: Path, assets):
    payload = {"schema_version": 1, "provider": "alpaca", "assets": list(assets)}
    payload["manifest_fingerprint"] = fingerprint(payload)
    path = root / "security_master/alpaca_us_equity_assets.json.gz"
    atomic_bytes(path, gzip.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
    atomic_json(path.with_suffix(path.suffix + ".manifest.json"), {
        "sha256": sha256_path(path), "security_count": len(payload["assets"]),
        "active_count": sum(bool(item.get("active")) for item in payload["assets"]),
        "inactive_count": sum(not bool(item.get("active")) for item in payload["assets"]),
        "provenance_fingerprint": payload["manifest_fingerprint"],
    })
    return path


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


class CorporateActionClient(FakeClient):
    def __init__(self, *, duplicate=False):
        super().__init__()
        self.duplicate = duplicate

    def request(self, url, params):
        self.request_count += 1
        self.calls.append((url, dict(params)))
        if params.get("page_token") == "page-2":
            return {
                "corporate_actions": {
                    "cash_dividends": [{"id": "event-1" if self.duplicate else "event-2", "symbol": "AAA", "ex_date": "2021-01-04"}],
                },
                "next_page_token": None,
            }
        return {
            "corporate_actions": {
                "name_changes": [{"id": "event-1", "symbol": "AAA", "effective_date": "2020-01-02"}],
            },
            "next_page_token": "page-2",
        }


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

    def queued_v3_partition(self, root):
        write_security_master(root, build_security_master([asset("a", "AAA")], [], NOW))
        client = FakeClient([{"bars": {"AAA": [raw_bar()]}, "next_page_token": None}])
        client.rate_limit = 200; client.rate_limit_remaining = 199
        probe = lambda _now: {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True}
        acquisition = Acquisition(root, client, now=lambda: NOW, capacity_probe=probe)
        acquisition.disk_gate = lambda: 900_000_000_000
        state = self.partition_state(); acquisition._state_defaults(state)
        item = {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}
        state["partitions"] = [item]; state["partitions_total"] = 1
        original_gate = acquisition._capacity_gate

        def legacy_gate(value, partition, *, finalization=False):
            if finalization:
                raise CooperativeStop("simulate old deferred-finalization boundary")
            return original_gate(value, partition, finalization=False)

        with patch.object(acquisition, "_capacity_gate", side_effect=legacy_gate):
            with self.assertRaises(CooperativeStop):
                acquisition.acquire_partition(state, item)
        context = acquisition._partition_context(state, item)
        checkpoint = json.loads(
            (root / "acquisition_state/pages/year=2026/batch=00000/checkpoint.json").read_text()
        )
        acquisition._enqueue_pending_finalization(
            state, item, context["descriptor"], context["request_fingerprint"],
            checkpoint["page"],
        )
        return state, item, client

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
            self.assertEqual(sum(sleeps), 180); self.assertTrue(all(value == 1.0 for value in sleeps))
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

    def test_network_outage_at_old_cutoff_resumes_under_coexistence(self):
        cutoff = datetime(2026, 9, 4, 12, 45, tzinfo=timezone.utc)
        error = ProviderError("dns", transient=True, failure_class="DNS_RESOLUTION_FAILURE")
        with tempfile.TemporaryDirectory() as folder:
            acquisition = ScriptedAcquisition(Path(folder), run_state(), [error, None], now=lambda: cutoff)
            result = acquisition.run(max_partitions=1)
            self.assertEqual(result["partitions_complete"], 1)
            self.assertEqual(acquisition.calls, 2)

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

    def test_corporate_action_dates_fail_closed_when_not_canonical(self):
        with self.assertRaises(ValueError):
            normalize_corporate_action(
                {"id": "e", "symbol": "AAA", "ex_date": "2020-1-2"},
                "cash_dividend",
                NOW,
            )

    def test_daily_aggregation_is_deterministic(self):
        rows = [{"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:30:00-04:00", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "4"}, {"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:45:00-04:00", "open": "11", "high": "13", "low": "10", "close": "12", "volume": "6"}]
        result = aggregate_bars(rows, "daily")[0]
        self.assertEqual((result["open"], result["close"], result["volume"]), ("10", "12", "10"))

    def test_hourly_aggregation_is_deterministic(self):
        rows = [{"provider_asset_id": "a", "session_date": "2026-09-03", "market_timestamp": "2026-09-03T09:30:00-04:00", "open": "10", "high": "12", "low": "9", "close": "11", "volume": "4"}]
        self.assertEqual(aggregate_bars(rows, "hourly")[0]["bucket"], "2026-09-03T09:00:00-04:00")

    def test_morning_boundary_is_replaced_by_coexistence_controller(self):
        acquisition = Acquisition(Path(tempfile.gettempdir()) / "qpx-test", FakeClient(), now=lambda: datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc))
        self.assertFalse(acquisition._deadline_reached())

    def test_off_market_uses_normal_rate(self):
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), FakeClient(), capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False})
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
            self.assertEqual(state["historical_request_ceiling_per_minute"], 120)

    def test_live_mode_uses_low_rate_and_detects_clean_v2(self):
        with tempfile.TemporaryDirectory() as folder:
            assessment = {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True, "clean_v2_service_state": "active"}
            acquisition = Acquisition(Path(folder), FakeClient(), capacity_probe=lambda _now: assessment)
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
            self.assertEqual(state["operating_mode"], "LIVE_COEXISTENCE")
            self.assertEqual(state["historical_request_ceiling_per_minute"], LIVE_REQUESTS_PER_MINUTE)

    def test_live_pressure_waits_without_spin_then_resumes(self):
        with tempfile.TemporaryDirectory() as folder:
            decisions = iter((
                {"mode": "WAITING_FOR_LIVE_CAPACITY", "live_qpx_active": True, "reason": "CPU_LOAD_PRESSURE"},
                {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True, "reason": None},
            )); sleeps = []
            acquisition = Acquisition(Path(folder), FakeClient(), capacity_probe=lambda _now: next(decisions), sleep=sleeps.append)
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
            self.assertEqual(sum(sleeps), 30); self.assertEqual(state["operating_mode"], "LIVE_COEXISTENCE")

    def test_live_429_latches_session_yield(self):
        class Limited(FakeClient):
            def request(self, url, params):
                raise ProviderError("limited", status=429, transient=True, failure_class="HTTP_429")
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), Limited(), now=lambda: NOW, capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True})
            acquisition.disk_gate = lambda: 900_000_000_000
            state = self.partition_state(); acquisition._state_defaults(state)
            with self.assertRaises(ProviderError):
                acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(state["live_session_yield_date"], NOW.astimezone().date().isoformat())

    def test_live_download_finalizes_immediately_without_pending_entry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_security_master(root, build_security_master([asset("a", "AAA")], [], NOW))
            client = FakeClient([{"bars": {"AAA": [raw_bar()]}, "next_page_token": None}])
            client.rate_limit = 200; client.rate_limit_remaining = 199
            probe = lambda _now: {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True, "clean_v2_service_state": "active"}
            acquisition = Acquisition(root, client, now=lambda: NOW, capacity_probe=probe)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(client.request_count, 1)
            self.assertFalse(state["pending_finalizations"])
            self.assertEqual(state["partitions_complete"], 1)
            self.assertEqual(state["rows_15m"], 1)
            self.assertTrue((root / "bars_15m/year=2026/batch=00000.csv.gz").exists())

    def test_pending_finalization_survives_restart_and_is_not_redownloaded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state, _item, client = self.queued_v3_partition(root)
            Acquisition(root, FakeClient(), now=lambda: NOW).save_state(state)
            reloaded = Acquisition(root, FakeClient(), now=lambda: NOW).load_state()
            self.assertEqual(reloaded["pending_finalizations"][0]["partition"], "year=2026/batch=00000")
            self.assertEqual(client.request_count, 1)

    def test_off_market_drains_pending_finalization_without_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state, _item, _client = self.queued_v3_partition(root)
            off_client = FakeClient(); off = Acquisition(root, off_client, now=lambda: NOW, capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False})
            off.disk_gate = lambda: 900_000_000_000; off._drain_pending_finalizations(state)
            self.assertEqual(off_client.request_count, 0); self.assertEqual(state["partitions_complete"], 1)
            self.assertFalse(state["pending_finalizations"])

    def test_live_coexistence_drains_pending_finalization_without_download(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state, _item, _client = self.queued_v3_partition(root)
            client = FakeClient()
            live = Acquisition(root, client, now=lambda: NOW, capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True})
            live.disk_gate = lambda: 900_000_000_000
            live._drain_pending_finalizations(state)
            self.assertEqual(client.request_count, 0)
            self.assertFalse(state["pending_finalizations"])
            self.assertEqual(state["partitions_complete"], 1)
            self.assertEqual(state["rows_15m"], 1)

    def test_denied_capacity_keeps_pending_finalization_queued(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state, _item, _client = self.queued_v3_partition(root)
            holder = {}; client = FakeClient()

            def sleeper(_seconds):
                holder["acquisition"].stop_requested = True

            denied = Acquisition(
                root, client, now=lambda: NOW, sleep=sleeper,
                capacity_probe=lambda _now: {
                    "mode": "WAITING_FOR_LIVE_CAPACITY",
                    "reason": "CPU_LOAD_PRESSURE",
                    "live_qpx_active": True,
                },
            )
            holder["acquisition"] = denied
            with self.assertRaises(CooperativeStop):
                denied._drain_pending_finalizations(state)
            self.assertEqual(client.request_count, 0)
            self.assertEqual(
                [item["partition"] for item in state["pending_finalizations"]],
                ["year=2026/batch=00000"],
            )

    def test_live_finalization_ignores_provider_request_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            client = FakeClient(); client.request_count = 1
            acquisition = Acquisition(
                Path(folder), client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE", "live_qpx_active": True},
            )
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0}, finalization=True)
            self.assertEqual(state["operating_mode"], "LIVE_COEXISTENCE")

    def test_recent_historical_activity_makes_clean_lag_yield_then_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            decisions = iter((
                {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CLEAN_V2_DECISION_LATENCY", "live_qpx_active": True},
                {"mode": "LIVE_COEXISTENCE", "reason": None, "live_qpx_active": True},
            )); sleeps=[]
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW, sleep=sleeps.append, capacity_probe=lambda _now: next(decisions))
            state = self.partition_state(); acquisition._state_defaults(state); state["last_historical_activity_at_utc"] = NOW.isoformat()
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
            self.assertEqual(sum(sleeps), 30); self.assertEqual(state["operating_mode"], "LIVE_COEXISTENCE")

    def test_old_historical_activity_does_not_latch_unrelated_clean_lag(self):
        with tempfile.TemporaryDirectory() as folder:
            assessment = {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CLEAN_V2_DECISION_LATENCY", "live_qpx_active": True, "clean_v2_degradation_observed_at_utc": NOW.isoformat()}
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW, capacity_probe=lambda _now: assessment)
            state = self.partition_state(); acquisition._state_defaults(state)
            state["last_historical_activity_at_utc"] = "2026-09-03T18:00:00+00:00"
            acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
            self.assertEqual(state["operating_mode"], "LIVE_COEXISTENCE")
            self.assertIsNone(state["live_session_yield_date"])
            journal = (Path(folder) / "acquisition_state/coexistence_journal.jsonl").read_text()
            self.assertIn("LIVE_DEGRADATION_NOT_ATTRIBUTABLE_TO_HISTORICAL", journal)

    def test_transition_journal_records_reason_and_pending_count(self):
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW)
            state = self.partition_state(); acquisition._state_defaults(state)
            acquisition._set_mode(state, "WAITING_FOR_LIVE_CAPACITY", "CPU_LOAD_PRESSURE", {"load_1m": 9.0}, "ATTRIBUTABLE_RECENT_HISTORICAL_ACTIVITY")
            record = json.loads((Path(folder) / "acquisition_state/coexistence_journal.jsonl").read_text().strip())
            self.assertEqual(record["reason"], "CPU_LOAD_PRESSURE"); self.assertEqual(record["pending_finalization_count"], 0)

    def test_stop_interrupts_capacity_and_protected_window_without_spin(self):
        for mode in ("WAITING_FOR_LIVE_CAPACITY", "PROTECTED_DECISION_WINDOW"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                holder = {}; sleeps = []
                def sleeper(seconds):
                    sleeps.append(seconds); holder["acquisition"].stop_requested = True
                acquisition = Acquisition(Path(folder), FakeClient(), sleep=sleeper,
                                          capacity_probe=lambda _now: {"mode": mode, "reason": "TEST_WAIT"})
                holder["acquisition"] = acquisition; state = self.partition_state(); acquisition._state_defaults(state)
                with self.assertRaises(CooperativeStop):
                    acquisition._capacity_gate(state, {"year": 2026, "batch": 0})
                self.assertEqual(sleeps, [1.0])

    def test_stop_interrupts_network_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            holder = {}; sleeps=[]
            def sleeper(seconds):
                sleeps.append(seconds); holder["acquisition"].stop_requested = True
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW, sleep=sleeper)
            holder["acquisition"] = acquisition; state = self.partition_state(); acquisition._state_defaults(state)
            with self.assertRaises(CooperativeStop):
                acquisition._wait_for_network(state, {"year": 2026, "batch": 0}, ProviderError("dns", transient=True, failure_class="DNS_RESOLUTION_FAILURE"))
            self.assertEqual(sleeps, [1.0]); self.assertEqual(state["status"], "WAITING_FOR_NETWORK")

    def test_stop_interrupts_provider_retry_backoff(self):
        with tempfile.TemporaryDirectory() as folder:
            holder = {}; sleeps=[]
            def sleeper(seconds):
                sleeps.append(seconds); holder["acquisition"].stop_requested = True
            client = AlpacaHistoricalClient(RateGovernor(clock=lambda: 0.0))
            acquisition = Acquisition(Path(folder), client, sleep=sleeper); holder["acquisition"] = acquisition
            error = urllib.error.URLError(socket.gaierror(-3, "temporary failure"))
            with patch("qpx_bot.ml_historical_acquisition.credentials", return_value=("test-key", "test-secret")), patch("qpx_bot.ml_historical_acquisition.urllib.request.urlopen", side_effect=error):
                with self.assertRaises(CooperativeStop): client.request(BARS_URL, {"symbols": "AAA"})
            self.assertEqual(sleeps, [1.0])

    def test_stop_interrupts_finalization_capacity_wait(self):
        with tempfile.TemporaryDirectory() as folder:
            holder = {}; sleeps=[]
            def sleeper(seconds):
                sleeps.append(seconds); holder["acquisition"].stop_requested = True
            acquisition = Acquisition(Path(folder), FakeClient(), sleep=sleeper,
                                      capacity_probe=lambda _now: {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "TEST_WAIT"})
            holder["acquisition"] = acquisition; state = self.partition_state(); acquisition._state_defaults(state)
            with self.assertRaises(CooperativeStop):
                acquisition._capacity_gate(state, {"year": 2026, "batch": 0}, finalization=True)
            self.assertEqual(sleeps, [1.0]); self.assertEqual(state["status"], "WAITING_FOR_LIVE_CAPACITY")

    def test_cooperative_stop_preserves_unfinished_fragment_and_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); page_root = write_v2_resume(root)
            state = run_state(); state.update({
                "requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"},
                "partitions": [{"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}],
            })
            holder = {}
            def sleeper(_seconds): holder["acquisition"].stop_requested = True
            acquisition = Acquisition(root, FakeClient(), now=lambda: NOW, sleep=sleeper,
                                      capacity_probe=lambda _now: {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "TEST_WAIT"})
            holder["acquisition"] = acquisition; acquisition.save_state(state)
            result = acquisition.run(max_partitions=1)
            self.assertEqual(result["status"], "STOPPED_FOR_MARKET_WINDOW")
            self.assertTrue((page_root / "checkpoint.json").exists()); self.assertTrue(next(page_root.glob("page-*.csv.gz")).exists())
            self.assertFalse(result["completed"])

    def test_cooperative_shutdown_bound_and_systemd_failsafe(self):
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), FakeClient(), sleep=lambda _seconds: None)
            acquisition.stop_requested = True
            with self.assertRaises(CooperativeStop): acquisition._cooperative_wait(900)
        unit = (Path(__file__).parents[1] / "deploy/qpx-ml-historical-acquisition.service").read_text()
        self.assertIn("TimeoutStopSec=90", unit)

    @patch("qpx_bot.ml_historical_acquisition._latest_clean_cycle_evidence", return_value={"lag_seconds": 181.0, "observed_at_utc": "2026-09-04T14:05:00+00:00"})
    @patch("qpx_bot.ml_historical_acquisition._proc_io_pressure", return_value=0.0)
    @patch("qpx_bot.ml_historical_acquisition._proc_available_memory", return_value=8_000_000_000)
    @patch("qpx_bot.ml_historical_acquisition._clean_provider_state", return_value="HEALTHY")
    @patch("qpx_bot.ml_historical_acquisition._clean_service_state", return_value="active")
    def test_high_clean_v2_latency_yields(self, *_patches):
        moment = datetime(2026, 9, 4, 14, 5, tzinfo=timezone.utc)
        with patch("qpx_bot.ml_historical_acquisition.os.getloadavg", return_value=(1.0, 1.0, 1.0)):
            result = coexistence_capacity(moment)
        self.assertEqual(result["mode"], "WAITING_FOR_LIVE_CAPACITY")
        self.assertEqual(result["reason"], "CLEAN_V2_DECISION_LATENCY")

    @patch("qpx_bot.ml_historical_acquisition._clean_service_state", return_value="inactive")
    def test_expected_clean_v2_inactive_fails_safe(self, _service):
        moment = datetime(2026, 9, 4, 14, 5, tzinfo=timezone.utc)
        result = coexistence_capacity(moment)
        self.assertEqual(result["mode"], "WAITING_FOR_LIVE_CAPACITY")

    def test_read_only_status_reports_operating_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state = run_state(); state["operating_mode"] = "LIVE_COEXISTENCE"
            Acquisition(root, FakeClient()).save_state(state)
            self.assertEqual(status(root)["operating_mode"], "LIVE_COEXISTENCE")

    def test_read_only_status_does_not_create_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "missing"; result = status(root)
            self.assertFalse(root.exists()); self.assertFalse(result["state_exists"])

    def test_reservoir_isolated_from_forward_and_broker_state(self):
        self.assertNotIn("runtime", DEFAULT_ROOT.parts); self.assertNotIn("operator_state", DEFAULT_ROOT.parts)

    def test_qualified_frozen_root_is_distinct(self):
        self.assertNotEqual(DEFAULT_ROOT, QUALIFIED_FROZEN_ROOT)

    def test_initialization_state_is_not_training_eligible(self):
        with tempfile.TemporaryDirectory() as folder:
            acquisition = Acquisition(Path(folder), FakeClient(), now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = acquisition.initialize()
            self.assertEqual(
                state["training_eligibility"],
                "ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE",
            )

    def test_finalize_reports_complete_without_training_qualification(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            master_path = write_security_master(
                root,
                build_security_master(
                    [asset()], [asset("id-z", "ZZZ", "inactive")], NOW
                ),
            )
            master_before = master_path.read_bytes()
            state = {
                "observed_ranges": {
                    "id-a": [
                        "2026-09-01T09:30:00-04:00",
                        "2026-09-03T15:45:00-04:00",
                    ]
                }
            }
            acquisition = Acquisition(root, FakeClient(), now=lambda: NOW)
            acquisition.finalize(state)
            self.assertEqual(master_path.read_bytes(), master_before)
            coverage_path = root / state["observational_coverage_path"]
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            self.assertEqual(
                coverage["observational_coverage_fingerprint"],
                state["observational_coverage_fingerprint"],
            )
            self.assertEqual(state["status"], "COMPLETE")
            self.assertEqual(state["stage"], "COMPLETE")
            self.assertEqual(
                state["training_eligibility"],
                "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE",
            )

    def test_coverage_changes_do_not_change_provider_population_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, build_security_master([asset()], [], NOW))
            population = load_provider_population(root)
            first = observational_coverage_evidence({"observed_ranges": {}}, population)
            second = observational_coverage_evidence({
                "observed_ranges": {"id-a": [
                    "2026-09-01T09:30:00-04:00", "2026-09-03T15:45:00-04:00",
                ]},
            }, population)
            self.assertNotEqual(
                first["observational_coverage_fingerprint"],
                second["observational_coverage_fingerprint"],
            )
            self.assertEqual(
                first["provider_population_fingerprint"],
                second["provider_population_fingerprint"],
            )

    def test_corporate_action_identity_resolution_never_guesses(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(
                root,
                build_security_master(
                    [asset("a", "AAA"), asset("d1", "DUP"), asset("d2", "DUP")],
                    [], NOW,
                ),
            )
            population = load_provider_population(root)
            records = [
                normalize_corporate_action({"id": "one", "symbol": "AAA"}, "name_change", NOW),
                normalize_corporate_action({"id": "two", "symbol": "DUP"}, "cash_dividend", NOW),
            ]
            result = corporate_action_identity_resolution(records, population)
            by_id = {item["provider_event_id"]: item for item in result["records"]}
            self.assertEqual(by_id["one"]["provider_asset_id"], "a")
            self.assertEqual(by_id["two"]["outcome"], "UNRESOLVED_CORPORATE_ACTION_IDENTITY")
            self.assertEqual(by_id["two"]["excluded_provider_asset_ids"], ["d1", "d2"])

    def test_corporate_action_pagination_and_artifacts_are_complete(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, build_security_master([asset()], [], NOW))
            state = {
                "requested_range": {"requested_start": "2016-09-03", "requested_end": "2026-09-03"},
                "api_request_count": 0, "retry_count": 0,
            }
            client = CorporateActionClient()
            acquisition = Acquisition(
                root, client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False},
            )
            acquisition._state_defaults(state)
            acquisition.acquire_corporate_actions(state)
            manifest = json.loads((root / state["corporate_action_manifest_path"]).read_text())
            self.assertEqual(manifest["page_count"], 2)
            self.assertEqual(manifest["event_count"], 2)
            self.assertFalse(manifest["page_evidence"][0]["terminal_page"])
            self.assertTrue(manifest["page_evidence"][1]["terminal_page"])
            self.assertIsNone(manifest["terminal_page_token"])
            self.assertEqual(state["corporate_action_status"], "COMPLETE")

    def test_duplicate_corporate_action_provider_id_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, build_security_master([asset()], [], NOW))
            state = {
                "requested_range": {"requested_start": "2016-09-03", "requested_end": "2026-09-03"},
                "api_request_count": 0, "retry_count": 0,
            }
            acquisition = Acquisition(
                root, CorporateActionClient(duplicate=True), now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET", "live_qpx_active": False},
            )
            acquisition._state_defaults(state)
            with self.assertRaisesRegex(RuntimeError, "Duplicate corporate-action"):
                acquisition.acquire_corporate_actions(state)
            self.assertNotEqual(state.get("corporate_action_status"), "COMPLETE")

    def test_status_preserves_complete_not_qualified_state(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state = run_state()
            state.update({
                "status": "COMPLETE",
                "training_eligibility": "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE",
            })
            Acquisition(root, FakeClient()).save_state(state)
            result = status(root)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(
                result["training_eligibility"],
                "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE",
            )

    def test_acquisition_has_no_positive_training_eligibility_literal(self):
        source = (
            Path(__file__).parents[1] / "qpx_bot/ml_historical_acquisition.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn('"TRAINING_ELIGIBLE"', source)


class HistoricalAcquisitionV3EvidenceTests(unittest.TestCase):
    calendar = load_frozen_historical_calendar()

    @staticmethod
    def state(start="2026-09-01", end="2026-09-03"):
        return {
            "requested_range": {
                "actual_first_requested_session": start,
                "actual_last_completed_session": end,
            },
            "completed": [], "observed_ranges": {}, "unqueryable_symbols": [],
            "rows_15m": 0, "api_request_count": 0, "retry_count": 0,
            "pending_finalizations": [],
        }

    @staticmethod
    def governed_assets(*pairs):
        return build_security_master(
            [asset(identity, symbol) for identity, symbol in pairs], [], NOW,
        )

    def acquisition(self, root, client):
        result = Acquisition(
            root, client, now=lambda: NOW,
            capacity_probe=lambda _now: {"mode": "OFF_MARKET", "reason": "TEST"},
        )
        result.disk_gate = lambda: 900_000_000_000
        return result

    def committed_v3_partition(self, root):
        write_security_master(root, self.governed_assets(("a", "AAA")))
        item = {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}
        producer = self.acquisition(root, FakeClient([{
            "bars": {"AAA": [raw_bar("2026-09-01T13:30:00Z"), raw_bar("2026-09-03T13:30:00Z")]},
            "next_page_token": None,
        }]))
        producer.acquire_partition(self.state(), item)
        return item

    @staticmethod
    def rewrite_v3_manifest(path, **changes):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(changes)
        manifest["manifest_fingerprint"] = fingerprint({
            key: value for key, value in manifest.items()
            if key not in {"manifest_fingerprint", "completed_at_utc"}
        })
        atomic_json(path, manifest)

    def classify(self, stamp, *, start=date(2016, 9, 6), end=date(2026, 9, 3), **changes):
        raw = raw_bar(stamp)
        raw.update(changes)
        return classify_bar(raw, "AAA", "a", "f", start, end, NOW, self.calendar)

    def test_frozen_calendar_classification_contract(self):
        for stamp in (
            "2017-06-19T13:30:00Z", "2018-06-19T13:30:00Z",
            "2019-06-19T13:30:00Z", "2020-06-19T13:30:00Z",
            "2021-06-18T13:30:00Z", "2021-12-31T14:30:00Z",
        ):
            self.assertEqual(self.classify(stamp).outcome, "ACCEPTED", stamp)
        self.assertEqual(self.classify("2018-12-05T14:30:00Z").outcome, "CALENDAR_REJECTED")
        self.assertEqual(self.classify("2025-01-09T14:30:00Z").outcome, "CALENDAR_REJECTED")
        self.assertEqual(self.classify("2025-07-03T17:00:00Z").outcome, "OUTSIDE_REGULAR_SESSION")

    def test_legacy_and_v3_request_identities_remain_explicit(self):
        arguments = dict(year=2026, start=date(2026, 9, 1), end=date(2026, 9, 3), symbols=["AAA"], asset_ids=["a"])
        legacy = batch_descriptor(**arguments, provider_input_semantic_version=LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION)
        current = batch_descriptor(**arguments)
        request = {"symbols": "AAA"}
        self.assertNotEqual(legacy["batch_fingerprint"], current["batch_fingerprint"])
        self.assertNotEqual(
            request_identity(request, legacy["batch_fingerprint"], provider_input_semantic_version=LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION),
            request_identity(request, current["batch_fingerprint"]),
        )

    def test_classifier_precedence_and_single_outcomes(self):
        cases = (
            ({"t": "bad", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}, "BAD_TIMESTAMP"),
            ({"t": "2026-09-03T13:30:00Z", "o": "bad", "h": 1, "l": 1, "c": 1, "v": 1}, "MALFORMED_ROW"),
            ({"t": "2026-09-03T13:30:00Z", "o": 10, "h": 9, "l": 8, "c": 9, "v": 1}, "INVALID_OHLC"),
            ({"t": "2026-09-03T13:30:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": -1}, "NEGATIVE_VOLUME"),
            ([], "MALFORMED_ROW"),
        )
        for raw, expected in cases:
            outcome = classify_bar(raw, "AAA", "a", "f", date(2026, 9, 1), date(2026, 9, 3), NOW, self.calendar)
            self.assertEqual(outcome.outcome, expected)
            self.assertIn(outcome.outcome, BAR_OUTCOMES)

    def test_ambiguous_provider_population_is_explicit_and_deterministic(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("d2", "DUP"), ("a", "AAA"), ("d1", "DUP")))
            first = load_provider_population(root)
            second = load_provider_population(root)
            exclusion = first["ambiguous_exclusion_set"]
            self.assertEqual(exclusion, second["ambiguous_exclusion_set"])
            self.assertEqual(first["ambiguous_by_symbol"]["DUP"], ("d1", "d2"))
            self.assertEqual(exclusion["record_count"], 1)
            self.assertEqual(exclusion["affected_provider_id_count"], 2)
            item = {"symbols": ["DUP", "AAA", "DUP"], "asset_ids": ["d2", "a", "d1"]}
            disposition = partition_population_disposition(item, first)
            self.assertEqual(disposition["requested_unambiguous_provider_ids"], ["a"])
            self.assertEqual(sorted(disposition["ambiguous_identity_excluded_provider_ids"]), ["d1", "d2"])
            write_security_master(root, self.governed_assets(("d3", "DUP"), ("a", "AAA"), ("d1", "DUP")))
            changed = load_provider_population(root)
            self.assertNotEqual(exclusion["exclusion_set_fingerprint"], changed["ambiguous_exclusion_set"]["exclusion_set_fingerprint"])

    def test_v3_partition_reconciles_population_pages_and_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("d1", "DUP"), ("d2", "DUP"), ("a", "AAA")))
            client = FakeClient([{"bars": {"AAA": [raw_bar(), {**raw_bar(), "o": -1}]}, "next_page_token": None}])
            acquisition = self.acquisition(root, client)
            item = {"year": 2026, "batch": 0, "symbols": ["DUP", "DUP", "AAA"], "asset_ids": ["d1", "d2", "a"]}
            acquisition.acquire_partition(self.state(), item)
            self.assertEqual(client.calls[0][1]["symbols"], "AAA")
            manifest = json.loads((root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json").read_text())
            self.assertEqual(manifest["source_row_count"], 2)
            self.assertEqual(manifest["accepted_row_count"], 1)
            self.assertEqual(manifest["rejected_row_count"], 1)
            self.assertEqual(manifest["rejection_counts_by_category"]["INVALID_OHLC"], 1)
            population = manifest["population_disposition"]
            self.assertEqual(
                len(population["planned_provider_ids"]),
                len(population["requested_unambiguous_provider_ids"])
                + len(population["ambiguous_identity_excluded_provider_ids"])
                + len(population["other_governed_excluded_provider_ids"]),
            )
            self.assertEqual(manifest["frozen_calendar_fingerprint"], FROZEN_CALENDAR_CONTENT_FINGERPRINT)
            self.assertFalse((root / "acquisition_state/pages/year=2026/batch=00000").exists())
            self.assertTrue((root / "rejection_evidence/year=2026/batch=00000.rejections.jsonl.gz").exists())

    def test_provider_rejection_remains_explicitly_accounted_for(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("bad", "BAD"), ("a", "AAA")))
            state = self.state()
            acquisition = self.acquisition(root, InvalidThenValidClient())
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["BAD", "AAA"], "asset_ids": ["bad", "a"]})
            manifest = json.loads((root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json").read_text())
            self.assertEqual(manifest["population_disposition"]["other_governed_excluded_provider_ids"], ["bad"])
            self.assertEqual(manifest["population_disposition"]["requested_unambiguous_provider_ids"], ["a"])

    def test_exclusions_only_partition_makes_no_provider_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("d1", "DUP"), ("d2", "DUP")))
            client = FakeClient()
            acquisition = self.acquisition(root, client)
            acquisition.acquire_partition(self.state(), {"year": 2026, "batch": 0, "symbols": ["DUP", "DUP"], "asset_ids": ["d1", "d2"]})
            self.assertEqual(client.request_count, 0)
            manifest = json.loads((root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json").read_text())
            self.assertEqual((manifest["source_row_count"], manifest["accepted_row_count"], manifest["rejected_row_count"], manifest["page_count"]), (0, 0, 0, 0))

    def test_unexpected_provider_symbol_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("a", "AAA")))
            acquisition = self.acquisition(root, FakeClient([{"bars": {"OTHER": [raw_bar()]}, "next_page_token": None}]))
            with self.assertRaisesRegex(ProviderError, "Unexpected provider response"):
                acquisition.acquire_partition(self.state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})

    def test_changed_calendar_identity_changes_page_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            accepted = root / "accepted.gz"; rejected = root / "rejected.gz"
            atomic_bytes(accepted, encode_gzip_csv([], BAR_COLUMNS)); atomic_bytes(rejected, gzip.compress(b"", mtime=0))
            arguments = dict(page=1, source_row_count=0, accepted_row_count=0, rejected_row_count=0,
                             rejection_counts_by_category={}, request_fingerprint="r", batch_fingerprint="b",
                             provider_population_fingerprint="p", population_disposition_fingerprint="d",
                             exclusion_set_fingerprint="e")
            first = page_evidence(accepted, rejected, calendar_fingerprint="1" * 64, **arguments)
            second = page_evidence(accepted, rejected, calendar_fingerprint="2" * 64, **arguments)
            self.assertNotEqual(first["page_evidence_fingerprint"], second["page_evidence_fingerprint"])

    def test_missing_rejection_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("a", "AAA")))
            acquisition = Acquisition(
                root, FakeClient([{"bars": {"AAA": [raw_bar()]}, "next_page_token": None}]),
                now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE", "reason": "TEST", "live_qpx_active": True},
            )
            state = self.state()
            item = {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}
            original_gate = acquisition._capacity_gate

            def denied_finalization(value, partition, *, finalization=False):
                if finalization:
                    raise CooperativeStop("retain transient evidence for validation test")
                return original_gate(value, partition, finalization=False)

            with patch.object(acquisition, "_capacity_gate", side_effect=denied_finalization):
                with self.assertRaises(CooperativeStop):
                    acquisition.acquire_partition(state, item)
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"
            (page_root / "page-000001.rejections.jsonl.gz").unlink()
            context = acquisition._partition_context(state, item)
            page, token = acquisition._validated_resume(
                page_root,
                expected_request_fingerprint=context["request_fingerprint"],
                expected_batch_fingerprint=context["descriptor"]["batch_fingerprint"],
                descriptor=context["descriptor"],
                provider_population_fingerprint=context["population"]["provider_population_fingerprint"],
                population_disposition_fingerprint=context["disposition"]["population_disposition_fingerprint"],
                exclusion_set_fingerprint=context["disposition"]["exclusion_set_fingerprint"],
            )
            self.assertEqual((page, token), (0, None))
            self.assertTrue(list((root / "acquisition_state/rebuild_evidence").iterdir()))

    def test_duplicate_rejection_record_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("a", "AAA")))
            acquisition = Acquisition(
                root, FakeClient([{"bars": {"AAA": [{**raw_bar(), "o": -1}]}, "next_page_token": None}]),
                now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE", "reason": "TEST", "live_qpx_active": True},
            )
            state = self.state()
            item = {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]}
            original_gate = acquisition._capacity_gate

            def denied_finalization(value, partition, *, finalization=False):
                if finalization:
                    raise CooperativeStop("retain transient evidence for validation test")
                return original_gate(value, partition, finalization=False)

            with patch.object(acquisition, "_capacity_gate", side_effect=denied_finalization):
                with self.assertRaises(CooperativeStop):
                    acquisition.acquire_partition(state, item)
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"
            rejection_path = page_root / "page-000001.rejections.jsonl.gz"
            record = gzip.decompress(rejection_path.read_bytes())
            atomic_bytes(rejection_path, gzip.compress(record + record, mtime=0))
            context = acquisition._partition_context(state, item)
            page, token = acquisition._validated_resume(
                page_root,
                expected_request_fingerprint=context["request_fingerprint"],
                expected_batch_fingerprint=context["descriptor"]["batch_fingerprint"],
                descriptor=context["descriptor"],
                provider_population_fingerprint=context["population"]["provider_population_fingerprint"],
                population_disposition_fingerprint=context["disposition"]["population_disposition_fingerprint"],
                exclusion_set_fingerprint=context["disposition"]["exclusion_set_fingerprint"],
            )
            self.assertEqual((page, token), (0, None))
            self.assertTrue(list((root / "acquisition_state/rebuild_evidence").iterdir()))

    def test_old_checkpoint_quarantines_only_incomplete_partition(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("a", "AAA")))
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"
            page_root.mkdir(parents=True)
            atomic_json(page_root / "checkpoint.json", {"schema_version": 2, "page": 0})
            client = FakeClient([{"bars": {}, "next_page_token": None}])
            self.acquisition(root, client).acquire_partition(
                self.state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]},
            )
            self.assertTrue(list((root / "acquisition_state/rebuild_evidence").iterdir()))
            self.assertEqual(client.request_count, 1)

    def test_final_manifest_failure_preserves_transient_page_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_security_master(root, self.governed_assets(("a", "AAA")))
            acquisition = self.acquisition(root, FakeClient([{"bars": {"AAA": [raw_bar()]}, "next_page_token": None}]))
            final_manifest = root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json"
            original_atomic_json = atomic_json

            def fail_final(path, payload):
                if path == final_manifest:
                    raise OSError("simulated final-manifest failure")
                original_atomic_json(path, payload)

            with patch("qpx_bot.ml_historical_acquisition.atomic_json", side_effect=fail_final):
                with self.assertRaisesRegex(OSError, "final-manifest"):
                    acquisition.acquire_partition(self.state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"
            self.assertTrue((page_root / "page-000001.csv.gz").exists())
            self.assertTrue((page_root / "page-000001.rejections.jsonl.gz").exists())

    def test_committed_v3_partition_recovers_state_once_without_provider_request(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = self.committed_v3_partition(root)
            client = FakeClient()
            acquisition = self.acquisition(root, client)
            state = self.state()
            state["rows_15m"] = 7
            state["observed_ranges"] = {"prior": ["2020-01-02T09:30:00-05:00", "2020-01-02T09:45:00-05:00"]}
            acquisition.acquire_partition(state, item)
            self.assertEqual(client.request_count, 0)
            self.assertEqual(state["completed"], ["year=2026/batch=00000"])
            self.assertEqual(state["last_partition_recovery"]["reason"], "FINAL_EVIDENCE_COMMITTED_STATE_RECOVERY")
            self.assertEqual(state["rows_15m"], 9)
            self.assertEqual(state["partitions_complete"], 1)
            self.assertEqual(
                state["observed_ranges"]["a"],
                ["2026-09-01T09:30:00-04:00", "2026-09-03T09:30:00-04:00"],
            )
            self.assertEqual(
                state["bytes_stored"],
                sum(path.stat().st_size for path in root.rglob("*") if path.is_file()),
            )
            snapshot = json.loads(json.dumps(state))
            acquisition.acquire_partition(state, item)
            self.assertEqual(state, snapshot)
            self.assertEqual(client.request_count, 0)

    def test_valid_committed_v3_evidence_cleans_stale_transient_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            item = self.committed_v3_partition(root)
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"
            page_root.mkdir(parents=True)
            (page_root / "checkpoint.json").write_text("stale", encoding="utf-8")
            client = FakeClient()
            state = self.state()
            self.acquisition(root, client).acquire_partition(state, item)
            self.assertFalse(page_root.exists())
            self.assertEqual(client.request_count, 0)
            self.assertEqual(state["completed"], ["year=2026/batch=00000"])

    def test_missing_or_corrupt_v3_rejection_evidence_fails_closed(self):
        for mutation in ("missing", "corrupt"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                item = self.committed_v3_partition(root)
                rejection = root / "rejection_evidence/year=2026/batch=00000.rejections.jsonl.gz"
                if mutation == "missing":
                    rejection.unlink()
                else:
                    rejection.write_bytes(b"not-gzip")
                state = self.state(); client = FakeClient()
                with self.assertRaisesRegex(RuntimeError, "missing or corrupt"):
                    self.acquisition(root, client).acquire_partition(state, item)
                self.assertEqual(state["completed"], [])
                self.assertEqual(client.request_count, 0)

    def test_corrupt_v3_manifest_fingerprint_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = self.committed_v3_partition(root)
            manifest_path = root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json"
            manifest = json.loads(manifest_path.read_text()); manifest["manifest_fingerprint"] = "0" * 64
            atomic_json(manifest_path, manifest)
            state = self.state(); client = FakeClient()
            with self.assertRaisesRegex(RuntimeError, "manifest fingerprint"):
                self.acquisition(root, client).acquire_partition(state, item)
            self.assertEqual(state["completed"], []); self.assertEqual(client.request_count, 0)

    def test_v3_accepted_partition_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = self.committed_v3_partition(root)
            manifest_path = root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json"
            self.rewrite_v3_manifest(manifest_path, accepted_partition_sha256="0" * 64, sha256="0" * 64)
            state = self.state(); client = FakeClient()
            with self.assertRaisesRegex(RuntimeError, "accepted-partition checksum"):
                self.acquisition(root, client).acquire_partition(state, item)
            self.assertEqual(state["completed"], []); self.assertEqual(client.request_count, 0)

    def test_v3_bound_identity_mismatches_fail_closed(self):
        fields = (
            "request_fingerprint", "batch_fingerprint", "frozen_calendar_fingerprint",
            "provider_population_fingerprint", "population_disposition_fingerprint",
            "exclusion_set_fingerprint",
        )
        for field in fields:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); item = self.committed_v3_partition(root)
                manifest_path = root / "bars_15m/year=2026/batch=00000.csv.gz.manifest.json"
                self.rewrite_v3_manifest(manifest_path, **{field: "0" * 64})
                state = self.state(); client = FakeClient()
                with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                    self.acquisition(root, client).acquire_partition(state, item)
                self.assertEqual(state["completed"], []); self.assertEqual(client.request_count, 0)

    def test_legacy_partition_absent_from_completed_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / "bars_15m/year=2026/batch=00000.csv.gz"
            atomic_bytes(destination, b"legacy")
            legacy_manifest = {"schema_version": 2, "sha256": sha256_path(destination)}
            atomic_json(destination.with_suffix(destination.suffix + ".manifest.json"), legacy_manifest)
            client = FakeClient()
            with self.assertRaisesRegex(RuntimeError, "refusing implicit adoption"):
                self.acquisition(root, client).acquire_partition(
                    self.state(), {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]},
                )
            self.assertEqual(client.request_count, 0)
            self.assertEqual(json.loads(destination.with_suffix(destination.suffix + ".manifest.json").read_text()), legacy_manifest)


if __name__ == "__main__":
    unittest.main()
