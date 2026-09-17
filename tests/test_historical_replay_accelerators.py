from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from qpx_bot.candidate_v1_config import load_candidate_v1_config
from qpx_bot.historical_paper_replay import ReplayConfigurationError, load_replay_configuration
from qpx_bot.historical_paper_replay_runner import (
    CandidateV1HistoricalPaperRuntime, CompletedBarEvidence, CompletedBoundary,
    _fingerprint, _load_strategy_profile, _read_runtime_state,
    _write_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import load_bound_universe
from qpx_bot.intraday_six_paper import IntradayBar
from qpx_bot.portfolio import Position
from qpx_bot.risk import PositionSize


ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_top100_aggressive_accelerated_v1.json"
PROFILE_PATH = ROOT / "qpx_bot/paper_profiles/top100_aggressive_accelerated_v1.json"
DATASET = ROOT / "research_data/qpx_ml_historical_v1"
NY = ZoneInfo("America/New_York")


def split_contract() -> dict:
    event = {
        "provider_event_id": "split-event-1", "action_type": "reverse_split",
        "affected_provider_asset_id": "asset-a", "effective_date": "2025-01-03",
        "old_rate": 10.0, "new_rate": 1.0, "share_multiplier": 0.1,
        "price_multiplier": 10.0,
        "ratio_convention": "NEW_SHARES_PER_OLD_SHARES_EQUALS_NEW_RATE_DIVIDED_BY_OLD_RATE",
        "split_record_fingerprint": hashlib.sha256(b"split-event-1").hexdigest(),
    }
    return {
        "manifest_fingerprint": "a" * 64,
        "corporate_action_ratio_artifact_fingerprint": "b" * 64,
        "derived_identity_resolution_fingerprint": "c" * 64,
        "derived_asset_id_universe_fingerprint": "d" * 64,
        "source_corporate_action_artifact_fingerprint": "e" * 64,
        "source_identity_resolution_fingerprint": "f" * 64,
        "split_accounting_semantic_version": "QPX_CAUSAL_SPLIT_ACCOUNTING_V1",
        "split_event_count": 1, "split_events": [event],
    }


class HistoricalReplayAcceleratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_replay_configuration(CONFIG_PATH)
        self.snapshot = _load_strategy_profile(PROFILE_PATH, self.config)

    def runtime(self, *, splits: dict | None = None) -> CandidateV1HistoricalPaperRuntime:
        return CandidateV1HistoricalPaperRuntime(
            self.config, candidate_snapshot=self.snapshot,
            asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
            split_contract=splits,
        )

    def position(self) -> Position:
        return Position(
            symbol="asset-a", shares=4, entry_date=date(2025, 1, 2),
            entry_price=100.0, entry_atr=10.0, stop_price=75.0,
            target_price=150.0, highest_price=120.0,
            entry_stop_atr_multiple=2.5, entry_target_atr_multiple=5.0,
            entry_trailing_activation_atr=3.0, exit_slippage_rate=0.00075,
        )

    def test_exact_configuration_and_top100_binding(self) -> None:
        bot = self.snapshot.bot_config
        self.assertEqual((bot.maximum_swing_positions, bot.risk_per_trade, bot.maximum_active_portfolio_risk), (12, 0.10, 0.60))
        self.assertEqual(self.snapshot.maximum_position_notional_fraction, 0.90)
        self.assertEqual(self.snapshot.momentum_persistence_level, 52.0)
        self.assertEqual((self.snapshot.vix_exclusion_low, self.snapshot.vix_exclusion_high), (20.0, 25.0))
        assets, manifest = load_bound_universe(self.config, DATASET)
        self.assertEqual(manifest["selected_count"], 100)
        self.assertEqual(len(assets), 101)
        self.assertEqual(sum(label == "QDTE" for label in assets.values()), 1)
        self.assertEqual(set(self.config.payload["accelerators"]), {"profit_recycling", "dynamic_sizing", "pyramiding", "regime_allocation"})

    def test_dynamic_sizing_is_reduction_only_and_persists_evidence(self) -> None:
        runtime = self.runtime()
        sizing = PositionSize(10, 100.0, 75.0, 150.0, 25.0, 250.0, 0.10)
        adjusted = runtime._apply_dynamic_sizing(
            asset_id="asset-a", decision_timestamp=datetime(2025, 1, 2, 10, tzinfo=NY),
            equity=1000.0, deployable_cash=1000.0, active_risk=400.0,
            risk_budget_shares=10, sizing=sizing,
        )
        self.assertEqual(adjusted.shares, 7)
        evidence = runtime.state["accelerators"]["dynamic_sizing"]
        self.assertEqual((evidence["opportunities"], evidence["reductions"], evidence["unchanged"]), (1, 1, 0))
        self.assertEqual(evidence["decisions"][0]["configuration_version"], "dynamic-sizing-risk-utilization-v1-cap-90pct")

    def test_profit_recycling_classifies_close_and_attributes_later_deployment(self) -> None:
        runtime = self.runtime()
        runtime._portfolio.cash = 1000.0
        position = self.position()
        runtime._portfolio.positions["asset-a"] = position
        runtime._register_position_for_pyramiding("asset-a", position)
        runtime.state["last_marks"]["asset-a"] = 120.0
        before_equity = runtime._current_equity()
        trade = runtime._close_position(
            asset_id="asset-a", exit_price=120.0, exit_date=date(2025, 1, 3),
            reason="TEST", decision_timestamp=datetime(2025, 1, 3, 10, tzinfo=NY),
        )
        self.assertGreater(trade.pnl, 0)
        profit = runtime.state["accelerators"]["profit_recycling"]
        self.assertEqual(len(profit["decisions"]), 1)
        self.assertGreater(profit["ledger"]["recycled_profit_balance"], 0)
        self.assertAlmostEqual(runtime._current_equity(), before_equity, delta=1.0)
        cost = min(25.0, runtime._portfolio.cash)
        runtime._portfolio.cash -= cost
        used = runtime._consume_recycled_cash(cost)
        self.assertGreater(used, 0)
        self.assertEqual(profit["ledger"]["already_recycled_amount"], used)

    def test_pyramid_uses_prior_close_and_authentic_open_then_regime_rebalances(self) -> None:
        runtime = self.runtime()
        runtime._portfolio.cash = 2000.0
        position = self.position()
        runtime._portfolio.positions["asset-a"] = position
        runtime._register_position_for_pyramiding("asset-a", position)
        runtime.state["last_marks"].update({"asset-a": 120.0, "income-id": 50.0})
        runtime.state["last_atr"]["asset-a"] = 10.0
        start = datetime(2025, 1, 2, 9, 30, tzinfo=NY)
        evidence = CompletedBarEvidence(
            "AAA", "asset-a", IntradayBar(start, 121.0, 123.0, 120.0, 122.0, 100000),
            start + timedelta(minutes=15), None,
        )
        runtime._apply_pyramids_open(start, {"asset-a": evidence})
        pyramid = runtime.state["accelerators"]["pyramiding"]
        self.assertEqual((pyramid["opportunities"], pyramid["additions"]), (1, 1))
        self.assertEqual(position.shares, 6)
        self.assertIsInstance(pyramid["positions"]["asset-a"]["additions"][0]["shares_added"], int)

        qdte = CompletedBarEvidence(
            "QDTE", "income-id", IntradayBar(start, 50.0, 50.0, 50.0, 50.0, 1000),
            start + timedelta(minutes=15), None,
        )
        runtime._rebalance_income_open(
            start, {"income-id": qdte, "asset-a": evidence}, 18.0,
            datetime(2024, 12, 31, 16, 0, tzinfo=NY),
        )
        regime = runtime.state["accelerators"]["regime_allocation"]
        self.assertEqual(regime["decisions"][0]["proposed_target_qdte_weight"], 0.05)
        self.assertIn("rebalance_action", regime["decisions"][0])

    def test_split_scales_pyramid_metadata_and_restart_is_exact(self) -> None:
        runtime = self.runtime(splits=split_contract())
        runtime._portfolio.cash = 1000.0
        position = self.position()
        runtime._portfolio.positions["asset-a"] = position
        runtime._register_position_for_pyramiding("asset-a", position)
        meta = runtime.state["accelerators"]["pyramiding"]["positions"]["asset-a"]
        meta["additions"].append({
            "event_id": "x", "event_sequence": 1, "timestamp": "2025-01-02T10:00:00-05:00",
            "fill_price": 110.0, "shares_added": 2, "atr_used": 10.0,
            "configuration_fingerprint": runtime._accelerators.pyramiding_config.fingerprint,
            "decision_id": "y",
        })
        runtime.state["last_marks"]["asset-a"] = 120.0
        runtime.state["last_atr"]["asset-a"] = 10.0
        start = datetime(2025, 1, 3, 9, 30, tzinfo=NY)
        runtime.process_boundary(CompletedBoundary(
            _fingerprint({"start": start.isoformat()}), start + timedelta(minutes=15),
            (), 18.0, datetime(2025, 1, 2, 16, 0, tzinfo=NY),
        ), {})
        self.assertEqual(position.shares, 0.4)
        self.assertEqual(meta["original_entry_shares"], 0.4)
        self.assertEqual(meta["additions"][0]["shares_added"], 0.2)
        self.assertEqual(meta["original_entry_price"], 1000.0)

        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            _write_runtime_state(run_dir, "run-1", self.config, runtime)
            restored_state = _read_runtime_state(run_dir, self.config)
            restored = CandidateV1HistoricalPaperRuntime(
                self.config, restored_state, candidate_snapshot=self.snapshot,
                asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
                split_contract=split_contract(),
            )
            self.assertEqual(_fingerprint(runtime.snapshot()), _fingerprint(restored.snapshot()))
            corrupted = json.loads(json.dumps(restored_state))
            corrupted["accelerators"]["configuration_fingerprints"]["pyramiding"] = "0" * 64
            with self.assertRaisesRegex(ReplayConfigurationError, "accelerator identity"):
                CandidateV1HistoricalPaperRuntime(
                    self.config, corrupted, candidate_snapshot=self.snapshot,
                    asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
                    split_contract=split_contract(),
                )


if __name__ == "__main__":
    unittest.main()
