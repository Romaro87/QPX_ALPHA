from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from qpx_bot.ml_historical_acquisition import (
    BARS_URL,
    ProviderError,
    atomic_bytes,
    atomic_json,
    build_security_master,
    encode_gzip_csv,
    fingerprint,
    sha256_path,
)
from qpx_bot.ml_historical_calendar_repair import (
    AUDITED_FALSE_OPEN_DATES,
    CALENDAR_REPAIR_SESSIONS,
    HistoricalCalendarRepair,
)


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def _asset(identity: str, symbol: str) -> dict[str, object]:
    return {
        "id": identity, "symbol": symbol, "class": "us_equity",
        "exchange": "NYSE", "status": "active", "tradable": True,
        "fractionable": False, "marginable": True, "shortable": True,
        "easy_to_borrow": False, "attributes": [],
    }


def _write_master(root: Path) -> None:
    assets = build_security_master(
        [_asset("a", "AAA"), _asset("d1", "DUP"), _asset("d2", "DUP")], [], NOW,
    )
    payload = {"schema_version": 1, "provider": "alpaca", "assets": assets}
    payload["manifest_fingerprint"] = fingerprint(payload)
    path = root / "security_master/alpaca_us_equity_assets.json.gz"
    atomic_bytes(path, gzip.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
    atomic_json(path.with_suffix(path.suffix + ".manifest.json"), {
        "sha256": sha256_path(path), "security_count": 3,
        "active_count": 3, "inactive_count": 0,
        "provenance_fingerprint": payload["manifest_fingerprint"],
    })


def _write_original(root: Path) -> tuple[Path, dict[str, object]]:
    path = root / "bars_15m/year=2021/batch=00000.csv.gz"
    atomic_bytes(path, encode_gzip_csv([], (
        "provider_asset_id", "observation_symbol", "market_timestamp", "session_date",
        "open", "high", "low", "close", "volume", "provider", "feed",
        "adjustment", "request_fingerprint",
    )))
    manifest: dict[str, object] = {
        "schema_version": 1, "partition": "year=2021/batch=00000",
        "provider": "alpaca", "feed": "sip", "adjustment": "raw",
        "resolution": "15Min", "row_count": 0, "security_count": 0,
        "sha256": sha256_path(path), "request_fingerprint": "a" * 64,
        "first_observed_bar": None, "last_observed_bar": None,
        "first_session": None, "last_session": None,
        "synthetic_bars": False, "forward_fill": False,
        "timestamp_substitution": False, "completed_at_utc": NOW.isoformat(),
    }
    manifest["manifest_fingerprint"] = fingerprint(manifest)
    atomic_json(path.with_suffix(path.suffix + ".manifest.json"), manifest)
    return path, manifest


class RepairClient:
    request_count = 0
    retry_count = 0

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def request(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.request_count += 1
        self.calls.append(dict(params))
        if url != BARS_URL:
            raise AssertionError("unexpected endpoint")
        stamp = (
            "2021-06-18T13:30:00Z"
            if params["start"].startswith("2021-06-18")
            else "2021-12-31T14:30:00Z"
        )
        return {"bars": {"AAA": [{"t": stamp, "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]}, "next_page_token": None}


class RejectionRepairClient(RepairClient):
    def request(self, url: str, params: dict[str, str]) -> dict[str, object]:
        payload = super().request(url, params)
        rows = payload["bars"]["AAA"]
        assert isinstance(rows, list)
        rows.append({**rows[0], "o": -1})
        return payload


class PagedRepairClient(RepairClient):
    def __init__(self, *, fail_second: bool = False, duplicate_second: bool = False) -> None:
        super().__init__()
        self.fail_second = fail_second
        self.duplicate_second = duplicate_second

    def request(self, url: str, params: dict[str, str]) -> dict[str, object]:
        self.request_count += 1
        self.calls.append(dict(params))
        if url != BARS_URL:
            raise AssertionError("unexpected endpoint")
        if params["start"].startswith("2021-12-31"):
            return {"bars": {"AAA": [{"t": "2021-12-31T14:30:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]}, "next_page_token": None}
        if params.get("page_token") == "next-june-page":
            if self.fail_second:
                raise ProviderError("transient page failure", status=503)
            stamp = "2021-06-18T13:30:00Z" if self.duplicate_second else "2021-06-18T13:45:00Z"
            return {"bars": {"AAA": [{"t": stamp, "o": 11, "h": 13, "l": 10, "c": 12, "v": 100}]}, "next_page_token": None}
        return {"bars": {"AAA": [{"t": "2021-06-18T13:30:00Z", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}]}, "next_page_token": "next-june-page"}


class HistoricalCalendarRepairTests(unittest.TestCase):
    @staticmethod
    def item() -> dict[str, object]:
        return {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]}

    def test_repair_session_set_is_exactly_the_six_audited_false_closures(self) -> None:
        self.assertEqual(
            tuple(value.isoformat() for value in CALENDAR_REPAIR_SESSIONS),
            (
                "2017-06-19", "2018-06-19", "2019-06-19",
                "2020-06-19", "2021-06-18", "2021-12-31",
            ),
        )

    def test_overlay_targets_only_governed_sessions_and_preserves_original(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_master(root)
            original, _manifest = _write_original(root)
            original_bytes = original.read_bytes()
            original_manifest_bytes = original.with_suffix(original.suffix + ".manifest.json").read_bytes()
            client = RepairClient()
            repair = HistoricalCalendarRepair(
                root, client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            )
            item = {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]}
            result = repair.repair_partition({"unqueryable_symbols": []}, item)
            self.assertEqual(
                result["target_sessions"],
                ["2021-06-18", "2021-12-31"],
            )
            self.assertEqual(result["source_row_count"], 2)
            self.assertEqual(result["accepted_row_count"], 2)
            self.assertEqual(result["rejected_row_count"], 0)
            self.assertEqual(len(client.calls), 2)
            self.assertTrue(all(call["symbols"] == "AAA" for call in client.calls))
            self.assertFalse(any(
                call["start"].startswith(day.isoformat())
                for call in client.calls for day in AUDITED_FALSE_OPEN_DATES
            ))
            self.assertEqual(original.read_bytes(), original_bytes)
            self.assertEqual(
                original.with_suffix(original.suffix + ".manifest.json").read_bytes(),
                original_manifest_bytes,
            )
            self.assertEqual(
                tuple(day.isoformat() for day in CALENDAR_REPAIR_SESSIONS if day.year == 2021),
                ("2021-06-18", "2021-12-31"),
            )

    def test_live_coexistence_allows_repair_requests(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); _write_master(root); _write_original(root)
            client = RepairClient()
            client.rate_limit = 200
            client.rate_limit_remaining = 199
            result = HistoricalCalendarRepair(
                root, client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "LIVE_COEXISTENCE"},
            ).repair_partition(
                {"unqueryable_symbols": []},
                {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]},
            )
            self.assertEqual(result["accepted_row_count"], 2)
            self.assertEqual(len(client.calls), 2)

    def test_denied_capacity_issues_no_repair_request(self) -> None:
        for mode in ("WAITING_FOR_LIVE_CAPACITY", "PROTECTED_DECISION_WINDOW"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); _write_master(root); _write_original(root)
                client = RepairClient()
                repair = HistoricalCalendarRepair(
                    root, client, now=lambda: NOW,
                    capacity_probe=lambda _now: {"mode": mode},
                )
                with self.assertRaisesRegex(RuntimeError, "DEFERRED_BY_EXISTING_LIFECYCLE"):
                    repair.repair_partition(
                        {"unqueryable_symbols": []},
                        {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]},
                    )
                self.assertFalse(client.calls)

    def test_overlay_is_content_deterministic_and_duplicate_free(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_master(root)
            _write_original(root)
            item = {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]}
            first = HistoricalCalendarRepair(
                root, RepairClient(), now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            ).repair_partition({"unqueryable_symbols": []}, item)
            second = HistoricalCalendarRepair(
                root, RepairClient(), now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            ).repair_partition({"unqueryable_symbols": []}, item)
            self.assertEqual(first["repair_fingerprint"], second["repair_fingerprint"])
            self.assertEqual(first, second)

    def test_overlay_reconciles_accepted_and_rejected_source_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _write_master(root)
            _write_original(root)
            item = {"year": 2021, "batch": 0, "symbols": ["AAA", "DUP", "DUP"], "asset_ids": ["a", "d1", "d2"]}
            result = HistoricalCalendarRepair(
                root, RejectionRepairClient(), now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            ).repair_partition({"unqueryable_symbols": []}, item)
            self.assertEqual(result["source_row_count"], 4)
            self.assertEqual(result["accepted_row_count"], 2)
            self.assertEqual(result["rejected_row_count"], 2)
            self.assertEqual(result["rejection_counts_by_category"]["INVALID_OHLC"], 2)

    def test_successful_page_survives_failure_and_restart_resumes_next_page(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); _write_master(root); _write_original(root)
            first_client = PagedRepairClient(fail_second=True)
            repair = HistoricalCalendarRepair(
                root, first_client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            )
            with self.assertRaisesRegex(ProviderError, "transient page failure"):
                repair.repair_partition({"unqueryable_symbols": []}, self.item())
            pages = list((root / "calendar_repairs/durable_pages").rglob("page-*.json"))
            self.assertEqual(len(pages), 1)
            preserved = pages[0].read_bytes()

            second_client = PagedRepairClient()
            result = HistoricalCalendarRepair(
                root, second_client, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            ).repair_partition({"unqueryable_symbols": []}, self.item())
            self.assertEqual(second_client.calls[0].get("page_token"), "next-june-page")
            self.assertFalse(any(
                call["start"].startswith("2021-06-18") and "page_token" not in call
                for call in second_client.calls
            ))
            self.assertEqual(pages[0].read_bytes(), preserved)
            self.assertEqual(result["accepted_row_count"], 3)
            self.assertEqual(result["source_row_count"], 3)

            no_network = PagedRepairClient(fail_second=True)
            repeated = HistoricalCalendarRepair(
                root, no_network, now=lambda: NOW,
                capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
            ).repair_partition({"unqueryable_symbols": []}, self.item())
            self.assertEqual(repeated, result)
            self.assertEqual(no_network.calls, [])

    def test_corrupt_durable_page_fails_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); _write_master(root); _write_original(root)
            first = PagedRepairClient(fail_second=True)
            with self.assertRaises(ProviderError):
                HistoricalCalendarRepair(
                    root, first, now=lambda: NOW,
                    capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
                ).repair_partition({"unqueryable_symbols": []}, self.item())
            page = next((root / "calendar_repairs/durable_pages").rglob("page-*.json"))
            corrupt = json.loads(page.read_text())
            corrupt["accepted_rows"][0]["close"] = "999"
            page.write_text(json.dumps(corrupt))
            client = PagedRepairClient()
            with self.assertRaisesRegex(RuntimeError, "identity is invalid"):
                HistoricalCalendarRepair(
                    root, client, now=lambda: NOW,
                    capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
                ).repair_partition({"unqueryable_symbols": []}, self.item())
            self.assertEqual(client.calls, [])

    def test_duplicate_across_durable_pages_fails_without_damaging_first(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); _write_master(root); _write_original(root)
            client = PagedRepairClient(duplicate_second=True)
            with self.assertRaisesRegex(RuntimeError, "Duplicate calendar-repair observation"):
                HistoricalCalendarRepair(
                    root, client, now=lambda: NOW,
                    capacity_probe=lambda _now: {"mode": "OFF_MARKET"},
                ).repair_partition({"unqueryable_symbols": []}, self.item())
            pages = list((root / "calendar_repairs/durable_pages").rglob("page-*.json"))
            self.assertEqual(len(pages), 1)
            self.assertTrue(json.loads(pages[0].read_text())["bundle_fingerprint"])


if __name__ == "__main__":
    unittest.main()
