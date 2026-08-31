from datetime import datetime, timezone
import hashlib
import json

import unittest
from unittest.mock import patch

from qpx_bot.fixed25_forward_paper import (
    Store, _minute_for_exit, fingerprint, initialize, load_contract,
    select_causal_execution_bar,
)
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

    def test_execution_bar_must_be_completed_and_regular_session(self):
        now = datetime(2026, 8, 31, 14, 32, 30, tzinfo=timezone.utc)
        rows = [{"t": "2026-08-31T14:31:00Z", "c": 40}, {"t": "2026-08-31T14:32:00Z", "c": 99}]
        selected = select_causal_execution_bar(rows, now)
        self.assertEqual(selected["source_price"], 40)
        self.assertEqual(selected["feed"], "sip")

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


if __name__ == "__main__": unittest.main()
