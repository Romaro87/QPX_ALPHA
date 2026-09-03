from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from qpx_bot.broker_account_provider import build_broker_account_provider, write_dummy_broker_account_state
from qpx_bot.dummy_broker_control import (
    INTERVENTION_TIME,
    main,
    preflight_clean_v2_intervention,
)


ET = ZoneInfo("America/New_York")


class FakeStore:
    def __init__(self, state, heartbeat, error=None):
        self._state = state
        self._heartbeat = heartbeat
        self._error = error

    def reconcile(self):
        if self._error:
            raise self._error
        return self._state

    def read_heartbeat(self):
        return self._heartbeat


class DummyInterventionPreflightTests(unittest.TestCase):
    def setUp(self):
        self.now = INTERVENTION_TIME

    @staticmethod
    def _account(identity="account-one", cash="24.416625"):
        return {
            "schema_version": 1,
            "provider_identity": "DUMMY",
            "account_identity": identity,
            "account_status": "ACTIVE",
            "cash": cash,
            "equity": None,
            "portfolio_value": None,
            "buying_power": None,
            "currency": "USD",
            "positions": [],
            "trading_blocked": False,
            "account_blocked": False,
            "restriction_flags": [],
        }

    def _fixture(self):
        folder = Path(tempfile.mkdtemp())
        account = folder / "account.json"
        checksum = folder / "account.sha256"
        config = folder / "providers.json"
        write_dummy_broker_account_state(account, self._account(), checksum_path=checksum)
        config.write_text(json.dumps({
            "schema_version": 1,
            "market_data_provider": "ALPACA_IEX",
            "broker_account_provider": "DUMMY",
            "order_execution_provider": "SIMULATED",
            "broker_account_configuration": {
                "state_path": str(account),
                "checksum_path": str(checksum),
            },
        }), encoding="utf-8")
        snapshot = build_broker_account_provider(
            __import__("qpx_bot.broker_account_provider", fromlist=["load_provider_selection"])
            .load_provider_selection(config)
        ).observe(self.now.astimezone(timezone.utc))
        state = {
            "simulated_fills_only": True,
            "live_broker_enabled": False,
            "broker_reconciliation": {
                "initial_binding_id": "b" * 64,
                "last_applied_identity_fingerprint": snapshot.identity_fingerprint,
                "broker_account_provider": "DUMMY",
                "last_snapshot": snapshot.as_dict(),
                "risk_block_reason": None,
            }
        }
        heartbeat = {"provider_state": "HEALTHY", "failure": None}
        props = {
            "ActiveState": "active",
            "Environment": f"QPX_BROKER_ACCOUNT_PROVIDER_CONFIG={config.resolve()}",
        }
        return folder, account, checksum, config, state, heartbeat, props

    def _run(self, fixture, *, now=None, state=None, heartbeat=None, props=None):
        folder, _account, _checksum, config, original_state, original_heartbeat, original_props = fixture
        fake = FakeStore(
            state if state is not None else original_state,
            heartbeat if heartbeat is not None else original_heartbeat,
        )
        with patch(
            "qpx_bot.pr50_iex_forward_research_paper.IEXResearchStore",
            return_value=fake,
        ):
            return preflight_clean_v2_intervention(
                config,
                folder / "runtime",
                now=now or self.now,
                systemd_properties=props or original_props,
            )

    def test_all_conditions_healthy_permit(self):
        fixture = self._fixture()
        result = self._run(fixture)
        self.assertEqual(result["status"], "INTERVENTION_PREFLIGHT_PASS")
        self.assertTrue(all(item["status"] == "PASS" for item in result["checks"].values()))

    def test_inactive_clean_v2_is_blocked(self):
        fixture = self._fixture()
        props = dict(fixture[-1], ActiveState="inactive")
        result = self._run(fixture, props=props)
        self.assertEqual(result["status"], "INTERVENTION_PREFLIGHT_FAIL")
        self.assertEqual(result["checks"]["clean_v2_active"]["status"], "FAIL")

    def test_wrong_provider_is_blocked(self):
        fixture = self._fixture()
        fixture[3].write_text(json.dumps({
            "schema_version": 1,
            "market_data_provider": "ALPACA_IEX",
            "broker_account_provider": "SCHWAB",
            "order_execution_provider": "SIMULATED",
            "broker_account_configuration": {},
        }), encoding="utf-8")
        result = self._run(fixture)
        self.assertEqual(result["checks"]["provider_roles"]["status"], "FAIL")

    def test_invalid_dummy_checksum_is_blocked(self):
        fixture = self._fixture()
        fixture[2].write_text("0" * 64 + "\n", encoding="utf-8")
        result = self._run(fixture)
        self.assertEqual(result["checks"]["dummy_state_checksum"]["status"], "FAIL")

    def test_baseline_missing_is_blocked(self):
        fixture = self._fixture()
        result = self._run(fixture, state={"broker_reconciliation": None})
        self.assertEqual(result["checks"]["dummy_baseline_bound"]["status"], "FAIL")

    def test_bound_identity_mismatch_is_blocked(self):
        fixture = self._fixture()
        write_dummy_broker_account_state(
            fixture[1], self._account(identity="different-account"), checksum_path=fixture[2]
        )
        result = self._run(fixture)
        self.assertEqual(result["checks"]["dummy_identity_matches_bound_baseline"]["status"], "FAIL")

    def test_unresolved_reconciliation_failure_is_blocked(self):
        fixture = self._fixture()
        result = self._run(
            fixture,
            heartbeat={"provider_state": "DEGRADED_RECOVERABLE", "failure": {"failure_class": "X"}},
        )
        self.assertEqual(result["checks"]["no_unresolved_reconciliation_failure"]["status"], "FAIL")

    def test_invalid_state_audit_integrity_is_blocked(self):
        fixture = self._fixture()
        folder = fixture[0]
        fake = FakeStore({}, {}, RuntimeError("audit chain broken"))
        with patch("qpx_bot.pr50_iex_forward_research_paper.IEXResearchStore", return_value=fake):
            result = preflight_clean_v2_intervention(
                fixture[3], folder / "runtime", now=self.now, systemd_properties=fixture[-1]
            )
        self.assertEqual(result["checks"]["clean_v2_state_audit_integrity"]["status"], "FAIL")

    def test_outside_time_window_is_blocked(self):
        fixture = self._fixture()
        result = self._run(fixture, now=datetime(2026, 9, 3, 10, 58, tzinfo=ET))
        self.assertEqual(result["checks"]["execution_time_window"]["status"], "FAIL")

    def test_failed_preflight_does_not_mutate_dummy_state(self):
        fixture = self._fixture()
        before = fixture[1].read_bytes(), fixture[2].read_bytes()
        result = self._run(fixture, now=datetime(2026, 9, 3, 10, 58, tzinfo=ET))
        self.assertEqual(result["status"], "INTERVENTION_PREFLIGHT_FAIL")
        self.assertEqual((fixture[1].read_bytes(), fixture[2].read_bytes()), before)

    def test_successful_control_path_is_1400_and_empty(self):
        fixture = self._fixture()
        result = main([
            "--provider-config", str(fixture[3]),
            "--set-cash", "1400.00",
            "--clear-positions",
        ])
        self.assertEqual(result, 0)
        payload = json.loads(fixture[1].read_text(encoding="utf-8"))
        self.assertEqual(payload["cash"], "1400")
        self.assertEqual(payload["positions"], [])


if __name__ == "__main__":
    unittest.main()
