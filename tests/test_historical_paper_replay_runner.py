from __future__ import annotations

from datetime import datetime, timedelta
import json
import unittest
from zoneinfo import ZoneInfo

from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.historical_paper_replay import load_replay_configuration
from qpx_bot.historical_paper_replay_runner import (
    CompletedBarEvidence,
    CompletedBoundary,
    DEFAULT_CANDIDATE_POLICY,
    DEFAULT_CONFIG,
    DEFAULT_SYMBOLS,
    CandidateV1HistoricalPaperRuntime,
    _sha256,
)
from qpx_bot.intraday_six_paper import IntradayBar, load_policy


class CandidateV1HistoricalPaperRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_replay_configuration(DEFAULT_CONFIG)
        self.policy = load_policy(DEFAULT_CANDIDATE_POLICY)
        self.ny = ZoneInfo("America/New_York")

    def _boundary(self, start: datetime, *, open_price: float = 100.0) -> CompletedBoundary:
        bar = IntradayBar(
            start=start,
            open=open_price,
            high=max(open_price, 102.0),
            low=min(open_price, 99.0),
            close=101.0,
            volume=100_000,
        )
        inputs = CandidateV1CausalInputs(
            index=50,
            current_close=101.0,
            current_volume=100_000,
            current_fast=101.0,
            previous_fast=99.0,
            current_slow=100.0,
            previous_slow=100.0,
            current_rsi=60.0,
            previous_rsi=49.0,
            current_rmi=60.0,
            previous_rmi=49.0,
            current_sma=100.0,
            slope_sma=99.0,
            baseline_volume=80_000.0,
            current_atr=1.0,
            prior_high=100.0,
            vix=0.0,
        )
        completed = start + timedelta(minutes=15)
        evidence = CompletedBarEvidence(
            symbol="XLE",
            provider_asset_id="asset-xle",
            bar=bar,
            completed_at=completed,
            candidate_inputs=inputs,
        )
        return CompletedBoundary(
            boundary_id=completed.isoformat(),
            completed_at=completed,
            bars=(evidence,),
            previous_session_vix=20.0,
        )

    def test_primary_config_binds_current_candidate_manifest_without_monthly_policy(self):
        universe = self.config.payload["universe"]
        self.assertEqual(universe["mode"], "STATIC_FROZEN")
        self.assertFalse(universe["retrospective_selection"])
        self.assertIsNone(universe["policy"])
        self.assertEqual(universe["manifest_reference"], "qpx_bot/symbols.json")
        self.assertEqual(universe["manifest_fingerprint"], _sha256(DEFAULT_SYMBOLS))
        self.assertEqual(self.policy.interval, "15m")
        self.assertEqual(self.policy.history_range, "60d")
        self.assertEqual(
            self.policy.signal_evaluation,
            "all_candidates_each_completed_15m_bar",
        )
        self.assertEqual(self.policy.signal_execution, "next_completed_15m_bar_open")
        self.assertFalse(self.policy.rankings_enabled)
        self.assertEqual(self.policy.maximum_gap_atr_multiple, 2.0)

    def test_each_completed_15m_boundary_evaluates_candidate_without_monthly_gate(self):
        runtime = CandidateV1HistoricalPaperRuntime(self.config)
        first = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        runtime.process_boundary(self._boundary(first), {})
        runtime.process_boundary(self._boundary(first + timedelta(minutes=15)), {})
        self.assertEqual(runtime.state["boundaries"], 2)
        self.assertEqual(runtime.state["candidate_evaluations"], 2)

    def test_signal_waits_for_next_15m_open_and_snapshot_is_json_restartable(self):
        runtime = CandidateV1HistoricalPaperRuntime(self.config)
        first = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        runtime.process_boundary(self._boundary(first), {})
        self.assertNotIn("XLE", runtime._portfolio.positions)
        self.assertIn("XLE", runtime.state["pending"])

        runtime.process_boundary(
            self._boundary(first + timedelta(minutes=15), open_price=100.5),
            {},
        )
        self.assertIn("XLE", runtime._portfolio.positions)
        self.assertEqual(runtime._portfolio.positions["XLE"].entry_date.isoformat(), "2025-01-02")
        restored = CandidateV1HistoricalPaperRuntime(
            self.config,
            json.loads(json.dumps(runtime.snapshot())),
        )
        self.assertEqual(restored.snapshot(), runtime.snapshot())


if __name__ == "__main__":
    unittest.main()
