from datetime import datetime, timedelta, timezone
import errno
import hashlib
import io
import json
import multiprocessing
import os
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import qpx_bot.fixed25_forward_paper as sip
from qpx_bot.pr50_iex_forward_research_paper import (
    DEFAULT_RUNTIME,
    IEXResearchStore,
    ProviderFailure,
    VARIANT,
    _cycle,
    _expire_pending,
    _heartbeat_payload,
    _provider_failure,
    _request_json,
    decision_processing_due,
    execution_clock_action,
    expected_completed_decision_start,
    first_eligible_execution_minute,
    initialize,
    load_contract,
    main,
    request_bars,
)


def _attempt_lock_in_second_process(directory: str, result) -> None:
    try:
        with IEXResearchStore(Path(directory)).locked():
            result.put("acquired")
    except RuntimeError:
        result.put("rejected")


class PR50IEXForwardResearchPaperTests(unittest.TestCase):
    def test_contract_and_runtime_are_isolated_and_explicit(self):
        contract = load_contract()
        self.assertEqual(contract["feed"], "iex")
        self.assertEqual(contract["profit_recycling_policy"], "PR_FRACTION_50")
        self.assertEqual(contract["maximum_position_notional_fraction"], 0.25)
        self.assertFalse(contract["pyramiding_enabled"])
        self.assertFalse(contract["sip_parity_claimed"])
        self.assertNotEqual(DEFAULT_RUNTIME, sip.DEFAULT_RUNTIME)

    def test_market_request_uses_iex_without_mutating_sip_provider(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps({"bars": {"QDTE": []}}).encode()
        with patch("qpx_bot.pr50_iex_forward_research_paper.sip.credentials", return_value=("key", "secret")), patch(
            "qpx_bot.pr50_iex_forward_research_paper.urllib.request.urlopen", return_value=Response()
        ) as opened:
            request_bars(("QDTE",), "1Min", datetime(2026, 8, 31, tzinfo=timezone.utc),
                         datetime(2026, 8, 31, 1, tzinfo=timezone.utc))
        self.assertIn("feed=iex", opened.call_args.args[0].full_url)
        self.assertIsNot(request_bars, sip.request_bars)

    def test_initialization_uses_separate_iex_labeled_state_and_journal(self):
        observed = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.pr50_iex_forward_research_paper.request_bars",
            return_value={"QDTE": [{"t": "2026-08-31T14:59:00Z", "c": 40.0}]},
        ):
            store = IEXResearchStore(Path(folder))
            state = initialize(store, load_contract(), observed)
            self.assertEqual(state["mode"], VARIANT)
            self.assertEqual(state["initialization"]["feed"], "iex")
            self.assertFalse(state["sip_parity_claimed"])
            self.assertTrue(store.state.name.startswith("iex_research_"))
            self.assertTrue(store.journal.name.startswith("iex_research_"))
            self.assertEqual(store.load(), state)

    def test_missing_exact_qdte_bar_uses_only_prior_causal_close_for_valuation(self):
        from qpx_bot.fixed25_forward_paper import _iex_qdte_sizing_mark
        from zoneinfo import ZoneInfo
        bar_time = datetime(2026, 8, 31, 14, 0, tzinfo=ZoneInfo("America/New_York"))
        rows = [
            {"start": datetime(2026, 8, 31, 13, 30, tzinfo=bar_time.tzinfo), "close": 41.25},
            {"start": datetime(2026, 8, 31, 14, 15, tzinfo=bar_time.tzinfo), "close": 99.0},
        ]
        mark, source = _iex_qdte_sizing_mark({"QDTE": rows}, {"QDTE": {
            rows[0]["start"]: 0, rows[1]["start"]: 1,
        }}, bar_time)
        self.assertEqual(mark, 41.25)
        self.assertEqual(source, rows[0]["start"])
        self.assertLess(source, bar_time)
        self.assertEqual(_iex_qdte_sizing_mark({"QDTE": []}, {"QDTE": {}}, bar_time), (None, None))

    def test_normal_causal_next_minute_execution_window(self):
        observed = datetime(2026, 8, 31, 18, 3, 27, tzinfo=timezone.utc)
        eligible = first_eligible_execution_minute(observed)
        signal = {"first_eligible_execution_minute_utc": eligible.isoformat(),
                  "execution_window_observed_at_utc": None}
        self.assertEqual(eligible, datetime(2026, 8, 31, 18, 4, tzinfo=timezone.utc))
        self.assertEqual(execution_clock_action(signal, eligible + timedelta(seconds=10)),
                         "WINDOW_ACTIVE")

    def test_delayed_decision_processing_schedules_from_observation_not_bar(self):
        delayed_observation = datetime(2026, 8, 31, 18, 47, 59, tzinfo=timezone.utc)
        eligible = first_eligible_execution_minute(delayed_observation)
        self.assertEqual(eligible, datetime(2026, 8, 31, 18, 48, tzinfo=timezone.utc))
        self.assertNotEqual(eligible, datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc))

    def test_restart_after_unobserved_execution_window_expires_without_fill(self):
        eligible = datetime(2026, 8, 31, 18, 4, tzinfo=timezone.utc)
        signal = {"first_eligible_execution_minute_utc": eligible.isoformat(),
                  "execution_window_observed_at_utc": None}
        recovered = datetime(2026, 8, 31, 18, 47, 59, tzinfo=timezone.utc)
        self.assertEqual(execution_clock_action(signal, recovered), "EXPIRE_MISSED_WINDOW")
        signal["execution_window_observed_at_utc"] = "2026-08-31T18:04:10+00:00"
        self.assertEqual(execution_clock_action(signal, recovered), "EXPIRE_MISSED_WINDOW")

    def test_pending_expiration_is_deterministic_and_never_creates_position(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            state = {"contract_fingerprint": "c" * 64, "positions": {},
                     "completed_execution_ids": [], "pending": {}}
            signal = {"signal_id": "s" * 64,
                      "decision_observed_at_utc": "2026-08-31T18:03:27+00:00",
                      "first_eligible_execution_minute_utc": "2026-08-31T18:04:00+00:00"}
            state["pending"]["TSLL"] = signal
            _expire_pending(state, store, "TSLL", signal,
                            datetime(2026, 8, 31, 18, 47, 59, tzinfo=timezone.utc),
                            "PROCESS_NOT_OBSERVED_DURING_ELIGIBLE_MINUTE")
            self.assertNotIn("TSLL", state["pending"])
            self.assertEqual(state["positions"], {})
            self.assertEqual(len(state["completed_execution_ids"]), 1)


class DecisionCycleTelemetryTests(unittest.TestCase):
    def test_candidate_cycle_telemetry_reconciles_exact_top100_outcomes(self):
        symbols = tuple(f"S{index:03d}" for index in range(100))
        bar_time = datetime(2026, 9, 1, 19, 15, tzinfo=timezone.utc)
        histories = {
            symbol: [{"symbol": symbol, "close": float(index + 1)}]
            for index, symbol in enumerate(symbols)
        }
        indices = {
            symbol: ({bar_time: 0} if symbol != "S000" else {})
            for symbol in symbols
        }

        def inputs(rows, *_args):
            symbol = rows[0]["symbol"]
            if symbol == "S003":
                return None
            return SimpleNamespace(
                symbol=symbol,
                current_atr=1.0,
                current_close=rows[0]["close"],
            )

        def evaluation(*, inputs, config):
            del config
            return SimpleNamespace(should_enter=inputs.symbol == "S004")

        with patch.object(sip, "_entry_inputs", side_effect=inputs), patch.object(
            sip, "evaluate_candidate_v1_causal", side_effect=evaluation
        ):
            qualifying, census = sip._evaluate_candidate_v1_cycle(
                symbols=symbols,
                histories=histories,
                indices=indices,
                indicators={symbol: object() for symbol in symbols},
                positions={"S001": object()},
                pending={"S002": {}},
                bar_time=bar_time,
                vix=18.25,
                config=object(),
            )
        details = sip._decision_cycle_telemetry(
            symbols=symbols,
            bar_time=bar_time,
            decision_id="d" * 64,
            state_revision=44,
            feed="iex",
            vix=18.25,
            census=census,
        )

        self.assertEqual([value[1] for value in qualifying], ["S004"])
        self.assertEqual(details["requested_symbol_count"], 100)
        self.assertEqual(details["usable_exact_causal_bar_count"], 99)
        self.assertEqual(details["missing_sparse_bar_count"], 1)
        self.assertEqual(details["insufficient_indicator_history_count"], 1)
        self.assertEqual(details["other_eligibility_skip_count"], 2)
        self.assertEqual(details["candidate_v1_evaluated_count"], 96)
        self.assertEqual(details["candidate_v1_no_action_count"], 95)
        self.assertEqual(details["signal_count"], 1)
        self.assertEqual(details["signaled_symbols"], ["S004"])
        self.assertEqual(details["vix_status"], "AVAILABLE")
        self.assertEqual(
            details["input_availability_status"],
            "PARTIAL_INSUFFICIENT_INDICATOR_HISTORY",
        )
        self.assertEqual(
            {value["symbol"]: value["reason_code"]
             for value in details["skipped_symbols"]},
            {
                "S000": sip.MISSING_SPARSE_BAR,
                "S001": sip.OPEN_POSITION,
                "S002": sip.PENDING_SIGNAL,
                "S003": sip.INSUFFICIENT_INDICATOR_HISTORY,
            },
        )
        self.assertEqual(
            details["candidate_v1_evaluated_count"]
            + details["skipped_symbol_count"],
            details["requested_symbol_count"],
        )

    def test_vix_unavailable_is_one_reconciled_fail_closed_reason(self):
        symbols = tuple(f"S{index:03d}" for index in range(100))
        bar_time = datetime(2026, 9, 1, 19, 15, tzinfo=timezone.utc)
        with patch.object(sip, "_entry_inputs") as inputs, patch.object(
            sip, "evaluate_candidate_v1_causal"
        ) as evaluate:
            qualifying, census = sip._evaluate_candidate_v1_cycle(
                symbols=symbols,
                histories={symbol: [{}] for symbol in symbols},
                indices={symbol: {bar_time: 0} for symbol in symbols},
                indicators={symbol: object() for symbol in symbols},
                positions={},
                pending={},
                bar_time=bar_time,
                vix=None,
                config=object(),
            )
        details = sip._decision_cycle_telemetry(
            symbols=symbols,
            bar_time=bar_time,
            decision_id="d" * 64,
            state_revision=44,
            feed="iex",
            vix=None,
            census=census,
        )
        self.assertEqual(qualifying, [])
        inputs.assert_not_called()
        evaluate.assert_not_called()
        self.assertEqual(details["candidate_v1_evaluated_count"], 0)
        self.assertEqual(details["other_eligibility_skip_count"], 100)
        self.assertEqual(details["vix_status"], "UNAVAILABLE_FAIL_CLOSED")
        self.assertEqual(details["input_availability_status"], sip.VIX_UNAVAILABLE)

    def test_pending_telemetry_recovers_once_without_refetch_or_reconstruction(self):
        symbols = tuple(f"S{index:03d}" for index in range(100))
        bar_time = datetime(2026, 9, 1, 19, 15, tzinfo=timezone.utc)
        details = sip._decision_cycle_telemetry(
            symbols=symbols,
            bar_time=bar_time,
            decision_id="d" * 64,
            state_revision=44,
            feed="iex",
            vix=18.25,
            census={
                "usable": list(symbols),
                "missing": [],
                "insufficient": [],
                "other": [],
                "evaluated": list(symbols),
                "no_action_count": 100,
                "signaled": [],
            },
        )
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.event("TEST_INITIALIZED", {"revision": 43})
            store.save({
                "revision": 44,
                "mode": VARIANT,
                "decision_cycle_telemetry_pending": details,
            })
            restarted = IEXResearchStore(Path(folder))
            state = restarted.reconcile()
            self.assertTrue(sip._flush_pending_decision_cycle_telemetry(state, restarted))
            self.assertFalse(sip._flush_pending_decision_cycle_telemetry(state, restarted))
            records = [
                json.loads(line)
                for line in restarted.journal.read_text(encoding="utf-8").splitlines()
            ]
            telemetry = [
                record for record in records
                if record["event_type"] == sip.DECISION_CYCLE_TELEMETRY_EVENT
            ]
            self.assertEqual(len(telemetry), 1)
            self.assertEqual(telemetry[0]["details"]["decision_id"], "d" * 64)
            self.assertNotIn("decision_cycle_telemetry_pending", restarted.reconcile())
            self.assertEqual(restarted.verify_journal()[2], 2)


class LockLifecycleTests(unittest.TestCase):
    def test_lock_is_acquired_and_released_normally(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            with store.locked():
                owner = json.loads(store.lock.read_text(encoding="utf-8"))
                self.assertEqual(owner["pid"], os.getpid())
                self.assertTrue(owner["token"])
            self.assertFalse(store.lock.exists())

    def test_network_exception_releases_owned_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            with self.assertRaises(urllib.error.URLError):
                with store.locked():
                    raise urllib.error.URLError("temporary connectivity loss")
            self.assertFalse(store.lock.exists())
            with store.locked():
                self.assertTrue(store.lock.exists())

    def test_same_daemon_process_can_perform_multiple_cycles(self):
        class StopDaemon(Exception):
            pass

        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.pr50_iex_forward_research_paper._cycle",
            side_effect=[{"revision": 1}, {"revision": 2}, StopDaemon()],
        ) as run_cycle, patch("qpx_bot.pr50_iex_forward_research_paper.time.sleep"):
            with self.assertRaises(StopDaemon):
                main(["--daemon", "--poll-seconds", "15", "--runtime-dir", folder])
            self.assertEqual(run_cycle.call_count, 3)
            self.assertFalse(IEXResearchStore(Path(folder)).lock.exists())

    def test_second_live_process_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            context = multiprocessing.get_context("fork")
            result = context.Queue()
            with store.locked():
                process = context.Process(
                    target=_attempt_lock_in_second_process, args=(folder, result)
                )
                process.start()
                self.assertEqual(result.get(timeout=5), "rejected")
                process.join(timeout=5)
                self.assertEqual(process.exitcode, 0)
                self.assertTrue(store.lock.exists())

    def test_dead_owner_stale_lock_is_recovered_safely(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.directory.mkdir(parents=True, exist_ok=True)
            dead_pid = os.getpid() + 1_000_000
            while Path(f"/proc/{dead_pid}").exists():
                dead_pid += 1
            store.lock.write_text(str(dead_pid), encoding="utf-8")
            with store.locked():
                owner = json.loads(store.lock.read_text(encoding="utf-8"))
                self.assertEqual(owner["pid"], os.getpid())
                self.assertTrue(owner["token"])
            self.assertFalse(store.lock.exists())


class OutageRecoveryTests(unittest.TestCase):
    def test_transient_network_loss_waits_then_reconciles_and_resumes(self):
        class StopDaemon(BaseException):
            pass

        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)
            initial_store = IEXResearchStore(runtime)
            initial_state = {"revision": 9, "mode": VARIANT}
            initial_store.event("TEST_INITIALIZED", {"revision": 9})
            initial_store.save(initial_state)
            state_hash = hashlib.sha256(initial_store.state.read_bytes()).hexdigest()
            calls = 0

            def interrupted_cycle(store, observed_at):
                nonlocal calls
                calls += 1
                recovered = store.reconcile()
                self.assertEqual(recovered, initial_state)
                if calls == 1:
                    raise ProviderFailure(
                        failure_class="CONNECTIVITY_FAILURE",
                        provider="alpaca",
                        operation="market_bars",
                        endpoint=sip.DATA_URL,
                        recoverable=True,
                        exception_type="URLError",
                        message="temporary socket disconnect",
                        request_parameters={"feed": "iex", "timeframe": "15Min"},
                    )
                if calls == 2:
                    return recovered
                raise StopDaemon()

            with patch(
                "qpx_bot.pr50_iex_forward_research_paper._cycle",
                side_effect=interrupted_cycle,
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.market_session_state",
                return_value="REGULAR_SESSION",
            ), patch("qpx_bot.pr50_iex_forward_research_paper.time.sleep") as sleeper:
                with self.assertRaises(StopDaemon):
                    main(["--daemon", "--poll-seconds", "15", "--runtime-dir", folder])
            self.assertEqual(calls, 3)
            self.assertEqual(sleeper.call_count, 2)
            self.assertEqual(
                hashlib.sha256(initial_store.state.read_bytes()).hexdigest(), state_hash
            )
            event_types = [
                json.loads(line)["event_type"]
                for line in initial_store.journal.read_text(encoding="utf-8").splitlines()
            ]
            self.assertIn("IEX_RESEARCH_PROVIDER_DEGRADED", event_types)
            self.assertIn("IEX_RESEARCH_PROVIDER_RECOVERED", event_types)
            heartbeat = initial_store.read_heartbeat()
            self.assertEqual(heartbeat["provider_state"], "HEALTHY")

    def test_process_restart_reconciles_checksum_and_audit_idempotently(self):
        with tempfile.TemporaryDirectory() as folder:
            first = IEXResearchStore(Path(folder))
            state = {"revision": 12, "mode": VARIANT, "completed_execution_ids": ["x"]}
            self.assertTrue(first.event("SIMULATED_TEST_COMMIT", {"execution_id": "x"}))
            self.assertFalse(first.event("SIMULATED_TEST_COMMIT", {"execution_id": "x"}))
            first.save(state)
            restarted = IEXResearchStore(Path(folder))
            self.assertEqual(restarted.reconcile(), state)
            self.assertEqual(restarted.verify_journal()[2], 1)

    def test_process_restart_restores_degraded_retry_state_then_recovers(self):
        class StopDaemon(BaseException):
            pass

        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            state = {"revision": 12, "mode": VARIANT}
            store.event("TEST_INITIALIZED", {"revision": 12})
            store.save(state)
            failure = ProviderFailure(
                failure_class="REQUEST_TIMEOUT",
                provider="alpaca",
                operation="market_bars",
                endpoint=sip.DATA_URL,
                recoverable=True,
                exception_type="URLError",
                message="timed out",
                request_parameters={"feed": "iex", "timeframe": "15Min"},
            )
            heartbeat = _heartbeat_payload(
                daemon_started_at_utc="2026-09-01T10:00:00+00:00",
                state=state,
                provider_state="DEGRADED_RECOVERABLE",
                session_state="REGULAR_SESSION",
                retry_count=3,
                backoff_seconds=120,
                last_successful_provider_contact_at_utc="2026-09-01T09:59:00+00:00",
                failure=failure,
                degraded_since_at_utc="2026-09-01T10:01:00+00:00",
            )
            store.write_heartbeat(heartbeat)
            with patch(
                "qpx_bot.pr50_iex_forward_research_paper._cycle",
                side_effect=[state, StopDaemon()],
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.market_session_state",
                return_value="REGULAR_SESSION",
            ), patch("qpx_bot.pr50_iex_forward_research_paper.time.sleep"):
                with self.assertRaises(StopDaemon):
                    main(["--daemon", "--poll-seconds", "15", "--runtime-dir", folder])
            records = [
                json.loads(line)
                for line in store.journal.read_text(encoding="utf-8").splitlines()
            ]
            recovered = [
                record for record in records
                if record["event_type"] == "IEX_RESEARCH_PROVIDER_RECOVERED"
            ]
            self.assertEqual(len(recovered), 1)
            self.assertEqual(
                recovered[0]["details"]["previous_consecutive_failures"],
                3,
            )
            self.assertEqual(store.read_heartbeat()["provider_state"], "HEALTHY")

    def test_restart_fails_closed_when_state_integrity_cannot_be_proven(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.event("TEST_INITIALIZED", {"revision": 1})
            store.save({"revision": 1, "mode": VARIANT})
            store.checksum.write_text("0" * 64 + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                IEXResearchStore(Path(folder)).reconcile()


class ProviderFailureClassificationTests(unittest.TestCase):
    def context(self, error):
        return _provider_failure(
            error,
            provider="alpaca",
            operation="market_bars",
            endpoint=sip.DATA_URL,
            parameters={"feed": "iex", "symbols": "QDTE", "timeframe": "1Min"},
        )

    def test_timeout_and_connectivity_are_distinguished(self):
        timeout = self.context(urllib.error.URLError(socket.timeout("timed out")))
        self.assertEqual(timeout.failure_class, "REQUEST_TIMEOUT")
        local = self.context(
            urllib.error.URLError(OSError(errno.ENETUNREACH, "unreachable"))
        )
        self.assertEqual(local.failure_class, "LOCAL_NETWORK_UNAVAILABLE")
        dns = self.context(
            urllib.error.URLError(socket.gaierror(-2, "name resolution failed"))
        )
        self.assertEqual(dns.failure_class, "DNS_CONNECTIVITY_FAILURE")

    def test_429_5xx_and_permission_are_distinguished_with_response(self):
        def error(code, body):
            return urllib.error.HTTPError(
                sip.DATA_URL,
                code,
                "provider response",
                {},
                io.BytesIO(body.encode("utf-8")),
            )

        limited_error = error(429, '{"message":"rate limit"}')
        limited = self.context(limited_error)
        limited_error.close()
        self.assertEqual(limited.failure_class, "ALPACA_RATE_LIMIT")
        self.assertEqual(limited.http_status, 429)
        self.assertIn("rate limit", limited.response_body)
        outage_error = error(503, '{"message":"unavailable"}')
        outage = self.context(outage_error)
        outage_error.close()
        self.assertEqual(outage.failure_class, "ALPACA_PROVIDER_5XX")
        denied_error = error(403, '{"message":"forbidden"}')
        denied = self.context(denied_error)
        denied_error.close()
        self.assertEqual(denied.failure_class, "AUTHENTICATION_PERMISSION_FAILURE")
        self.assertFalse(denied.recoverable)

    def test_malformed_response_is_not_labeled_network(self):
        failure = self.context(json.JSONDecodeError("bad json", "{", 0))
        self.assertEqual(failure.failure_class, "MALFORMED_PROVIDER_RESPONSE")

    def test_timeout_and_429_recover_inside_bounded_request(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"bars":{}}'

        limited = urllib.error.HTTPError(
            sip.DATA_URL,
            429,
            "rate limited",
            {"Retry-After": "1"},
            io.BytesIO(b'{"message":"slow down"}'),
        )
        with patch(
            "qpx_bot.pr50_iex_forward_research_paper.sip.credentials",
            return_value=("key", "secret"),
        ), patch(
            "qpx_bot.pr50_iex_forward_research_paper.urllib.request.urlopen",
            side_effect=[urllib.error.URLError(socket.timeout("timed out")), limited, Response()],
        ) as opened, patch(
            "qpx_bot.pr50_iex_forward_research_paper.time.sleep"
        ) as sleeper:
            payload = _request_json(
                provider="alpaca",
                operation="market_bars",
                endpoint=sip.DATA_URL,
                parameters={"feed": "iex", "symbols": "QDTE", "timeframe": "1Min"},
                user_agent="test",
            )
        self.assertEqual(payload, {"bars": {}})
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(sleeper.call_count, 2)

    def test_5xx_exhaustion_is_bounded_and_preserves_response(self):
        failures = [
            urllib.error.HTTPError(
                sip.DATA_URL,
                503,
                "unavailable",
                {},
                io.BytesIO(b'{"message":"provider unavailable"}'),
            )
            for _ in range(4)
        ]
        with patch(
            "qpx_bot.pr50_iex_forward_research_paper.sip.credentials",
            return_value=("key", "secret"),
        ), patch(
            "qpx_bot.pr50_iex_forward_research_paper.urllib.request.urlopen",
            side_effect=failures,
        ) as opened, patch(
            "qpx_bot.pr50_iex_forward_research_paper.time.sleep"
        ) as sleeper:
            with self.assertRaises(ProviderFailure) as raised:
                _request_json(
                    provider="alpaca",
                    operation="market_bars",
                    endpoint=sip.DATA_URL,
                    parameters={"feed": "iex", "symbols": "QDTE", "timeframe": "1Min"},
                    user_agent="test",
                )
        self.assertEqual(raised.exception.failure_class, "ALPACA_PROVIDER_5XX")
        self.assertEqual(raised.exception.http_status, 503)
        self.assertIn("provider unavailable", raised.exception.response_body)
        self.assertEqual(opened.call_count, 4)
        self.assertEqual(sleeper.call_count, 3)


class UnattendedClockAndHeartbeatTests(unittest.TestCase):
    def test_closed_market_does_not_poll_decision_provider(self):
        observed = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)  # 08:00 ET
        contract = load_contract()
        state = {
            "schema_version": sip.SCHEMA,
            "mode": VARIANT,
            "contract_fingerprint": sip.fingerprint(contract),
            "last_decision_bar": "2026-08-31T15:45:00-04:00",
            "last_corporate_action_observation_at_utc": observed.isoformat(),
            "pending": {},
            "revision": 10,
        }
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.event("TEST_INITIALIZED", {"revision": 10})
            store.save(state)
            with patch.object(sip, "process_latest_decision") as process:
                self.assertEqual(_cycle(store, observed), state)
            process.assert_not_called()
            self.assertFalse(decision_processing_due(state, observed))

    def test_empty_sparse_iex_boundary_is_recoverable_data_failure(self):
        observed = datetime(2026, 9, 1, 14, 1, tzinfo=timezone.utc)  # 10:01 ET
        contract = load_contract()
        state = {
            "schema_version": sip.SCHEMA,
            "mode": VARIANT,
            "contract_fingerprint": sip.fingerprint(contract),
            "last_decision_bar": "2026-09-01T09:30:00-04:00",
            "last_corporate_action_observation_at_utc": observed.isoformat(),
            "pending": {},
            "revision": 10,
        }
        self.assertEqual(
            expected_completed_decision_start(observed).isoformat(),
            "2026-09-01T09:45:00-04:00",
        )
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.event("TEST_INITIALIZED", {"revision": 10})
            store.save(state)
            with patch.object(
                sip,
                "process_latest_decision",
                side_effect=RuntimeError(
                    "No completed Alpaca SIP 15-minute decision bars are available."
                ),
            ):
                with self.assertRaises(ProviderFailure) as raised:
                    _cycle(store, observed)
            self.assertEqual(
                raised.exception.failure_class,
                "EMPTY_SPARSE_MARKET_DATA",
            )

    def test_durable_heartbeat_contains_unattended_status_fields(self):
        state = {
            "revision": 29,
            "last_decision_bar": "2026-09-01T13:15:00-04:00",
            "last_completed_execution_observation_utc": None,
        }
        payload = _heartbeat_payload(
            daemon_started_at_utc="2026-09-01T10:32:31+00:00",
            state=state,
            provider_state="HEALTHY",
            session_state="REGULAR_SESSION",
            retry_count=0,
            backoff_seconds=30,
            last_successful_provider_contact_at_utc="2026-09-01T17:32:28+00:00",
        )
        required = {
            "daemon_started_at_utc",
            "daemon_alive_at_utc",
            "last_successful_provider_contact_at_utc",
            "last_completed_decision_time",
            "last_completed_execution_observation",
            "provider_state",
            "retry_count",
            "backoff_seconds",
            "state_revision",
        }
        self.assertTrue(required.issubset(payload))
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            store.write_heartbeat(payload)
            self.assertEqual(store.read_heartbeat(), payload)


if __name__ == "__main__":
    unittest.main()
