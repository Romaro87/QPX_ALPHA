#!/usr/bin/env python3
"""Install, test, push, and initialize QPX qualification."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (
            start,
            *start.parents,
        ):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
BACKUP = (
    ROOT
    / "backups"
    / "qpx_execution_qualification_v2"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.14.0"\n',
    "qpx_bot/qualification_config.json": '{\n  "schema_version": 1,\n  "minimum_observation_sessions": 20,\n  "minimum_instruction_outcomes": 3,\n  "minimum_opening_window_coverage": 0.95,\n  "minimum_after_close_coverage": 0.95,\n  "minimum_backup_coverage": 0.90,\n  "minimum_instruction_processing_rate": 0.95,\n  "maximum_missed_window_events": 0,\n  "maximum_stale_instruction_events": 0,\n  "maximum_extended_hours_events": 0,\n  "maximum_duplicate_terminal_orders": 0,\n  "live_broker_enabled": false\n}\n',
    "qpx_bot/qualification.py": '"""Operational qualification ledger for QPX paper execution."""\n\nfrom __future__ import annotations\n\nimport argparse\nimport csv\nimport json\nimport os\nimport shutil\nimport subprocess\nimport time\nfrom contextlib import contextmanager\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, time as clock_time, timezone\nfrom pathlib import Path\nfrom typing import Any, Iterator, Mapping, Sequence\n\nfrom qpx_bot.backup import (\n    default_archive_directory,\n    latest_backup,\n    load_backup_config,\n    verify_backup,\n)\nfrom qpx_bot.market_calendar import (\n    NEW_YORK,\n    is_market_session,\n    latest_completed_session,\n    next_market_session,\n)\nfrom qpx_bot.paper_state import StateStore\nfrom qpx_bot.session_execution import (\n    load_session_execution_config,\n    session_phase,\n)\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_CONFIG_PATH = PACKAGE_DIR / "qualification_config.json"\nDEFAULT_RUNTIME_DIR = PACKAGE_DIR / "qualification_runtime"\nDEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "qpx_qualification"\nDEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_OPERATIONS_RUNTIME = PACKAGE_DIR / "operations_runtime"\nDEFAULT_SESSION_REPORT = (\n    PROJECT_ROOT\n    / "reports"\n    / "qpx_session_execution"\n    / "latest_session_execution.json"\n)\nDEFAULT_OPERATIONS_REPORT = (\n    PROJECT_ROOT\n    / "reports"\n    / "qpx_operations"\n    / "latest_health.json"\n)\nDEFAULT_BACKUP_REPORT = (\n    PROJECT_ROOT\n    / "reports"\n    / "qpx_backup"\n    / "latest_backup.json"\n)\n\n\nTERMINAL_SUCCESS_TYPES = {\n    "ENTRY_FILLED_REGULAR_SESSION",\n    "ENTRY_REJECTED_OPENING_GAP",\n    "ENTRY_REJECTED_POSITION_SIZING",\n}\nTERMINAL_FAILURE_TYPES = {\n    "ENTRY_CANCELLED_MISSED_WINDOW",\n    "ENTRY_CANCELLED_STALE_SESSION",\n}\nTERMINAL_TYPES = (\n    TERMINAL_SUCCESS_TYPES\n    | TERMINAL_FAILURE_TYPES\n)\n\n\n@dataclass(frozen=True, slots=True)\nclass QualificationConfig:\n    schema_version: int\n    minimum_observation_sessions: int\n    minimum_instruction_outcomes: int\n    minimum_opening_window_coverage: float\n    minimum_after_close_coverage: float\n    minimum_backup_coverage: float\n    minimum_instruction_processing_rate: float\n    maximum_missed_window_events: int\n    maximum_stale_instruction_events: int\n    maximum_extended_hours_events: int\n    maximum_duplicate_terminal_orders: int\n    live_broker_enabled: bool\n\n    def validate(self) -> None:\n        if self.schema_version != 1:\n            raise ValueError(\n                "Unsupported qualification configuration."\n            )\n\n        if self.minimum_observation_sessions < 5:\n            raise ValueError(\n                "Qualification requires at least five sessions."\n            )\n\n        if self.minimum_instruction_outcomes < 1:\n            raise ValueError(\n                "At least one instruction outcome is required."\n            )\n\n        for name, value in {\n            "opening coverage": self.minimum_opening_window_coverage,\n            "after-close coverage": self.minimum_after_close_coverage,\n            "backup coverage": self.minimum_backup_coverage,\n            "instruction processing": (\n                self.minimum_instruction_processing_rate\n            ),\n        }.items():\n            if not 0.0 <= value <= 1.0:\n                raise ValueError(\n                    f"{name.capitalize()} must be between zero and one."\n                )\n\n        integer_limits = {\n            "missed-window events": self.maximum_missed_window_events,\n            "stale-instruction events": (\n                self.maximum_stale_instruction_events\n            ),\n            "extended-hours events": (\n                self.maximum_extended_hours_events\n            ),\n            "duplicate terminal orders": (\n                self.maximum_duplicate_terminal_orders\n            ),\n        }\n\n        for name, value in integer_limits.items():\n            if value < 0:\n                raise ValueError(\n                    f"Maximum {name} cannot be negative."\n                )\n\n        if self.live_broker_enabled:\n            raise ValueError(\n                "Live broker mode must remain disabled during "\n                "paper execution qualification."\n            )\n\n\n@dataclass(frozen=True, slots=True)\nclass AuditMetrics:\n    journal_valid: bool\n    journal_records: int\n    signals: int\n    instruction_outcomes: int\n    successful_instruction_outcomes: int\n    quote_backed_outcomes: int\n    missed_window_events: int\n    stale_instruction_events: int\n    extended_hours_events: int\n    duplicate_terminal_orders: int\n\n\n@dataclass(frozen=True, slots=True)\nclass EnvironmentSnapshot:\n    paper_state_valid: bool\n    journal_valid: bool\n    scheduler_installed: bool\n    cron_running: bool\n    paper_kill_switch: bool\n    operations_paused: bool\n\n\n@dataclass(frozen=True, slots=True)\nclass QualificationResult:\n    generated_at_utc: str\n    market_time: str\n    status: str\n    message: str\n    first_eligible_session: str\n    latest_expected_session: str | None\n    expected_sessions: int\n    opening_window_sessions: int\n    after_close_healthy_sessions: int\n    verified_backup_sessions: int\n    instruction_signals: int\n    instruction_outcomes: int\n    successful_instruction_outcomes: int\n    opening_window_coverage: float\n    after_close_coverage: float\n    backup_coverage: float\n    instruction_processing_rate: float\n    quote_backed_outcomes: int\n    missed_window_events: int\n    stale_instruction_events: int\n    extended_hours_events: int\n    duplicate_terminal_orders: int\n    paper_state_valid: bool\n    journal_valid: bool\n    scheduler_installed: bool\n    cron_running: bool\n    paper_kill_switch: bool\n    operations_paused: bool\n    live_broker_enabled: bool\n    criteria: Mapping[str, Mapping[str, Any]]\n    blockers: tuple[str, ...]\n\n\ndef load_qualification_config(\n    filename: str | Path = DEFAULT_CONFIG_PATH,\n) -> QualificationConfig:\n    path = Path(filename).expanduser().resolve()\n    payload = json.loads(\n        path.read_text(encoding="utf-8")\n    )\n\n    if not isinstance(payload, Mapping):\n        raise ValueError(\n            "Qualification configuration must be an object."\n        )\n\n    config = QualificationConfig(\n        schema_version=int(payload["schema_version"]),\n        minimum_observation_sessions=int(\n            payload["minimum_observation_sessions"]\n        ),\n        minimum_instruction_outcomes=int(\n            payload["minimum_instruction_outcomes"]\n        ),\n        minimum_opening_window_coverage=float(\n            payload["minimum_opening_window_coverage"]\n        ),\n        minimum_after_close_coverage=float(\n            payload["minimum_after_close_coverage"]\n        ),\n        minimum_backup_coverage=float(\n            payload["minimum_backup_coverage"]\n        ),\n        minimum_instruction_processing_rate=float(\n            payload["minimum_instruction_processing_rate"]\n        ),\n        maximum_missed_window_events=int(\n            payload["maximum_missed_window_events"]\n        ),\n        maximum_stale_instruction_events=int(\n            payload["maximum_stale_instruction_events"]\n        ),\n        maximum_extended_hours_events=int(\n            payload["maximum_extended_hours_events"]\n        ),\n        maximum_duplicate_terminal_orders=int(\n            payload["maximum_duplicate_terminal_orders"]\n        ),\n        live_broker_enabled=bool(\n            payload["live_broker_enabled"]\n        ),\n    )\n    config.validate()\n    return config\n\n\ndef _atomic_json(\n    path: Path,\n    payload: Mapping[str, Any],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n\n    with temporary.open("w", encoding="utf-8") as file:\n        json.dump(payload, file, indent=2, sort_keys=True)\n        file.write("\\n")\n        file.flush()\n        os.fsync(file.fileno())\n\n    temporary.replace(path)\n\n\ndef _load_optional_json(path: Path) -> Mapping[str, Any]:\n    if not path.exists():\n        return {}\n\n    try:\n        payload = json.loads(\n            path.read_text(encoding="utf-8")\n        )\n    except (OSError, json.JSONDecodeError):\n        return {}\n\n    return payload if isinstance(payload, Mapping) else {}\n\n\ndef _market_now(\n    current: datetime | None = None,\n) -> datetime:\n    moment = current or datetime.now(tz=NEW_YORK)\n\n    if moment.tzinfo is None:\n        return moment.replace(tzinfo=NEW_YORK)\n\n    return moment.astimezone(NEW_YORK)\n\n\ndef qualification_start_session(\n    current: datetime | None = None,\n) -> date:\n    moment = _market_now(current)\n    execution_config = load_session_execution_config()\n    phase = session_phase(moment, execution_config)\n\n    if phase in {\n        "PRE_MARKET",\n        "OPENING_DELAY",\n        "OPENING_WINDOW",\n    }:\n        return moment.date()\n\n    return next_market_session(moment.date())\n\n\ndef _new_state(\n    current: datetime | None = None,\n) -> dict[str, Any]:\n    moment = _market_now(current)\n    return {\n        "schema_version": 1,\n        "started_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "first_eligible_session": (\n            qualification_start_session(\n                moment\n            ).isoformat()\n        ),\n        "sessions": {},\n    }\n\n\ndef load_state(\n    runtime_directory: str | Path,\n    *,\n    current: datetime | None = None,\n) -> dict[str, Any]:\n    directory = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    path = directory / "qualification_state.json"\n\n    if not path.exists():\n        return _new_state(current)\n\n    payload = json.loads(\n        path.read_text(encoding="utf-8")\n    )\n\n    if not isinstance(payload, dict):\n        raise RuntimeError(\n            "Qualification state root must be an object."\n        )\n\n    if int(payload.get("schema_version", -1)) != 1:\n        raise RuntimeError(\n            "Unsupported qualification state version."\n        )\n\n    date.fromisoformat(\n        str(payload["first_eligible_session"])\n    )\n\n    sessions = payload.get("sessions")\n\n    if not isinstance(sessions, dict):\n        raise RuntimeError(\n            "Qualification sessions must be an object."\n        )\n\n    return payload\n\n\ndef save_state(\n    runtime_directory: str | Path,\n    state: Mapping[str, Any],\n) -> Path:\n    directory = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    path = directory / "qualification_state.json"\n    _atomic_json(path, state)\n    return path\n\n\n@contextmanager\ndef qualification_lock(\n    runtime_directory: str | Path,\n    *,\n    stale_after_seconds: float = 21_600.0,\n) -> Iterator[None]:\n    directory = Path(\n        runtime_directory\n    ).expanduser().resolve()\n    directory.mkdir(parents=True, exist_ok=True)\n    lock_path = directory / "qualification.lock"\n\n    for attempt in range(2):\n        try:\n            descriptor = os.open(\n                lock_path,\n                os.O_CREAT | os.O_EXCL | os.O_WRONLY,\n            )\n\n            with os.fdopen(\n                descriptor,\n                "w",\n                encoding="utf-8",\n            ) as file:\n                file.write(\n                    json.dumps(\n                        {\n                            "pid": os.getpid(),\n                            "created_at_utc": datetime.now(\n                                timezone.utc\n                            ).isoformat(),\n                        }\n                    )\n                )\n            break\n        except FileExistsError:\n            age = time.time() - lock_path.stat().st_mtime\n\n            if (\n                attempt == 0\n                and age > stale_after_seconds\n            ):\n                lock_path.unlink(missing_ok=True)\n                continue\n\n            raise RuntimeError(\n                "Another qualification update is active."\n            )\n    else:\n        raise RuntimeError(\n            "Unable to acquire qualification lock."\n        )\n\n    try:\n        yield\n    finally:\n        lock_path.unlink(missing_ok=True)\n\n\ndef _default_session_record() -> dict[str, Any]:\n    return {\n        "session_checks": 0,\n        "opening_window_checks": 0,\n        "command_failures": 0,\n        "quote_retry_checks": 0,\n        "statuses": [],\n        "phases": [],\n        "instruction_order_ids": [],\n        "terminal_outcome": None,\n        "quote_success": False,\n        "extended_hours_seen": False,\n        "after_close_seen": False,\n        "after_close_healthy": False,\n        "paper_processed": False,\n        "backup_verified": False,\n        "recovery_drill_passed": False,\n        "audit_valid": False,\n        "paper_state_valid": False,\n        "scheduler_installed": False,\n        "cron_running": False,\n        "paper_kill_switch": False,\n        "operations_paused": False,\n        "first_seen_utc": None,\n        "last_seen_utc": None,\n    }\n\n\ndef _append_unique(\n    values: list[Any],\n    value: Any,\n) -> None:\n    if value not in values:\n        values.append(value)\n\n\ndef _session_record(\n    state: dict[str, Any],\n    session_date: date,\n) -> dict[str, Any]:\n    sessions = state["sessions"]\n    key = session_date.isoformat()\n    record = sessions.get(key)\n\n    if not isinstance(record, dict):\n        record = _default_session_record()\n        sessions[key] = record\n\n    return record\n\n\ndef record_session_report(\n    state: dict[str, Any],\n    report: Mapping[str, Any],\n    *,\n    command_status: int,\n) -> date:\n    market_time = datetime.fromisoformat(\n        str(report["market_time"])\n    ).astimezone(NEW_YORK)\n    session_date = market_time.date()\n    first_eligible = date.fromisoformat(\n        str(state["first_eligible_session"])\n    )\n\n    if session_date < first_eligible:\n        return session_date\n\n    record = _session_record(\n        state,\n        session_date,\n    )\n    now_utc = datetime.now(\n        timezone.utc\n    ).isoformat()\n\n    if record["first_seen_utc"] is None:\n        record["first_seen_utc"] = now_utc\n\n    record["last_seen_utc"] = now_utc\n    record["session_checks"] += 1\n\n    if command_status != 0:\n        record["command_failures"] += 1\n\n    phase = str(\n        report.get("market_phase", "UNKNOWN")\n    )\n    status = str(\n        report.get("status", "UNKNOWN")\n    )\n    _append_unique(record["phases"], phase)\n    _append_unique(record["statuses"], status)\n\n    if phase == "OPENING_WINDOW":\n        record["opening_window_checks"] += 1\n\n    if status == "QUOTE_RETRY":\n        record["quote_retry_checks"] += 1\n\n    order_id = str(\n        report.get("pending_order_id") or ""\n    ).strip()\n\n    if order_id:\n        _append_unique(\n            record["instruction_order_ids"],\n            order_id,\n        )\n\n    terminal_statuses = {\n        "FILLED",\n        "REJECTED_GAP",\n        "REJECTED_RISK",\n        "CANCELLED_STALE",\n        "CANCELLED_EXPIRED",\n    }\n\n    if status in terminal_statuses:\n        record["terminal_outcome"] = status\n\n    if (\n        report.get("quote_source")\n        and report.get("opening_price") is not None\n    ):\n        record["quote_success"] = True\n\n    if bool(report.get("extended_hours", False)):\n        record["extended_hours_seen"] = True\n\n    if (\n        status == "FILLED"\n        and phase != "OPENING_WINDOW"\n    ):\n        record["extended_hours_seen"] = True\n\n    return session_date\n\n\ndef _crond_running() -> bool:\n    pgrep = shutil.which("pgrep")\n\n    if pgrep is None:\n        return False\n\n    completed = subprocess.run(\n        [pgrep, "-x", "crond"],\n        stdout=subprocess.DEVNULL,\n        stderr=subprocess.DEVNULL,\n        check=False,\n    )\n    return completed.returncode == 0\n\n\ndef _environment_snapshot(\n    *,\n    paper_runtime: Path,\n    operations_runtime: Path,\n) -> EnvironmentSnapshot:\n    store = StateStore(paper_runtime)\n    paper_valid = False\n    journal_valid = False\n\n    try:\n        if store.exists():\n            store.load()\n            paper_valid = True\n            store.verify_journal()\n            journal_valid = True\n    except Exception:\n        paper_valid = False\n        journal_valid = False\n\n    scheduler = _load_optional_json(\n        operations_runtime / "scheduler.json"\n    )\n    operations = _load_optional_json(\n        operations_runtime / "operations_state.json"\n    )\n\n    return EnvironmentSnapshot(\n        paper_state_valid=paper_valid,\n        journal_valid=journal_valid,\n        scheduler_installed=bool(\n            scheduler.get("installed", False)\n        ),\n        cron_running=_crond_running(),\n        paper_kill_switch=(\n            store.kill_switch_active()\n        ),\n        operations_paused=bool(\n            operations.get("paused", False)\n        ),\n    )\n\n\ndef _verify_latest_backup_for_session(\n    session_date: date,\n) -> tuple[bool, bool]:\n    report = _load_optional_json(\n        DEFAULT_BACKUP_REPORT\n    )\n    recovery_drill = bool(\n        report.get("recovery_drill", False)\n    )\n\n    try:\n        backup_config = load_backup_config()\n        directory = default_archive_directory(\n            PROJECT_ROOT,\n            backup_config,\n        )\n        archive = latest_backup(directory)\n        verified = verify_backup(archive)\n        current = (\n            verified.paper_last_processed_date\n            == session_date.isoformat()\n        )\n        return current, recovery_drill\n    except Exception:\n        return False, recovery_drill\n\n\ndef record_after_close_report(\n    state: dict[str, Any],\n    *,\n    command_status: int,\n    health: Mapping[str, Any],\n    environment: EnvironmentSnapshot,\n    backup_verified: bool,\n    recovery_drill_passed: bool,\n    current: datetime | None = None,\n) -> date:\n    moment = _market_now(current)\n    raw_session = (\n        health.get("last_successful_session")\n        or health.get("expected_session")\n    )\n\n    if raw_session:\n        session_date = date.fromisoformat(\n            str(raw_session)\n        )\n    else:\n        session_date = latest_completed_session(\n            moment\n        )[0]\n\n    first_eligible = date.fromisoformat(\n        str(state["first_eligible_session"])\n    )\n\n    if session_date < first_eligible:\n        return session_date\n\n    record = _session_record(\n        state,\n        session_date,\n    )\n    status = str(\n        health.get("status", "UNKNOWN")\n    )\n    successful_session = str(\n        health.get("last_successful_session") or ""\n    )\n    processed = str(\n        health.get("paper_last_processed_bar") or ""\n    )\n\n    record["after_close_seen"] = True\n    record["after_close_healthy"] = (\n        command_status == 0\n        and status in {"HEALTHY", "CURRENT"}\n        and successful_session\n        == session_date.isoformat()\n        and not bool(\n            health.get("stale_data", True)\n        )\n    )\n    record["paper_processed"] = (\n        processed >= session_date.isoformat()\n    )\n    record["backup_verified"] = backup_verified\n    record["recovery_drill_passed"] = (\n        recovery_drill_passed\n    )\n    record["audit_valid"] = (\n        environment.journal_valid\n    )\n    record["paper_state_valid"] = (\n        environment.paper_state_valid\n    )\n    record["scheduler_installed"] = (\n        environment.scheduler_installed\n    )\n    record["cron_running"] = (\n        environment.cron_running\n    )\n    record["paper_kill_switch"] = (\n        environment.paper_kill_switch\n    )\n    record["operations_paused"] = (\n        environment.operations_paused\n    )\n    record["last_seen_utc"] = datetime.now(\n        timezone.utc\n    ).isoformat()\n\n    if record["first_seen_utc"] is None:\n        record["first_seen_utc"] = (\n            record["last_seen_utc"]\n        )\n\n    return session_date\n\n\ndef _audit_records(\n    store: StateStore,\n) -> list[Mapping[str, Any]]:\n    store.verify_journal()\n\n    if not store.journal_path.exists():\n        return []\n\n    records: list[Mapping[str, Any]] = []\n\n    for raw_line in store.journal_path.read_text(\n        encoding="utf-8"\n    ).splitlines():\n        if not raw_line.strip():\n            continue\n\n        payload = json.loads(raw_line)\n\n        if isinstance(payload, Mapping):\n            records.append(payload)\n\n    return records\n\n\ndef audit_metrics(\n    paper_runtime: str | Path,\n    *,\n    first_eligible_session: date,\n) -> AuditMetrics:\n    store = StateStore(paper_runtime)\n\n    try:\n        records = _audit_records(store)\n        journal_valid = True\n    except Exception:\n        return AuditMetrics(\n            journal_valid=False,\n            journal_records=0,\n            signals=0,\n            instruction_outcomes=0,\n            successful_instruction_outcomes=0,\n            quote_backed_outcomes=0,\n            missed_window_events=0,\n            stale_instruction_events=0,\n            extended_hours_events=0,\n            duplicate_terminal_orders=0,\n        )\n\n    signals = 0\n    terminal_order_ids: list[str] = []\n    successful = 0\n    quote_backed = 0\n    missed = 0\n    stale = 0\n    extended = 0\n\n    for record in records:\n        try:\n            event_date = date.fromisoformat(\n                str(record.get("event_date"))\n            )\n        except (TypeError, ValueError):\n            continue\n\n        details = record.get("details")\n\n        if not isinstance(details, Mapping):\n            details = {}\n\n        event_type = str(\n            record.get("event_type", "")\n        )\n\n        scheduled_session = event_date\n\n        if event_type == "ENTRY_SIGNAL":\n            scheduled_session = next_market_session(\n                event_date\n            )\n\n        if scheduled_session < first_eligible_session:\n            continue\n\n        if event_type == "ENTRY_SIGNAL":\n            signals += 1\n\n        if event_type in TERMINAL_TYPES:\n            order_id = str(\n                details.get("order_id", "")\n            ).strip()\n\n            if order_id:\n                terminal_order_ids.append(order_id)\n\n            if event_type in TERMINAL_SUCCESS_TYPES:\n                successful += 1\n\n            if (\n                details.get("quote_source")\n                and details.get(\n                    "opening_reference_price"\n                )\n                is not None\n            ):\n                quote_backed += 1\n\n        if event_type == "ENTRY_CANCELLED_MISSED_WINDOW":\n            missed += 1\n\n        if event_type == "ENTRY_CANCELLED_STALE_SESSION":\n            stale += 1\n\n        if bool(details.get("extended_hours", False)):\n            extended += 1\n\n        if (\n            event_type == "ENTRY_FILLED"\n            and event_date >= first_eligible_session\n        ):\n            extended += 1\n\n        if event_type == "ENTRY_FILLED_REGULAR_SESSION":\n            if (\n                details.get("execution_session")\n                != "REGULAR_SESSION"\n            ):\n                extended += 1\n\n    counts: dict[str, int] = {}\n\n    for order_id in terminal_order_ids:\n        counts[order_id] = (\n            counts.get(order_id, 0) + 1\n        )\n\n    duplicates = sum(\n        max(0, count - 1)\n        for count in counts.values()\n    )\n\n    return AuditMetrics(\n        journal_valid=journal_valid,\n        journal_records=len(records),\n        signals=signals,\n        instruction_outcomes=len(\n            terminal_order_ids\n        ),\n        successful_instruction_outcomes=successful,\n        quote_backed_outcomes=quote_backed,\n        missed_window_events=missed,\n        stale_instruction_events=stale,\n        extended_hours_events=extended,\n        duplicate_terminal_orders=duplicates,\n    )\n\n\ndef _market_sessions_between(\n    start: date,\n    end: date,\n) -> tuple[date, ...]:\n    if end < start:\n        return ()\n\n    sessions: list[date] = []\n    current = start\n\n    while current <= end:\n        if is_market_session(current):\n            sessions.append(current)\n\n        current = current.fromordinal(\n            current.toordinal() + 1\n        )\n\n    return tuple(sessions)\n\n\ndef _criterion(\n    *,\n    current: Any,\n    required: Any,\n    passed: bool,\n) -> dict[str, Any]:\n    return {\n        "current": current,\n        "required": required,\n        "passed": passed,\n    }\n\n\ndef evaluate_qualification(\n    *,\n    state: Mapping[str, Any],\n    config: QualificationConfig,\n    audit: AuditMetrics,\n    environment: EnvironmentSnapshot,\n    current: datetime | None = None,\n) -> QualificationResult:\n    config.validate()\n    moment = _market_now(current)\n    first_eligible = date.fromisoformat(\n        str(state["first_eligible_session"])\n    )\n    latest_session, calendar_status = (\n        latest_completed_session(moment)\n    )\n\n    if calendar_status == "WAITING_FOR_MARKET_DATA":\n        latest_session = latest_completed_session(\n            moment.replace(\n                hour=17,\n                minute=15,\n            )\n        )[0]\n\n        if latest_session == moment.date():\n            latest_session = date.fromordinal(\n                latest_session.toordinal() - 1\n            )\n\n            while not is_market_session(\n                latest_session\n            ):\n                latest_session = date.fromordinal(\n                    latest_session.toordinal() - 1\n                )\n\n    expected = _market_sessions_between(\n        first_eligible,\n        latest_session,\n    )\n    sessions = state.get("sessions", {})\n\n    if not isinstance(sessions, Mapping):\n        sessions = {}\n\n    opening_count = 0\n    after_close_count = 0\n    backup_count = 0\n\n    for session_date in expected:\n        record = sessions.get(\n            session_date.isoformat(),\n            {},\n        )\n\n        if not isinstance(record, Mapping):\n            continue\n\n        if int(\n            record.get(\n                "opening_window_checks",\n                0,\n            )\n        ) > 0:\n            opening_count += 1\n\n        if (\n            bool(\n                record.get(\n                    "after_close_healthy",\n                    False,\n                )\n            )\n            and bool(\n                record.get(\n                    "paper_processed",\n                    False,\n                )\n            )\n            and bool(\n                record.get(\n                    "audit_valid",\n                    False,\n                )\n            )\n            and bool(\n                record.get(\n                    "paper_state_valid",\n                    False,\n                )\n            )\n        ):\n            after_close_count += 1\n\n        if (\n            bool(\n                record.get(\n                    "backup_verified",\n                    False,\n                )\n            )\n            and bool(\n                record.get(\n                    "recovery_drill_passed",\n                    False,\n                )\n            )\n        ):\n            backup_count += 1\n\n    expected_count = len(expected)\n\n    def rate(numerator: int) -> float:\n        return (\n            numerator / expected_count\n            if expected_count\n            else 0.0\n        )\n\n    opening_rate = rate(opening_count)\n    after_close_rate = rate(\n        after_close_count\n    )\n    backup_rate = rate(backup_count)\n    instruction_rate = (\n        audit.successful_instruction_outcomes\n        / audit.instruction_outcomes\n        if audit.instruction_outcomes\n        else 0.0\n    )\n\n    criteria = {\n        "observation_sessions": _criterion(\n            current=expected_count,\n            required=(\n                f">={config.minimum_observation_sessions}"\n            ),\n            passed=(\n                expected_count\n                >= config.minimum_observation_sessions\n            ),\n        ),\n        "instruction_outcomes": _criterion(\n            current=audit.instruction_outcomes,\n            required=(\n                f">={config.minimum_instruction_outcomes}"\n            ),\n            passed=(\n                audit.instruction_outcomes\n                >= config.minimum_instruction_outcomes\n            ),\n        ),\n        "opening_window_coverage": _criterion(\n            current=opening_rate,\n            required=(\n                f">={config.minimum_opening_window_coverage}"\n            ),\n            passed=(\n                opening_rate\n                >= config.minimum_opening_window_coverage\n            ),\n        ),\n        "after_close_coverage": _criterion(\n            current=after_close_rate,\n            required=(\n                f">={config.minimum_after_close_coverage}"\n            ),\n            passed=(\n                after_close_rate\n                >= config.minimum_after_close_coverage\n            ),\n        ),\n        "backup_coverage": _criterion(\n            current=backup_rate,\n            required=(\n                f">={config.minimum_backup_coverage}"\n            ),\n            passed=(\n                backup_rate\n                >= config.minimum_backup_coverage\n            ),\n        ),\n        "instruction_processing_rate": _criterion(\n            current=instruction_rate,\n            required=(\n                f">={config.minimum_instruction_processing_rate}"\n            ),\n            passed=(\n                instruction_rate\n                >= config.minimum_instruction_processing_rate\n            ),\n        ),\n        "missed_window_events": _criterion(\n            current=audit.missed_window_events,\n            required=(\n                f"<={config.maximum_missed_window_events}"\n            ),\n            passed=(\n                audit.missed_window_events\n                <= config.maximum_missed_window_events\n            ),\n        ),\n        "stale_instruction_events": _criterion(\n            current=audit.stale_instruction_events,\n            required=(\n                f"<={config.maximum_stale_instruction_events}"\n            ),\n            passed=(\n                audit.stale_instruction_events\n                <= config.maximum_stale_instruction_events\n            ),\n        ),\n        "extended_hours_events": _criterion(\n            current=audit.extended_hours_events,\n            required=(\n                f"<={config.maximum_extended_hours_events}"\n            ),\n            passed=(\n                audit.extended_hours_events\n                <= config.maximum_extended_hours_events\n            ),\n        ),\n        "duplicate_terminal_orders": _criterion(\n            current=(\n                audit.duplicate_terminal_orders\n            ),\n            required=(\n                "<="\n                f"{config.maximum_duplicate_terminal_orders}"\n            ),\n            passed=(\n                audit.duplicate_terminal_orders\n                <= config.maximum_duplicate_terminal_orders\n            ),\n        ),\n        "paper_state_valid": _criterion(\n            current=environment.paper_state_valid,\n            required=True,\n            passed=environment.paper_state_valid,\n        ),\n        "journal_valid": _criterion(\n            current=(\n                environment.journal_valid\n                and audit.journal_valid\n            ),\n            required=True,\n            passed=(\n                environment.journal_valid\n                and audit.journal_valid\n            ),\n        ),\n        "scheduler_installed": _criterion(\n            current=environment.scheduler_installed,\n            required=True,\n            passed=environment.scheduler_installed,\n        ),\n        "cron_running": _criterion(\n            current=environment.cron_running,\n            required=True,\n            passed=environment.cron_running,\n        ),\n        "paper_kill_switch_off": _criterion(\n            current=environment.paper_kill_switch,\n            required=False,\n            passed=not environment.paper_kill_switch,\n        ),\n        "operations_not_paused": _criterion(\n            current=environment.operations_paused,\n            required=False,\n            passed=not environment.operations_paused,\n        ),\n        "live_broker_disabled": _criterion(\n            current=config.live_broker_enabled,\n            required=False,\n            passed=not config.live_broker_enabled,\n        ),\n    }\n\n    blockers = tuple(\n        name\n        for name, payload in criteria.items()\n        if not bool(payload["passed"])\n    )\n\n    hard_safety_names = {\n        "extended_hours_events",\n        "duplicate_terminal_orders",\n        "paper_state_valid",\n        "journal_valid",\n        "paper_kill_switch_off",\n        "operations_not_paused",\n        "live_broker_disabled",\n    }\n    hard_blocked = any(\n        name in hard_safety_names\n        for name in blockers\n    )\n    sample_ready = (\n        expected_count\n        >= config.minimum_observation_sessions\n        and audit.instruction_outcomes\n        >= config.minimum_instruction_outcomes\n    )\n\n    if hard_blocked:\n        status = "BLOCKED"\n        message = (\n            "A hard safety or integrity requirement failed. "\n            "Broker connectivity remains prohibited."\n        )\n    elif not sample_ready:\n        status = "COLLECTING"\n        message = (\n            "Operational paper evidence is still accumulating. "\n            "Broker connectivity remains prohibited."\n        )\n    elif blockers:\n        status = "NOT_QUALIFIED"\n        message = (\n            "The minimum sample exists, but one or more "\n            "operational criteria failed."\n        )\n    else:\n        status = "PAPER_QUALIFIED"\n        message = (\n            "Paper execution met the configured operational "\n            "criteria. This does not authorize live trading; "\n            "broker connectivity remains disabled."\n        )\n\n    return QualificationResult(\n        generated_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        market_time=moment.isoformat(),\n        status=status,\n        message=message,\n        first_eligible_session=(\n            first_eligible.isoformat()\n        ),\n        latest_expected_session=(\n            latest_session.isoformat()\n            if expected_count\n            else None\n        ),\n        expected_sessions=expected_count,\n        opening_window_sessions=opening_count,\n        after_close_healthy_sessions=(\n            after_close_count\n        ),\n        verified_backup_sessions=backup_count,\n        instruction_signals=audit.signals,\n        instruction_outcomes=(\n            audit.instruction_outcomes\n        ),\n        successful_instruction_outcomes=(\n            audit.successful_instruction_outcomes\n        ),\n        opening_window_coverage=opening_rate,\n        after_close_coverage=after_close_rate,\n        backup_coverage=backup_rate,\n        instruction_processing_rate=(\n            instruction_rate\n        ),\n        quote_backed_outcomes=(\n            audit.quote_backed_outcomes\n        ),\n        missed_window_events=(\n            audit.missed_window_events\n        ),\n        stale_instruction_events=(\n            audit.stale_instruction_events\n        ),\n        extended_hours_events=(\n            audit.extended_hours_events\n        ),\n        duplicate_terminal_orders=(\n            audit.duplicate_terminal_orders\n        ),\n        paper_state_valid=(\n            environment.paper_state_valid\n        ),\n        journal_valid=(\n            environment.journal_valid\n            and audit.journal_valid\n        ),\n        scheduler_installed=(\n            environment.scheduler_installed\n        ),\n        cron_running=environment.cron_running,\n        paper_kill_switch=(\n            environment.paper_kill_switch\n        ),\n        operations_paused=(\n            environment.operations_paused\n        ),\n        live_broker_enabled=(\n            config.live_broker_enabled\n        ),\n        criteria=criteria,\n        blockers=blockers,\n    )\n\n\ndef _result_text(\n    result: QualificationResult,\n) -> str:\n    lines = [\n        "=" * 78,\n        "QPX BOT v1.14 — PAPER EXECUTION QUALIFICATION",\n        "=" * 78,\n        f"Status                       : {result.status}",\n        f"Message                      : {result.message}",\n        (\n            "Qualification begins          : "\n            f"{result.first_eligible_session}"\n        ),\n        (\n            "Latest expected session       : "\n            f"{result.latest_expected_session}"\n        ),\n        (\n            "Observed/expected sessions    : "\n            f"{result.expected_sessions}"\n        ),\n        (\n            "Opening-window sessions       : "\n            f"{result.opening_window_sessions}"\n        ),\n        (\n            "Healthy after-close sessions  : "\n            f"{result.after_close_healthy_sessions}"\n        ),\n        (\n            "Verified backup sessions      : "\n            f"{result.verified_backup_sessions}"\n        ),\n        (\n            "Instruction signals           : "\n            f"{result.instruction_signals}"\n        ),\n        (\n            "Instruction outcomes          : "\n            f"{result.instruction_outcomes}"\n        ),\n        (\n            "Operational outcomes          : "\n            f"{result.successful_instruction_outcomes}"\n        ),\n        (\n            "Opening-window coverage       : "\n            f"{result.opening_window_coverage:.2%}"\n        ),\n        (\n            "After-close coverage          : "\n            f"{result.after_close_coverage:.2%}"\n        ),\n        (\n            "Backup + drill coverage       : "\n            f"{result.backup_coverage:.2%}"\n        ),\n        (\n            "Instruction processing rate   : "\n            f"{result.instruction_processing_rate:.2%}"\n        ),\n        (\n            "Extended-hours events         : "\n            f"{result.extended_hours_events}"\n        ),\n        (\n            "Missed-window events          : "\n            f"{result.missed_window_events}"\n        ),\n        (\n            "Stale-instruction events      : "\n            f"{result.stale_instruction_events}"\n        ),\n        (\n            "Duplicate terminal orders     : "\n            f"{result.duplicate_terminal_orders}"\n        ),\n        (\n            "Paper state / audit valid     : "\n            f"{result.paper_state_valid} / "\n            f"{result.journal_valid}"\n        ),\n        (\n            "Scheduler / cron active       : "\n            f"{result.scheduler_installed} / "\n            f"{result.cron_running}"\n        ),\n        (\n            "Kill switch / ops paused      : "\n            f"{result.paper_kill_switch} / "\n            f"{result.operations_paused}"\n        ),\n        (\n            "Live broker enabled           : "\n            f"{result.live_broker_enabled}"\n        ),\n        (\n            "Unmet criteria                : "\n            + (\n                ", ".join(result.blockers)\n                if result.blockers\n                else "None"\n            )\n        ),\n        "=" * 78,\n        (\n            "Qualification measures operational reliability, "\n            "not profitability. No brokerage connection exists."\n        ),\n    ]\n    return "\\n".join(lines)\n\n\ndef write_reports(\n    *,\n    result: QualificationResult,\n    state: Mapping[str, Any],\n    report_directory: str | Path,\n) -> dict[str, Path]:\n    directory = Path(\n        report_directory\n    ).expanduser().resolve()\n    directory.mkdir(parents=True, exist_ok=True)\n    json_path = directory / "latest_qualification.json"\n    text_path = directory / "latest_qualification.txt"\n    csv_path = directory / "session_ledger.csv"\n\n    _atomic_json(\n        json_path,\n        asdict(result),\n    )\n    text_path.write_text(\n        _result_text(result) + "\\n",\n        encoding="utf-8",\n    )\n\n    sessions = state.get("sessions", {})\n\n    with csv_path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "session_date",\n                "session_checks",\n                "opening_window_checks",\n                "command_failures",\n                "quote_retry_checks",\n                "statuses",\n                "phases",\n                "terminal_outcome",\n                "quote_success",\n                "extended_hours_seen",\n                "after_close_healthy",\n                "paper_processed",\n                "backup_verified",\n                "recovery_drill_passed",\n                "audit_valid",\n                "paper_state_valid",\n                "scheduler_installed",\n                "cron_running",\n                "paper_kill_switch",\n                "operations_paused",\n            )\n        )\n\n        if isinstance(sessions, Mapping):\n            for session_date in sorted(sessions):\n                record = sessions[session_date]\n\n                if not isinstance(record, Mapping):\n                    continue\n\n                writer.writerow(\n                    (\n                        session_date,\n                        record.get(\n                            "session_checks",\n                            0,\n                        ),\n                        record.get(\n                            "opening_window_checks",\n                            0,\n                        ),\n                        record.get(\n                            "command_failures",\n                            0,\n                        ),\n                        record.get(\n                            "quote_retry_checks",\n                            0,\n                        ),\n                        "|".join(\n                            record.get(\n                                "statuses",\n                                [],\n                            )\n                        ),\n                        "|".join(\n                            record.get(\n                                "phases",\n                                [],\n                            )\n                        ),\n                        record.get(\n                            "terminal_outcome"\n                        ),\n                        record.get(\n                            "quote_success",\n                            False,\n                        ),\n                        record.get(\n                            "extended_hours_seen",\n                            False,\n                        ),\n                        record.get(\n                            "after_close_healthy",\n                            False,\n                        ),\n                        record.get(\n                            "paper_processed",\n                            False,\n                        ),\n                        record.get(\n                            "backup_verified",\n                            False,\n                        ),\n                        record.get(\n                            "recovery_drill_passed",\n                            False,\n                        ),\n                        record.get(\n                            "audit_valid",\n                            False,\n                        ),\n                        record.get(\n                            "paper_state_valid",\n                            False,\n                        ),\n                        record.get(\n                            "scheduler_installed",\n                            False,\n                        ),\n                        record.get(\n                            "cron_running",\n                            False,\n                        ),\n                        record.get(\n                            "paper_kill_switch",\n                            False,\n                        ),\n                        record.get(\n                            "operations_paused",\n                            False,\n                        ),\n                    )\n                )\n\n    return {\n        "json": json_path,\n        "text": text_path,\n        "csv": csv_path,\n    }\n\n\ndef update_and_evaluate(\n    *,\n    config: QualificationConfig,\n    runtime_directory: str | Path,\n    report_directory: str | Path,\n    paper_runtime: str | Path,\n    operations_runtime: str | Path,\n    current: datetime | None = None,\n) -> QualificationResult:\n    state = load_state(\n        runtime_directory,\n        current=current,\n    )\n    environment = _environment_snapshot(\n        paper_runtime=Path(\n            paper_runtime\n        ).expanduser().resolve(),\n        operations_runtime=Path(\n            operations_runtime\n        ).expanduser().resolve(),\n    )\n    metrics = audit_metrics(\n        paper_runtime,\n        first_eligible_session=date.fromisoformat(\n            str(state["first_eligible_session"])\n        ),\n    )\n    result = evaluate_qualification(\n        state=state,\n        config=config,\n        audit=metrics,\n        environment=environment,\n        current=current,\n    )\n    save_state(\n        runtime_directory,\n        state,\n    )\n    write_reports(\n        result=result,\n        state=state,\n        report_directory=report_directory,\n    )\n    return result\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Record and evaluate QPX regular-session paper "\n            "execution qualification."\n        )\n    )\n    action = parser.add_mutually_exclusive_group()\n    action.add_argument(\n        "--initialize",\n        action="store_true",\n    )\n    action.add_argument(\n        "--record-session",\n        action="store_true",\n    )\n    action.add_argument(\n        "--record-after-close",\n        action="store_true",\n    )\n    action.add_argument(\n        "--status",\n        action="store_true",\n    )\n    parser.add_argument(\n        "--command-status",\n        type=int,\n        default=0,\n    )\n    parser.add_argument(\n        "--config",\n        default=str(DEFAULT_CONFIG_PATH),\n    )\n    parser.add_argument(\n        "--runtime-dir",\n        default=str(DEFAULT_RUNTIME_DIR),\n    )\n    parser.add_argument(\n        "--report-dir",\n        default=str(DEFAULT_REPORT_DIR),\n    )\n    parser.add_argument(\n        "--paper-runtime-dir",\n        default=str(DEFAULT_PAPER_RUNTIME),\n    )\n    parser.add_argument(\n        "--operations-runtime-dir",\n        default=str(DEFAULT_OPERATIONS_RUNTIME),\n    )\n    parser.add_argument(\n        "--session-report",\n        default=str(DEFAULT_SESSION_REPORT),\n    )\n    parser.add_argument(\n        "--operations-report",\n        default=str(DEFAULT_OPERATIONS_REPORT),\n    )\n    return parser\n\n\ndef main(\n    argv: Sequence[str] | None = None,\n) -> int:\n    args = _parser().parse_args(argv)\n    config = load_qualification_config(\n        args.config\n    )\n    runtime = Path(\n        args.runtime_dir\n    ).expanduser().resolve()\n    reports = Path(\n        args.report_dir\n    ).expanduser().resolve()\n    paper = Path(\n        args.paper_runtime_dir\n    ).expanduser().resolve()\n    operations = Path(\n        args.operations_runtime_dir\n    ).expanduser().resolve()\n\n    with qualification_lock(runtime):\n        state = load_state(runtime)\n\n        if args.initialize:\n            save_state(runtime, state)\n        elif args.record_session:\n            report = _load_optional_json(\n                Path(\n                    args.session_report\n                ).expanduser().resolve()\n            )\n\n            if not report:\n                raise RuntimeError(\n                    "Session execution report is missing."\n                )\n\n            record_session_report(\n                state,\n                report,\n                command_status=args.command_status,\n            )\n            save_state(runtime, state)\n        elif args.record_after_close:\n            health = _load_optional_json(\n                Path(\n                    args.operations_report\n                ).expanduser().resolve()\n            )\n\n            if not health:\n                raise RuntimeError(\n                    "Operations health report is missing."\n                )\n\n            environment = _environment_snapshot(\n                paper_runtime=paper,\n                operations_runtime=operations,\n            )\n            raw_session = (\n                health.get(\n                    "last_successful_session"\n                )\n                or health.get(\n                    "expected_session"\n                )\n            )\n            session_date = (\n                date.fromisoformat(\n                    str(raw_session)\n                )\n                if raw_session\n                else latest_completed_session(\n                    _market_now()\n                )[0]\n            )\n            backup_verified, drill_passed = (\n                _verify_latest_backup_for_session(\n                    session_date\n                )\n            )\n            record_after_close_report(\n                state,\n                command_status=args.command_status,\n                health=health,\n                environment=environment,\n                backup_verified=backup_verified,\n                recovery_drill_passed=drill_passed,\n            )\n            save_state(runtime, state)\n\n        environment = _environment_snapshot(\n            paper_runtime=paper,\n            operations_runtime=operations,\n        )\n        metrics = audit_metrics(\n            paper,\n            first_eligible_session=date.fromisoformat(\n                str(\n                    state[\n                        "first_eligible_session"\n                    ]\n                )\n            ),\n        )\n        result = evaluate_qualification(\n            state=state,\n            config=config,\n            audit=metrics,\n            environment=environment,\n        )\n        write_reports(\n            result=result,\n            state=state,\n            report_directory=reports,\n        )\n\n    print(_result_text(result))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_QUALIFICATION.py": '#!/usr/bin/env python3\n"""Record and report QPX paper execution qualification."""\n\nfrom qpx_bot.qualification import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_execution_qualification.py": 'from datetime import date, datetime, time\nfrom pathlib import Path\n\nfrom qpx_bot.market_calendar import (\n    NEW_YORK,\n    next_market_session,\n)\nfrom qpx_bot.qualification import (\n    AuditMetrics,\n    EnvironmentSnapshot,\n    QualificationConfig,\n    evaluate_qualification,\n)\n\n\nconfig = QualificationConfig(\n    schema_version=1,\n    minimum_observation_sessions=20,\n    minimum_instruction_outcomes=3,\n    minimum_opening_window_coverage=0.95,\n    minimum_after_close_coverage=0.95,\n    minimum_backup_coverage=0.90,\n    minimum_instruction_processing_rate=0.95,\n    maximum_missed_window_events=0,\n    maximum_stale_instruction_events=0,\n    maximum_extended_hours_events=0,\n    maximum_duplicate_terminal_orders=0,\n    live_broker_enabled=False,\n)\nconfig.validate()\n\nfirst = date(2026, 1, 5)\nsessions = []\ncurrent = first\n\nwhile len(sessions) < 20:\n    sessions.append(current)\n    current = next_market_session(current)\n\nstate = {\n    "schema_version": 1,\n    "started_at_utc": "2026-01-05T00:00:00+00:00",\n    "first_eligible_session": first.isoformat(),\n    "sessions": {},\n}\n\nfor session_date in sessions:\n    state["sessions"][\n        session_date.isoformat()\n    ] = {\n        "session_checks": 3,\n        "opening_window_checks": 2,\n        "command_failures": 0,\n        "quote_retry_checks": 0,\n        "statuses": ["NO_PENDING"],\n        "phases": ["OPENING_WINDOW"],\n        "instruction_order_ids": [],\n        "terminal_outcome": None,\n        "quote_success": False,\n        "extended_hours_seen": False,\n        "after_close_seen": True,\n        "after_close_healthy": True,\n        "paper_processed": True,\n        "backup_verified": True,\n        "recovery_drill_passed": True,\n        "audit_valid": True,\n        "paper_state_valid": True,\n        "scheduler_installed": True,\n        "cron_running": True,\n        "paper_kill_switch": False,\n        "operations_paused": False,\n        "first_seen_utc": "2026-01-05T14:35:00+00:00",\n        "last_seen_utc": "2026-01-05T22:30:00+00:00",\n    }\n\naudit = AuditMetrics(\n    journal_valid=True,\n    journal_records=100,\n    signals=3,\n    instruction_outcomes=3,\n    successful_instruction_outcomes=3,\n    quote_backed_outcomes=3,\n    missed_window_events=0,\n    stale_instruction_events=0,\n    extended_hours_events=0,\n    duplicate_terminal_orders=0,\n)\nenvironment = EnvironmentSnapshot(\n    paper_state_valid=True,\n    journal_valid=True,\n    scheduler_installed=True,\n    cron_running=True,\n    paper_kill_switch=False,\n    operations_paused=False,\n)\nlast = sessions[-1]\nevaluation_time = datetime.combine(\n    last,\n    time(18, 0),\n    tzinfo=NEW_YORK,\n)\nresult = evaluate_qualification(\n    state=state,\n    config=config,\n    audit=audit,\n    environment=environment,\n    current=evaluation_time,\n)\n\nassert result.status == "PAPER_QUALIFIED"\nassert result.expected_sessions == 20\nassert result.opening_window_coverage == 1.0\nassert result.after_close_coverage == 1.0\nassert result.backup_coverage == 1.0\nassert result.instruction_processing_rate == 1.0\nassert result.live_broker_enabled is False\nassert not result.blockers\n\nblocked_audit = AuditMetrics(\n    journal_valid=True,\n    journal_records=101,\n    signals=3,\n    instruction_outcomes=3,\n    successful_instruction_outcomes=3,\n    quote_backed_outcomes=3,\n    missed_window_events=0,\n    stale_instruction_events=0,\n    extended_hours_events=1,\n    duplicate_terminal_orders=0,\n)\nblocked = evaluate_qualification(\n    state=state,\n    config=config,\n    audit=blocked_audit,\n    environment=environment,\n    current=evaluation_time,\n)\nassert blocked.status == "BLOCKED"\nassert "extended_hours_events" in blocked.blockers\n\ntry:\n    QualificationConfig(\n        **{\n            **config.__dict__,\n            "live_broker_enabled": True,\n        }\n    ).validate()\nexcept (AttributeError, ValueError):\n    pass\nelse:\n    raise AssertionError(\n        "Live broker qualification flag was not rejected."\n    )\n\nroot = Path(__file__).resolve().parents[1]\nsession_shell = (\n    root / "QPX_TERMUX_SESSION.sh"\n).read_text(encoding="utf-8")\ndaily_shell = (\n    root / "QPX_TERMUX_DAILY.sh"\n).read_text(encoding="utf-8")\n\nassert (\n    "QPX_RUN_QUALIFICATION.py --record-session"\n    in " ".join(session_shell.replace("\\\\\\n", " ").split())\n)\nassert (\n    "QPX_RUN_QUALIFICATION.py --record-after-close"\n    in " ".join(daily_shell.replace("\\\\\\n", " ").split())\n)\n\nprint("QPX Bot Paper Execution Qualification PASS")\n',
    "qpx_bot/EXECUTION_QUALIFICATION_README.txt": 'QPX PAPER EXECUTION QUALIFICATION\n=================================\n\nPurpose\n-------\n\nThis milestone is an operational reliability gate between simulated\npaper execution and any future broker sandbox work.\n\nIt does not measure profitability and it does not enable a broker.\n\nThe qualification ledger records:\n\n- regular-session scheduler heartbeats;\n- opening-window coverage;\n- after-close processing health;\n- paper-state checksum validity;\n- audit-journal hash-chain validity;\n- verified backup and recovery-drill coverage;\n- staged instruction outcomes;\n- quote-backed regular-session outcomes;\n- stale or missed instructions;\n- duplicate terminal order IDs;\n- any extended-hours execution evidence;\n- kill-switch, circuit-breaker, scheduler, and cron status.\n\nDefault qualification sample\n----------------------------\n\n- at least 20 completed market sessions;\n- at least 3 staged instruction outcomes;\n- at least 95% opening-window coverage;\n- at least 95% healthy after-close coverage;\n- at least 90% verified backup + drill coverage;\n- at least 95% operational instruction processing;\n- zero missed-window cancellations;\n- zero stale-instruction cancellations;\n- zero extended-hours events;\n- zero duplicate terminal order outcomes.\n\nThe result can be:\n\nCOLLECTING\n    The minimum evidence sample has not accumulated.\n\nBLOCKED\n    A hard safety or integrity rule failed.\n\nNOT_QUALIFIED\n    The minimum sample exists, but reliability criteria failed.\n\nPAPER_QUALIFIED\n    The paper execution layer met the configured operational criteria.\n\nPAPER_QUALIFIED still does not authorize live trading. The\nqualification configuration requires live_broker_enabled=false.\n\nCommands\n--------\n\nShow status:\n\npython QPX_RUN_QUALIFICATION.py --status\n\nInitialize without changing the paper account:\n\npython QPX_RUN_QUALIFICATION.py --initialize\n\nReports\n-------\n\nreports/qpx_qualification/latest_qualification.txt\nreports/qpx_qualification/latest_qualification.json\nreports/qpx_qualification/session_ledger.csv\n\nThe Termux regular-session and after-close wrappers update the ledger\nautomatically.\n',
}

PATCHES = {
    "QPX_TERMUX_SESSION.sh": [
        (
            'cd "${ROOT}" || exit 1\n"${PYTHON_BIN}" QPX_RUN_REGULAR_SESSION.py >>"${LOG_FILE}" 2>&1\nstatus=$?\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
            'cd "${ROOT}" || exit 1\n"${PYTHON_BIN}" QPX_RUN_REGULAR_SESSION.py >>"${LOG_FILE}" 2>&1\nstatus=$?\n\n"${PYTHON_BIN}" QPX_RUN_QUALIFICATION.py \\\n    --record-session \\\n    --command-status "${status}" >>"${LOG_FILE}" 2>&1\nqualification_status=$?\n\nif [ "${status}" -eq 0 ] \\\n    && [ "${qualification_status}" -ne 0 ]; then\n    status="${qualification_status}"\nfi\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
        )
    ],
    "QPX_TERMUX_DAILY.sh": [
        (
            'fi\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
            'fi\n\n"${PYTHON_BIN}" QPX_RUN_QUALIFICATION.py \\\n    --record-after-close \\\n    --command-status "${status}" >>"${LOG_FILE}" 2>&1\nqualification_status=$?\n\nif [ "${status}" -eq 0 ] \\\n    && [ "${qualification_status}" -ne 0 ]; then\n    status="${qualification_status}"\nfi\n\nif [ "${wake_locked}" -eq 1 ] \\\n',
        )
    ],
    "qpx_bot/backup.py": [
        (
            '"qpx_bot/session_execution_config.json",\n',
            '"qpx_bot/session_execution_config.json",\n"qpx_bot/qualification_config.json",\n',
        ),
        (
            '"reports/qpx_session_execution/latest_session_execution.json",\n',
            '"reports/qpx_session_execution/latest_session_execution.json",\n"reports/qpx_qualification/latest_qualification.txt",\n"reports/qpx_qualification/latest_qualification.json",\n"reports/qpx_qualification/session_ledger.csv",\n',
        ),
        (
            '"qpx_bot/operations_runtime",\n',
            '"qpx_bot/operations_runtime",\n"qpx_bot/qualification_runtime",\n',
        ),
        (
            '"backup.lock",\n',
            '"backup.lock",\n"qualification.lock",\n',
        ),
    ],
}

GITIGNORE_APPEND = '# QPX paper execution qualification runtime and reports\nqpx_bot/qualification_runtime/\nreports/qpx_qualification/\n'
TARGETS = [*FILES, *PATCHES, ".gitignore"]
originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(
        command,
        cwd=ROOT,
        check=True,
    )


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            relative,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )
        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )

        if (
            worktree.returncode != 0
            or staged.returncode != 0
        ):
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and "
            "were not overwritten:\n"
            + "\n".join(changed)
        )


def validate_patch_markers() -> None:
    failures: list[str] = []

    for relative, replacements in PATCHES.items():
        path = ROOT / relative

        if not path.exists():
            failures.append(
                f"{relative}: file not found"
            )
            continue

        content = path.read_text(
            encoding="utf-8"
        )

        for old, new in replacements:
            if old in content:
                content = content.replace(
                    old,
                    new,
                    1,
                )
            elif new in content:
                continue
            else:
                failures.append(
                    f"{relative}: expected marker not found\n{old}"
                )
                break

    if failures:
        raise RuntimeError(
            "Patch preflight failed before any file changed:\n\n"
            + "\n\n".join(failures)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            path,
            backup_path,
        )


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(
                content
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def patch_files() -> None:
    for relative, replacements in PATCHES.items():
        preserve(relative)
        path = ROOT / relative
        content = path.read_text(
            encoding="utf-8"
        )

        for old, new in replacements:
            if old in content:
                content = content.replace(
                    old,
                    new,
                    1,
                )
            elif new in content:
                continue
            else:
                raise RuntimeError(
                    f"Expected patch marker not found in "
                    f"{relative}:\n{old}"
                )

        path.write_text(
            content,
            encoding="utf-8",
        )

        if path.suffix == ".sh":
            path.chmod(0o700)

        print(f"Updated: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(
        encoding="utf-8"
    )
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print(
        "Restoring previous target files..."
    )

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(
                Path(__file__)
                .resolve()
                .relative_to(ROOT)
            )
        )
    except ValueError:
        pass

    run([
        "git",
        "add",
        "--",
        *paths,
    ])

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print(
            "Execution qualification is already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Implement QPX Bot paper "
            "execution qualification"
        ),
    ])

    branch = subprocess.check_output(
        [
            "git",
            "branch",
            "--show-current",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run([
        "git",
        "push",
        "origin",
        branch,
    ])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — PAPER EXECUTION "
        "QUALIFICATION INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()
    patch_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_execution_qualification"
            ),
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print(
        "Initializing the qualification ledger..."
    )
    print()

    try:
        run([
            sys.executable,
            "QPX_RUN_QUALIFICATION.py",
            "--initialize",
        ])
    except Exception:
        print()
        print("=" * 78)
        print(
            "QPX QUALIFICATION CODE: "
            "INSTALLED AND PUSHED"
        )
        print(
            "LEDGER INITIALIZATION: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_QUALIFICATION.py "
            "--initialize"
        )
        return 2

    print()
    print("=" * 78)
    print(
        "QPX PAPER EXECUTION QUALIFICATION: COMPLETE"
    )
    print("=" * 78)
    print(
        "The ledger is collecting operational evidence. "
        "Live broker connectivity remains disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
