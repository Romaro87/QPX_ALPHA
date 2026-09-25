"""Focused deterministic proof of causal live OPEN, durability and additive marks."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import qpx_bot.pr50_iex_forward_research_paper as runner
from qpx_bot import fixed25_forward_paper as sip
from qpx_bot.iex_paper_observability import performance

NOW = datetime(2026, 9, 24, 14, 1, 10, tzinfo=timezone.utc)
ELIGIBLE = NOW.replace(second=0)


class Clock(datetime):
    current = NOW

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)


class LiveExecutionRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = runner.IEXResearchStore(Path(self.temp.name))
        with patch.object(runner, "request_bars", return_value={"QDTE": [{"t": (NOW - timedelta(minutes=2)).isoformat(), "c": 30.0}]}):
            self.state = runner.initialize(self.store, runner.load_contract(), NOW)
        self.state["cash"] = 10000.0
        self.state["account_marks"] = {"QDTE": {"price": 30.0, "market_data_timestamp": (ELIGIBLE - timedelta(minutes=1)).isoformat()}}
        self.snapshot = sip.load_candidate_v1_config()
        self.state["pending"] = {"TSLL": self.signal("one")}
        self.store.save(self.state)
        Clock.current = NOW

    def signal(self, identity):
        return {"signal_id": identity, "signal_bar": "2026-09-24T09:45:00-04:00",
                "decision_bar_interval": {"start_market": "2026-09-24T09:45:00-04:00", "end_market": "2026-09-24T10:00:00-04:00"},
                "decision_observed_at_utc": (ELIGIBLE - timedelta(seconds=30)).isoformat(),
                "first_eligible_execution_minute_utc": ELIGIBLE.isoformat(),
                "execution_window_observed_at_utc": None, "prior_close": 10.0, "atr": 1.0,
                "candidate_v1_config_snapshot": self.snapshot.as_dict(), "candidate_v1_config_fingerprint": self.snapshot.fingerprint}

    def open(self):
        return {"t": ELIGIBLE.isoformat(), "o": 10.0, "observed_at_utc": NOW.isoformat(),
                "price_source": "ALPACA_IEX_FIRST_ELIGIBLE_TRADE", "causal_status": "OBSERVED_WITHIN_ELIGIBLE_MINUTE",
                "trade": {"t": (ELIGIBLE + timedelta(seconds=1)).isoformat(), "p": 10.0, "s": 100, "x": "V", "z": "C", "c": ["@"]}}

    def events(self, kind):
        return [r for r in map(json.loads, self.store.journal.read_text().splitlines()) if r["event_type"] == kind]

    def test_pending_survives_restart_then_authentic_open_fills_once(self):
        restarted = runner.IEXResearchStore(Path(self.temp.name))
        state = restarted.reconcile()
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=self.open()):
            self.assertFalse(runner.process_pending_execution_clock(state, restarted, NOW))
            after = deepcopy(state)
            self.assertFalse(runner.process_pending_execution_clock(state, restarted, NOW))
            self.assertEqual(state, after)
        self.assertEqual(len(self.events("SIMULATED_ENTRY_FILLED")), 1)
        self.assertEqual(len(state["positions"]), 1)
        self.assertEqual(restarted.reconcile(), state)
        self.assertFalse(state["live_broker_enabled"])

    def test_first_symbol_no_data_does_not_starve_second(self):
        self.state["pending"]["AAAA"] = self.signal("two")
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", side_effect=lambda symbol, *_: None if symbol == "AAAA" else self.open()):
            self.assertTrue(runner.process_pending_execution_clock(self.state, self.store, NOW))
        self.assertIn("TSLL", self.state["positions"])
        self.assertEqual(set(self.state["pending"]), {"AAAA"})
        self.assertIsNotNone(self.state["pending"]["AAAA"]["execution_window_observed_at_utc"])

    def test_observed_unavailable_minute_rejects_once_with_evidence(self):
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=None):
            runner.process_pending_execution_clock(self.state, self.store, NOW)
            Clock.current += timedelta(minutes=1)
            runner.process_pending_execution_clock(self.state, self.store, Clock.current)
            runner.process_pending_execution_clock(self.state, self.store, Clock.current)
        missed = self.events("IEX_RESEARCH_ENTRY_EXECUTION_MISSED")
        self.assertEqual(len(missed), 1)
        self.assertEqual(missed[0]["details"]["reason"], "AUTHENTIC_OPEN_UNAVAILABLE_DURING_ELIGIBLE_MINUTE")
        self.assertIsNotNone(missed[0]["details"]["last_open_attempt_at_utc"])
        self.assertFalse(self.state["positions"])

    def test_crash_after_state_before_audit_recovers_without_duplicate_fill(self):
        original = sip.Store.event
        def fail_delivery(store, kind, details):
            if kind == "SIMULATED_ENTRY_FILLED":
                raise OSError("injected audit delivery interruption")
            return original(store, kind, details)
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=self.open()), patch.object(sip.Store, "event", fail_delivery):
            with self.assertRaises(OSError):
                runner.process_pending_execution_clock(self.state, self.store, NOW)
        restarted = runner.IEXResearchStore(Path(self.temp.name))
        state = restarted.reconcile()
        cash = state["cash"]
        runner.process_pending_execution_clock(state, restarted, NOW)
        self.assertEqual(state["cash"], cash)
        self.assertEqual(len(self.events("SIMULATED_ENTRY_FILLED")), 1)
        self.assertEqual(state["audit_outbox"], [])

    def test_cached_open_cannot_be_filled_on_restart_after_deadline(self):
        self.state["pending"]["TSLL"]["authentic_open"] = self.open()
        later = NOW + timedelta(minutes=1)
        runner.process_pending_execution_clock(self.state, self.store, later)
        self.assertFalse(self.state["positions"])

    def test_trade_source_uses_first_eligible_trade_and_bounded_get(self):
        odd = {**self.open()["trade"], "c": ["@", "I"], "p": 999}
        with patch.object(runner, "datetime", Clock), patch.object(runner, "_request_json", return_value={"trades": [odd, self.open()["trade"]]}) as request:
            result = runner.request_authentic_open("TSLL", ELIGIBLE, NOW)
        self.assertEqual(result["o"], 10)
        self.assertEqual(request.call_args.kwargs["attempts"], 1)
        self.assertEqual(request.call_args.kwargs["parameters"]["end"], NOW.isoformat())
        with patch.object(runner, "_request_json") as request:
            self.assertIsNone(runner.request_authentic_open("TSLL", ELIGIBLE, NOW + timedelta(minutes=1)))
            request.assert_not_called()

    def test_late_provider_response_is_not_a_live_open(self):
        Clock.current = NOW + timedelta(minutes=1)
        with patch.object(runner, "datetime", Clock), patch.object(runner, "_request_json", return_value={"trades": [self.open()["trade"]]}):
            self.assertIsNone(runner.request_authentic_open("TSLL", ELIGIBLE, NOW))

    def test_marks_metrics_and_dividends_migrate_without_account_reset(self):
        self.state.update(cash=28.0282, qdte_shares=50, qdte_cost=1421.065, contributed_capital=1443.34, realized_pnl=0, pending={})
        self.state["qdte_corporate_actions"] = {
            "a": {"entitlement": {"entitled_shares": 50, "rate": .115064}, "cash_released": 5.7532},
            "b": {"entitlement": {"entitled_shares": 50, "rate": .109967}},
        }
        before = deepcopy(self.state)
        self.store.publish_metrics(self.state, NOW)
        for key in before:
            self.assertEqual(self.state[key], before[key])
        metrics = self.store.reconcile()["account_metrics"]
        self.assertAlmostEqual(metrics["marked_equity"], 1528.0282)
        self.assertAlmostEqual(metrics["net_pnl"], 84.6882)
        self.assertAlmostEqual(metrics["unrealized_pnl"], 78.935)
        self.assertAlmostEqual(metrics["dividends_pending"], 5.49835)
        self.assertAlmostEqual(metrics["dividends_released"], 5.7532)
        self.assertEqual(metrics["swing_market_value"], 0)
        payload = runner._heartbeat_payload(daemon_started_at_utc=NOW.isoformat(), state=self.state, provider_state="HEALTHY", session_state="REGULAR_SESSION", retry_count=0, backoff_seconds=0, last_successful_provider_contact_at_utc=NOW.isoformat())
        self.assertEqual(payload["account_metrics"], metrics)
        self.assertFalse(payload["live_broker_enabled"])
        self.assertFalse(payload["broker_reconciliation"]["broker_orders_enabled"])

    def test_session_early_close_dst_and_outside_execution(self):
        self.assertEqual(runner.market_session_state(datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)), "POST_CLOSE_DECISION_FINALIZATION")
        self.assertEqual(runner.expected_completed_decision_start(datetime(2026, 11, 27, 18, 1, tzinfo=timezone.utc)).hour, 12)
        self.assertEqual(runner.market_session_state(datetime(2026, 12, 1, 14, 29, tzinfo=timezone.utc)), "PRE_MARKET")
        self.state["pending"]["TSLL"]["first_eligible_execution_minute_utc"] = "2026-09-24T20:00:00+00:00"
        runner.process_pending_execution_clock(self.state, self.store, datetime(2026, 9, 24, 20, 0, 5, tzinfo=timezone.utc))
        self.assertEqual(self.events("IEX_RESEARCH_ENTRY_EXECUTION_MISSED")[0]["details"]["reason"], "ELIGIBLE_MINUTE_OUTSIDE_REGULAR_SESSION")

    def test_worker_does_not_terminate_between_close_and_eligible_minute(self):
        before = ELIGIBLE - timedelta(seconds=1)
        with patch.object(runner, "request_authentic_open") as request:
            self.assertTrue(runner.process_pending_execution_clock(self.state, self.store, before))
            request.assert_not_called()
        unit = (Path(__file__).parents[1] / "deploy/qpx-pr50-iex-forward-research-paper-clean-v2.service").read_text()
        self.assertIn("--daemon --poll-seconds 5", unit)
        self.assertNotIn("RuntimeMaxSec", unit)

    def test_completed_close_stages_one_durable_entry_then_next_minute_fills(self):
        self.state["pending"] = {}
        self.state["last_decision_bar"] = "2026-09-24T09:30:00-04:00"
        Clock.current = ELIGIBLE - timedelta(seconds=30)
        row = {"t": "2026-09-24T13:45:00Z", "o": 10.0, "h": 11.0, "l": 9.0, "c": 10.0, "v": 100000}
        self.store.bind(self.state)
        with patch.object(sip, "datetime", Clock), patch.object(sip, "request_bars", side_effect=lambda symbols, *_: {s: [row] for s in symbols}), patch.object(sip, "_vix_previous_close", return_value=18.0), patch.object(sip, "_evaluate_candidate_v1_cycle", return_value=([("rank", "TSLL", 1.0, 10.0)], {})), patch.object(sip, "_decision_cycle_telemetry", return_value={"decision_id": "test-cycle"}):
            sip.process_latest_decision(self.state, self.store, Clock.current)
            sip.process_latest_decision(self.state, self.store, Clock.current)
        self.assertEqual(set(self.state["pending"]), {"TSLL"})
        self.assertEqual(len(self.events("ENTRY_STAGED_15M")), 1)
        self.assertEqual(self.state["pending"]["TSLL"]["first_eligible_execution_minute_utc"], ELIGIBLE.isoformat())
        restarted = runner.IEXResearchStore(Path(self.temp.name))
        state = restarted.reconcile()
        Clock.current = NOW
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=self.open()):
            runner.process_pending_execution_clock(state, restarted, NOW)
        self.assertEqual(len(self.events("SIMULATED_ENTRY_FILLED")), 1)

    def test_open_phase_wait_does_not_prevent_pending_observation(self):
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=self.open()):
            runner.process_pending_execution_clock(self.state, self.store, NOW, allow_execution=False)
        self.assertFalse(self.state["positions"])
        signal = self.store.reconcile()["pending"]["TSLL"]
        self.assertEqual(signal["authentic_open"], self.open())
        self.assertEqual(signal["last_open_observation_error"], "WAITING_FOR_ACCOUNT_OPEN_PHASE")

    def test_performance_win_loss_and_window_are_persisted_not_inferred_later(self):
        records = [{"event_type": "SIMULATED_EXIT_FILLED", "observed_at_utc": NOW.isoformat(), "details": {"realized_pnl": pnl}} for pnl in (20.0, -5.0, 0.0)]
        report = performance(self.state, records, NOW, sip.NY)
        totals = report["account_to_date"]
        self.assertEqual(totals["closed_trades"], 3)
        self.assertEqual((totals["wins"], totals["losses"]), (1, 1))
        self.assertEqual(totals["profit_factor"], 4.0)
        self.assertEqual(totals["win_rate"], 1 / 3)
        self.assertIsNone(report["window_14_calendar_days"]["starting_equity"])

    def test_open_trade_provider_remains_get_only(self):
        import io
        with patch.object(sip, "credentials", return_value=("test", "test")), patch.object(runner.urllib.request, "urlopen", return_value=io.BytesIO(b'{"trades":[]}')) as opened:
            runner._request_json(provider="ALPACA_IEX", operation="authentic_minute_open", endpoint="https://data.alpaca.markets/v2/stocks/TSLL/trades", parameters={"feed": "iex"}, user_agent="test", attempts=1)
        request = opened.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)

    def test_persisted_ninety_percent_cap_overrides_legacy_fixed25_artifact(self):
        from types import SimpleNamespace
        self.state["contract"]["maximum_position_notional_fraction"] = 0.9
        # Sizing supplies a trade larger than 25%; the existing governed cap is 90%.
        sizing = SimpleNamespace(entry_fill=10.0, shares=800, is_tradeable=True, stop_price=8.0, target_price=14.0)
        with patch.object(runner, "datetime", Clock), patch.object(runner, "request_authentic_open", return_value=self.open()), patch.object(sip, "calculate_position_size", return_value=sizing):
            runner.process_pending_execution_clock(self.state, self.store, NOW)
        self.assertEqual(self.state["positions"]["TSLL"]["shares"], 800)


if __name__ == "__main__":
    unittest.main()
