import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qpx_bot.ml_historical_acquisition import (
    Acquisition, ProviderError, atomic_bytes, encode_gzip_jsonl,
    normalize_corporate_action,
)
from qpx_bot.ml_historical_identity_enrichment import acquire_identity_enrichment
from tests.test_ml_historical_acquisition import NOW, asset, build_security_master, write_security_master


class EnrichmentClient:
    request_count = 0
    retry_count = 0

    def __init__(self, fail_second=False):
        self.fail_second = fail_second
        self.ids_requests = []

    def request(self, url, params):
        self.request_count += 1
        if "corporate-actions" in url:
            ids = params["ids"].split(",")
            self.ids_requests.append(ids)
            if self.fail_second and len(self.ids_requests) == 2:
                raise ProviderError("transient", transient=True)
            return {
                "corporate_actions": {
                    "cash_dividends": [
                        {"id": event_id, "cusip": f"CUSIP{event_id}"}
                        for event_id in ids
                    ],
                },
                "next_page_token": None,
            }
        if params.get("status") in {"active", "inactive"}:
            return []
        if "/v2/assets/" in url:
            raise ProviderError("not found", status=404)
        raise AssertionError((url, params))


class HistoricalIdentityEnrichmentTests(unittest.TestCase):
    def fixture(self, root, ids):
        write_security_master(root, build_security_master([asset("a", "AAA")], [], NOW))
        records = [
            normalize_corporate_action(
                {"id": event_id, "effective_date": "2021-01-04"},
                "cash_dividend", NOW,
            )
            for event_id in ids
        ]
        artifact = root / "corporate_actions/artifacts/source.jsonl.gz"
        atomic_bytes(artifact, encode_gzip_jsonl(records))
        state = {
            "corporate_action_artifact_path": str(artifact.relative_to(root)),
            "api_request_count": 0, "retry_count": 0,
        }
        return state

    def acquisition(self, root, client):
        value = Acquisition(root, client, now=lambda: NOW, sleep=lambda _seconds: None)
        value._capacity_gate = lambda *_args, **_kwargs: None
        return value

    def test_completed_batch_survives_failure_and_resume_skips_it(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.ml_historical_identity_enrichment.IDENTITY_ENRICHMENT_BATCH_SIZE", 2,
        ):
            root = Path(folder); state = self.fixture(root, ["1", "2", "3"])
            first = EnrichmentClient(fail_second=True)
            with self.assertRaisesRegex(ProviderError, "transient"):
                acquire_identity_enrichment(self.acquisition(root, first), state, ["1", "2", "3"])
            pages = list((root / "corporate_actions/identity_enrichment").glob("*/event_batches/*.json"))
            self.assertEqual(len(pages), 1)
            saved = pages[0].read_bytes()

            second = EnrichmentClient()
            result = acquire_identity_enrichment(self.acquisition(root, second), state, ["1", "2", "3"])
            self.assertEqual(second.ids_requests, [["3"]])
            self.assertEqual(pages[0].read_bytes(), saved)
            self.assertEqual(len(result["records"]), 3)

    def test_corrupt_completed_batch_fails_before_network(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.ml_historical_identity_enrichment.IDENTITY_ENRICHMENT_BATCH_SIZE", 2,
        ):
            root = Path(folder); state = self.fixture(root, ["1", "2", "3"])
            first = EnrichmentClient(fail_second=True)
            with self.assertRaises(ProviderError):
                acquire_identity_enrichment(self.acquisition(root, first), state, ["1", "2", "3"])
            page = next((root / "corporate_actions/identity_enrichment").glob("*/event_batches/*.json"))
            page.write_text("{}")
            second = EnrichmentClient()
            with self.assertRaisesRegex(RuntimeError, "identity mismatch|fingerprint"):
                acquire_identity_enrichment(self.acquisition(root, second), state, ["1", "2", "3"])
            self.assertEqual(second.request_count, 0)

    def test_unexpected_and_duplicate_provider_ids_fail_closed(self):
        class BadClient(EnrichmentClient):
            def __init__(self, mode): super().__init__(); self.mode = mode
            def request(self, url, params):
                if "corporate-actions" not in url: return []
                event_id = "unexpected" if self.mode == "unexpected" else params["ids"].split(",")[0]
                row = {"id": event_id, "cusip": "ONE"}
                values = [row, row] if self.mode == "duplicate" else [row]
                return {"corporate_actions": {"cash_dividends": values}, "next_page_token": None}
        for mode, message in (("unexpected", "unexpected"), ("duplicate", "duplicate")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); state=self.fixture(root,["1"])
                with self.assertRaisesRegex(RuntimeError, message):
                    acquire_identity_enrichment(self.acquisition(root,BadClient(mode)),state,["1"])

    def test_cusip_lookup_outside_population_and_not_found_remain_explicit(self):
        class LookupClient(EnrichmentClient):
            def __init__(self, found): super().__init__(); self.found = found
            def request(self, url, params):
                self.request_count += 1
                if "corporate-actions" in url:
                    return {"corporate_actions": {"cash_dividends": [{"id": params["ids"], "cusip": "OUTSIDE"}]}, "next_page_token": None}
                if params.get("status") in {"active", "inactive"}:
                    return []
                if self.found:
                    return {"id": "external", "symbol": "EXT", "class": "us_equity", "status": "inactive"}
                raise ProviderError("not found", status=404)

        for found, status, ids in (
            (True, "PROVIDER_ASSET_MATCH", ["external"]),
            (False, "NO_PROVIDER_ASSET_LOOKUP_RESULT", []),
        ):
            with self.subTest(found=found), tempfile.TemporaryDirectory() as folder:
                root=Path(folder); state=self.fixture(root,["1"])
                result=acquire_identity_enrichment(self.acquisition(root,LookupClient(found)),state,["1"])
                token=result["records"][0]["identity_tokens"][0]
                self.assertEqual(token["lookup_status"],status)
                self.assertEqual(token["provider_asset_ids"],ids)

    def test_missing_requested_event_is_preserved_as_missing_not_outside(self):
        class MissingClient(EnrichmentClient):
            def request(self,url,params):
                self.request_count += 1
                if "corporate-actions" in url:
                    return {"corporate_actions": {}, "next_page_token": None}
                if params.get("status") in {"active","inactive"}: return []
                raise AssertionError((url,params))
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); state=self.fixture(root,["1"])
            result=acquire_identity_enrichment(self.acquisition(root,MissingClient()),state,["1"])
            self.assertEqual(result["records"][0]["identity_tokens"],[])
            self.assertIsNone(result["records"][0]["targeted_record_fingerprint"])


if __name__ == "__main__":
    unittest.main()
