from datetime import datetime, timezone
import hashlib
import io
import json
import urllib.error

import unittest
from unittest.mock import patch

from qpx_bot.fixed25_forward_paper import (
    Store, _minute_for_exit, _persist_profit_runtime, _profit_runtime,
    apply_qdte_corporate_actions, fingerprint, initialize, load_contract,
    select_causal_execution_bar,
)
from qpx_bot.accelerators.profit_recycling import ProfitRecyclingContext, ProfitSource
from qpx_bot.portfolio import Position


class Fixed25ForwardPaperTest(unittest.TestCase):
    def test_contract_is_fixed25_paper_only(self):
        contract = load_contract()
        self.assertEqual(contract["maximum_position_notional_fraction"], 0.25)
        self.assertFalse(contract["live_broker_enabled"])
        self.assertTrue(contract["simulated_fills_only"])
        self.assertEqual(contract["decision_timeframe"], "15Min")
        self.assertEqual(contract["execution_timeframe"], "1Min")
        self.assertEqual(len(contract["symbols"]), 100)
        self.assertEqual(contract["profit_recycling_policy"], "PR_FRACTION_50")
        self.assertFalse(contract["pyramiding_enabled"])

    def test_execution_bar_must_be_completed_and_regular_session(self):
        now = datetime(2026, 8, 31, 14, 32, 30, tzinfo=timezone.utc)
        rows = [{"t": "2026-08-31T14:31:00Z", "c": 40}, {"t": "2026-08-31T14:32:00Z", "c": 99}]
        selected = select_causal_execution_bar(rows, now)
        self.assertEqual(selected["source_price"], 40)
        self.assertEqual(selected["feed"], "sip")

    def test_nonretryable_alpaca_error_preserves_status_and_body(self):
        from qpx_bot.fixed25_forward_paper import request_bars
        failure = urllib.error.HTTPError(
            "https://data.alpaca.markets/v2/stocks/bars", 403, "Forbidden", {},
            io.BytesIO(b'{"message":"subscription does not permit querying recent SIP data"}'),
        )
        with patch("qpx_bot.fixed25_forward_paper.credentials", return_value=("key", "secret")), patch(
            "qpx_bot.fixed25_forward_paper.urllib.request.urlopen", side_effect=failure
        ) as opened:
            with self.assertRaisesRegex(RuntimeError, "HTTP 403 Forbidden") as raised:
                request_bars(
                    ("QDTE",), "1Min", datetime(2026, 8, 31, tzinfo=timezone.utc),
                    datetime(2026, 8, 31, 1, tzinfo=timezone.utc),
                )
        self.assertIn("subscription does not permit querying recent SIP data", str(raised.exception))
        self.assertIn("feed=sip", str(raised.exception))
        self.assertEqual(opened.call_count, 1)

    def test_initialization_is_integer_qdte_with_remainder_and_restart_safe(self):
        import tempfile
        observed = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.fixed25_forward_paper.request_bars",
            return_value={"QDTE": [{"t": "2026-08-31T14:59:00Z", "c": 40.0}]},
        ):
            contract = load_contract(); store = Store(__import__("pathlib").Path(folder))
            state = initialize(store, contract, observed)
            self.assertEqual(state["qdte_shares"], 36)
            self.assertGreaterEqual(state["cash"], 0)
            self.assertLess(state["cash"], state["initialization"]["fill_price"])
            self.assertEqual(state["initialization_fingerprint"], fingerprint(state["initialization"]))
            encoded = store.state.read_bytes()
            self.assertEqual(store.checksum.read_text().strip(), hashlib.sha256(encoded).hexdigest())
            self.assertEqual(store.load(), state)

    def test_exit_timing_requires_supporting_one_minute_bar(self):
        position = Position(
            symbol="TEST", shares=1, entry_date=datetime(2026, 8, 31).date(),
            entry_price=100, entry_atr=2, stop_price=95, target_price=110,
            highest_price=100,
        )
        rows = [
            {"t": "2026-08-31T14:30:00Z", "l": 96, "h": 104},
            {"t": "2026-08-31T14:31:00Z", "l": 94, "h": 105},
        ]
        from zoneinfo import ZoneInfo
        bar = datetime(2026, 8, 31, 10, 30, tzinfo=ZoneInfo("America/New_York"))
        self.assertEqual(_minute_for_exit(rows, bar, position, "ATR_STOP")["t"], rows[1]["t"])
        with self.assertRaises(RuntimeError):
            _minute_for_exit(rows, bar, position, "ATR_TARGET")

    def _state(self, folder):
        observed = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
        with patch(
            "qpx_bot.fixed25_forward_paper.request_bars",
            return_value={"QDTE": [{"t": "2026-08-31T14:59:00Z", "c": 40.0}]},
        ):
            store = Store(__import__("pathlib").Path(folder))
            return store, initialize(store, load_contract(), observed)

    def test_pr50_tax_separation_withheld_release_and_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            store, state = self._state(folder)
            runtime = _profit_runtime(state)
            decision = runtime.decide(ProfitRecyclingContext(
                decision_timestamp=datetime(2026, 9, 1, 15, tzinfo=timezone.utc),
                realized_event_id="a" * 64, event_sequence=1,
                realized_event_source=ProfitSource.SWING_REALIZED_PROFIT,
                gross_realized_pnl=100.0, tax_reserved=37.0,
                ordinary_investable_cash=500.0, recycled_profit_balance=0.0,
                current_portfolio_equity=1470.0,
            ))
            self.assertEqual(decision.eligible_net_profit, 63.0)
            self.assertEqual(runtime.ledger.recycled_profit_balance, 31.5)
            self.assertEqual(runtime.ledger.withheld_profit_balance, 31.5)
            released = runtime.ledger.on_sleeve_rebalance(500.0, 2)
            self.assertEqual(released, 63.0)
            _persist_profit_runtime(state, runtime)
            state["profit_recycling"]["event_sequence"] = 2
            store.save(state)
            restored = _profit_runtime(store.load())
            self.assertEqual(restored.ledger.released_at_sleeve_rebalance, 63.0)
            self.assertEqual(restored.ledger.profit_lots[0].status, "SETTLED_AT_SLEEVE_REBALANCE")

    def test_qdte_entitlement_and_later_payable_process_release(self):
        import tempfile
        from zoneinfo import ZoneInfo
        with tempfile.TemporaryDirectory() as folder:
            store, state = self._state(folder)
            state["qdte_shares"] = 10.0
            state["qdte_corporate_actions"]["event-1"] = {
                "event_id": "event-1", "first_observed_at_utc": "2026-09-01T12:00:00+00:00",
                "fields": {
                    "ex_date": {"value": "2026-09-03", "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                    "rate": {"value": 0.25, "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                    "payable_date": {"value": "2026-09-04", "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                    "process_date": {"value": "2026-09-08", "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                }, "entitlement": None, "cash_released_at_utc": None,
            }
            ny = ZoneInfo("America/New_York")
            apply_qdte_corporate_actions(state, store, datetime(2026, 9, 3, 9, 30, tzinfo=ny))
            self.assertEqual(state["qdte_corporate_actions"]["event-1"]["entitlement"]["entitled_shares"], 10.0)
            before = state["cash"]
            apply_qdte_corporate_actions(state, store, datetime(2026, 9, 4, 9, 30, tzinfo=ny))
            self.assertEqual(state["cash"], before)
            apply_qdte_corporate_actions(state, store, datetime(2026, 9, 8, 9, 30, tzinfo=ny))
            self.assertEqual(state["cash"], before + 2.5)

    def test_qdte_missing_timing_fails_closed(self):
        import tempfile
        from zoneinfo import ZoneInfo
        with tempfile.TemporaryDirectory() as folder:
            store, state = self._state(folder)
            state["qdte_corporate_actions"]["event-2"] = {
                "event_id": "event-2", "first_observed_at_utc": "2026-09-01T12:00:00+00:00",
                "fields": {
                    "ex_date": {"value": "2026-09-03", "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                    "rate": {"value": 0.20, "first_observed_at_utc": "2026-09-01T12:00:00+00:00"},
                }, "entitlement": None, "cash_released_at_utc": None,
            }
            before = state["cash"]
            apply_qdte_corporate_actions(
                state, store, datetime(2026, 9, 3, 9, 30, tzinfo=ZoneInfo("America/New_York"))
            )
            event = state["qdte_corporate_actions"]["event-2"]
            self.assertEqual(event["settlement_status"], "FAIL_CLOSED_MISSING_PAYABLE_OR_PROCESS_DATE")
            self.assertEqual(state["cash"], before)


if __name__ == "__main__": unittest.main()
