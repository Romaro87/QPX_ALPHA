from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import qpx_bot.pr50_iex_forward_research_paper as runner
from qpx_bot import fixed25_forward_paper as engine


NOW = datetime(2026, 9, 25, 14, 0, 10, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


class LivePaperSIPAuthorityTests(unittest.TestCase):
    def test_profile_is_sip_only_and_iex_request_fails_before_network(self):
        contract = runner.load_contract()
        self.assertEqual(contract["market_data_provider"], "alpaca")
        self.assertEqual(contract["feed"], "sip")
        self.assertIsNone(contract["market_data_fallback"])
        self.assertEqual(
            contract["paper_profile_path"],
            "qpx_bot/paper_profiles/volume_confirmation_25_v1.json",
        )
        with patch.object(runner.urllib.request, "urlopen") as opened:
            with self.assertRaises(runner.ProviderFailure) as raised:
                runner._request_json(
                    provider="alpaca", operation="market_bars",
                    endpoint=engine.DATA_URL,
                    parameters={"feed": "iex", "symbols": "QDTE"},
                    user_agent="test", attempts=1,
                )
        self.assertEqual(raised.exception.failure_class, "MARKET_DATA_AUTHORITY_MISMATCH")
        opened.assert_not_called()

    def test_decision_bars_request_and_attest_sip(self):
        row = {"t": "2026-09-25T13:45:00Z", "o": 1, "h": 2, "l": 1, "c": 2, "v": 10}
        with patch.object(engine, "credentials", return_value=("key", "secret")), patch.object(
            runner.urllib.request, "urlopen", return_value=Response({"bars": {"QDTE": [row]}})
        ) as opened:
            result = runner.request_bars(
                ("QDTE",), "15Min", NOW - timedelta(hours=1), NOW
            )
        self.assertIn("feed=sip", opened.call_args.args[0].full_url)
        self.assertEqual(result["QDTE"][0]["qpx_market_data_feed"], "sip")
        self.assertEqual(
            result["QDTE"][0]["qpx_feed_identity_fingerprint"],
            runner.load_contract()["feed_identity_fingerprint"],
        )

    def test_eligible_open_accepts_consolidated_sip_trade_and_records_identity(self):
        eligible = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        observed = eligible + timedelta(seconds=30)
        trade = {
            "t": (eligible + timedelta(seconds=1)).isoformat(),
            "p": 10.0, "s": 100, "x": "N", "z": "C", "c": ["@"],
        }
        with patch.object(runner, "_request_json", return_value={"trades": [trade]}) as request:
            result = runner.request_authentic_open("TSLL", eligible, observed)
        self.assertEqual(request.call_args.kwargs["parameters"]["feed"], "sip")
        self.assertEqual(result["feed"], "sip")
        self.assertEqual(result["price_source"], "ALPACA_SIP_FIRST_ELIGIBLE_TRADE")
        self.assertEqual(result["trade"]["x"], "N")

    def test_feed_authority_migration_preserves_account_and_restart_identity(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(
            runner, "request_bars",
            return_value={"QDTE": [{"t": "2026-09-25T13:59:00Z", "c": 30.0}]},
        ):
            store = runner.IEXResearchStore(Path(folder))
            contract = runner.load_contract()
            state = runner.initialize(store, contract, NOW)
            legacy = deepcopy(contract)
            legacy.update({
                "feed": "iex",
                "runner_variant": "VOLUME_CONFIRMATION_25_IEX_FORWARD_RESEARCH_PAPER_ONLY",
                "semantic_version": "PR50_IEX_CANDIDATE_V1_CONFIG_AUTHORITY_V3",
                "provider_input_semantics_version": "ALPACA_IEX_15M_COMPLETED_SPLIT_V1",
                "sip_parity_claimed": False,
            })
            for key in ("market_data_provider", "market_data_fallback", "feed_identity_fingerprint"):
                legacy.pop(key, None)
            state["contract"] = legacy
            state["contract_fingerprint"] = engine.fingerprint(legacy)
            state["mode"] = legacy["runner_variant"]
            state["sip_parity_claimed"] = False
            state["cash"] = 28.0282
            state["qdte_shares"] = 50
            state["qdte_cost"] = 1421.065
            before = runner._preserved_account_payload(state)
            store.save(state)
            self.assertTrue(runner._migrate_market_data_contract_if_required(state, store, contract, NOW))
            state["contract"]["paper_profile_path"] = "/release-dependent/profile.json"
            state["contract_fingerprint"] = engine.fingerprint(state["contract"])
            store.save(state)
            self.assertTrue(runner._normalize_sip_contract_identity_if_required(
                state, store, contract, NOW
            ))
            state["market_data_authority"].update({
                "effective_provider_feed": "sip",
                "sip_entitlement_result": "AVAILABLE",
            })
            store.save(state)
            self.assertEqual(runner._preserved_account_payload(state), before)
            restarted = runner.IEXResearchStore(Path(folder)).reconcile()
            self.assertEqual(restarted["market_data_authority"]["configured_feed"], "sip")
            self.assertEqual(restarted["market_data_authority"]["effective_provider_feed"], "sip")
            self.assertEqual(restarted["contract"]["feed"], "sip")
            self.assertEqual(restarted["cash"], 28.0282)
            self.assertEqual(restarted["qdte_shares"], 50)
            store.publish_metrics(restarted, NOW)
            report = json.loads((Path(folder) / "iex_research_paper_performance.json").read_text())
            self.assertEqual(report["current"]["configured_market_data_feed"], "sip")
            self.assertEqual(report["current"]["effective_provider_feed"], "sip")

    def test_optional_broker_observer_requires_sip_and_remains_simulated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            state_path = root / "dummy.json"
            config_path = root / "provider.json"
            config_path.write_text(json.dumps({
                "schema_version": 1,
                "market_data_provider": "ALPACA_SIP",
                "broker_account_provider": "DUMMY",
                "order_execution_provider": "SIMULATED",
                "broker_account_configuration": {"state_path": str(state_path)},
            }))
            with patch.dict("os.environ", {runner.BROKER_PROVIDER_CONFIG_ENV: str(config_path)}):
                selection, _provider = runner.configured_broker_account_provider()
            self.assertEqual(selection.market_data_provider, "ALPACA_SIP")
            self.assertEqual(selection.order_execution_provider, "SIMULATED")

    def test_heartbeat_reports_sip_and_broker_orders_remain_disabled(self):
        with patch.object(runner, "_last_effective_market_data_authority", None):
            payload = runner._heartbeat_payload(
                daemon_started_at_utc=NOW.isoformat(), state=None,
                provider_state="PRE_MARKET", session_state="PRE_MARKET",
                retry_count=0, backoff_seconds=5,
                last_successful_provider_contact_at_utc=None,
            )
        self.assertEqual(payload["configured_market_data_feed"], "sip")
        self.assertIsNone(payload["effective_provider_feed"])
        self.assertFalse(payload["live_broker_enabled"])
        self.assertFalse(payload["broker_reconciliation"]["broker_orders_enabled"])


if __name__ == "__main__":
    unittest.main()
