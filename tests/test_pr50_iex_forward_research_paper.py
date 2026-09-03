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
from qpx_bot.broker_account_provider import (
    BrokerAccountSnapshot,
    ProviderSelection,
    build_broker_account_provider,
    write_dummy_broker_account_state,
)
from qpx_bot.pr50_iex_forward_research_paper import (
    BROKER_PROVIDER_BASELINE_EVENT,
    BROKER_RECONCILIATION_MODE,
    BROKER_RECONCILIATION_POLL_SECONDS,
    DEFAULT_RUNTIME,
    EXTERNAL_BROKER_RECONCILIATION_EVENT,
    EXTERNAL_BROKER_RISK_BLOCK,
    OLD_SEMANTIC_CONTRACT_FINGERPRINT,
    SEMANTIC_TRANSITION_EVENT,
    SEMANTIC_VERSION_NEW,
    _transition_semantic_contract_if_required,
    _flush_pending_semantic_transition,
    IEXResearchStore,
    ProviderFailure,
    VARIANT,
    _broker_configuration_fingerprint,
    _cycle,
    _expire_pending,
    _heartbeat_payload,
    _observe_broker_provider,
    _provider_failure,
    _request_json,
    broker_reconciliation_due,
    decision_processing_due,
    execution_clock_action,
    expected_completed_decision_start,
    first_eligible_execution_minute,
    initialize,
    load_contract,
    main,
    observe_and_reconcile_broker_account,
    process_pending_execution_clock,
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

    def test_allowlisted_semantic_transition_preserves_flat_account(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            state = {
                "contract_fingerprint": OLD_SEMANTIC_CONTRACT_FINGERPRINT,
                "contract": {"semantic_version": "PR50_IEX_PRE_PARITY_V1"},
                "initialization_fingerprint": "i" * 64,
                "positions": {}, "pending": {}, "revision": 7,
                "cash": 1400.0, "qdte_shares": 0.0,
                "broker_reconciliation": {
                    "broker_account_provider": "DUMMY",
                    "risk_block_reason": None,
                    "last_snapshot": {
                        "provider_identity": "DUMMY",
                        "account_identity_fingerprint": "a" * 64,
                        "account_status": "ACTIVE",
                        "account_blocked": False,
                        "trading_blocked": False,
                    },
                },
            }
            store.event("TEST_RUNTIME_INITIALIZED", {})
            store.save(state)
            with patch.dict(os.environ, {"QPX_BROKER_ACCOUNT_PROVIDER_CONFIG": "dummy"}):
                self.assertTrue(_transition_semantic_contract_if_required(
                    state, store, load_contract(), datetime(2026, 9, 3, 13, 25, tzinfo=timezone.utc)
                ))
            self.assertEqual(state["semantic_contract_version"], SEMANTIC_VERSION_NEW)
            self.assertEqual(state["cash"], 1400.0)
            self.assertEqual(state["revision"], 8)
            self.assertEqual(sum(
                json.loads(line)["event_type"] == SEMANTIC_TRANSITION_EVENT
                for line in store.journal.read_text().splitlines()
            ), 1)

    def test_semantic_transition_blocks_positions_and_unknown_old_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            state = {
                "contract_fingerprint": OLD_SEMANTIC_CONTRACT_FINGERPRINT,
                "initialization_fingerprint": "i" * 64,
                "positions": {"TSLL": {}}, "pending": {}, "revision": 1,
                "broker_reconciliation": {"broker_account_provider": "DUMMY",
                    "risk_block_reason": None, "last_snapshot": {"provider_identity": "DUMMY", "account_identity_fingerprint": "a" * 64, "account_status": "ACTIVE"}},
            }
            store.event("TEST_RUNTIME_INITIALIZED", {})
            store.save(state)
            with self.assertRaisesRegex(RuntimeError, "no open positions"):
                with patch.dict(os.environ, {"QPX_BROKER_ACCOUNT_PROVIDER_CONFIG": "dummy"}):
                    _transition_semantic_contract_if_required(state, store, load_contract(), datetime(2026, 9, 3, 13, 25, tzinfo=timezone.utc))
            state["positions"] = {}
            state["contract_fingerprint"] = "x" * 64
            with self.assertRaisesRegex(RuntimeError, "allowlisted OLD"):
                _transition_semantic_contract_if_required(state, store, load_contract(), datetime(2026, 9, 3, 13, 25, tzinfo=timezone.utc))

    def test_transition_pending_event_recovery_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            store = IEXResearchStore(Path(folder))
            details = {"event_id": "t" * 64, "old_contract_fingerprint": OLD_SEMANTIC_CONTRACT_FINGERPRINT,
                       "new_contract_fingerprint": "n" * 64}
            state = {"revision": 2, "semantic_transition_event_pending": details,
                     "contract_fingerprint": "n" * 64}
            store.save(state)
            self.assertTrue(_flush_pending_semantic_transition(state, store))
            self.assertFalse(_flush_pending_semantic_transition(state, store))
            records = [json.loads(line) for line in store.journal.read_text().splitlines()]
            self.assertEqual(sum(r["event_type"] == SEMANTIC_TRANSITION_EVENT for r in records), 1)

    def test_position_entry_semantic_snapshot_round_trips(self):
        snapshot = {"semantic_contract_fingerprint": "n" * 64,
                    "candidate_v1_semantic_version": "CANDIDATE_V1_HISTORICAL_NINE_GATE_V1"}
        position = sip.Position("TSLL", 2, datetime(2026, 9, 3).date(), 10.0, 1.0, 8.0, 15.0, 10.0,
                                entry_semantic_snapshot=snapshot)
        restored = sip._position(sip._position_dict(position))
        self.assertEqual(restored.entry_semantic_snapshot, snapshot)

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


class BrokerAccountReconciliationTests(unittest.TestCase):
    observed = datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc)

    @staticmethod
    def dummy_state(cash: str, positions: list[dict]) -> dict:
        market_value = sum(float(item.get("market_value", "0")) for item in positions)
        return {
            "schema_version": 1,
            "provider_identity": "DUMMY",
            "account_identity": "clean-v2-focused-test-account",
            "account_status": "ACTIVE",
            "cash": cash,
            "equity": str(float(cash) + market_value),
            "portfolio_value": str(float(cash) + market_value),
            "buying_power": cash,
            "currency": "USD",
            "positions": positions,
            "trading_blocked": False,
            "account_blocked": False,
            "restriction_flags": [],
        }

    @staticmethod
    def position(
        symbol: str,
        quantity: str,
        average_entry_price: str,
        *,
        current_price: str | None = None,
    ) -> dict:
        return {
            "symbol": symbol,
            "side": "long",
            "quantity": quantity,
            "average_entry_price": average_entry_price,
            "cost_basis": str(float(quantity) * float(average_entry_price)),
            "market_value": str(
                float(quantity) * float(current_price or average_entry_price)
            ),
            "current_price": current_price or average_entry_price,
            "asset_class": "us_equity",
        }

    @staticmethod
    def selection(state_path: Path) -> ProviderSelection:
        return ProviderSelection(
            schema_version=1,
            market_data_provider="ALPACA_IEX",
            broker_account_provider="DUMMY",
            order_execution_provider="SIMULATED",
            broker_account_configuration={"state_path": str(state_path)},
        )

    def initialized(self, folder: str) -> tuple[IEXResearchStore, dict]:
        store = IEXResearchStore(Path(folder))
        with patch(
            "qpx_bot.pr50_iex_forward_research_paper.request_bars",
            return_value={"QDTE": [{"t": "2026-09-02T13:59:00Z", "c": 40.0}]},
        ):
            state = initialize(store, load_contract(), self.observed)
        return store, state

    def compatible_dummy_state(self, state: dict) -> dict:
        positions: list[dict] = []
        qdte_shares = float(state.get("qdte_shares", 0.0))
        if qdte_shares > 0:
            qdte_cost = float(state["qdte_cost"])
            positions.append(
                self.position(
                    "QDTE",
                    str(qdte_shares),
                    str(qdte_cost / qdte_shares),
                )
            )
        for symbol, managed in sorted(state.get("positions", {}).items()):
            positions.append(
                self.position(
                    symbol,
                    str(managed["shares"]),
                    str(managed["entry_price"]),
                )
            )
        cash = float(state["cash"]) + float(state.get("tax_reserve_cash", 0.0))
        return self.dummy_state(str(cash), positions)

    def reconcile(
        self,
        state: dict,
        store: IEXResearchStore,
        selection: ProviderSelection,
        observed: datetime,
    ) -> bool:
        return observe_and_reconcile_broker_account(
            state,
            store,
            observed,
            force=True,
            selection=selection,
            provider=build_broker_account_provider(selection),
        )

    def test_manual_liquidation_reconciles_without_reinitializing_or_strategy_pnl(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            write_dummy_broker_account_state(
                state_path,
                self.compatible_dummy_state(state),
            )
            self.assertFalse(self.reconcile(state, store, selection, self.observed))
            initial_broker_cash = float(
                state["broker_reconciliation"]["last_snapshot"]["cash"]
            )

            state["positions"] = {
                "TSLL": {
                    "symbol": "TSLL",
                    "shares": 10,
                    "entry_date": "2026-09-02",
                    "entry_price": 10.0,
                    "entry_atr": 1.0,
                    "stop_price": 8.0,
                    "target_price": 14.0,
                    "highest_price": 10.0,
                }
            }
            state["pending"] = {
                "JMIA": {
                    "signal_id": "s" * 64,
                    "decision_observed_at_utc": "2026-09-02T14:00:10+00:00",
                    "first_eligible_execution_minute_utc": "2026-09-02T14:01:00+00:00",
                }
            }
            state["realized_pnl"] = 123.45
            strategy_history = list(state["completed_execution_ids"])
            profit_state = json.loads(json.dumps(state["profit_recycling"]))
            contributed = state["contributed_capital"]
            initialization = dict(state["initialization"])
            store.save(state)

            revision_before = state["revision"]
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("1600.25", []),
            )
            self.assertTrue(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=5),
                )
            )
            self.assertEqual(state["cash"], 1600.25)
            self.assertEqual(state["qdte_shares"], 0.0)
            self.assertEqual(state["qdte_cost"], 0.0)
            self.assertEqual(state["positions"], {})
            self.assertEqual(state["pending"], {})
            self.assertEqual(state["realized_pnl"], 123.45)
            self.assertEqual(state["contributed_capital"], contributed)
            self.assertEqual(state["profit_recycling"], profit_state)
            self.assertEqual(state["initialization"], initialization)
            self.assertEqual(state["revision"], revision_before + 1)
            self.assertEqual(
                state["completed_execution_ids"][: len(strategy_history)],
                strategy_history,
            )
            self.assertEqual(len(state["completed_execution_ids"]), len(strategy_history) + 1)
            broker = state["broker_reconciliation"]
            self.assertEqual(broker["external_positions"], {})
            self.assertIsNone(broker["risk_block_reason"])
            self.assertEqual(
                broker["external_account_cash_delta_total"],
                1600.25 - initial_broker_cash,
            )

            records = [
                json.loads(line)
                for line in store.journal.read_text(encoding="utf-8").splitlines()
            ]
            reconciliations = [
                item
                for item in records
                if item["event_type"] == EXTERNAL_BROKER_RECONCILIATION_EVENT
            ]
            self.assertEqual(len(reconciliations), 1)
            last = reconciliations[-1]["details"]
            self.assertEqual(
                last["cash_change_classification"],
                "EXTERNAL_ACCOUNT_CASH_CHANGE_UNCLASSIFIED_NOT_STRATEGY_PNL",
            )
            self.assertEqual(last["strategy_realized_pnl_before"], 123.45)
            self.assertEqual(last["strategy_realized_pnl_after"], 123.45)
            self.assertEqual(len(last["invalidated_pending_actions"]), 1)
            self.assertFalse(last["broker_orders_submitted"])

            restarted = IEXResearchStore(Path(folder))
            recovered = restarted.reconcile()
            self.assertEqual(recovered, state)
            self.assertEqual(restarted.verify_journal()[2], len(records))
            revision_after = state["revision"]
            self.assertFalse(
                self.reconcile(
                    state,
                    restarted,
                    selection,
                    self.observed + timedelta(minutes=10),
                )
            )
            self.assertEqual(state["revision"], revision_after)
            self.assertEqual(state["positions"], {})
            self.assertEqual(state["pending"], {})
            repeated_records = restarted.journal.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(repeated_records), len(records))

    def test_external_positions_are_preserved_exactly_and_block_new_entries(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            write_dummy_broker_account_state(
                state_path,
                self.compatible_dummy_state(state),
            )
            self.assertFalse(self.reconcile(state, store, selection, self.observed))
            qdte = self.position("QDTE", "12.5", "41.25")
            aapl = self.position("AAPL", "3", "230.50")
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("500", [aapl, qdte]),
            )
            self.assertTrue(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=5),
                )
            )
            self.assertEqual(state["qdte_shares"], 12.5)
            self.assertEqual(state["qdte_cost"], 515.625)
            self.assertEqual(state["positions"], {})
            broker = state["broker_reconciliation"]
            self.assertEqual(list(broker["external_positions"]), ["AAPL"])
            self.assertEqual(
                broker["external_positions"]["AAPL"]["quantity"],
                "3",
            )
            self.assertEqual(broker["risk_block_reason"], EXTERNAL_BROKER_RISK_BLOCK)

            symbols = ("AAPL", "TSLL")
            bar_time = datetime(2026, 9, 2, 10, 0, tzinfo=sip.NY)
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
                    vix=18.0,
                    config=object(),
                    global_entry_block_reason=broker["risk_block_reason"],
                )
            self.assertEqual(qualifying, [])
            inputs.assert_not_called()
            evaluate.assert_not_called()
            self.assertEqual(
                census["other"],
                [
                    {"symbol": "AAPL", "reason_code": EXTERNAL_BROKER_RISK_BLOCK},
                    {"symbol": "TSLL", "reason_code": EXTERNAL_BROKER_RISK_BLOCK},
                ],
            )

    def test_dummy_cash_and_position_changes_are_discovered_as_external(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            state["realized_pnl"] = 77.0
            store.save(state)

            write_dummy_broker_account_state(
                state_path,
                self.compatible_dummy_state(state),
            )
            self.assertFalse(self.reconcile(state, store, selection, self.observed))
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("1200", []),
            )
            self.assertTrue(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=5),
                )
            )
            self.assertEqual(state["cash"], 1200.0)
            self.assertEqual(state["realized_pnl"], 77.0)

            external = self.position("EXAMPLE", "2", "50")
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("900", [external]),
            )
            self.assertTrue(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=10),
                )
            )
            self.assertEqual(
                list(state["broker_reconciliation"]["external_positions"]),
                ["EXAMPLE"],
            )
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("950", []),
            )
            self.assertTrue(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=15),
                )
            )
            self.assertEqual(state["cash"], 950.0)
            self.assertEqual(state["broker_reconciliation"]["external_positions"], {})
            self.assertEqual(state["realized_pnl"], 77.0)
            revision = state["revision"]
            event_count = store.verify_journal()[2]
            self.assertFalse(
                self.reconcile(
                    state,
                    store,
                    selection,
                    self.observed + timedelta(minutes=20),
                )
            )
            self.assertEqual(state["revision"], revision)
            self.assertEqual(store.verify_journal()[2], event_count)

    def test_compatible_initial_binding_is_not_external_reconciliation_and_repeats_noop(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            write_dummy_broker_account_state(
                state_path,
                self.compatible_dummy_state(state),
            )
            account_before = {
                key: json.loads(json.dumps(state[key]))
                for key in ("initialization", "cash", "qdte_shares", "qdte_cost", "positions")
            }
            revision_before = state["revision"]

            self.assertFalse(self.reconcile(state, store, selection, self.observed))
            self.assertEqual(state["revision"], revision_before + 1)
            self.assertEqual(
                {
                    key: state[key]
                    for key in ("initialization", "cash", "qdte_shares", "qdte_cost", "positions")
                },
                account_before,
            )
            records = [
                json.loads(line)
                for line in store.journal.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                sum(item["event_type"] == BROKER_PROVIDER_BASELINE_EVENT for item in records),
                1,
            )
            self.assertEqual(
                sum(
                    item["event_type"] == EXTERNAL_BROKER_RECONCILIATION_EVENT
                    for item in records
                ),
                0,
            )
            stable_revision = state["revision"]
            stable_events = len(records)
            for minutes in (5, 10):
                self.assertFalse(
                    self.reconcile(
                        state,
                        store,
                        selection,
                        self.observed + timedelta(minutes=minutes),
                    )
                )
            self.assertEqual(state["revision"], stable_revision)
            self.assertEqual(store.verify_journal()[2], stable_events)

    def test_incompatible_initial_binding_fails_closed_without_account_adoption(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("999", []),
            )
            account_before = json.loads(json.dumps(state))
            with self.assertRaises(ProviderFailure) as raised:
                self.reconcile(state, store, selection, self.observed)
            self.assertEqual(
                raised.exception.failure_class,
                "BROKER_INITIAL_STATE_INCOMPATIBLE",
            )
            persisted = IEXResearchStore(Path(folder)).reconcile()
            self.assertEqual(persisted["cash"], account_before["cash"])
            self.assertEqual(persisted["qdte_shares"], account_before["qdte_shares"])
            self.assertIsNone(
                state["broker_reconciliation"]["last_applied_identity_fingerprint"]
            )
            records = [
                json.loads(line)
                for line in store.journal.read_text(encoding="utf-8").splitlines()
            ]
            self.assertFalse(any(
                item["event_type"] in {
                    BROKER_PROVIDER_BASELINE_EVENT,
                    EXTERNAL_BROKER_RECONCILIATION_EVENT,
                }
                for item in records
            ))

    def test_persisted_broker_risk_block_expires_pending_without_market_request(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state["broker_reconciliation"] = {
                "risk_block_reason": EXTERNAL_BROKER_RISK_BLOCK,
            }
            state["pending"] = {
                "TSLL": {
                    "signal_id": "s" * 64,
                    "decision_observed_at_utc": "2026-09-02T14:00:10+00:00",
                    "first_eligible_execution_minute_utc": "2026-09-02T14:01:00+00:00",
                }
            }
            with patch(
                "qpx_bot.pr50_iex_forward_research_paper.request_bars"
            ) as market_request:
                self.assertFalse(
                    process_pending_execution_clock(
                        state,
                        store,
                        self.observed + timedelta(minutes=1, seconds=10),
                    )
                )
            market_request.assert_not_called()
            self.assertEqual(state["pending"], {})
            self.assertEqual(len(state["completed_execution_ids"]), 2)
            records = [
                json.loads(line)
                for line in store.journal.read_text(encoding="utf-8").splitlines()
            ]
            missed = [
                item for item in records
                if item["event_type"] == "IEX_RESEARCH_ENTRY_EXECUTION_MISSED"
            ]
            self.assertEqual(len(missed), 1)
            self.assertIn(
                EXTERNAL_BROKER_RISK_BLOCK,
                missed[0]["details"]["reason"],
            )

    def test_changed_snapshot_requires_stable_confirmation(self):
        class AlternatingProvider:
            provider_identity = "DUMMY"

            def __init__(self, snapshots: list[BrokerAccountSnapshot]):
                self.snapshots = iter(snapshots)

            def observe(self, _observed_at: datetime) -> BrokerAccountSnapshot:
                return next(self.snapshots)

        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("100", []),
            )
            dummy = build_broker_account_provider(selection)
            first = dummy.observe(self.observed)
            write_dummy_broker_account_state(
                state_path,
                self.dummy_state("101", []),
            )
            second = dummy.observe(self.observed)
            with self.assertRaises(ProviderFailure) as raised:
                observe_and_reconcile_broker_account(
                    state,
                    store,
                    self.observed,
                    force=True,
                    selection=selection,
                    provider=AlternatingProvider([first, second]),
                )
            self.assertEqual(raised.exception.failure_class, "BROKER_SNAPSHOT_UNSTABLE")
            self.assertNotIn("broker_reconciliation_event_pending", state)
            self.assertIsNone(
                state["broker_reconciliation"]["last_applied_identity_fingerprint"]
            )
            self.assertEqual(IEXResearchStore(Path(folder)).reconcile()["revision"], 1)

    def test_runner_rejects_provider_native_payload_instead_of_consuming_it(self):
        class NativePayloadProvider:
            provider_identity = "DUMMY"

            def observe(self, _observed_at: datetime):
                return {"cash": "100", "positions": []}

        with self.assertRaisesRegex(RuntimeError, "non-canonical snapshot"):
            _observe_broker_provider(NativePayloadProvider(), self.observed)

    def test_poll_cadence_and_cycle_order_reconcile_before_risky_work(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            state_path = Path(folder) / "dummy_broker_account.json"
            selection = self.selection(state_path)
            broker = {
                "schema_version": 1,
                "policy_identity": "BROKER_ANCHORED_SIMULATION_V1",
                "configuration_fingerprint": _broker_configuration_fingerprint(selection),
                "mode": BROKER_RECONCILIATION_MODE,
                "market_data_provider": "ALPACA_IEX",
                "broker_account_provider": "DUMMY",
                "order_execution_provider": "SIMULATED",
                "poll_seconds": BROKER_RECONCILIATION_POLL_SECONDS,
                "broker_orders_enabled": False,
                "simulated_strategy_fills_only": True,
                "last_observed_at_utc": self.observed.isoformat(),
                "last_snapshot": None,
                "last_applied_identity_fingerprint": None,
                "last_reconciliation_id": None,
                "reconciliation_count": 0,
                "external_account_cash_delta_total": 0.0,
                "external_positions": {},
                "risk_block_reason": None,
            }
            state["broker_reconciliation"] = broker
            state["last_corporate_action_observation_at_utc"] = self.observed.isoformat()
            store.save(state)
            self.assertFalse(
                broker_reconciliation_due(
                    state,
                    self.observed + timedelta(seconds=BROKER_RECONCILIATION_POLL_SECONDS - 1),
                )
            )
            self.assertTrue(
                broker_reconciliation_due(
                    state,
                    self.observed + timedelta(seconds=BROKER_RECONCILIATION_POLL_SECONDS),
                )
            )

            order: list[str] = []

            def reconcile_first(*_args, **_kwargs):
                order.append("broker_reconciliation")
                return False

            def pending_second(*_args, **_kwargs):
                order.append("pending_execution")
                return False

            with patch(
                "qpx_bot.pr50_iex_forward_research_paper.broker_reconciliation_enabled",
                return_value=True,
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.observe_and_reconcile_broker_account",
                side_effect=reconcile_first,
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.process_pending_execution_clock",
                side_effect=pending_second,
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.decision_processing_due",
                return_value=False,
            ):
                _cycle(store, self.observed + timedelta(minutes=1))
            self.assertEqual(order, ["broker_reconciliation", "pending_execution"])

    def test_startup_or_provider_recovery_forces_reconciliation_without_reinitialize(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            premarket = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
            state["last_corporate_action_observation_at_utc"] = premarket.isoformat()
            store.save(state)
            with patch(
                "qpx_bot.pr50_iex_forward_research_paper.broker_reconciliation_enabled",
                return_value=True,
            ), patch(
                "qpx_bot.pr50_iex_forward_research_paper.observe_and_reconcile_broker_account",
                return_value=False,
            ) as reconcile, patch(
                "qpx_bot.pr50_iex_forward_research_paper.initialize"
            ) as initialize_account:
                recovered = _cycle(
                    store,
                    premarket,
                    force_broker_reconciliation=True,
                )
            self.assertEqual(recovered["initialization"], state["initialization"])
            initialize_account.assert_not_called()
            self.assertTrue(reconcile.call_args.kwargs["force"])

    def test_reconciliation_transaction_recovers_pending_audit_once_after_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            store, state = self.initialized(folder)
            details = {
                "event_id": "r" * 64,
                "revision_before": 1,
                "revision_after": 2,
            }
            state["revision"] = 2
            state["broker_reconciliation_event_pending"] = details
            premarket = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
            state["last_corporate_action_observation_at_utc"] = premarket.isoformat()
            store.save(state)
            restarted = IEXResearchStore(Path(folder))
            with patch.dict(os.environ, {}, clear=True):
                recovered = _cycle(restarted, premarket)
            self.assertNotIn("broker_reconciliation_event_pending", recovered)
            records = [
                json.loads(line)
                for line in restarted.journal.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(
                sum(
                    item["event_type"] == EXTERNAL_BROKER_RECONCILIATION_EVENT
                    for item in records
                ),
                1,
            )
            self.assertEqual(restarted.verify_journal()[2], len(records))


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
            entered = inputs.symbol == "S004"
            return SimpleNamespace(
                should_enter=entered,
                checks={"data_ready": True, "price_above_sma": entered},
                failed_checks=() if entered else ("price_above_sma",),
                triggers=(),
            )

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
        self.assertEqual(details["candidate_v1_first_failed_gate_counts"], {"price_above_sma": 95})
        self.assertTrue(details["candidate_v1_rejection_invariant"]["reconciles"])
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
                "first_failed_gate_counts": {"data_ready": 100},
                "near_misses": [],
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
