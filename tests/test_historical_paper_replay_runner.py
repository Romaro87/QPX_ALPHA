from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
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
    _load_strategy_profile,
    _read_runtime_state,
    _write_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import _inputs
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators
from qpx_bot.candidate_v1_config import load_candidate_v1_config
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
            provider_asset_id="XLE",
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

    def _asset_boundary(self, start: datetime, assets: list[tuple[str, str, float]]) -> CompletedBoundary:
        template = self._boundary(start).bars[0]
        bars = []
        for asset_id, label, ratio in assets:
            inputs = CandidateV1CausalInputs(**{
                **asdict(template.candidate_inputs),
                "current_volume": 100_000 * ratio,
                "baseline_volume": 100_000.0,
            })
            bar = IntradayBar(start=start, open=100.0, high=102.0, low=99.0, close=101.0, volume=int(100_000 * ratio))
            bars.append(CompletedBarEvidence(label, asset_id, bar, start + timedelta(minutes=15), inputs))
        return CompletedBoundary(start.isoformat(), start + timedelta(minutes=15), tuple(bars), 20.0)

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

    def test_volume_confirmation_profile_is_bound_to_selection_and_restart(self):
        config = load_replay_configuration(
            Path(__file__).parents[1]
            / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_primary_v1.json"
        )
        snapshot = load_candidate_v1_config(
            Path(__file__).parents[1]
            / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json"
        )
        runtime = CandidateV1HistoricalPaperRuntime(config, candidate_snapshot=snapshot)
        first = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        runtime.process_boundary(self._boundary(first), {})
        decisions = runtime.state["capacity_decisions"]
        self.assertEqual(decisions[0]["policy"], "volume_confirmation")
        self.assertEqual(decisions[0]["configuration_fingerprint"], "b9a5008ec61f919a4c9da9c4d8afe8fe20c36c1e10fca8690c880ade23b6e89b")
        restored = CandidateV1HistoricalPaperRuntime(
            config, json.loads(json.dumps(runtime.snapshot())), candidate_snapshot=snapshot,
        )
        self.assertEqual(restored.snapshot(), runtime.snapshot())

    def test_profile_rejects_mismatched_experiment_account(self):
        config = load_replay_configuration(
            Path(__file__).parents[1]
            / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_primary_v1.json"
        )
        payload = config.as_dict()
        payload["starting_account"]["starting_cash"] = 1300.0
        from qpx_bot.historical_paper_replay import replay_configuration_from_mapping
        changed = replay_configuration_from_mapping(payload)
        profile = Path(__file__).parents[1] / "qpx_bot/paper_profiles/volume_confirmation_25_v1.json"
        with self.assertRaisesRegex(Exception, "starting account"):
            _load_strategy_profile(profile, changed)

    def test_duplicate_symbol_assets_are_isolated_and_selected_by_asset_id(self):
        config = load_replay_configuration(Path(__file__).parents[1] / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_primary_v1.json")
        snapshot = load_candidate_v1_config(Path(__file__).parents[1] / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json")
        assets = [("asset-a", "DUP", 1.20), ("asset-b", "DUP", 1.19)] + [(f"asset-{n}", f"S{n}", 1.18 - n / 100) for n in range(2, 7)]
        mapping = {asset_id: label for asset_id, label, _ in assets} | {"income-id": "QDTE"}
        runtime = CandidateV1HistoricalPaperRuntime(config, candidate_snapshot=snapshot, asset_symbols=mapping)
        runtime.process_boundary(self._asset_boundary(datetime(2025, 1, 2, 9, 30, tzinfo=self.ny), assets), {})
        decision = runtime.state["capacity_decisions"][0]
        self.assertIn("asset-a", decision["qualifying_asset_ids"])
        self.assertIn("asset-b", decision["qualifying_asset_ids"])
        self.assertEqual(len(decision["selected_asset_ids"]), 6)
        self.assertIn("asset-a", runtime.state["pending"])
        self.assertIn("asset-b", runtime.state["pending"])
        self.assertNotIn("DUP", runtime.state["pending"])

        runtime.process_boundary(
            self._asset_boundary(datetime(2025, 1, 2, 9, 45, tzinfo=self.ny), assets), {}
        )
        self.assertNotIn("DUP", runtime._portfolio.positions)
        self.assertTrue(set(runtime._portfolio.positions).issubset({item[0] for item in assets}))
        for asset_id, position in runtime._portfolio.positions.items():
            self.assertEqual(position.symbol, asset_id)
        self.assertTrue(runtime.state["outcome_reconciliation"]["reconciled"])

    def test_restart_rejects_changed_asset_label_binding(self):
        mapping = {"XLE": "XLE", "income-id": "QDTE"}
        runtime = CandidateV1HistoricalPaperRuntime(self.config, asset_symbols=mapping)
        restored = json.loads(json.dumps(runtime.snapshot()))
        CandidateV1HistoricalPaperRuntime(self.config, restored, asset_symbols=mapping)
        with self.assertRaisesRegex(Exception, "provider-asset identity"):
            CandidateV1HistoricalPaperRuntime(self.config, restored, asset_symbols={"XLE": "OTHER", "income-id": "QDTE"})

    def test_checksummed_restart_preserves_asset_identity(self):
        mapping = {"XLE": "XLE", "income-id": "QDTE"}
        runtime = CandidateV1HistoricalPaperRuntime(self.config, asset_symbols=mapping)
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            _write_runtime_state(run_dir, "run-id", self.config, runtime)
            self.assertTrue((run_dir / "checkpoint.json.sha256").is_file())
            state = _read_runtime_state(run_dir, self.config)
            restored = CandidateV1HistoricalPaperRuntime(self.config, state, asset_symbols=mapping)
            self.assertEqual(restored.snapshot(), runtime.snapshot())

    def test_v3_volume_baseline_excludes_signal_bar(self):
        snapshot = load_candidate_v1_config(
            Path(__file__).parents[1] / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json"
        )
        first = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        bars = [
            IntradayBar(first + timedelta(minutes=15 * index), 100, 102, 99, 101, 100_000)
            for index in range(230)
        ]
        bars[-1] = IntradayBar(bars[-1].start, 100, 102, 99, 101, 9_000_000)
        values = _inputs(bars, snapshot.bot_config)
        candles = [Candle(b.start.date(), b.open, b.high, b.low, b.close, b.volume) for b in bars]
        indicators = calculate_indicators(candles, snapshot.bot_config)
        self.assertIsNotNone(values[-1])
        self.assertEqual(values[-1].baseline_volume, indicators.average_volume[-2])
        self.assertNotEqual(values[-1].baseline_volume, indicators.average_volume[-1])

    def test_dividend_entitlement_precedes_later_cash_release_and_survives_restart(self):
        runtime = CandidateV1HistoricalPaperRuntime(self.config)
        runtime.state["income_shares"] = 10.0

        def income_boundary(day: int) -> CompletedBoundary:
            start = datetime(2025, 1, day, 9, 30, tzinfo=self.ny)
            bar = IntradayBar(start, 20.0, 20.0, 20.0, 20.0, 1000)
            return CompletedBoundary(start.isoformat(), start + timedelta(minutes=15), (
                CompletedBarEvidence("QDTE", "QDTE", bar, start + timedelta(minutes=15), None),
            ), 20.0)

        event = {
            "provider_event_id": "div-1", "ex_or_effective_date": "2025-01-06",
            "record_date": "2025-01-06", "payable_date": "2025-01-10",
            "process_date": "2025-01-13", "rate": 0.25,
        }
        before = runtime._portfolio.cash
        runtime.process_boundary(income_boundary(6), {date(2025, 1, 6): [event]})
        self.assertEqual(runtime._portfolio.cash, before)
        self.assertEqual(runtime.state["dividend_entitlements"]["div-1"]["entitled_shares"], 10.0)
        restored = CandidateV1HistoricalPaperRuntime(
            self.config, json.loads(json.dumps(runtime.snapshot()))
        )
        restored.state["income_shares"] = 1.0
        restored.process_boundary(income_boundary(13), {})
        self.assertAlmostEqual(restored.state["income_dividends"], 2.5)
        restored.process_boundary(income_boundary(14), {})
        self.assertAlmostEqual(restored.state["income_dividends"], 2.5)

    def test_exact_sizing_rejection_reason_reconciles_after_restart(self):
        config_path = Path(__file__).parents[1] / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_primary_v1.json"
        config = load_replay_configuration(config_path)
        snapshot = load_candidate_v1_config(
            Path(__file__).parents[1] / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json"
        )
        runtime = CandidateV1HistoricalPaperRuntime(
            config, candidate_snapshot=snapshot, asset_symbols={"asset-a": "AAA", "income-id": "QDTE"}
        )
        runtime._portfolio.cash = 0.0
        start = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        runtime.process_boundary(self._asset_boundary(start, [("asset-a", "AAA", 1.2)]), {})
        runtime.process_boundary(self._asset_boundary(start + timedelta(minutes=15), [("asset-a", "AAA", 1.2)]), {})
        reconciliation = runtime.state["outcome_reconciliation"]
        self.assertEqual(reconciliation["selected"], 2)
        self.assertEqual(reconciliation["rejected"], 1)
        self.assertEqual(reconciliation["pending"], 1)
        self.assertEqual(sum(reconciliation["sizing_rejection_reasons"].values()), 1)
        restored = CandidateV1HistoricalPaperRuntime(
            config, json.loads(json.dumps(runtime.snapshot())),
            candidate_snapshot=snapshot, asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
        )
        self.assertEqual(restored.state["outcome_reconciliation"], reconciliation)

    def test_exact_asset_position_receives_later_mark_and_exit(self):
        config = load_replay_configuration(
            Path(__file__).parents[1] / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_primary_v1.json"
        )
        snapshot = load_candidate_v1_config(
            Path(__file__).parents[1] / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json"
        )
        mapping = {"provider:CaseSensitive": "DUP", "income-id": "QDTE"}
        runtime = CandidateV1HistoricalPaperRuntime(
            config, candidate_snapshot=snapshot, asset_symbols=mapping
        )
        start = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny)
        runtime.process_boundary(
            self._asset_boundary(start, [("provider:CaseSensitive", "DUP", 1.2)]), {}
        )
        runtime.process_boundary(
            self._asset_boundary(start + timedelta(minutes=15), [("provider:CaseSensitive", "DUP", 1.2)]), {}
        )
        self.assertIn("provider:CaseSensitive", runtime._portfolio.positions)
        self.assertNotIn("PROVIDER:CASESENSITIVE", runtime._portfolio.positions)
        template = self._asset_boundary(
            start + timedelta(minutes=30), [("provider:CaseSensitive", "DUP", 1.2)]
        ).bars[0]
        stop_bar = IntradayBar(template.bar.start, 80.0, 80.0, 80.0, 80.0, template.bar.volume)
        runtime.process_boundary(CompletedBoundary(
            "stop", stop_bar.start + timedelta(minutes=15),
            (CompletedBarEvidence("DUP", "provider:CaseSensitive", stop_bar,
                                  stop_bar.start + timedelta(minutes=15), template.candidate_inputs),),
            20.0,
        ), {})
        self.assertNotIn("provider:CaseSensitive", runtime._portfolio.positions)
        self.assertEqual(runtime._portfolio.closed_trades[-1].symbol, "provider:CaseSensitive")
        self.assertEqual(runtime.state["last_marks"]["provider:CaseSensitive"], 80.0)


if __name__ == "__main__":
    unittest.main()
