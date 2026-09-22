from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from qpx_bot.historical_paper_replay import ReplayConfigurationError
from qpx_bot.historical_paper_replay_v3 import (
    DEFAULT_CHECKPOINT_INTERVAL_BOUNDARIES,
    _checkpoint_final_replay_state,
    _checkpoint_replay_state,
    _pending_boundary_rows,
    _validate_checkpoint_interval_boundaries,
    main,
)


class V3CheckpointIntervalTests(unittest.TestCase):
    def test_default_interval_and_positive_validation(self) -> None:
        self.assertEqual(DEFAULT_CHECKPOINT_INTERVAL_BOUNDARIES, 32)
        self.assertEqual(_validate_checkpoint_interval_boundaries(1), 1)
        self.assertEqual(_validate_checkpoint_interval_boundaries(32), 32)
        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ReplayConfigurationError, "positive integer"):
                    _validate_checkpoint_interval_boundaries(invalid)

    def test_cadence_writes_each_interval_and_always_final(self) -> None:
        writer = Mock(return_value="fingerprint")
        with patch(
            "qpx_bot.historical_paper_replay_v3._write_runtime_state", writer
        ):
            pending = 0
            for _ in range(65):
                pending += 1
                pending = _checkpoint_replay_state(
                    Path("run"), "run-id", object(), object(), pending, 32,
                )
            _checkpoint_final_replay_state(
                Path("run"), "run-id", object(), object(), pending,
            )
        self.assertEqual(writer.call_count, 3)

    def test_final_does_not_duplicate_current_interval_checkpoint(self) -> None:
        writer = Mock(return_value="fingerprint")
        with tempfile.TemporaryDirectory() as folder, patch(
            "qpx_bot.historical_paper_replay_v3._write_runtime_state", writer
        ):
            run_dir = Path(folder)
            pending = _checkpoint_replay_state(
                run_dir, "run-id", object(), object(), 32, 32,
            )
            (run_dir / "checkpoint.json").touch()
            _checkpoint_final_replay_state(
                run_dir, "run-id", object(), object(), pending,
            )
        self.assertEqual(writer.call_count, 1)

    def test_restart_selects_only_suffix_after_last_durable_boundary(self) -> None:
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE boundaries(start TEXT PRIMARY KEY)")
        first = datetime(2025, 1, 2, 9, 30, tzinfo=timezone.utc)
        starts = [(first + timedelta(minutes=15 * index)).isoformat() for index in range(5)]
        db.executemany("INSERT INTO boundaries(start) VALUES(?)", ((item,) for item in starts))
        last_durable_completion = first + timedelta(minutes=45)
        self.assertEqual(
            [item[0] for item in _pending_boundary_rows(db, last_durable_completion.isoformat())],
            starts[3:],
        )

    def test_cli_passes_default_and_override_to_run(self) -> None:
        with patch("qpx_bot.historical_paper_replay_v3.run", return_value=Path("result")) as runner:
            self.assertEqual(main([]), 0)
            self.assertEqual(runner.call_args.args[-1], 32)
        with patch("qpx_bot.historical_paper_replay_v3.run", return_value=Path("result")) as runner:
            self.assertEqual(main(["--checkpoint-interval-boundaries", "7"]), 0)
            self.assertEqual(runner.call_args.args[-1], 7)

    def test_run_manifest_records_checkpoint_interval(self) -> None:
        class ManifestCaptured(Exception):
            pass

        config = Mock()
        config.fingerprint = "config-fingerprint"
        config.payload = {
            "dataset": {"snapshot_fingerprint": "dataset-fingerprint"},
            "accelerators": None,
            "authority": {},
        }
        config.as_dict.return_value = {"configuration": "test"}
        universe = {"manifest_fingerprint": "universe-fingerprint", "selected_count": 1}
        captured = {}

        def capture_manifest(path, payload):
            if path.name == "run_manifest.json":
                captured.update(payload)
                raise ManifestCaptured
            return "fingerprint"

        with tempfile.TemporaryDirectory() as folder, patch.multiple(
            "qpx_bot.historical_paper_replay_v3",
            load_replay_configuration=Mock(return_value=config),
            _load_strategy_profile=Mock(return_value=object()),
            load_bound_universe=Mock(return_value=({"asset-id": "AAA"}, universe)),
            _sha256=Mock(return_value="source-fingerprint"),
            _write_evidence=Mock(side_effect=capture_manifest),
        ), patch(
            "qpx_bot.historical_paper_replay_v3.subprocess.check_output",
            return_value="source-commit\n",
        ):
            from qpx_bot.historical_paper_replay_v3 import run

            with self.assertRaises(ManifestCaptured):
                run(dataset=Path(folder), checkpoint_interval_boundaries=7)
        self.assertEqual(captured["checkpoint_interval_boundaries"], 7)


if __name__ == "__main__":
    unittest.main()
