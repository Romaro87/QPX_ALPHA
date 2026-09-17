from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.historical_paper_replay import ReplayConfigurationError, load_replay_configuration
from qpx_bot.historical_paper_replay_runner import (
    CandidateV1HistoricalPaperRuntime,
    CompletedBarEvidence,
    CompletedBoundary,
    PendingEntry,
    _load_strategy_profile,
    _read_runtime_state,
    _write_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import _inputs, load_bound_universe
from qpx_bot.intraday_six_paper import IntradayBar
from qpx_bot.portfolio import Portfolio, Position
from qpx_bot.top100_split_evidence import _split_records


ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_top100_causal_split_v1.json"
PROFILE = ROOT / "qpx_bot/paper_profiles/volume_confirmation_25_v1.json"
MANIFEST = ROOT / "qpx_bot/research_universes/alpaca_top100_asset_id_split_v1.json"
SELECTION = ROOT / "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json"
DATASET = ROOT / "research_data/qpx_ml_historical_v1"
NY = ZoneInfo("America/New_York")
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64
HEX_D = "d" * 64
HEX_E = "e" * 64
HEX_F = "f" * 64


def contract(*events: dict) -> dict:
    return {
        "manifest_fingerprint": HEX_A,
        "corporate_action_ratio_artifact_fingerprint": HEX_B,
        "derived_identity_resolution_fingerprint": HEX_C,
        "derived_asset_id_universe_fingerprint": HEX_D,
        "source_corporate_action_artifact_fingerprint": HEX_E,
        "source_identity_resolution_fingerprint": HEX_F,
        "split_accounting_semantic_version": "QPX_CAUSAL_SPLIT_ACCOUNTING_V1",
        "split_event_count": len(events),
        "split_events": list(events),
    }


def split_event(
    *, event_id: str = "split-1", asset_id: str = "asset-a",
    effective: str = "2025-01-03", old_rate: float = 10.0,
    new_rate: float = 1.0,
) -> dict:
    share = new_rate / old_rate
    return {
        "provider_event_id": event_id,
        "action_type": "forward_split" if share > 1 else "reverse_split",
        "affected_provider_asset_id": asset_id,
        "effective_date": effective,
        "old_rate": old_rate,
        "new_rate": new_rate,
        "share_multiplier": share,
        "price_multiplier": 1.0 / share,
        "ratio_convention": "NEW_SHARES_PER_OLD_SHARES_EQUALS_NEW_RATE_DIVIDED_BY_OLD_RATE",
        "split_record_fingerprint": hashlib.sha256(event_id.encode()).hexdigest(),
    }


def boundary(start: datetime, evidence: tuple[CompletedBarEvidence, ...] = ()) -> CompletedBoundary:
    return CompletedBoundary(
        boundary_id=hashlib.sha256(start.isoformat().encode()).hexdigest(),
        completed_at=start + timedelta(minutes=15), bars=evidence,
        previous_session_vix=20.0,
    )


class Top100UniverseEvidenceTests(unittest.TestCase):
    def test_targeted_ratio_acquisition_uses_provider_old_and_new_rate(self) -> None:
        event_id = "event-1"

        class Client:
            def request(self, _url, _params):
                return {
                    "corporate_actions": {"reverse_splits": [{
                        "id": event_id, "symbol": "AAA", "ex_date": "2025-01-03",
                        "old_rate": 7, "new_rate": 2,
                    }]},
                    "next_page_token": None,
                }

        records, request = _split_records(
            client=Client(), event_ids=[event_id],
            source_by_id={event_id: {
                "provider_event_id": event_id, "action_type": "reverse_split",
                "symbol": "AAA", "new_symbol": None, "old_symbol": None,
                "ex_or_effective_date": "2025-01-03",
                "provenance_fingerprint": HEX_A,
            }},
            asset_by_event={event_id: "asset-a"},
        )
        self.assertEqual(records[0]["share_multiplier"], 2 / 7)
        self.assertEqual(records[0]["price_multiplier"], 7 / 2)
        self.assertEqual(request["params"]["ids"], event_id)

    def test_targeted_ratio_acquisition_fails_closed_without_rates(self) -> None:
        event_id = "event-1"

        class Client:
            def request(self, _url, _params):
                return {
                    "corporate_actions": {"reverse_splits": [{
                        "id": event_id, "symbol": "AAA", "ex_date": "2025-01-03",
                        "old_rate": None, "new_rate": None,
                    }]},
                    "next_page_token": None,
                }

        with self.assertRaisesRegex(RuntimeError, "ratio is unusable"):
            _split_records(
                client=Client(), event_ids=[event_id],
                source_by_id={event_id: {
                    "provider_event_id": event_id, "action_type": "reverse_split",
                    "symbol": "AAA", "new_symbol": None, "old_symbol": None,
                    "ex_or_effective_date": "2025-01-03",
                    "provenance_fingerprint": HEX_A,
                }},
                asset_by_event={event_id: "asset-a"},
            )

    def test_exact_frozen_100_asset_binding_and_checksums(self) -> None:
        selection = json.loads(SELECTION.read_text())
        manifest = json.loads(MANIFEST.read_text())
        core = {key: value for key, value in manifest.items() if key != "manifest_fingerprint"}
        encoded = MANIFEST.read_bytes()
        self.assertEqual(manifest["manifest_fingerprint"], hashlib.sha256(
            json.dumps(core, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest())
        self.assertEqual(
            MANIFEST.with_suffix(MANIFEST.suffix + ".sha256").read_text().strip(),
            hashlib.sha256(encoded).hexdigest(),
        )
        self.assertEqual(manifest["frozen_selection_fingerprint"], selection["manifest_fingerprint"])
        self.assertEqual([item["symbol_label"] for item in manifest["members"]], selection["top100"])
        self.assertEqual(manifest["selected_count"], 100)
        self.assertEqual(len({item["provider_asset_id"] for item in manifest["members"]}), 100)
        self.assertNotIn("QDTE", {item["symbol_label"] for item in manifest["members"]})
        self.assertEqual(manifest["income_asset"]["symbol_label"], "QDTE")
        self.assertEqual(manifest["selection_bias_label"], "RETROSPECTIVELY_SELECTED_SELECTION_BIASED_IN_SAMPLE")
        self.assertEqual(manifest["price_bar_requests"], 0)

    def test_targeted_identity_evidence_resolves_ambiguous_labels_and_bbby(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        members = {item["symbol_label"]: item for item in manifest["members"]}
        expected = {
            "ECHO": "644a3939-7c9d-495e-8fcd-2399ca5f1507",
            "EVLV": "1b7fd307-e704-4f3d-b1ba-c5bcd883d04d",
            "HIVE": "7c02602a-afe0-4a02-81c4-f39ab5e15cfe",
            "PRME": "badc472d-332e-4300-8639-e50641afe2fe",
            "VISN": "b4344ff5-3ab3-4c75-b7a0-be67746efc97",
            "BBBY": "96a49f53-6ed9-4900-b92a-44814b21cf92",
        }
        self.assertEqual({key: members[key]["provider_asset_id"] for key in expected}, expected)
        self.assertEqual(members["BBBY"]["historical_overlap"]["common_bar_count"], 6112)
        self.assertEqual(members["BBBY"]["historical_overlap"]["mismatch_count"], 0)
        self.assertEqual(members["PRME"]["historical_overlap"]["mismatch_count"], 0)
        self.assertEqual(members["VISN"]["historical_overlap"]["mismatch_count"], 0)

    def test_all_governed_split_ratios_are_explicit_and_directional(self) -> None:
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["split_event_count"], 36)
        self.assertEqual(Counter(item["action_type"] for item in manifest["split_events"]), {
            "reverse_split": 31, "forward_split": 5,
        })
        for event in manifest["split_events"]:
            self.assertGreater(event["old_rate"], 0)
            self.assertGreater(event["new_rate"], 0)
            self.assertAlmostEqual(
                event["share_multiplier"], event["new_rate"] / event["old_rate"],
            )
            self.assertAlmostEqual(
                event["share_multiplier"] * event["price_multiplier"], 1.0,
            )
        symbols = {event["symbol_label"] for event in manifest["split_events"]}
        self.assertIn("HIVE", symbols)
        self.assertIn("WBX", symbols)  # MVST lineage before its name change.

    def test_configuration_loads_exact_100_swing_assets_plus_income(self) -> None:
        config = load_replay_configuration(CONFIG)
        assets, manifest = load_bound_universe(config, DATASET)
        self.assertEqual(manifest["selected_count"], 100)
        self.assertEqual(len(assets), 101)
        self.assertEqual(sum(label == "QDTE" for label in assets.values()), 1)
        self.assertTrue(config.payload["universe"]["retrospective_selection"])
        self.assertEqual(config.payload["starting_account"]["starting_cash"], 1443.34)
        self.assertEqual(config.payload["capacity_arbitration"]["policy"], "volume_confirmation")


class CausalSplitAccountingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_replay_configuration(CONFIG)
        cls.snapshot = _load_strategy_profile(PROFILE, cls.config)

    def runtime(self, *events: dict, assets: dict[str, str] | None = None) -> CandidateV1HistoricalPaperRuntime:
        return CandidateV1HistoricalPaperRuntime(
            self.config, candidate_snapshot=self.snapshot,
            asset_symbols=assets or {"asset-a": "AAA", "income-id": "QDTE"},
            split_contract=contract(*events),
        )

    @staticmethod
    def install_position(runtime: CandidateV1HistoricalPaperRuntime, *, shares: float = 10.0) -> None:
        runtime._portfolio.cash = 100.0
        runtime._portfolio.positions["asset-a"] = Position(
            symbol="asset-a", shares=shares, entry_date=date(2025, 1, 2),
            entry_price=10.0, entry_atr=1.0, stop_price=8.0,
            target_price=15.0, highest_price=12.0,
            entry_stop_atr_multiple=2.0, entry_target_atr_multiple=5.0,
            entry_trailing_activation_atr=3.0, exit_slippage_rate=0.0,
        )
        runtime.state["last_marks"]["asset-a"] = 11.0

    def test_reverse_split_preserves_value_cost_basis_and_dollar_risk(self) -> None:
        runtime = self.runtime(split_event())
        self.install_position(runtime)
        before_total = runtime._portfolio.cash + 11.0 * 10.0
        before_realized = runtime._portfolio.realized_pnl
        runtime.process_boundary(boundary(datetime(2025, 1, 3, 9, 30, tzinfo=NY)), {})
        position = runtime._portfolio.positions["asset-a"]
        self.assertEqual(position.shares, 1.0)
        self.assertEqual(position.entry_price, 100.0)
        self.assertEqual(position.entry_atr, 10.0)
        self.assertEqual(position.stop_price, 80.0)
        self.assertEqual(position.target_price, 150.0)
        self.assertEqual(position.highest_price, 120.0)
        self.assertEqual(
            position.entry_price
            + position.entry_atr * position.entry_trailing_activation_atr,
            130.0,
        )
        self.assertEqual(runtime.state["last_marks"]["asset-a"], 110.0)
        self.assertAlmostEqual(runtime._portfolio.cash + 110.0 * 1.0, before_total)
        self.assertEqual(runtime._portfolio.realized_pnl, before_realized)
        reconciliation = runtime.state["applied_splits"][0]["position_reconciliation"]
        self.assertEqual(reconciliation["pre_cost_basis"], reconciliation["post_cost_basis"])
        self.assertEqual(reconciliation["pre_dollar_risk"], reconciliation["post_dollar_risk"])

    def test_forward_split_creates_corporate_action_fraction_only(self) -> None:
        portfolio = Portfolio(100.0, preserve_identity=True)
        portfolio.positions["asset-a"] = Position(
            symbol="asset-a", shares=3.0, entry_date=date(2025, 1, 2),
            entry_price=12.0, entry_atr=2.0, stop_price=10.0,
            target_price=18.0, highest_price=15.0,
        )
        reconciliation = portfolio.apply_split(symbol="asset-a", share_multiplier=1.5)
        self.assertEqual(portfolio.positions["asset-a"].shares, 4.5)
        self.assertAlmostEqual(portfolio.positions["asset-a"].entry_price, 8.0)
        self.assertEqual(reconciliation["pre_cost_basis"], reconciliation["post_cost_basis"])
        self.assertAlmostEqual(
            reconciliation["pre_dollar_risk"], reconciliation["post_dollar_risk"],
        )

    def test_pending_entry_and_gap_inputs_transform_before_admission(self) -> None:
        runtime = self.runtime(split_event())
        signal = PendingEntry(
            signal_id="signal-1", provider_asset_id="asset-a", symbol_label="AAA",
            signal_completed_at="2025-01-02T16:00:00-05:00", signal_atr=2.0,
            prior_close=10.0, tie_key="tie",
        )
        runtime.state["pending"]["asset-a"] = asdict(signal)
        runtime.state["entry_outcomes"]["signal-1"] = {
            "provider_asset_id": "asset-a", "symbol_label": "AAA",
            "decision_completed_at": signal.signal_completed_at,
            "status": "PENDING", "reason": None,
        }
        runtime.state["capacity_decisions"].append({
            "qualifying_asset_ids": ["asset-a"],
            "selected_asset_ids": ["asset-a"],
            "deferred_asset_ids": [],
        })
        runtime.process_boundary(boundary(datetime(2025, 1, 3, 9, 30, tzinfo=NY)), {})
        pending = runtime.state["pending"]["asset-a"]
        self.assertEqual(pending["signal_atr"], 20.0)
        self.assertEqual(pending["prior_close"], 100.0)
        evidence = runtime.state["applied_splits"][0]["pending_reconciliation"]
        self.assertIsNone(evidence["expected_entry_price"])
        self.assertIsNone(evidence["precomputed_share_count"])
        self.assertTrue(runtime.state["outcome_reconciliation"]["reconciled"])

    def test_split_precedes_open_exit_and_fractional_close(self) -> None:
        runtime = self.runtime(split_event())
        self.install_position(runtime)
        inputs = CandidateV1CausalInputs(
            index=250, current_close=79.0, current_volume=1000,
            current_fast=90.0, previous_fast=90.0, current_slow=89.0,
            previous_slow=89.0, current_rsi=55.0, previous_rsi=54.0,
            current_rmi=55.0, previous_rmi=54.0, current_sma=88.0,
            slope_sma=87.0, baseline_volume=900.0, current_atr=10.0,
            prior_high=100.0, vix=20.0,
        )
        start = datetime(2025, 1, 3, 9, 30, tzinfo=NY)
        bar = IntradayBar(start, 79.0, 79.0, 79.0, 79.0, 1000)
        item = CompletedBarEvidence("AAA", "asset-a", bar, start + timedelta(minutes=15), inputs)
        runtime.process_boundary(boundary(start, (item,)), {})
        self.assertNotIn("asset-a", runtime._portfolio.positions)
        self.assertEqual(runtime._portfolio.closed_trades[-1].shares, 1.0)
        self.assertEqual(runtime.state["applied_splits"][0]["effective_boundary"], start.isoformat())

    def test_restart_before_and_after_split_is_idempotent_and_fingerprint_bound(self) -> None:
        event = split_event()
        before = self.runtime(event)
        self.install_position(before)
        before_state = before.snapshot()
        restored_before = CandidateV1HistoricalPaperRuntime(
            self.config, json.loads(json.dumps(before_state)), candidate_snapshot=self.snapshot,
            asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
            split_contract=contract(event),
        )
        split_boundary = boundary(datetime(2025, 1, 3, 9, 30, tzinfo=NY))
        before.process_boundary(split_boundary, {})
        restored_before.process_boundary(split_boundary, {})
        self.assertEqual(restored_before.snapshot(), before.snapshot())

        after_state = before.snapshot()
        restored_after = CandidateV1HistoricalPaperRuntime(
            self.config, json.loads(json.dumps(after_state)), candidate_snapshot=self.snapshot,
            asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
            split_contract=contract(event),
        )
        restored_after.process_boundary(
            boundary(datetime(2025, 1, 3, 9, 45, tzinfo=NY)), {}
        )
        self.assertEqual(restored_after._portfolio.positions["asset-a"].shares, 1.0)
        self.assertEqual(len(restored_after.state["applied_splits"]), 1)

        changed = contract(event)
        changed["corporate_action_ratio_artifact_fingerprint"] = "0" * 64
        with self.assertRaisesRegex(ReplayConfigurationError, "corporate-action evidence"):
            CandidateV1HistoricalPaperRuntime(
                self.config, json.loads(json.dumps(after_state)), candidate_snapshot=self.snapshot,
                asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
                split_contract=changed,
            )

    def test_checksummed_restart_preserves_split_identity_and_state(self) -> None:
        event = split_event()
        runtime = self.runtime(event)
        self.install_position(runtime)
        runtime.process_boundary(boundary(datetime(2025, 1, 3, 9, 30, tzinfo=NY)), {})
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            _write_runtime_state(run_dir, "run-id", self.config, runtime)
            state = _read_runtime_state(run_dir, self.config)
            restored = CandidateV1HistoricalPaperRuntime(
                self.config, state, candidate_snapshot=self.snapshot,
                asset_symbols={"asset-a": "AAA", "income-id": "QDTE"},
                split_contract=contract(event),
            )
            self.assertEqual(restored.snapshot(), runtime.snapshot())

    def test_multiple_splits_are_chronological_and_each_applies_once(self) -> None:
        first = split_event(event_id="split-a", effective="2025-01-03", old_rate=10, new_rate=1)
        second = split_event(event_id="split-b", effective="2025-01-06", old_rate=1, new_rate=4)
        runtime = self.runtime(first, second)
        self.install_position(runtime)
        runtime.process_boundary(boundary(datetime(2025, 1, 3, 9, 30, tzinfo=NY)), {})
        runtime.process_boundary(boundary(datetime(2025, 1, 6, 9, 30, tzinfo=NY)), {})
        self.assertAlmostEqual(runtime._portfolio.positions["asset-a"].shares, 4.0)
        self.assertEqual(runtime.state["applied_split_event_ids"], ["split-a", "split-b"])
        self.assertEqual(
            [item["provider_event_id"] for item in runtime.state["applied_splits"]],
            ["split-a", "split-b"],
        )

    def test_duplicate_provider_event_identity_is_rejected(self) -> None:
        event = split_event()
        with self.assertRaisesRegex(ReplayConfigurationError, "duplicate"):
            self.runtime(event, dict(event))

    def test_causal_indicator_continuity_does_not_change_pre_effective_inputs(self) -> None:
        start = datetime(2024, 1, 2, 9, 30, tzinfo=NY)
        bars = []
        for index in range(260):
            split_side = index >= 230
            price = 100.0 if split_side else 10.0
            volume = 100 if split_side else 1000
            bars.append(IntradayBar(
                start + timedelta(days=index), price, price, price, price, volume,
            ))
        effective = bars[230].start.date().isoformat()
        event = split_event(effective=effective, old_rate=10, new_rate=1)
        causal = _inputs(bars, self.snapshot.bot_config, (event,))
        control = _inputs(bars, self.snapshot.bot_config)
        self.assertEqual(causal[229], control[229])
        self.assertIsNotNone(causal[230])
        self.assertAlmostEqual(causal[230].current_fast, 100.0, places=8)
        self.assertAlmostEqual(causal[230].current_slow, 100.0, places=8)
        self.assertAlmostEqual(causal[230].prior_high, 100.0, places=8)
        self.assertAlmostEqual(causal[230].baseline_volume, 100.0, places=8)
        self.assertGreater(abs(control[230].current_fast - 100.0), 1.0)


if __name__ == "__main__":
    unittest.main()
