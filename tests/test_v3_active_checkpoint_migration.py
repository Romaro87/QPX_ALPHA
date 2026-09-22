from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from zoneinfo import ZoneInfo

from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.historical_paper_replay import (
    ReplayConfigurationError,
    load_replay_configuration,
)
from qpx_bot.historical_paper_replay_runner import (
    CandidateV1HistoricalPaperRuntime,
    CompletedBarEvidence,
    CompletedBoundary,
    _fingerprint,
    _load_strategy_profile,
    _read_runtime_state,
    _sha256,
    _write_runtime_state,
)
from qpx_bot.historical_paper_replay_v3 import (
    ROOT,
    _database,
    _pending_boundary_rows,
)
from qpx_bot.intraday_six_paper import IntradayBar


PROFILE = ROOT / "qpx_bot/paper_profiles/top100_aggressive_accelerated_v1.json"
ACTIVE_IMPLEMENTATION_FINGERPRINT = (
    "ac8af84e2b7e9ec9d9e914855ae0dd7cf595480dc9961a440a44dd9ba39da23f"
)
ACTIVE_RUNS = (
    ("top100_aggressive_stop05_exposure17_v1.json", "22f458012777e4dab515886f36d6149e8a89e878576619ae199ffdba729a887b", "f1b31b1f5310db967c2257cae96603cf6a67cd730bd6d72853593d29f7378ea9"),
    ("top100_aggressive_stop07_exposure17_v1.json", "00051ffb03f81b74a210f49c7d7c92b6838fc14e3b18b53756f66275e4e8ccfa", "b7a77f13e09b14903c0f5c0e03768749562dde45bb231005894ef7a3ff6683c4"),
    ("top100_aggressive_stop09_exposure17_v1.json", "17e34fbfbc0e9eabafa2e8891ad98f9bd01d17cd207e1278be3f837ac6df6b31", "780821b03737a7853c072f875e8ef92258923d13913e32713959c44014958d84"),
    ("top100_aggressive_stop09_exposure25_v1.json", "e086c1fd1b2a97326d5bbe8c444e1931cd6893d71194fa88b10b36d3de5d264b", "874d0e7040bd39b5afc23c104eb4278be4aa0f63f565c9ccbe46b1a01c7b8a9b"),
    ("top100_aggressive_stop11_exposure25_v1.json", "110807b41f8c07adb4bf8696ae3a197a0478c76898da0d45c1f4d444fafa46d2", "f996dd17749ab50f688aa7786f7a567a7cb70b5f1f45af547b13729074ef6eec"),
    ("top100_aggressive_stop13_exposure25_v1.json", "c189a4a464f2a02cd364a950aab3afcb76d0abca1953131822965bb2ef1d195d", "dc830b3609558b733646e87e11cdde101164dd9c0d02c989380f5e18a4ea73ea"),
    ("top100_aggressive_stop15_exposure25_v1.json", "d99c615028ec661ea111dafaecbf978d3efd5257c2804e90ec6f48f56ce8370b", "292d70a4cd46bdb7769a7bfe03a0084dcf63d55b0d288260fcdb110f3a2e26d0"),
)


def _worktree_implementation_fingerprint() -> str:
    return _fingerprint({
        "v3_runner": _sha256(ROOT / "qpx_bot/historical_paper_replay_v3.py"),
        "replay_configuration": _sha256(ROOT / "qpx_bot/historical_paper_replay.py"),
        "runtime": _sha256(ROOT / "qpx_bot/historical_paper_replay_runner.py"),
        "portfolio": _sha256(ROOT / "qpx_bot/portfolio.py"),
        "top100_evidence_builder": _sha256(ROOT / "qpx_bot/top100_split_evidence.py"),
        "historical_replay_accelerators": _sha256(ROOT / "qpx_bot/historical_replay_accelerators.py"),
        "dynamic_sizing": _sha256(ROOT / "qpx_bot/accelerators/dynamic_sizing.py"),
        "profit_recycling": _sha256(ROOT / "qpx_bot/accelerators/profit_recycling.py"),
        "pyramiding": _sha256(ROOT / "qpx_bot/accelerators/pyramiding.py"),
        "regime_allocation": _sha256(ROOT / "qpx_bot/accelerators/regime_allocation.py"),
    })


class V3ActiveCheckpointMigrationTests(unittest.TestCase):
    ny = ZoneInfo("America/New_York")

    def boundary(self, index: int) -> CompletedBoundary:
        start = datetime(2025, 1, 2, 9, 30, tzinfo=self.ny) + timedelta(
            minutes=15 * index
        )
        bar = IntradayBar(start, 100.0, 102.0, 99.0, 101.0, 100_000)
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
        completed = start + timedelta(minutes=15)
        return CompletedBoundary(
            boundary_id=completed.isoformat(),
            completed_at=completed,
            bars=(CompletedBarEvidence("AAA", "asset-a", bar, completed, inputs),),
            previous_session_vix=15.0,
        )

    def test_all_seven_configs_resume_exactly_after_durable_boundary(self) -> None:
        boundaries = [self.boundary(index) for index in range(6)]
        for config_name, run_id, expected_config_fingerprint in ACTIVE_RUNS:
            with self.subTest(config=config_name):
                config = load_replay_configuration(
                    ROOT / "qpx_bot/replay_configs" / config_name
                )
                self.assertEqual(config.fingerprint, expected_config_fingerprint)
                snapshot = _load_strategy_profile(PROFILE, config)
                kwargs = {
                    "candidate_snapshot": snapshot,
                    "asset_symbols": {"asset-a": "AAA", "income-id": "QDTE"},
                }
                uninterrupted = CandidateV1HistoricalPaperRuntime(config, **kwargs)
                durable = CandidateV1HistoricalPaperRuntime(config, **kwargs)
                for boundary in boundaries:
                    uninterrupted.process_boundary(boundary, {})
                for boundary in boundaries[:3]:
                    durable.process_boundary(boundary, {})

                with tempfile.TemporaryDirectory() as folder:
                    run_dir = Path(folder)
                    _write_runtime_state(run_dir, run_id, config, durable)
                    payload = json.loads((run_dir / "checkpoint.json").read_text())
                    self.assertEqual(payload["run_id"], run_id)
                    self.assertEqual(
                        payload["configuration_fingerprint"],
                        expected_config_fingerprint,
                    )
                    self.assertEqual(
                        _sha256(run_dir / "checkpoint.json"),
                        (run_dir / "checkpoint.json.sha256").read_text().strip(),
                    )
                    restored_state = _read_runtime_state(run_dir, config)

                restored = CandidateV1HistoricalPaperRuntime(
                    config, restored_state, **kwargs
                )
                db = sqlite3.connect(":memory:")
                db.execute("CREATE TABLE boundaries(start TEXT PRIMARY KEY)")
                db.executemany(
                    "INSERT INTO boundaries(start) VALUES(?)",
                    (
                        (
                            (item.completed_at - timedelta(minutes=15)).isoformat(),
                        )
                        for item in boundaries
                    ),
                )
                by_start = {
                    (item.completed_at - timedelta(minutes=15)).isoformat(): item
                    for item in boundaries
                }
                resumed_starts = [
                    item[0]
                    for item in _pending_boundary_rows(
                        db, restored.state["last_completed_boundary"]
                    )
                ]
                self.assertEqual(resumed_starts, list(by_start)[3:])
                for start in resumed_starts:
                    restored.process_boundary(by_start[start], {})
                self.assertEqual(restored.snapshot(), uninterrupted.snapshot())
                self.assertEqual(
                    _fingerprint(restored.snapshot()),
                    _fingerprint(uninterrupted.snapshot()),
                )
                db.close()

    def test_cache_identity_blocks_cross_implementation_restart(self) -> None:
        current = _worktree_implementation_fingerprint()
        self.assertNotEqual(current, ACTIVE_IMPLEMENTATION_FINGERPRINT)
        with tempfile.TemporaryDirectory() as folder:
            cache = Path(folder) / "cache.sqlite3"
            original = {
                "run_id": ACTIVE_RUNS[0][1],
                "configuration_fingerprint": ACTIVE_RUNS[0][2],
                "implementation_fingerprint": ACTIVE_IMPLEMENTATION_FINGERPRINT,
            }
            _database(cache, original).close()
            with self.assertRaisesRegex(
                ReplayConfigurationError, "implementation_fingerprint"
            ):
                _database(cache, {**original, "implementation_fingerprint": current})
            with self.assertRaisesRegex(ReplayConfigurationError, "run_id"):
                _database(cache, {**original, "run_id": "new-run-id"})


if __name__ == "__main__":
    unittest.main()
