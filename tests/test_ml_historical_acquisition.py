from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from qpx_bot.ml_historical_acquisition import (
    ADJUSTMENT, BARS_URL, DEFAULT_ROOT, FEED, QUALIFIED_FROZEN_ROOT,
    Acquisition, ProviderError, RateGovernor, aggregate_bars, atomic_bytes,
    build_security_master, calculate_range, encode_gzip_csv, fingerprint,
    initial_estimate, normalize_corporate_action, read_gzip_csv, sha256_path,
    status, validate_bar,
)


NOW = datetime(2026, 9, 3, 22, 0, tzinfo=timezone.utc)


def asset(identity="id-a", symbol="AAA", state="active"):
    return {"id": identity, "symbol": symbol, "class": "us_equity", "exchange": "NYSE", "status": state, "tradable": state == "active", "fractionable": False, "marginable": True, "shortable": True, "easy_to_borrow": False, "attributes": []}


def raw_bar(stamp="2026-09-03T13:30:00Z"):
    return {"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}


class FakeClient:
    request_count = 0
    retry_count = 0
    def __init__(self, pages=None): self.pages = list(pages or [])
    def assets(self, state):
        self.request_count += 1
        return [asset("active-id", "AAA", "active")] if state == "active" else [asset("inactive-id", "OLD", "inactive")]
    def request(self, url, params):
        self.request_count += 1
        if url == BARS_URL:
            return self.pages.pop(0) if self.pages else {"bars": {}, "next_page_token": None}
        return {"corporate_actions": {}, "next_page_token": None}


class InvalidThenValidClient(FakeClient):
    def request(self, url, params):
        self.request_count += 1
        if "BAD" in params.get("symbols", ""):
            raise ProviderError('Alpaca HTTP 400: {"message":"invalid symbol: BAD"}', status=400)
        return {"bars": {}, "next_page_token": None}


class MLHistoricalAcquisitionTests(unittest.TestCase):
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

    def test_provider_rejected_symbol_is_bounded_and_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            client = InvalidThenValidClient(); acquisition = Acquisition(Path(folder), client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "unqueryable_symbols": [], "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["BAD", "AAA"], "asset_ids": ["bad-id", "good-id"]})
            self.assertEqual(state["unqueryable_symbols"][0]["provider_asset_id"], "bad-id")
            self.assertEqual(client.request_count, 2)

    def test_interrupted_page_resume_uses_saved_token(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); client = FakeClient([{"bars": {}, "next_page_token": None}]); acquisition = Acquisition(root, client, now=lambda: NOW)
            acquisition.disk_gate = lambda: 900_000_000_000
            page_root = root / "acquisition_state/pages/year=2026/batch=00000"; page_root.mkdir(parents=True)
            (page_root / "checkpoint.json").write_text(json.dumps({"page": 1, "next_page_token": "resume", "invalid_rows": 0, "request_fingerprint": "x"}))
            state = {"requested_range": {"actual_first_requested_session": "2026-09-01", "actual_last_completed_session": "2026-09-03"}, "completed": [], "observed_ranges": {}, "rows_15m": 0, "api_request_count": 0, "retry_count": 0}
            acquisition.acquire_partition(state, {"year": 2026, "batch": 0, "symbols": ["AAA"], "asset_ids": ["a"]})
            self.assertEqual(client.request_count, 1)

    def test_rate_governor_waits_globally(self):
        values = iter([0.0, 0.0, 0.1, 0.5]); sleeps=[]
        governor = RateGovernor(60, clock=lambda: next(values), sleep=sleeps.append); governor.wait(); governor.wait()
        self.assertTrue(sleeps and sleeps[0] > 0)

    def test_systemic_provider_failure_is_explicit(self):
        error = ProviderError("auth", status=401, systemic=True)
        self.assertTrue(error.systemic); self.assertEqual(error.status, 401)

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
