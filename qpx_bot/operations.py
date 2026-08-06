"""Automated QPX paper operations, health checks, and recovery."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from qpx_bot.market_calendar import (
    NEW_YORK,
    latest_completed_session,
)
from qpx_bot.paper_state import AuditEvent, StateStore


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "operations_config.json"
DEFAULT_RUNTIME_DIR = PACKAGE_DIR / "operations_runtime"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_operations"
DEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_SELECTION_RUNTIME = PACKAGE_DIR / "selection_runtime"
DEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"
AUTO_RUNNER = PROJECT_ROOT / "QPX_RUN_AUTO_PAPER.py"


@dataclass(frozen=True, slots=True)
class OperationsConfig:
    schema_version: int
    market_timezone: str
    market_ready_time: str
    maximum_attempts: int
    retry_delay_seconds: float
    command_timeout_seconds: int
    circuit_breaker_failures: int
    notify_with_termux_api: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported operations configuration version."
            )

        if self.market_timezone != "America/New_York":
            raise ValueError(
                "QPX market operations require America/New_York."
            )

        _parse_ready_time(self.market_ready_time)

        if self.maximum_attempts < 1:
            raise ValueError(
                "Maximum attempts must be positive."
            )

        if self.retry_delay_seconds < 0:
            raise ValueError(
                "Retry delay cannot be negative."
            )

        if self.command_timeout_seconds < 60:
            raise ValueError(
                "Command timeout must be at least 60 seconds."
            )

        if self.circuit_breaker_failures < 2:
            raise ValueError(
                "Circuit breaker requires at least two failures."
            )


@dataclass(slots=True)
class OperationsState:
    last_successful_session: str | None = None
    consecutive_failures: int = 0
    paused: bool = False
    last_status: str = "NEVER_RUN"
    last_message: str = ""
    last_attempt_utc: str | None = None
    last_recovery_utc: str | None = None

    def validate(self) -> None:
        if self.consecutive_failures < 0:
            raise ValueError(
                "Consecutive failures cannot be negative."
            )

        if self.last_successful_session:
            date.fromisoformat(self.last_successful_session)

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "OperationsState":
        state = cls(
            last_successful_session=(
                str(payload["last_successful_session"])
                if payload.get("last_successful_session")
                else None
            ),
            consecutive_failures=int(
                payload.get("consecutive_failures", 0)
            ),
            paused=bool(payload.get("paused", False)),
            last_status=str(
                payload.get("last_status", "UNKNOWN")
            ),
            last_message=str(
                payload.get("last_message", "")
            ),
            last_attempt_utc=(
                str(payload["last_attempt_utc"])
                if payload.get("last_attempt_utc")
                else None
            ),
            last_recovery_utc=(
                str(payload["last_recovery_utc"])
                if payload.get("last_recovery_utc")
                else None
            ),
        )
        state.validate()
        return state


@dataclass(frozen=True, slots=True)
class HealthReport:
    generated_at_utc: str
    market_time: str
    status: str
    message: str
    calendar_status: str
    expected_session: str
    last_successful_session: str | None
    latest_swing_bar: str | None
    paper_last_processed_bar: str | None
    selected_symbol: str | None
    execution_symbol: str | None
    paper_revision: int | None
    journal_records: int | None
    kill_switch_active: bool
    operations_paused: bool
    consecutive_failures: int
    scheduler_backend: str | None
    stale_data: bool
    run_log: str | None


CommandRunner = Callable[
    [Sequence[str], Path, int],
    tuple[int, str, str],
]


def _parse_ready_time(value: str) -> clock_time:
    try:
        hour_text, minute_text = value.split(":", 1)
        parsed = clock_time(
            int(hour_text),
            int(minute_text),
        )
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Market ready time must use HH:MM."
        ) from exc

    return parsed


def load_operations_config(
    filename: str | Path = DEFAULT_CONFIG_PATH,
) -> OperationsConfig:
    path = Path(filename).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, Mapping):
        raise ValueError(
            "Operations configuration must be an object."
        )

    config = OperationsConfig(
        schema_version=int(payload["schema_version"]),
        market_timezone=str(payload["market_timezone"]),
        market_ready_time=str(
            payload["market_ready_time"]
        ),
        maximum_attempts=int(payload["maximum_attempts"]),
        retry_delay_seconds=float(
            payload["retry_delay_seconds"]
        ),
        command_timeout_seconds=int(
            payload["command_timeout_seconds"]
        ),
        circuit_breaker_failures=int(
            payload["circuit_breaker_failures"]
        ),
        notify_with_termux_api=bool(
            payload["notify_with_termux_api"]
        ),
    )
    config.validate()
    return config


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


def load_operations_state(
    runtime_directory: str | Path,
) -> OperationsState:
    path = (
        Path(runtime_directory).expanduser().resolve()
        / "operations_state.json"
    )

    if not path.exists():
        return OperationsState()

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, Mapping):
        raise RuntimeError(
            "Operations state root must be an object."
        )

    return OperationsState.from_dict(payload)


def save_operations_state(
    runtime_directory: str | Path,
    state: OperationsState,
) -> Path:
    path = (
        Path(runtime_directory).expanduser().resolve()
        / "operations_state.json"
    )
    _atomic_json(path, state.to_dict())
    return path


@contextmanager
def operations_lock(
    runtime_directory: str | Path,
    *,
    stale_after_seconds: float = 21_600.0,
) -> Iterator[None]:
    directory = Path(
        runtime_directory
    ).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "operations.lock"

    for attempt in range(2):
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )

            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
            ) as file:
                file.write(
                    json.dumps(
                        {
                            "pid": os.getpid(),
                            "created_utc": datetime.now(
                                timezone.utc
                            ).isoformat(),
                        }
                    )
                )
            break
        except FileExistsError:
            age = time.time() - lock_path.stat().st_mtime

            if (
                attempt == 0
                and age > stale_after_seconds
            ):
                lock_path.unlink(missing_ok=True)
                continue

            raise RuntimeError(
                "Another QPX daily-operations run is active."
            )
    else:
        raise RuntimeError(
            "Unable to acquire operations lock."
        )

    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def read_latest_csv_date(path: str | Path) -> date | None:
    filename = Path(path)

    if not filename.exists():
        return None

    latest: date | None = None

    with filename.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            raw = (
                row.get("Date")
                or row.get("date")
                or ""
            ).strip()

            if not raw:
                continue

            current = date.fromisoformat(raw)

            if latest is None or current > latest:
                latest = current

    return latest


def _load_optional_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, Mapping) else {}


def _subprocess_runner(
    command: Sequence[str],
    cwd: Path,
    timeout_seconds: int,
) -> tuple[int, str, str]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )
    return (
        completed.returncode,
        completed.stdout,
        completed.stderr,
    )


def _notify(
    *,
    title: str,
    content: str,
    high_priority: bool,
    enabled: bool,
) -> None:
    if not enabled:
        return

    command = shutil.which("termux-notification")

    if command is None:
        return

    subprocess.run(
        [
            command,
            "--id",
            "qpx-daily-health",
            "--title",
            title,
            "--content",
            content[:500],
            "--priority",
            "high" if high_priority else "default",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def _write_run_log(
    report_directory: Path,
    *,
    attempt: int,
    stdout: str,
    stderr: str,
) -> Path:
    report_directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    path = (
        report_directory
        / f"run_{stamp}_attempt_{attempt}.log"
    )
    path.write_text(
        (
            f"ATTEMPT: {attempt}\n"
            f"UTC: {datetime.now(timezone.utc).isoformat()}\n"
            "\nSTDOUT\n"
            + stdout
            + "\nSTDERR\n"
            + stderr
        ),
        encoding="utf-8",
    )
    return path


def _health_text(report: HealthReport) -> str:
    lines = [
        "=" * 78,
        "QPX BOT v1.11 — DAILY OPERATIONS HEALTH",
        "=" * 78,
        f"Status                    : {report.status}",
        f"Message                   : {report.message}",
        f"Market time               : {report.market_time}",
        f"Calendar status           : {report.calendar_status}",
        f"Expected completed session: {report.expected_session}",
        (
            "Last successful session   : "
            f"{report.last_successful_session}"
        ),
        f"Latest swing bar          : {report.latest_swing_bar}",
        (
            "Paper last processed bar  : "
            f"{report.paper_last_processed_bar}"
        ),
        f"Selected symbol           : {report.selected_symbol}",
        f"Execution symbol          : {report.execution_symbol}",
        f"Paper revision            : {report.paper_revision}",
        f"Audit records             : {report.journal_records}",
        (
            "Paper kill switch         : "
            f"{'ACTIVE' if report.kill_switch_active else 'OFF'}"
        ),
        (
            "Operations circuit breaker: "
            f"{'PAUSED' if report.operations_paused else 'ARMED'}"
        ),
        (
            "Consecutive failures      : "
            f"{report.consecutive_failures}"
        ),
        f"Scheduler backend         : {report.scheduler_backend}",
        f"Stale data                : {report.stale_data}",
        f"Run log                   : {report.run_log}",
        "=" * 78,
        "Simulation only. No brokerage connection or live orders.",
    ]
    return "\n".join(lines)


def write_health_report(
    report: HealthReport,
    report_directory: str | Path,
) -> dict[str, Path]:
    directory = Path(
        report_directory
    ).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    latest_json = directory / "latest_health.json"
    latest_text = directory / "latest_health.txt"
    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%SZ")
    history_json = directory / f"health_{stamp}.json"

    payload = asdict(report)
    _atomic_json(latest_json, payload)
    _atomic_json(history_json, payload)
    latest_text.write_text(
        _health_text(report) + "\n",
        encoding="utf-8",
    )
    return {
        "json": latest_json,
        "text": latest_text,
        "history": history_json,
    }


def _paper_snapshot(
    *,
    paper_runtime: Path,
    input_directory: Path,
    selection_runtime: Path,
) -> dict[str, Any]:
    store = StateStore(paper_runtime)
    snapshot: dict[str, Any] = {
        "paper_last_processed_bar": None,
        "execution_symbol": None,
        "paper_revision": None,
        "journal_records": None,
        "kill_switch_active": store.kill_switch_active(),
    }

    if store.exists():
        state = store.load()
        _, _, records = store.verify_journal()
        snapshot.update(
            {
                "paper_last_processed_bar": (
                    state.last_processed_date.isoformat()
                    if state.last_processed_date
                    else None
                ),
                "execution_symbol": state.swing_symbol,
                "paper_revision": state.revision,
                "journal_records": records,
            }
        )

    selection = _load_optional_json(
        selection_runtime / "selection_decision.json"
    )
    selected = str(
        selection.get("selected_symbol", "")
    ).strip().upper()
    snapshot["selected_symbol"] = selected or None

    latest_swing = read_latest_csv_date(
        input_directory / "SWING.csv"
    )
    snapshot["latest_swing_bar"] = (
        latest_swing.isoformat()
        if latest_swing
        else None
    )

    scheduler = _load_optional_json(
        DEFAULT_RUNTIME_DIR / "scheduler.json"
    )
    snapshot["scheduler_backend"] = (
        str(scheduler.get("backend"))
        if scheduler.get("backend")
        else None
    )
    return snapshot


def _build_report(
    *,
    now: datetime,
    status: str,
    message: str,
    calendar_status: str,
    expected_session: date,
    operations_state: OperationsState,
    paper_runtime: Path,
    input_directory: Path,
    selection_runtime: Path,
    run_log: Path | None,
) -> HealthReport:
    snapshot = _paper_snapshot(
        paper_runtime=paper_runtime,
        input_directory=input_directory,
        selection_runtime=selection_runtime,
    )
    latest_text = snapshot["latest_swing_bar"]
    paper_text = snapshot["paper_last_processed_bar"]
    latest_date = (
        date.fromisoformat(latest_text)
        if latest_text
        else None
    )
    paper_date = (
        date.fromisoformat(paper_text)
        if paper_text
        else None
    )
    stale = (
        latest_date is None
        or latest_date < expected_session
        or paper_date is None
        or paper_date < expected_session
    )

    return HealthReport(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        market_time=now.astimezone(
            NEW_YORK
        ).isoformat(),
        status=status,
        message=message,
        calendar_status=calendar_status,
        expected_session=expected_session.isoformat(),
        last_successful_session=(
            operations_state.last_successful_session
        ),
        latest_swing_bar=latest_text,
        paper_last_processed_bar=paper_text,
        selected_symbol=snapshot["selected_symbol"],
        execution_symbol=snapshot["execution_symbol"],
        paper_revision=snapshot["paper_revision"],
        journal_records=snapshot["journal_records"],
        kill_switch_active=bool(
            snapshot["kill_switch_active"]
        ),
        operations_paused=operations_state.paused,
        consecutive_failures=(
            operations_state.consecutive_failures
        ),
        scheduler_backend=snapshot["scheduler_backend"],
        stale_data=stale,
        run_log=str(run_log) if run_log else None,
    )


def _operations_event(
    event_type: str,
    details: Mapping[str, Any],
) -> AuditEvent:
    moment = datetime.now(timezone.utc)
    return AuditEvent(
        event_id=(
            f"operations-{event_type.lower()}-"
            f"{moment.strftime('%Y%m%d%H%M%S%f')}"
        ),
        event_type=event_type,
        event_date=moment.date(),
        details=dict(details),
    )


def resume_operations(
    *,
    runtime_directory: Path,
    paper_runtime: Path,
) -> None:
    state = load_operations_state(runtime_directory)
    state.paused = False
    state.consecutive_failures = 0
    state.last_status = "RESUMED"
    state.last_message = "Manual operations resume."
    state.last_recovery_utc = datetime.now(
        timezone.utc
    ).isoformat()
    save_operations_state(runtime_directory, state)
    (runtime_directory / "OPERATIONS_PAUSED").unlink(
        missing_ok=True
    )

    paper_store = StateStore(paper_runtime)
    paper_store.deactivate_kill_switch()
    paper_store.append_events(
        [
            _operations_event(
                "OPERATIONS_RESUMED",
                {"reason": "manual CLI command"},
            )
        ]
    )


def run_daily_operations(
    *,
    config: OperationsConfig,
    runtime_directory: str | Path,
    report_directory: str | Path,
    paper_runtime: str | Path,
    selection_runtime: str | Path,
    input_directory: str | Path,
    now: datetime | None = None,
    force: bool = False,
    check_only: bool = False,
    command_runner: CommandRunner | None = None,
    retry_sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, HealthReport]:
    runtime = Path(
        runtime_directory
    ).expanduser().resolve()
    reports = Path(
        report_directory
    ).expanduser().resolve()
    paper = Path(
        paper_runtime
    ).expanduser().resolve()
    selection = Path(
        selection_runtime
    ).expanduser().resolve()
    inputs = Path(
        input_directory
    ).expanduser().resolve()
    current = now or datetime.now(tz=NEW_YORK)
    expected_session, calendar_status = (
        latest_completed_session(
            current,
            ready_time=_parse_ready_time(
                config.market_ready_time
            ),
        )
    )
    runner = command_runner or _subprocess_runner

    with operations_lock(runtime):
        state = load_operations_state(runtime)
        paper_store = StateStore(paper)

        if (
            state.paused
            or (runtime / "OPERATIONS_PAUSED").exists()
        ):
            state.paused = True
            state.last_status = "PAUSED"
            state.last_message = (
                "Operations circuit breaker is active."
            )
            save_operations_state(runtime, state)
            report = _build_report(
                now=current,
                status="PAUSED",
                message=state.last_message,
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=None,
            )
            write_health_report(report, reports)
            _notify(
                title="QPX operations paused",
                content=report.message,
                high_priority=True,
                enabled=config.notify_with_termux_api,
            )
            return 6, report

        if paper_store.kill_switch_active():
            state.last_status = "PAPER_KILL_SWITCH"
            state.last_message = (
                "Paper kill switch is active; no run attempted."
            )
            save_operations_state(runtime, state)
            report = _build_report(
                now=current,
                status="PAUSED",
                message=state.last_message,
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=None,
            )
            write_health_report(report, reports)
            return 4, report

        if check_only:
            report = _build_report(
                now=current,
                status="CHECK_ONLY",
                message=(
                    "Integrity and freshness snapshot completed."
                ),
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=None,
            )
            write_health_report(report, reports)
            return 0, report

        if (
            calendar_status == "WAITING_FOR_MARKET_DATA"
            and not force
        ):
            state.last_status = "WAITING"
            state.last_message = (
                "Waiting until 17:15 New York time."
            )
            save_operations_state(runtime, state)
            report = _build_report(
                now=current,
                status="WAITING",
                message=state.last_message,
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=None,
            )
            write_health_report(report, reports)
            return 0, report

        if (
            state.last_successful_session
            == expected_session.isoformat()
            and not force
        ):
            state.last_status = "CURRENT"
            state.last_message = (
                "Expected market session is already processed."
            )
            save_operations_state(runtime, state)
            report = _build_report(
                now=current,
                status="CURRENT",
                message=state.last_message,
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=None,
            )
            write_health_report(report, reports)
            return 0, report

        state.last_attempt_utc = datetime.now(
            timezone.utc
        ).isoformat()
        last_log: Path | None = None
        failure_message = "Unknown execution failure."
        succeeded = False

        command = [
            sys.executable,
            str(AUTO_RUNNER),
        ]

        for attempt in range(1, config.maximum_attempts + 1):
            try:
                return_code, stdout, stderr = runner(
                    command,
                    PROJECT_ROOT,
                    config.command_timeout_seconds,
                )
            except subprocess.TimeoutExpired as exc:
                return_code = 124
                stdout = (
                    exc.stdout
                    if isinstance(exc.stdout, str)
                    else ""
                )
                stderr = (
                    exc.stderr
                    if isinstance(exc.stderr, str)
                    else ""
                ) + "\nQPX daily command timed out."
            except Exception as exc:
                return_code = 125
                stdout = ""
                stderr = (
                    f"{type(exc).__name__}: {exc}"
                )

            last_log = _write_run_log(
                reports,
                attempt=attempt,
                stdout=stdout,
                stderr=stderr,
            )

            if return_code == 0:
                try:
                    snapshot = _paper_snapshot(
                        paper_runtime=paper,
                        input_directory=inputs,
                        selection_runtime=selection,
                    )
                    latest = (
                        date.fromisoformat(
                            snapshot["latest_swing_bar"]
                        )
                        if snapshot["latest_swing_bar"]
                        else None
                    )
                    processed = (
                        date.fromisoformat(
                            snapshot[
                                "paper_last_processed_bar"
                            ]
                        )
                        if snapshot[
                            "paper_last_processed_bar"
                        ]
                        else None
                    )

                    if latest is None or latest < expected_session:
                        raise RuntimeError(
                            "Downloaded swing data is stale; "
                            f"expected {expected_session}, got "
                            f"{latest}."
                        )

                    if (
                        processed is None
                        or processed < expected_session
                    ):
                        raise RuntimeError(
                            "Paper state did not process the "
                            f"expected session {expected_session}."
                        )

                    if not snapshot["execution_symbol"]:
                        raise RuntimeError(
                            "Paper execution symbol is missing."
                        )

                    succeeded = True
                    break
                except Exception as exc:
                    failure_message = (
                        f"Post-run verification failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
            else:
                failure_message = (
                    f"Auto paper runner returned {return_code}. "
                    f"See {last_log}."
                )

            if attempt < config.maximum_attempts:
                retry_sleep(config.retry_delay_seconds)

        previous_failures = state.consecutive_failures

        if succeeded:
            recovered = previous_failures > 0
            state.last_successful_session = (
                expected_session.isoformat()
            )
            state.consecutive_failures = 0
            state.paused = False
            state.last_status = "HEALTHY"
            state.last_message = (
                "Daily selection, market refresh, paper "
                "processing, and reconciliation passed."
            )

            if recovered:
                state.last_recovery_utc = datetime.now(
                    timezone.utc
                ).isoformat()

            save_operations_state(runtime, state)
            report = _build_report(
                now=current,
                status="HEALTHY",
                message=state.last_message,
                calendar_status=calendar_status,
                expected_session=expected_session,
                operations_state=state,
                paper_runtime=paper,
                input_directory=inputs,
                selection_runtime=selection,
                run_log=last_log,
            )
            write_health_report(report, reports)

            if recovered:
                paper_store.append_events(
                    [
                        _operations_event(
                            "OPERATIONS_RECOVERED",
                            {
                                "session": (
                                    expected_session.isoformat()
                                ),
                                "previous_failures": (
                                    previous_failures
                                ),
                            },
                        )
                    ]
                )
                _notify(
                    title="QPX operations recovered",
                    content=state.last_message,
                    high_priority=False,
                    enabled=(
                        config.notify_with_termux_api
                    ),
                )

            return 0, report

        state.consecutive_failures += 1
        state.last_status = "FAILED"
        state.last_message = failure_message

        if (
            state.consecutive_failures
            >= config.circuit_breaker_failures
        ):
            state.paused = True
            state.last_status = "PAUSED"
            state.last_message = (
                failure_message
                + " Circuit breaker activated after "
                f"{state.consecutive_failures} failures."
            )
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "OPERATIONS_PAUSED").write_text(
                state.last_message + "\n",
                encoding="utf-8",
            )
            paper_store.activate_kill_switch(
                "QPX automated operations circuit breaker"
            )
            paper_store.append_events(
                [
                    _operations_event(
                        "OPERATIONS_PAUSED",
                        {
                            "failures": (
                                state.consecutive_failures
                            ),
                            "reason": failure_message,
                        },
                    )
                ]
            )

        save_operations_state(runtime, state)
        report = _build_report(
            now=current,
            status=state.last_status,
            message=state.last_message,
            calendar_status=calendar_status,
            expected_session=expected_session,
            operations_state=state,
            paper_runtime=paper,
            input_directory=inputs,
            selection_runtime=selection,
            run_log=last_log,
        )
        write_health_report(report, reports)
        _notify(
            title=(
                "QPX operations paused"
                if state.paused
                else "QPX operations failed"
            ),
            content=state.last_message,
            high_priority=True,
            enabled=config.notify_with_termux_api,
        )
        return (6 if state.paused else 5), report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run QPX automated paper operations with market "
            "calendar, retries, health verification, and a "
            "failure circuit breaker."
        )
    )
    parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG_PATH),
    )
    parser.add_argument(
        "--runtime-dir",
        default=str(DEFAULT_RUNTIME_DIR),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    parser.add_argument(
        "--paper-runtime-dir",
        default=str(DEFAULT_PAPER_RUNTIME),
    )
    parser.add_argument(
        "--selection-runtime-dir",
        default=str(DEFAULT_SELECTION_RUNTIME),
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run even if the expected session is already complete.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Write a health snapshot without running the bot.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reset the circuit breaker and paper kill switch.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    runtime = Path(
        args.runtime_dir
    ).expanduser().resolve()
    paper = Path(
        args.paper_runtime_dir
    ).expanduser().resolve()

    if args.resume:
        with operations_lock(runtime):
            resume_operations(
                runtime_directory=runtime,
                paper_runtime=paper,
            )
        print("QPX automated operations are RESUMED.")
        return 0

    config = load_operations_config(args.config)
    code, report = run_daily_operations(
        config=config,
        runtime_directory=runtime,
        report_directory=args.report_dir,
        paper_runtime=paper,
        selection_runtime=args.selection_runtime_dir,
        input_directory=args.input_dir,
        force=args.force,
        check_only=args.check_only,
    )
    print(_health_text(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
