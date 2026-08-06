"""Operational qualification ledger for QPX paper execution."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from qpx_bot.backup import (
    default_archive_directory,
    latest_backup,
    load_backup_config,
    verify_backup,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    is_market_session,
    latest_completed_session,
    next_market_session,
)
from qpx_bot.paper_state import StateStore
from qpx_bot.session_execution import (
    load_session_execution_config,
    session_phase,
)


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_CONFIG_PATH = PACKAGE_DIR / "qualification_config.json"
DEFAULT_RUNTIME_DIR = PACKAGE_DIR / "qualification_runtime"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_qualification"
DEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_OPERATIONS_RUNTIME = PACKAGE_DIR / "operations_runtime"
DEFAULT_SESSION_REPORT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_session_execution"
    / "latest_session_execution.json"
)
DEFAULT_OPERATIONS_REPORT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_operations"
    / "latest_health.json"
)
DEFAULT_BACKUP_REPORT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_backup"
    / "latest_backup.json"
)


TERMINAL_SUCCESS_TYPES = {
    "ENTRY_FILLED_REGULAR_SESSION",
    "ENTRY_REJECTED_OPENING_GAP",
    "ENTRY_REJECTED_POSITION_SIZING",
}
TERMINAL_FAILURE_TYPES = {
    "ENTRY_CANCELLED_MISSED_WINDOW",
    "ENTRY_CANCELLED_STALE_SESSION",
}
TERMINAL_TYPES = (
    TERMINAL_SUCCESS_TYPES
    | TERMINAL_FAILURE_TYPES
)


@dataclass(frozen=True, slots=True)
class QualificationConfig:
    schema_version: int
    minimum_observation_sessions: int
    minimum_instruction_outcomes: int
    minimum_opening_window_coverage: float
    minimum_after_close_coverage: float
    minimum_backup_coverage: float
    minimum_instruction_processing_rate: float
    maximum_missed_window_events: int
    maximum_stale_instruction_events: int
    maximum_extended_hours_events: int
    maximum_duplicate_terminal_orders: int
    live_broker_enabled: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported qualification configuration."
            )

        if self.minimum_observation_sessions < 5:
            raise ValueError(
                "Qualification requires at least five sessions."
            )

        if self.minimum_instruction_outcomes < 1:
            raise ValueError(
                "At least one instruction outcome is required."
            )

        for name, value in {
            "opening coverage": self.minimum_opening_window_coverage,
            "after-close coverage": self.minimum_after_close_coverage,
            "backup coverage": self.minimum_backup_coverage,
            "instruction processing": (
                self.minimum_instruction_processing_rate
            ),
        }.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{name.capitalize()} must be between zero and one."
                )

        integer_limits = {
            "missed-window events": self.maximum_missed_window_events,
            "stale-instruction events": (
                self.maximum_stale_instruction_events
            ),
            "extended-hours events": (
                self.maximum_extended_hours_events
            ),
            "duplicate terminal orders": (
                self.maximum_duplicate_terminal_orders
            ),
        }

        for name, value in integer_limits.items():
            if value < 0:
                raise ValueError(
                    f"Maximum {name} cannot be negative."
                )

        if self.live_broker_enabled:
            raise ValueError(
                "Live broker mode must remain disabled during "
                "paper execution qualification."
            )


@dataclass(frozen=True, slots=True)
class AuditMetrics:
    journal_valid: bool
    journal_records: int
    signals: int
    instruction_outcomes: int
    successful_instruction_outcomes: int
    quote_backed_outcomes: int
    missed_window_events: int
    stale_instruction_events: int
    extended_hours_events: int
    duplicate_terminal_orders: int


@dataclass(frozen=True, slots=True)
class EnvironmentSnapshot:
    paper_state_valid: bool
    journal_valid: bool
    scheduler_installed: bool
    cron_running: bool
    paper_kill_switch: bool
    operations_paused: bool


@dataclass(frozen=True, slots=True)
class QualificationResult:
    generated_at_utc: str
    market_time: str
    status: str
    message: str
    first_eligible_session: str
    latest_expected_session: str | None
    expected_sessions: int
    opening_window_sessions: int
    after_close_healthy_sessions: int
    verified_backup_sessions: int
    instruction_signals: int
    instruction_outcomes: int
    successful_instruction_outcomes: int
    opening_window_coverage: float
    after_close_coverage: float
    backup_coverage: float
    instruction_processing_rate: float
    quote_backed_outcomes: int
    missed_window_events: int
    stale_instruction_events: int
    extended_hours_events: int
    duplicate_terminal_orders: int
    paper_state_valid: bool
    journal_valid: bool
    scheduler_installed: bool
    cron_running: bool
    paper_kill_switch: bool
    operations_paused: bool
    live_broker_enabled: bool
    criteria: Mapping[str, Mapping[str, Any]]
    blockers: tuple[str, ...]


def load_qualification_config(
    filename: str | Path = DEFAULT_CONFIG_PATH,
) -> QualificationConfig:
    path = Path(filename).expanduser().resolve()
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, Mapping):
        raise ValueError(
            "Qualification configuration must be an object."
        )

    config = QualificationConfig(
        schema_version=int(payload["schema_version"]),
        minimum_observation_sessions=int(
            payload["minimum_observation_sessions"]
        ),
        minimum_instruction_outcomes=int(
            payload["minimum_instruction_outcomes"]
        ),
        minimum_opening_window_coverage=float(
            payload["minimum_opening_window_coverage"]
        ),
        minimum_after_close_coverage=float(
            payload["minimum_after_close_coverage"]
        ),
        minimum_backup_coverage=float(
            payload["minimum_backup_coverage"]
        ),
        minimum_instruction_processing_rate=float(
            payload["minimum_instruction_processing_rate"]
        ),
        maximum_missed_window_events=int(
            payload["maximum_missed_window_events"]
        ),
        maximum_stale_instruction_events=int(
            payload["maximum_stale_instruction_events"]
        ),
        maximum_extended_hours_events=int(
            payload["maximum_extended_hours_events"]
        ),
        maximum_duplicate_terminal_orders=int(
            payload["maximum_duplicate_terminal_orders"]
        ),
        live_broker_enabled=bool(
            payload["live_broker_enabled"]
        ),
    )
    config.validate()
    return config


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, sort_keys=True)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())

    temporary.replace(path)


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


def _market_now(
    current: datetime | None = None,
) -> datetime:
    moment = current or datetime.now(tz=NEW_YORK)

    if moment.tzinfo is None:
        return moment.replace(tzinfo=NEW_YORK)

    return moment.astimezone(NEW_YORK)


def qualification_start_session(
    current: datetime | None = None,
) -> date:
    moment = _market_now(current)
    execution_config = load_session_execution_config()
    phase = session_phase(moment, execution_config)

    if phase in {
        "PRE_MARKET",
        "OPENING_DELAY",
        "OPENING_WINDOW",
    }:
        return moment.date()

    return next_market_session(moment.date())


def _new_state(
    current: datetime | None = None,
) -> dict[str, Any]:
    moment = _market_now(current)
    return {
        "schema_version": 1,
        "started_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "first_eligible_session": (
            qualification_start_session(
                moment
            ).isoformat()
        ),
        "sessions": {},
    }


def load_state(
    runtime_directory: str | Path,
    *,
    current: datetime | None = None,
) -> dict[str, Any]:
    directory = Path(
        runtime_directory
    ).expanduser().resolve()
    path = directory / "qualification_state.json"

    if not path.exists():
        return _new_state(current)

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise RuntimeError(
            "Qualification state root must be an object."
        )

    if int(payload.get("schema_version", -1)) != 1:
        raise RuntimeError(
            "Unsupported qualification state version."
        )

    date.fromisoformat(
        str(payload["first_eligible_session"])
    )

    sessions = payload.get("sessions")

    if not isinstance(sessions, dict):
        raise RuntimeError(
            "Qualification sessions must be an object."
        )

    return payload


def save_state(
    runtime_directory: str | Path,
    state: Mapping[str, Any],
) -> Path:
    directory = Path(
        runtime_directory
    ).expanduser().resolve()
    path = directory / "qualification_state.json"
    _atomic_json(path, state)
    return path


@contextmanager
def qualification_lock(
    runtime_directory: str | Path,
    *,
    stale_after_seconds: float = 21_600.0,
) -> Iterator[None]:
    directory = Path(
        runtime_directory
    ).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / "qualification.lock"

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
                            "created_at_utc": datetime.now(
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
                "Another qualification update is active."
            )
    else:
        raise RuntimeError(
            "Unable to acquire qualification lock."
        )

    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def _default_session_record() -> dict[str, Any]:
    return {
        "session_checks": 0,
        "opening_window_checks": 0,
        "command_failures": 0,
        "quote_retry_checks": 0,
        "statuses": [],
        "phases": [],
        "instruction_order_ids": [],
        "terminal_outcome": None,
        "quote_success": False,
        "extended_hours_seen": False,
        "after_close_seen": False,
        "after_close_healthy": False,
        "paper_processed": False,
        "backup_verified": False,
        "recovery_drill_passed": False,
        "audit_valid": False,
        "paper_state_valid": False,
        "scheduler_installed": False,
        "cron_running": False,
        "paper_kill_switch": False,
        "operations_paused": False,
        "first_seen_utc": None,
        "last_seen_utc": None,
    }


def _append_unique(
    values: list[Any],
    value: Any,
) -> None:
    if value not in values:
        values.append(value)


def _session_record(
    state: dict[str, Any],
    session_date: date,
) -> dict[str, Any]:
    sessions = state["sessions"]
    key = session_date.isoformat()
    record = sessions.get(key)

    if not isinstance(record, dict):
        record = _default_session_record()
        sessions[key] = record

    return record


def record_session_report(
    state: dict[str, Any],
    report: Mapping[str, Any],
    *,
    command_status: int,
) -> date:
    market_time = datetime.fromisoformat(
        str(report["market_time"])
    ).astimezone(NEW_YORK)
    session_date = market_time.date()
    first_eligible = date.fromisoformat(
        str(state["first_eligible_session"])
    )

    if session_date < first_eligible:
        return session_date

    record = _session_record(
        state,
        session_date,
    )
    now_utc = datetime.now(
        timezone.utc
    ).isoformat()

    if record["first_seen_utc"] is None:
        record["first_seen_utc"] = now_utc

    record["last_seen_utc"] = now_utc
    record["session_checks"] += 1

    if command_status != 0:
        record["command_failures"] += 1

    phase = str(
        report.get("market_phase", "UNKNOWN")
    )
    status = str(
        report.get("status", "UNKNOWN")
    )
    _append_unique(record["phases"], phase)
    _append_unique(record["statuses"], status)

    if phase == "OPENING_WINDOW":
        record["opening_window_checks"] += 1

    if status == "QUOTE_RETRY":
        record["quote_retry_checks"] += 1

    order_id = str(
        report.get("pending_order_id") or ""
    ).strip()

    if order_id:
        _append_unique(
            record["instruction_order_ids"],
            order_id,
        )

    terminal_statuses = {
        "FILLED",
        "REJECTED_GAP",
        "REJECTED_RISK",
        "CANCELLED_STALE",
        "CANCELLED_EXPIRED",
    }

    if status in terminal_statuses:
        record["terminal_outcome"] = status

    if (
        report.get("quote_source")
        and report.get("opening_price") is not None
    ):
        record["quote_success"] = True

    if bool(report.get("extended_hours", False)):
        record["extended_hours_seen"] = True

    if (
        status == "FILLED"
        and phase != "OPENING_WINDOW"
    ):
        record["extended_hours_seen"] = True

    return session_date


def _crond_running() -> bool:
    pgrep = shutil.which("pgrep")

    if pgrep is None:
        return False

    completed = subprocess.run(
        [pgrep, "-x", "crond"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def _environment_snapshot(
    *,
    paper_runtime: Path,
    operations_runtime: Path,
) -> EnvironmentSnapshot:
    store = StateStore(paper_runtime)
    paper_valid = False
    journal_valid = False

    try:
        if store.exists():
            store.load()
            paper_valid = True
            store.verify_journal()
            journal_valid = True
    except Exception:
        paper_valid = False
        journal_valid = False

    scheduler = _load_optional_json(
        operations_runtime / "scheduler.json"
    )
    operations = _load_optional_json(
        operations_runtime / "operations_state.json"
    )

    return EnvironmentSnapshot(
        paper_state_valid=paper_valid,
        journal_valid=journal_valid,
        scheduler_installed=bool(
            scheduler.get("installed", False)
        ),
        cron_running=_crond_running(),
        paper_kill_switch=(
            store.kill_switch_active()
        ),
        operations_paused=bool(
            operations.get("paused", False)
        ),
    )


def _verify_latest_backup_for_session(
    session_date: date,
) -> tuple[bool, bool]:
    report = _load_optional_json(
        DEFAULT_BACKUP_REPORT
    )
    recovery_drill = bool(
        report.get("recovery_drill", False)
    )

    try:
        backup_config = load_backup_config()
        directory = default_archive_directory(
            PROJECT_ROOT,
            backup_config,
        )
        archive = latest_backup(directory)
        verified = verify_backup(archive)
        current = (
            verified.paper_last_processed_date
            == session_date.isoformat()
        )
        return current, recovery_drill
    except Exception:
        return False, recovery_drill


def record_after_close_report(
    state: dict[str, Any],
    *,
    command_status: int,
    health: Mapping[str, Any],
    environment: EnvironmentSnapshot,
    backup_verified: bool,
    recovery_drill_passed: bool,
    current: datetime | None = None,
) -> date:
    moment = _market_now(current)
    raw_session = (
        health.get("last_successful_session")
        or health.get("expected_session")
    )

    if raw_session:
        session_date = date.fromisoformat(
            str(raw_session)
        )
    else:
        session_date = latest_completed_session(
            moment
        )[0]

    first_eligible = date.fromisoformat(
        str(state["first_eligible_session"])
    )

    if session_date < first_eligible:
        return session_date

    record = _session_record(
        state,
        session_date,
    )
    status = str(
        health.get("status", "UNKNOWN")
    )
    successful_session = str(
        health.get("last_successful_session") or ""
    )
    processed = str(
        health.get("paper_last_processed_bar") or ""
    )

    record["after_close_seen"] = True
    record["after_close_healthy"] = (
        command_status == 0
        and status in {"HEALTHY", "CURRENT"}
        and successful_session
        == session_date.isoformat()
        and not bool(
            health.get("stale_data", True)
        )
    )
    record["paper_processed"] = (
        processed >= session_date.isoformat()
    )
    record["backup_verified"] = backup_verified
    record["recovery_drill_passed"] = (
        recovery_drill_passed
    )
    record["audit_valid"] = (
        environment.journal_valid
    )
    record["paper_state_valid"] = (
        environment.paper_state_valid
    )
    record["scheduler_installed"] = (
        environment.scheduler_installed
    )
    record["cron_running"] = (
        environment.cron_running
    )
    record["paper_kill_switch"] = (
        environment.paper_kill_switch
    )
    record["operations_paused"] = (
        environment.operations_paused
    )
    record["last_seen_utc"] = datetime.now(
        timezone.utc
    ).isoformat()

    if record["first_seen_utc"] is None:
        record["first_seen_utc"] = (
            record["last_seen_utc"]
        )

    return session_date


def _audit_records(
    store: StateStore,
) -> list[Mapping[str, Any]]:
    store.verify_journal()

    if not store.journal_path.exists():
        return []

    records: list[Mapping[str, Any]] = []

    for raw_line in store.journal_path.read_text(
        encoding="utf-8"
    ).splitlines():
        if not raw_line.strip():
            continue

        payload = json.loads(raw_line)

        if isinstance(payload, Mapping):
            records.append(payload)

    return records


def audit_metrics(
    paper_runtime: str | Path,
    *,
    first_eligible_session: date,
) -> AuditMetrics:
    store = StateStore(paper_runtime)

    try:
        records = _audit_records(store)
        journal_valid = True
    except Exception:
        return AuditMetrics(
            journal_valid=False,
            journal_records=0,
            signals=0,
            instruction_outcomes=0,
            successful_instruction_outcomes=0,
            quote_backed_outcomes=0,
            missed_window_events=0,
            stale_instruction_events=0,
            extended_hours_events=0,
            duplicate_terminal_orders=0,
        )

    signals = 0
    terminal_order_ids: list[str] = []
    successful = 0
    quote_backed = 0
    missed = 0
    stale = 0
    extended = 0

    for record in records:
        try:
            event_date = date.fromisoformat(
                str(record.get("event_date"))
            )
        except (TypeError, ValueError):
            continue

        details = record.get("details")

        if not isinstance(details, Mapping):
            details = {}

        event_type = str(
            record.get("event_type", "")
        )

        scheduled_session = event_date

        if event_type == "ENTRY_SIGNAL":
            scheduled_session = next_market_session(
                event_date
            )

        if scheduled_session < first_eligible_session:
            continue

        if event_type == "ENTRY_SIGNAL":
            signals += 1

        if event_type in TERMINAL_TYPES:
            order_id = str(
                details.get("order_id", "")
            ).strip()

            if order_id:
                terminal_order_ids.append(order_id)

            if event_type in TERMINAL_SUCCESS_TYPES:
                successful += 1

            if (
                details.get("quote_source")
                and details.get(
                    "opening_reference_price"
                )
                is not None
            ):
                quote_backed += 1

        if event_type == "ENTRY_CANCELLED_MISSED_WINDOW":
            missed += 1

        if event_type == "ENTRY_CANCELLED_STALE_SESSION":
            stale += 1

        if bool(details.get("extended_hours", False)):
            extended += 1

        if (
            event_type == "ENTRY_FILLED"
            and event_date >= first_eligible_session
        ):
            extended += 1

        if event_type == "ENTRY_FILLED_REGULAR_SESSION":
            if (
                details.get("execution_session")
                != "REGULAR_SESSION"
            ):
                extended += 1

    counts: dict[str, int] = {}

    for order_id in terminal_order_ids:
        counts[order_id] = (
            counts.get(order_id, 0) + 1
        )

    duplicates = sum(
        max(0, count - 1)
        for count in counts.values()
    )

    return AuditMetrics(
        journal_valid=journal_valid,
        journal_records=len(records),
        signals=signals,
        instruction_outcomes=len(
            terminal_order_ids
        ),
        successful_instruction_outcomes=successful,
        quote_backed_outcomes=quote_backed,
        missed_window_events=missed,
        stale_instruction_events=stale,
        extended_hours_events=extended,
        duplicate_terminal_orders=duplicates,
    )


def _market_sessions_between(
    start: date,
    end: date,
) -> tuple[date, ...]:
    if end < start:
        return ()

    sessions: list[date] = []
    current = start

    while current <= end:
        if is_market_session(current):
            sessions.append(current)

        current = current.fromordinal(
            current.toordinal() + 1
        )

    return tuple(sessions)


def _criterion(
    *,
    current: Any,
    required: Any,
    passed: bool,
) -> dict[str, Any]:
    return {
        "current": current,
        "required": required,
        "passed": passed,
    }


def evaluate_qualification(
    *,
    state: Mapping[str, Any],
    config: QualificationConfig,
    audit: AuditMetrics,
    environment: EnvironmentSnapshot,
    current: datetime | None = None,
) -> QualificationResult:
    config.validate()
    moment = _market_now(current)
    first_eligible = date.fromisoformat(
        str(state["first_eligible_session"])
    )
    latest_session, calendar_status = (
        latest_completed_session(moment)
    )

    if calendar_status == "WAITING_FOR_MARKET_DATA":
        latest_session = latest_completed_session(
            moment.replace(
                hour=17,
                minute=15,
            )
        )[0]

        if latest_session == moment.date():
            latest_session = date.fromordinal(
                latest_session.toordinal() - 1
            )

            while not is_market_session(
                latest_session
            ):
                latest_session = date.fromordinal(
                    latest_session.toordinal() - 1
                )

    expected = _market_sessions_between(
        first_eligible,
        latest_session,
    )
    sessions = state.get("sessions", {})

    if not isinstance(sessions, Mapping):
        sessions = {}

    opening_count = 0
    after_close_count = 0
    backup_count = 0

    for session_date in expected:
        record = sessions.get(
            session_date.isoformat(),
            {},
        )

        if not isinstance(record, Mapping):
            continue

        if int(
            record.get(
                "opening_window_checks",
                0,
            )
        ) > 0:
            opening_count += 1

        if (
            bool(
                record.get(
                    "after_close_healthy",
                    False,
                )
            )
            and bool(
                record.get(
                    "paper_processed",
                    False,
                )
            )
            and bool(
                record.get(
                    "audit_valid",
                    False,
                )
            )
            and bool(
                record.get(
                    "paper_state_valid",
                    False,
                )
            )
        ):
            after_close_count += 1

        if (
            bool(
                record.get(
                    "backup_verified",
                    False,
                )
            )
            and bool(
                record.get(
                    "recovery_drill_passed",
                    False,
                )
            )
        ):
            backup_count += 1

    expected_count = len(expected)

    def rate(numerator: int) -> float:
        return (
            numerator / expected_count
            if expected_count
            else 0.0
        )

    opening_rate = rate(opening_count)
    after_close_rate = rate(
        after_close_count
    )
    backup_rate = rate(backup_count)
    instruction_rate = (
        audit.successful_instruction_outcomes
        / audit.instruction_outcomes
        if audit.instruction_outcomes
        else 0.0
    )

    criteria = {
        "observation_sessions": _criterion(
            current=expected_count,
            required=(
                f">={config.minimum_observation_sessions}"
            ),
            passed=(
                expected_count
                >= config.minimum_observation_sessions
            ),
        ),
        "instruction_outcomes": _criterion(
            current=audit.instruction_outcomes,
            required=(
                f">={config.minimum_instruction_outcomes}"
            ),
            passed=(
                audit.instruction_outcomes
                >= config.minimum_instruction_outcomes
            ),
        ),
        "opening_window_coverage": _criterion(
            current=opening_rate,
            required=(
                f">={config.minimum_opening_window_coverage}"
            ),
            passed=(
                opening_rate
                >= config.minimum_opening_window_coverage
            ),
        ),
        "after_close_coverage": _criterion(
            current=after_close_rate,
            required=(
                f">={config.minimum_after_close_coverage}"
            ),
            passed=(
                after_close_rate
                >= config.minimum_after_close_coverage
            ),
        ),
        "backup_coverage": _criterion(
            current=backup_rate,
            required=(
                f">={config.minimum_backup_coverage}"
            ),
            passed=(
                backup_rate
                >= config.minimum_backup_coverage
            ),
        ),
        "instruction_processing_rate": _criterion(
            current=instruction_rate,
            required=(
                f">={config.minimum_instruction_processing_rate}"
            ),
            passed=(
                instruction_rate
                >= config.minimum_instruction_processing_rate
            ),
        ),
        "missed_window_events": _criterion(
            current=audit.missed_window_events,
            required=(
                f"<={config.maximum_missed_window_events}"
            ),
            passed=(
                audit.missed_window_events
                <= config.maximum_missed_window_events
            ),
        ),
        "stale_instruction_events": _criterion(
            current=audit.stale_instruction_events,
            required=(
                f"<={config.maximum_stale_instruction_events}"
            ),
            passed=(
                audit.stale_instruction_events
                <= config.maximum_stale_instruction_events
            ),
        ),
        "extended_hours_events": _criterion(
            current=audit.extended_hours_events,
            required=(
                f"<={config.maximum_extended_hours_events}"
            ),
            passed=(
                audit.extended_hours_events
                <= config.maximum_extended_hours_events
            ),
        ),
        "duplicate_terminal_orders": _criterion(
            current=(
                audit.duplicate_terminal_orders
            ),
            required=(
                "<="
                f"{config.maximum_duplicate_terminal_orders}"
            ),
            passed=(
                audit.duplicate_terminal_orders
                <= config.maximum_duplicate_terminal_orders
            ),
        ),
        "paper_state_valid": _criterion(
            current=environment.paper_state_valid,
            required=True,
            passed=environment.paper_state_valid,
        ),
        "journal_valid": _criterion(
            current=(
                environment.journal_valid
                and audit.journal_valid
            ),
            required=True,
            passed=(
                environment.journal_valid
                and audit.journal_valid
            ),
        ),
        "scheduler_installed": _criterion(
            current=environment.scheduler_installed,
            required=True,
            passed=environment.scheduler_installed,
        ),
        "cron_running": _criterion(
            current=environment.cron_running,
            required=True,
            passed=environment.cron_running,
        ),
        "paper_kill_switch_off": _criterion(
            current=environment.paper_kill_switch,
            required=False,
            passed=not environment.paper_kill_switch,
        ),
        "operations_not_paused": _criterion(
            current=environment.operations_paused,
            required=False,
            passed=not environment.operations_paused,
        ),
        "live_broker_disabled": _criterion(
            current=config.live_broker_enabled,
            required=False,
            passed=not config.live_broker_enabled,
        ),
    }

    blockers = tuple(
        name
        for name, payload in criteria.items()
        if not bool(payload["passed"])
    )

    hard_safety_names = {
        "extended_hours_events",
        "duplicate_terminal_orders",
        "paper_state_valid",
        "journal_valid",
        "paper_kill_switch_off",
        "operations_not_paused",
        "live_broker_disabled",
    }
    hard_blocked = any(
        name in hard_safety_names
        for name in blockers
    )
    sample_ready = (
        expected_count
        >= config.minimum_observation_sessions
        and audit.instruction_outcomes
        >= config.minimum_instruction_outcomes
    )

    if hard_blocked:
        status = "BLOCKED"
        message = (
            "A hard safety or integrity requirement failed. "
            "Broker connectivity remains prohibited."
        )
    elif not sample_ready:
        status = "COLLECTING"
        message = (
            "Operational paper evidence is still accumulating. "
            "Broker connectivity remains prohibited."
        )
    elif blockers:
        status = "NOT_QUALIFIED"
        message = (
            "The minimum sample exists, but one or more "
            "operational criteria failed."
        )
    else:
        status = "PAPER_QUALIFIED"
        message = (
            "Paper execution met the configured operational "
            "criteria. This does not authorize live trading; "
            "broker connectivity remains disabled."
        )

    return QualificationResult(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        market_time=moment.isoformat(),
        status=status,
        message=message,
        first_eligible_session=(
            first_eligible.isoformat()
        ),
        latest_expected_session=(
            latest_session.isoformat()
            if expected_count
            else None
        ),
        expected_sessions=expected_count,
        opening_window_sessions=opening_count,
        after_close_healthy_sessions=(
            after_close_count
        ),
        verified_backup_sessions=backup_count,
        instruction_signals=audit.signals,
        instruction_outcomes=(
            audit.instruction_outcomes
        ),
        successful_instruction_outcomes=(
            audit.successful_instruction_outcomes
        ),
        opening_window_coverage=opening_rate,
        after_close_coverage=after_close_rate,
        backup_coverage=backup_rate,
        instruction_processing_rate=(
            instruction_rate
        ),
        quote_backed_outcomes=(
            audit.quote_backed_outcomes
        ),
        missed_window_events=(
            audit.missed_window_events
        ),
        stale_instruction_events=(
            audit.stale_instruction_events
        ),
        extended_hours_events=(
            audit.extended_hours_events
        ),
        duplicate_terminal_orders=(
            audit.duplicate_terminal_orders
        ),
        paper_state_valid=(
            environment.paper_state_valid
        ),
        journal_valid=(
            environment.journal_valid
            and audit.journal_valid
        ),
        scheduler_installed=(
            environment.scheduler_installed
        ),
        cron_running=environment.cron_running,
        paper_kill_switch=(
            environment.paper_kill_switch
        ),
        operations_paused=(
            environment.operations_paused
        ),
        live_broker_enabled=(
            config.live_broker_enabled
        ),
        criteria=criteria,
        blockers=blockers,
    )


def _result_text(
    result: QualificationResult,
) -> str:
    lines = [
        "=" * 78,
        "QPX BOT v1.14 — PAPER EXECUTION QUALIFICATION",
        "=" * 78,
        f"Status                       : {result.status}",
        f"Message                      : {result.message}",
        (
            "Qualification begins          : "
            f"{result.first_eligible_session}"
        ),
        (
            "Latest expected session       : "
            f"{result.latest_expected_session}"
        ),
        (
            "Observed/expected sessions    : "
            f"{result.expected_sessions}"
        ),
        (
            "Opening-window sessions       : "
            f"{result.opening_window_sessions}"
        ),
        (
            "Healthy after-close sessions  : "
            f"{result.after_close_healthy_sessions}"
        ),
        (
            "Verified backup sessions      : "
            f"{result.verified_backup_sessions}"
        ),
        (
            "Instruction signals           : "
            f"{result.instruction_signals}"
        ),
        (
            "Instruction outcomes          : "
            f"{result.instruction_outcomes}"
        ),
        (
            "Operational outcomes          : "
            f"{result.successful_instruction_outcomes}"
        ),
        (
            "Opening-window coverage       : "
            f"{result.opening_window_coverage:.2%}"
        ),
        (
            "After-close coverage          : "
            f"{result.after_close_coverage:.2%}"
        ),
        (
            "Backup + drill coverage       : "
            f"{result.backup_coverage:.2%}"
        ),
        (
            "Instruction processing rate   : "
            f"{result.instruction_processing_rate:.2%}"
        ),
        (
            "Extended-hours events         : "
            f"{result.extended_hours_events}"
        ),
        (
            "Missed-window events          : "
            f"{result.missed_window_events}"
        ),
        (
            "Stale-instruction events      : "
            f"{result.stale_instruction_events}"
        ),
        (
            "Duplicate terminal orders     : "
            f"{result.duplicate_terminal_orders}"
        ),
        (
            "Paper state / audit valid     : "
            f"{result.paper_state_valid} / "
            f"{result.journal_valid}"
        ),
        (
            "Scheduler / cron active       : "
            f"{result.scheduler_installed} / "
            f"{result.cron_running}"
        ),
        (
            "Kill switch / ops paused      : "
            f"{result.paper_kill_switch} / "
            f"{result.operations_paused}"
        ),
        (
            "Live broker enabled           : "
            f"{result.live_broker_enabled}"
        ),
        (
            "Unmet criteria                : "
            + (
                ", ".join(result.blockers)
                if result.blockers
                else "None"
            )
        ),
        "=" * 78,
        (
            "Qualification measures operational reliability, "
            "not profitability. No brokerage connection exists."
        ),
    ]
    return "\n".join(lines)


def write_reports(
    *,
    result: QualificationResult,
    state: Mapping[str, Any],
    report_directory: str | Path,
) -> dict[str, Path]:
    directory = Path(
        report_directory
    ).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "latest_qualification.json"
    text_path = directory / "latest_qualification.txt"
    csv_path = directory / "session_ledger.csv"

    _atomic_json(
        json_path,
        asdict(result),
    )
    text_path.write_text(
        _result_text(result) + "\n",
        encoding="utf-8",
    )

    sessions = state.get("sessions", {})

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "session_date",
                "session_checks",
                "opening_window_checks",
                "command_failures",
                "quote_retry_checks",
                "statuses",
                "phases",
                "terminal_outcome",
                "quote_success",
                "extended_hours_seen",
                "after_close_healthy",
                "paper_processed",
                "backup_verified",
                "recovery_drill_passed",
                "audit_valid",
                "paper_state_valid",
                "scheduler_installed",
                "cron_running",
                "paper_kill_switch",
                "operations_paused",
            )
        )

        if isinstance(sessions, Mapping):
            for session_date in sorted(sessions):
                record = sessions[session_date]

                if not isinstance(record, Mapping):
                    continue

                writer.writerow(
                    (
                        session_date,
                        record.get(
                            "session_checks",
                            0,
                        ),
                        record.get(
                            "opening_window_checks",
                            0,
                        ),
                        record.get(
                            "command_failures",
                            0,
                        ),
                        record.get(
                            "quote_retry_checks",
                            0,
                        ),
                        "|".join(
                            record.get(
                                "statuses",
                                [],
                            )
                        ),
                        "|".join(
                            record.get(
                                "phases",
                                [],
                            )
                        ),
                        record.get(
                            "terminal_outcome"
                        ),
                        record.get(
                            "quote_success",
                            False,
                        ),
                        record.get(
                            "extended_hours_seen",
                            False,
                        ),
                        record.get(
                            "after_close_healthy",
                            False,
                        ),
                        record.get(
                            "paper_processed",
                            False,
                        ),
                        record.get(
                            "backup_verified",
                            False,
                        ),
                        record.get(
                            "recovery_drill_passed",
                            False,
                        ),
                        record.get(
                            "audit_valid",
                            False,
                        ),
                        record.get(
                            "paper_state_valid",
                            False,
                        ),
                        record.get(
                            "scheduler_installed",
                            False,
                        ),
                        record.get(
                            "cron_running",
                            False,
                        ),
                        record.get(
                            "paper_kill_switch",
                            False,
                        ),
                        record.get(
                            "operations_paused",
                            False,
                        ),
                    )
                )

    return {
        "json": json_path,
        "text": text_path,
        "csv": csv_path,
    }


def update_and_evaluate(
    *,
    config: QualificationConfig,
    runtime_directory: str | Path,
    report_directory: str | Path,
    paper_runtime: str | Path,
    operations_runtime: str | Path,
    current: datetime | None = None,
) -> QualificationResult:
    state = load_state(
        runtime_directory,
        current=current,
    )
    environment = _environment_snapshot(
        paper_runtime=Path(
            paper_runtime
        ).expanduser().resolve(),
        operations_runtime=Path(
            operations_runtime
        ).expanduser().resolve(),
    )
    metrics = audit_metrics(
        paper_runtime,
        first_eligible_session=date.fromisoformat(
            str(state["first_eligible_session"])
        ),
    )
    result = evaluate_qualification(
        state=state,
        config=config,
        audit=metrics,
        environment=environment,
        current=current,
    )
    save_state(
        runtime_directory,
        state,
    )
    write_reports(
        result=result,
        state=state,
        report_directory=report_directory,
    )
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record and evaluate QPX regular-session paper "
            "execution qualification."
        )
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--initialize",
        action="store_true",
    )
    action.add_argument(
        "--record-session",
        action="store_true",
    )
    action.add_argument(
        "--record-after-close",
        action="store_true",
    )
    action.add_argument(
        "--status",
        action="store_true",
    )
    parser.add_argument(
        "--command-status",
        type=int,
        default=0,
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
        "--operations-runtime-dir",
        default=str(DEFAULT_OPERATIONS_RUNTIME),
    )
    parser.add_argument(
        "--session-report",
        default=str(DEFAULT_SESSION_REPORT),
    )
    parser.add_argument(
        "--operations-report",
        default=str(DEFAULT_OPERATIONS_REPORT),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    config = load_qualification_config(
        args.config
    )
    runtime = Path(
        args.runtime_dir
    ).expanduser().resolve()
    reports = Path(
        args.report_dir
    ).expanduser().resolve()
    paper = Path(
        args.paper_runtime_dir
    ).expanduser().resolve()
    operations = Path(
        args.operations_runtime_dir
    ).expanduser().resolve()

    with qualification_lock(runtime):
        state = load_state(runtime)

        if args.initialize:
            save_state(runtime, state)
        elif args.record_session:
            report = _load_optional_json(
                Path(
                    args.session_report
                ).expanduser().resolve()
            )

            if not report:
                raise RuntimeError(
                    "Session execution report is missing."
                )

            record_session_report(
                state,
                report,
                command_status=args.command_status,
            )
            save_state(runtime, state)
        elif args.record_after_close:
            health = _load_optional_json(
                Path(
                    args.operations_report
                ).expanduser().resolve()
            )

            if not health:
                raise RuntimeError(
                    "Operations health report is missing."
                )

            environment = _environment_snapshot(
                paper_runtime=paper,
                operations_runtime=operations,
            )
            raw_session = (
                health.get(
                    "last_successful_session"
                )
                or health.get(
                    "expected_session"
                )
            )
            session_date = (
                date.fromisoformat(
                    str(raw_session)
                )
                if raw_session
                else latest_completed_session(
                    _market_now()
                )[0]
            )
            backup_verified, drill_passed = (
                _verify_latest_backup_for_session(
                    session_date
                )
            )
            record_after_close_report(
                state,
                command_status=args.command_status,
                health=health,
                environment=environment,
                backup_verified=backup_verified,
                recovery_drill_passed=drill_passed,
            )
            save_state(runtime, state)

        environment = _environment_snapshot(
            paper_runtime=paper,
            operations_runtime=operations,
        )
        metrics = audit_metrics(
            paper,
            first_eligible_session=date.fromisoformat(
                str(
                    state[
                        "first_eligible_session"
                    ]
                )
            ),
        )
        result = evaluate_qualification(
            state=state,
            config=config,
            audit=metrics,
            environment=environment,
        )
        write_reports(
            result=result,
            state=state,
            report_directory=reports,
        )

    print(_result_text(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
