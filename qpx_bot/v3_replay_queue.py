"""Resource-bounded sequential launcher for V3 historical paper replays."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIGURATION = ROOT / "qpx_bot/replay_configs/v3_resource_queue_20260921.json"
SEMANTIC_VERSION = "QPX_V3_REPLAY_RESOURCE_QUEUE_V1"
TOTAL_MEMORY_BUDGET_BYTES = 2 * 1024**3


class ReplayQueueError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReplayJob:
    job_id: str
    configuration_path: Path


@dataclass(frozen=True, slots=True)
class ReplayQueueConfiguration:
    fingerprint: str
    dataset_path: Path
    strategy_profile_path: Path
    checkpoint_interval_boundaries: int
    gaming_inhibit_path: Path
    poll_seconds: float
    stop_timeout_seconds: float
    jobs: tuple[ReplayJob, ...]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _resolve_repo_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ReplayQueueError(f"{label} must be a nonempty repository-relative path.")
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError as exc:
        raise ReplayQueueError(f"{label} must remain inside the QPX repository.") from exc
    return path


def load_queue_configuration(path: Path = DEFAULT_CONFIGURATION) -> ReplayQueueConfiguration:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("semantic_version") != SEMANTIC_VERSION:
        raise ReplayQueueError("Unsupported V3 replay queue configuration identity.")
    interval = payload.get("checkpoint_interval_boundaries")
    if type(interval) is not int or interval < 1:
        raise ReplayQueueError("checkpoint_interval_boundaries must be a positive integer.")
    poll_seconds = payload.get("poll_seconds")
    stop_timeout_seconds = payload.get("stop_timeout_seconds")
    if not isinstance(poll_seconds, (int, float)) or poll_seconds <= 0:
        raise ReplayQueueError("poll_seconds must be positive.")
    if not isinstance(stop_timeout_seconds, (int, float)) or stop_timeout_seconds <= 0:
        raise ReplayQueueError("stop_timeout_seconds must be positive.")
    raw_jobs = payload.get("jobs")
    if not isinstance(raw_jobs, list) or not raw_jobs:
        raise ReplayQueueError("jobs must contain at least one replay configuration.")
    jobs: list[ReplayJob] = []
    for item in raw_jobs:
        if not isinstance(item, Mapping):
            raise ReplayQueueError("Each replay queue job must be an object.")
        job_id = item.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise ReplayQueueError("Each replay queue job requires a nonempty job_id.")
        jobs.append(ReplayJob(job_id, _resolve_repo_path(item.get("configuration"), "job configuration")))
    if len({item.job_id for item in jobs}) != len(jobs):
        raise ReplayQueueError("Replay queue job_id values must be unique.")
    if len({item.configuration_path for item in jobs}) != len(jobs):
        raise ReplayQueueError("Replay queue configuration paths must be unique.")
    required_paths = (
        _resolve_repo_path(payload.get("dataset"), "dataset"),
        _resolve_repo_path(payload.get("strategy_profile"), "strategy_profile"),
        *(item.configuration_path for item in jobs),
    )
    for required in required_paths:
        if not required.exists():
            raise ReplayQueueError(f"Required replay queue path does not exist: {required}")
    return ReplayQueueConfiguration(
        hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
        required_paths[0],
        required_paths[1],
        interval,
        _resolve_repo_path(payload.get("gaming_inhibit_path"), "gaming_inhibit_path"),
        float(poll_seconds),
        float(stop_timeout_seconds),
        tuple(jobs),
    )


def gamemode_active(
    inhibit_path: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[bool, str]:
    if inhibit_path.exists():
        return True, "MANUAL_GAMING_INHIBIT"
    try:
        result = runner(
            ("/usr/bin/gamemoded", "-s"),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return True, f"GAMEMODE_UNAVAILABLE:{type(exc).__name__}"
    response = (result.stdout + result.stderr).strip().lower()
    if result.returncode != 0:
        return True, f"GAMEMODE_UNAVAILABLE:exit={result.returncode}"
    if response == "gamemode is active":
        return True, "GAMEMODE_ACTIVE"
    if response == "gamemode is inactive":
        return False, "GAMEMODE_INACTIVE"
    return True, "GAMEMODE_UNRECOGNIZED"


def validate_cgroup_budget(
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    membership_path: Path = Path("/proc/self/cgroup"),
) -> None:
    relative = Path("/")
    for line in membership_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("0::"):
            relative = Path(line[3:].lstrip("/"))
            break
    current = (cgroup_root / relative).resolve()
    try:
        current.relative_to(cgroup_root.resolve())
    except ValueError as exc:
        raise ReplayQueueError("Cannot resolve the replay queue cgroup safely.") from exc
    qpx_slice = next((item for item in (current, *current.parents) if item.name == "qpx.slice"), None)
    if qpx_slice is None or not qpx_slice.exists():
        raise ReplayQueueError("Replay queue is not inside the aggregate qpx.slice budget.")
    memory_value = (qpx_slice / "memory.max").read_text(encoding="utf-8").strip()
    if memory_value == "max" or int(memory_value) > TOTAL_MEMORY_BUDGET_BYTES:
        raise ReplayQueueError("Aggregate qpx.slice memory.max exceeds 2 GiB.")
    if (qpx_slice / "memory.swap.max").read_text(encoding="utf-8").strip() != "0":
        raise ReplayQueueError("Aggregate qpx.slice must disable swap before work starts.")


class QueueStateStore:
    def __init__(self, directory: Path, configuration: ReplayQueueConfiguration) -> None:
        self.directory = directory
        self.configuration = configuration
        self.state_path = directory / "queue_state.json"
        self.checksum_path = directory / "queue_state.json.sha256"

    def initial(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "semantic_version": SEMANTIC_VERSION,
            "queue_configuration_fingerprint": self.configuration.fingerprint,
            "completed_job_ids": [],
            "current_job_id": None,
            "status": "READY",
            "last_reason": None,
        }

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists() and not self.checksum_path.exists():
            return self.initial()
        encoded = read_checksummed_state(
            self.state_path, self.checksum_path, label="V3 replay queue state",
        )
        state = json.loads(encoded)
        if state.get("queue_configuration_fingerprint") != self.configuration.fingerprint:
            raise ReplayQueueError("Replay queue state belongs to a different queue configuration.")
        completed = state.get("completed_job_ids")
        expected = [item.job_id for item in self.configuration.jobs]
        if not isinstance(completed, list) or completed != expected[:len(completed)]:
            raise ReplayQueueError("Replay queue completion state is not an ordered job prefix.")
        current = state.get("current_job_id")
        expected_current = expected[len(completed)] if len(completed) < len(expected) else None
        if current not in {None, expected_current}:
            raise ReplayQueueError("Replay queue current job does not match the next ordered job.")
        return state

    def write(self, state: Mapping[str, Any]) -> None:
        payload = {
            **state,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_checksummed_state(
            self.state_path,
            self.checksum_path,
            json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n",
        )


def replay_command(job: ReplayJob, configuration: ReplayQueueConfiguration) -> tuple[str, ...]:
    return (
        "/usr/bin/python3", "-u", "-m", "qpx_bot.historical_paper_replay_v3",
        "--config", str(job.configuration_path),
        "--dataset", str(configuration.dataset_path),
        "--strategy-profile", str(configuration.strategy_profile_path),
        "--checkpoint-interval-boundaries", str(configuration.checkpoint_interval_boundaries),
    )


def _stop_child(child: subprocess.Popen[Any], timeout: float) -> None:
    if child.poll() is not None:
        return
    os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def run_queue(
    configuration: ReplayQueueConfiguration,
    state_store: QueueStateStore,
    *,
    stop_requested: threading.Event | None = None,
    gaming_probe: Callable[[Path], tuple[bool, str]] = gamemode_active,
    popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    stopping = stop_requested or threading.Event()
    state = state_store.load()
    jobs_by_id = {item.job_id: item for item in configuration.jobs}
    child: subprocess.Popen[Any] | None = None
    previous_handlers: dict[int, Any] = {}

    def request_stop(_signum, _frame) -> None:
        stopping.set()

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
    try:
        while not stopping.is_set():
            completed = list(state["completed_job_ids"])
            if len(completed) == len(configuration.jobs):
                state.update(current_job_id=None, status="COMPLETE", last_reason=None)
                state_store.write(state)
                return 0
            job = jobs_by_id.get(state.get("current_job_id")) or configuration.jobs[len(completed)]
            inhibited, reason = gaming_probe(configuration.gaming_inhibit_path)
            if inhibited:
                state.update(current_job_id=job.job_id, status="PAUSED_FOR_GAME", last_reason=reason)
                state_store.write(state)
                sleeper(configuration.poll_seconds)
                continue
            state.update(current_job_id=job.job_id, status="RUNNING", last_reason=None)
            state_store.write(state)
            child = popen_factory(replay_command(job, configuration), cwd=ROOT, start_new_session=True)
            while child.poll() is None and not stopping.is_set():
                inhibited, reason = gaming_probe(configuration.gaming_inhibit_path)
                if inhibited:
                    _stop_child(child, configuration.stop_timeout_seconds)
                    state.update(status="PAUSED_FOR_GAME", last_reason=reason)
                    state_store.write(state)
                    child = None
                    break
                sleeper(configuration.poll_seconds)
            if stopping.is_set():
                if child is not None:
                    _stop_child(child, configuration.stop_timeout_seconds)
                state.update(status="STOPPED", last_reason="CONTROLLER_STOPPED")
                state_store.write(state)
                return 0
            if child is None:
                continue
            return_code = child.wait()
            child = None
            if return_code != 0:
                state.update(status="FAILED", last_reason=f"REPLAY_EXIT_{return_code}")
                state_store.write(state)
                return return_code if return_code > 0 else 1
            completed.append(job.job_id)
            state.update(completed_job_ids=completed, current_job_id=None, status="READY", last_reason=None)
            state_store.write(state)
        return 0
    finally:
        if child is not None:
            _stop_child(child, configuration.stop_timeout_seconds)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIGURATION)
    parser.add_argument(
        "--state-directory",
        type=Path,
        default=ROOT / "runtime/qpx_v3_replay_queue",
    )
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    configuration = load_queue_configuration(args.config.resolve())
    if args.validate_only:
        print(configuration.fingerprint)
        return 0
    validate_cgroup_budget()
    return run_queue(configuration, QueueStateStore(args.state_directory.resolve(), configuration))


if __name__ == "__main__":
    raise SystemExit(main())
