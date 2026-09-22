from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.historical_paper_replay import ReplayConfigurationError, load_replay_configuration
from qpx_bot.historical_paper_replay_runner import (
    CandidateV1HistoricalPaperRuntime,
    CompletedBarEvidence,
    CompletedBoundary,
    _load_strategy_profile,
    _read_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import ROOT, _write_checkpoint_transaction
from qpx_bot.historical_paper_replay_v3_evidence import (
    V3EvidenceArchive,
    initial_archive_state,
)
from qpx_bot.intraday_six_paper import IntradayBar


CONFIG = ROOT / "qpx_bot/replay_configs/top100_aggressive_stop09_exposure25_v1.json"
PROFILE = ROOT / "qpx_bot/paper_profiles/top100_aggressive_accelerated_v1.json"


class FakeRuntime:
    def __init__(self) -> None:
        self.state = {
            "last_completed_boundary": "2025-01-02T10:00:00-05:00",
            "boundaries": 2,
            "signals": 2,
            "fills": 1,
            "pending": {"asset-b": {}},
            "capacity_decisions": [{
                "decision_id": "capacity-1",
                "qualifying_asset_ids": ["asset-a", "asset-b"],
                "selected_asset_ids": ["asset-a", "asset-b"],
                "deferred_asset_ids": [],
            }],
            "entry_outcomes": {
                "signal-a": {
                    "provider_asset_id": "asset-a", "status": "FILLED", "reason": None,
                },
                "signal-b": {
                    "provider_asset_id": "asset-b", "status": "PENDING", "reason": None,
                },
            },
            "outcome_reconciliation": {
                "qualifying": 2, "selected": 2, "deferred": 0,
                "pending": 1, "filled": 1, "rejected": 0,
                "sizing_rejection_reasons": {}, "reconciled": True,
            },
            "accelerators": {
                "profit_recycling": {"decisions": [{
                    "decision_id": "profit-1", "amount_proposed_for_recycling": 12.5,
                }]},
                "dynamic_sizing": {"decisions": [{
                    "decision_id": "dynamic-1", "sizing_multiplier": 0.85,
                }]},
                "pyramiding": {"decisions": [{
                    "decision_id": "pyramid-1", "accepted_shares": 2,
                    "symbol": "asset-a",
                }]},
                "regime_allocation": {"decisions": [{"decision_id": "regime-1"}]},
            },
            "evidence_archive": initial_archive_state(),
        }

    def persistence_state(self):
        return {**self.state}


class V3BoundedEvidenceTests(unittest.TestCase):
    ny = ZoneInfo("America/New_York")

    def boundary(self, index: int) -> CompletedBoundary:
        start = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny) + timedelta(
            minutes=15 * index
        )
        completed = start + timedelta(minutes=15)
        inputs = CandidateV1CausalInputs(
            index=50 + index,
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
            vix=15.0,
        )
        return CompletedBoundary(
            boundary_id=completed.isoformat(),
            completed_at=completed,
            bars=(CompletedBarEvidence(
                "AAA", "asset-a",
                IntradayBar(start, 100.0, 102.0, 99.0, 101.0, 100_000),
                completed, inputs,
            ),),
            previous_session_vix=15.0,
        )

    def test_checkpoint_orders_verified_batch_before_release(self) -> None:
        runtime = FakeRuntime()
        identity = {"run_id": "run", "implementation_fingerprint": "implementation"}
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            archive = V3EvidenceArchive(run_dir, identity, runtime)

            def checkpoint_writer(*args, **kwargs):
                self.assertTrue(runtime.state["capacity_decisions"])
                batch = run_dir / "evidence_batches/batch-00000001.json"
                self.assertTrue(batch.exists())
                compact = kwargs["paper_state"]
                self.assertEqual(compact["capacity_decisions"], [])
                self.assertEqual(set(compact["entry_outcomes"]), {"signal-b"})
                (run_dir / "checkpoint-written").write_text("durable")

            with patch(
                "qpx_bot.historical_paper_replay_v3._write_runtime_state",
                side_effect=checkpoint_writer,
            ):
                _write_checkpoint_transaction(
                    run_dir, "run", object(), runtime, archive,
                )

            self.assertTrue((run_dir / "checkpoint-written").exists())
            self.assertEqual(runtime.state["capacity_decisions"], [])
            self.assertEqual(set(runtime.state["entry_outcomes"]), {"signal-b"})
            self.assertEqual(
                runtime.state["evidence_archive"]["rolling_totals"]["capacity"],
                {"decision_count": 1, "qualifying": 2, "selected": 2, "deferred": 0},
            )
            progress = json.loads((run_dir / "progress_report.json").read_text())
            self.assertNotIn("capacity_decisions", progress)
            self.assertNotIn("entry_outcomes", progress)

    def test_orphan_batch_is_reused_only_when_replay_is_identical(self) -> None:
        runtime = FakeRuntime()
        identity = {"run_id": "run", "implementation_fingerprint": "implementation"}
        with tempfile.TemporaryDirectory() as folder:
            archive = V3EvidenceArchive(Path(folder), identity, runtime)
            flush = archive.prepare_flush(runtime)
            archive.persist_and_verify_batch(flush)
            archive.persist_and_verify_batch(archive.prepare_flush(runtime))
            runtime.state["capacity_decisions"][0]["decision_id"] = "changed"
            with self.assertRaisesRegex(
                ReplayConfigurationError, "differs from replayed evidence",
            ):
                archive.persist_and_verify_batch(archive.prepare_flush(runtime))

    def test_referenced_batch_checksum_is_validated_on_restart(self) -> None:
        runtime = FakeRuntime()
        identity = {"run_id": "run", "implementation_fingerprint": "implementation"}
        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            archive = V3EvidenceArchive(run_dir, identity, runtime)
            flush = archive.prepare_flush(runtime)
            archive.persist_and_verify_batch(flush)
            archive.commit_flush(runtime, flush)
            V3EvidenceArchive(run_dir, identity, runtime)
            batch = run_dir / "evidence_batches/batch-00000001.json"
            batch.write_bytes(batch.read_bytes() + b" ")
            with self.assertRaisesRegex(ReplayConfigurationError, "checksum mismatch"):
                V3EvidenceArchive(run_dir, identity, runtime)

    def test_restart_replays_suffix_without_strategy_or_evidence_difference(self) -> None:
        config = load_replay_configuration(CONFIG)
        snapshot = _load_strategy_profile(PROFILE, config)
        kwargs = {
            "candidate_snapshot": snapshot,
            "asset_symbols": {"asset-a": "AAA", "income-id": "QDTE"},
        }
        boundaries = [self.boundary(index) for index in range(8)]
        uninterrupted = CandidateV1HistoricalPaperRuntime(config, **kwargs)
        for boundary in boundaries:
            uninterrupted.process_boundary(boundary, {})

        with tempfile.TemporaryDirectory() as folder:
            run_dir = Path(folder)
            bounded = CandidateV1HistoricalPaperRuntime(config, **kwargs)
            bounded.state["evidence_archive"] = initial_archive_state()
            identity = {
                "run_id": "bounded-run",
                "configuration_fingerprint": config.fingerprint,
                "implementation_fingerprint": "bounded-implementation",
            }
            archive = V3EvidenceArchive(run_dir, identity, bounded)
            for boundary in boundaries[:4]:
                bounded.process_boundary(boundary, {})
            _write_checkpoint_transaction(
                run_dir, "bounded-run", config, bounded, archive,
            )
            restored_state = _read_runtime_state(run_dir, config)
            restored = CandidateV1HistoricalPaperRuntime(
                config, restored_state, **kwargs,
            )
            restored_archive = V3EvidenceArchive(run_dir, identity, restored)
            for boundary in boundaries[4:]:
                restored.process_boundary(boundary, {})
            _write_checkpoint_transaction(
                run_dir, "bounded-run", config, restored, restored_archive,
            )
            self.assertEqual(restored.state["capacity_decisions"], [])
            self.assertEqual(
                restored.state["accelerators"]["pyramiding"]["decisions"], [],
            )

            old_state = uninterrupted.persistence_state()
            new_state = restored.persistence_state()
            old_capacity = old_state.pop("capacity_decisions")
            old_outcomes = old_state.pop("entry_outcomes")
            new_state.pop("capacity_decisions")
            new_state.pop("entry_outcomes")
            new_state.pop("evidence_archive")
            expected_accelerator_evidence = {
                key: old_state["accelerators"][key]["decisions"]
                for key in (
                    "profit_recycling", "dynamic_sizing", "pyramiding",
                    "regime_allocation",
                )
            }
            persisted_events = {
                "capacity_decisions": [], "entry_outcomes": [],
                "profit_recycling": [], "dynamic_sizing": [],
                "pyramiding": [], "regime_allocation": [],
            }
            for reference in restored.state["evidence_archive"]["batches"]:
                batch_events = restored_archive._read_reference(reference)["events"]
                for key in persisted_events:
                    persisted_events[key].extend(batch_events[key])
            self.assertEqual(
                persisted_events["capacity_decisions"],
                json.loads(json.dumps(old_capacity)),
            )
            self.assertEqual(
                sorted(
                    persisted_events["entry_outcomes"],
                    key=lambda item: item["signal_id"],
                ),
                sorted(
                    (
                        {"signal_id": signal_id, **outcome}
                        for signal_id, outcome in old_outcomes.items()
                    ),
                    key=lambda item: item["signal_id"],
                ),
            )
            for key in (
                "profit_recycling", "dynamic_sizing", "pyramiding",
                "regime_allocation",
            ):
                old_decisions = old_state["accelerators"][key].pop("decisions")
                new_state["accelerators"][key].pop("decisions")
                self.assertEqual(
                    persisted_events[key], json.loads(json.dumps(old_decisions)),
                )
                projected = restored_archive.report_evidence(
                    restored.persistence_state()
                )
                if key == "profit_recycling":
                    self.assertEqual(
                        projected[key]["decision_ids"],
                        [item["decision_id"] for item in old_decisions],
                    )
                elif key == "dynamic_sizing":
                    self.assertEqual(
                        projected[key]["decision_ids"],
                        [item["decision_id"] for item in old_decisions],
                    )
                elif key == "pyramiding":
                    self.assertEqual(
                        projected[key]["decision_count"], len(old_decisions),
                    )
                else:
                    self.assertEqual(projected[key]["decisions"], old_decisions)
            self.assertEqual(new_state, old_state)
            projected = restored_archive.report_evidence(restored.persistence_state())
            self.assertEqual(
                projected["capacity_decisions"],
                json.loads(json.dumps(old_capacity)),
            )
            self.assertEqual(
                restored.state["outcome_reconciliation"],
                uninterrupted.state["outcome_reconciliation"],
            )
            self.assertEqual(
                len(old_outcomes),
                restored.state["evidence_archive"]["rolling_totals"]
                ["entry_outcomes"]["terminal_count"],
            )
            self.assertEqual(
                {
                    key: len(value)
                    for key, value in expected_accelerator_evidence.items()
                },
                {
                    key: len(persisted_events[key])
                    for key in expected_accelerator_evidence
                },
            )


if __name__ == "__main__":
    unittest.main()
