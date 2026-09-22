from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from qpx_bot.v3_replay_queue import (
    DEFAULT_CONFIGURATION,
    QueueStateStore,
    ReplayQueueError,
    gamemode_active,
    load_queue_configuration,
    replay_command,
    run_queue,
    validate_cgroup_budget,
)


class FakeProcess:
    next_pid = 90000

    def __init__(self, return_code: int = 0) -> None:
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.return_code = return_code
        self.poll_count = 0

    def poll(self):
        self.poll_count += 1
        return None if self.poll_count == 1 else self.return_code

    def wait(self, timeout=None):
        return self.return_code


class V3ReplayQueueTests(unittest.TestCase):
    def test_governed_queue_has_seven_distinct_interval_32_jobs(self) -> None:
        configuration = load_queue_configuration(DEFAULT_CONFIGURATION)
        self.assertEqual(configuration.checkpoint_interval_boundaries, 32)
        self.assertEqual(len(configuration.jobs), 7)
        self.assertEqual(len({item.job_id for item in configuration.jobs}), 7)
        self.assertEqual(len({item.configuration_path for item in configuration.jobs}), 7)
        for job in configuration.jobs:
            command = replay_command(job, configuration)
            self.assertEqual(command[-2:], ("--checkpoint-interval-boundaries", "32"))

    def test_gamemode_and_manual_inhibit_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            inhibit = Path(folder) / "GAMING"
            inactive = Mock(return_value=Mock(returncode=0, stdout="gamemode is inactive\n", stderr=""))
            self.assertEqual(gamemode_active(inhibit, runner=inactive), (False, "GAMEMODE_INACTIVE"))
            active = Mock(return_value=Mock(returncode=0, stdout="gamemode is active\n", stderr=""))
            self.assertEqual(gamemode_active(inhibit, runner=active), (True, "GAMEMODE_ACTIVE"))
            inhibit.touch()
            self.assertEqual(gamemode_active(inhibit, runner=inactive), (True, "MANUAL_GAMING_INHIBIT"))

    def test_queue_runs_exactly_one_job_at_a_time_and_persists_order(self) -> None:
        configuration = load_queue_configuration(DEFAULT_CONFIGURATION)
        with tempfile.TemporaryDirectory() as folder:
            store = QueueStateStore(Path(folder), configuration)
            launched = []

            def launch(command, **kwargs):
                launched.append(command)
                return FakeProcess()

            self.assertEqual(
                run_queue(
                    configuration,
                    store,
                    gaming_probe=lambda _path: (False, "GAMEMODE_INACTIVE"),
                    popen_factory=launch,
                    sleeper=lambda _seconds: None,
                ),
                0,
            )
            self.assertEqual(len(launched), 7)
            state = store.load()
            self.assertEqual(state["status"], "COMPLETE")
            self.assertEqual(
                state["completed_job_ids"],
                [item.job_id for item in configuration.jobs],
            )

    def test_game_transition_stops_worker_without_advancing_queue(self) -> None:
        configuration = load_queue_configuration(DEFAULT_CONFIGURATION)
        with tempfile.TemporaryDirectory() as folder:
            store = QueueStateStore(Path(folder), configuration)
            process = FakeProcess()
            probes = iter(((False, "GAMEMODE_INACTIVE"), (True, "GAMEMODE_ACTIVE")))
            stopped = threading.Event()

            def probe(_path):
                try:
                    return next(probes)
                except StopIteration:
                    stopped.set()
                    return True, "GAMEMODE_ACTIVE"

            with patch("qpx_bot.v3_replay_queue._stop_child") as stop_child:
                self.assertEqual(
                    run_queue(
                        configuration,
                        store,
                        stop_requested=stopped,
                        gaming_probe=probe,
                        popen_factory=lambda *args, **kwargs: process,
                        sleeper=lambda _seconds: None,
                    ),
                    0,
                )
            stop_child.assert_called()
            state = store.load()
            self.assertEqual(state["completed_job_ids"], [])
            self.assertNotEqual(state["status"], "COMPLETE")

    def test_queue_state_rejects_configuration_identity_change(self) -> None:
        configuration = load_queue_configuration(DEFAULT_CONFIGURATION)
        with tempfile.TemporaryDirectory() as folder:
            store = QueueStateStore(Path(folder), configuration)
            state = store.initial()
            store.write({**state, "queue_configuration_fingerprint": "0" * 64})
            with self.assertRaisesRegex(ReplayQueueError, "different queue configuration"):
                store.load()

    def test_cgroup_contract_requires_qpx_slice_two_gib_and_zero_swap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "cgroup"
            service = root / "user.slice/user-1000.slice/qpx.slice/queue.service"
            service.mkdir(parents=True)
            qpx_slice = service.parent
            (qpx_slice / "memory.max").write_text(str(2 * 1024**3))
            (qpx_slice / "memory.swap.max").write_text("0")
            membership = Path(folder) / "membership"
            membership.write_text("0::/user.slice/user-1000.slice/qpx.slice/queue.service\n")
            validate_cgroup_budget(root, membership)
            (qpx_slice / "memory.swap.max").write_text("1")
            with self.assertRaisesRegex(ReplayQueueError, "disable swap"):
                validate_cgroup_budget(root, membership)


if __name__ == "__main__":
    unittest.main()
