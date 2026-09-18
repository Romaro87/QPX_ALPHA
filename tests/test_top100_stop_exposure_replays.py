from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from qpx_bot.historical_paper_replay import (
    ReplayConfigurationError,
    load_replay_configuration,
)
from qpx_bot.historical_paper_replay_runner import (
    CandidateV1HistoricalPaperRuntime, CompletedBarEvidence,
    _fingerprint,
    _load_strategy_profile,
    _read_runtime_state,
    _write_evidence,
    _write_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import _account_report_fields
from qpx_bot.intraday_six_paper import IntradayBar
from qpx_bot.portfolio import Portfolio, Position


ROOT = Path(__file__).parents[1]
PROFILE = ROOT / "qpx_bot/paper_profiles/top100_aggressive_accelerated_v1.json"
CONFIGS = {
    stop: ROOT / f"qpx_bot/replay_configs/top100_aggressive_stop{stop:02d}_exposure17_v1.json"
    for stop in (5, 7, 9)
}
NY = ZoneInfo("America/New_York")


class Top100StopExposureReplayTests(unittest.TestCase):
    def runtime(self, stop: int) -> CandidateV1HistoricalPaperRuntime:
        config = load_replay_configuration(CONFIGS[stop])
        snapshot = _load_strategy_profile(PROFILE, config)
        return CandidateV1HistoricalPaperRuntime(
            config,
            candidate_snapshot=snapshot,
            asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
        )

    def test_three_effective_strategy_configs_differ_only_by_stop(self) -> None:
        configs = [load_replay_configuration(CONFIGS[stop]) for stop in (5, 7, 9)]
        self.assertEqual(len({item.fingerprint for item in configs}), 3)
        normalized = []
        for config in configs:
            payload = config.as_dict()
            payload["experiment_id"] = "VARIANT"
            payload["experiment_risk"]["initial_stop_fraction"] = "VARIANT"
            normalized.append(payload)
            self.assertEqual(
                config.payload["experiment_risk"][
                    "maximum_provider_asset_exposure_fraction"
                ],
                0.17,
            )
            self.assertIs(
                config.payload["experiment_risk"]["per_position_risk_cap_enabled"],
                False,
            )
        self.assertEqual(normalized[0], normalized[1])
        self.assertEqual(normalized[1], normalized[2])

    def test_percentage_stop_and_provider_asset_exposure_sizing(self) -> None:
        for stop in (5, 7, 9):
            with self.subTest(stop=stop):
                runtime = self.runtime(stop)
                sizing = runtime._experiment_position_size(
                    account_equity=10_000.0,
                    available_cash=10_000.0,
                    entry_price=100.0,
                    atr=4.0,
                    active_risk=0.0,
                )
                self.assertEqual(sizing.shares, 16)
                self.assertEqual(sizing.risk_fraction, 0.0)
                self.assertAlmostEqual(
                    sizing.stop_price,
                    sizing.entry_fill * (1.0 - stop / 100.0),
                )
                self.assertLessEqual(
                    sizing.entry_fill * sizing.shares,
                    10_000.0 * 0.17,
                )

    def test_checkpoint_persists_and_restart_validates_direct_valuation(self) -> None:
        runtime = self.runtime(7)
        runtime.state["last_completed_boundary"] = "2025-01-02T10:00:00-05:00"
        runtime.state["boundaries"] = 1
        runtime._portfolio.cash = 1_000.0
        runtime._portfolio.tax_reserve_cash = 100.0
        position = Position(
            symbol="asset-a", shares=2, entry_date=date(2025, 1, 2),
            entry_price=100.0, entry_atr=4.0, stop_price=93.0,
            target_price=120.0, highest_price=120.0,
            entry_stop_atr_multiple=2.5, entry_target_atr_multiple=5.0,
            entry_trailing_activation_atr=3.0, exit_slippage_rate=0.00075,
            entry_semantic_snapshot={
                "initial_stop_mode": "ENTRY_PRICE_FRACTION",
                "initial_stop_fraction": 0.07,
            },
        )
        runtime._portfolio.positions["asset-a"] = position
        runtime._register_position_for_pyramiding("asset-a", position)
        runtime.state["last_marks"].update({"asset-a": 120.0, "income-id": 50.0})
        runtime.state["income_shares"] = 1.0

        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            _write_runtime_state(run_dir, "run-1", runtime.config, runtime)
            payload = json.loads((run_dir / "checkpoint.json").read_text())
            valuation = payload["account_valuation"]
            self.assertEqual(
                set(valuation),
                {
                    "valuation_boundary", "current_marked_equity",
                    "net_profit_loss", "deployable_cash", "tax_reserve",
                    "swing_market_value", "income_sleeve_market_value",
                },
            )
            self.assertEqual(valuation["current_marked_equity"], 1_390.0)
            self.assertAlmostEqual(valuation["net_profit_loss"], -53.34)
            self.assertEqual(_account_report_fields(valuation)["current_marked_equity"], 1_390.0)

            restored_state = _read_runtime_state(run_dir, runtime.config)
            restored = CandidateV1HistoricalPaperRuntime(
                runtime.config,
                restored_state,
                candidate_snapshot=runtime.candidate._snapshot,
                asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
            )
            self.assertEqual(restored.account_valuation(), valuation)

            payload["account_valuation"]["current_marked_equity"] += 1.0
            payload["account_valuation_fingerprint"] = _fingerprint(
                payload["account_valuation"]
            )
            _write_evidence(run_dir / "checkpoint.json", payload)
            with self.assertRaisesRegex(
                ReplayConfigurationError, "account valuation is invalid"
            ):
                _read_runtime_state(run_dir, runtime.config)

    def test_pyramid_addition_respects_aggregate_provider_asset_exposure(self) -> None:
        runtime = self.runtime(7)
        runtime._portfolio.cash = 5_000.0
        position = Position(
            symbol="asset-a", shares=4, entry_date=date(2025, 1, 2),
            entry_price=100.0, entry_atr=10.0, stop_price=93.0,
            target_price=150.0, highest_price=120.0,
            entry_stop_atr_multiple=2.5, entry_target_atr_multiple=5.0,
            entry_trailing_activation_atr=3.0, exit_slippage_rate=0.00075,
            entry_semantic_snapshot={
                "initial_stop_mode": "ENTRY_PRICE_FRACTION",
                "initial_stop_fraction": 0.07,
            },
        )
        runtime._portfolio.positions["asset-a"] = position
        runtime._register_position_for_pyramiding("asset-a", position)
        runtime.state["last_marks"]["asset-a"] = 120.0
        runtime.state["last_atr"]["asset-a"] = 10.0
        equity_before = runtime._current_equity()
        start = datetime(2025, 1, 3, 9, 30, tzinfo=NY)
        evidence = CompletedBarEvidence(
            "AAA", "asset-a",
            IntradayBar(start, 121.0, 123.0, 120.0, 122.0, 100_000),
            start + timedelta(minutes=15), None,
        )
        runtime._apply_pyramids_open(start, {"asset-a": evidence})
        decision = runtime.state["accelerators"]["pyramiding"]["decisions"][-1]
        self.assertGreater(decision["accepted_shares"], 0)
        self.assertLessEqual(
            position.shares * decision["execution_price"],
            equity_before * 0.17 + 1e-9,
        )

    def test_percentage_entry_risk_survives_split_and_drives_result_r(self) -> None:
        runtime = self.runtime(7)
        config = runtime.candidate._snapshot.bot_config
        portfolio = Portfolio(1_000.0, preserve_identity=True)
        position = Position(
            symbol="asset-a", shares=2, entry_date=date(2025, 1, 2),
            entry_price=100.0, entry_atr=1.0, stop_price=93.0,
            target_price=120.0, highest_price=100.0,
            entry_stop_atr_multiple=2.5, entry_target_atr_multiple=5.0,
            entry_trailing_activation_atr=3.0, exit_slippage_rate=0.0,
            entry_semantic_snapshot={
                "initial_stop_mode": "ENTRY_PRICE_FRACTION",
                "initial_stop_fraction": 0.07,
            },
        )
        portfolio.positions["asset-a"] = position
        before_risk = position.initial_risk_per_share(config) * position.shares
        portfolio.apply_split(symbol="asset-a", share_multiplier=0.5)
        after = portfolio.positions["asset-a"]
        self.assertEqual(
            after.initial_risk_per_share(config) * after.shares,
            before_risk,
        )
        trade = portfolio.close_position(
            symbol="asset-a", exit_price=214.0, exit_date=date(2025, 1, 3),
            reason="TEST", config=config,
        )
        self.assertAlmostEqual(trade.result_r, trade.pnl / before_risk)


if __name__ == "__main__":
    unittest.main()
