from datetime import date, datetime, time
from pathlib import Path

from qpx_bot.market_calendar import (
    NEW_YORK,
    next_market_session,
)
from qpx_bot.qualification import (
    AuditMetrics,
    EnvironmentSnapshot,
    QualificationConfig,
    evaluate_qualification,
)


config = QualificationConfig(
    schema_version=1,
    minimum_observation_sessions=20,
    minimum_instruction_outcomes=3,
    minimum_opening_window_coverage=0.95,
    minimum_after_close_coverage=0.95,
    minimum_backup_coverage=0.90,
    minimum_instruction_processing_rate=0.95,
    maximum_missed_window_events=0,
    maximum_stale_instruction_events=0,
    maximum_extended_hours_events=0,
    maximum_duplicate_terminal_orders=0,
    live_broker_enabled=False,
)
config.validate()

first = date(2026, 1, 5)
sessions = []
current = first

while len(sessions) < 20:
    sessions.append(current)
    current = next_market_session(current)

state = {
    "schema_version": 1,
    "started_at_utc": "2026-01-05T00:00:00+00:00",
    "first_eligible_session": first.isoformat(),
    "sessions": {},
}

for session_date in sessions:
    state["sessions"][
        session_date.isoformat()
    ] = {
        "session_checks": 3,
        "opening_window_checks": 2,
        "command_failures": 0,
        "quote_retry_checks": 0,
        "statuses": ["NO_PENDING"],
        "phases": ["OPENING_WINDOW"],
        "instruction_order_ids": [],
        "terminal_outcome": None,
        "quote_success": False,
        "extended_hours_seen": False,
        "after_close_seen": True,
        "after_close_healthy": True,
        "paper_processed": True,
        "backup_verified": True,
        "recovery_drill_passed": True,
        "audit_valid": True,
        "paper_state_valid": True,
        "scheduler_installed": True,
        "cron_running": True,
        "paper_kill_switch": False,
        "operations_paused": False,
        "first_seen_utc": "2026-01-05T14:35:00+00:00",
        "last_seen_utc": "2026-01-05T22:30:00+00:00",
    }

audit = AuditMetrics(
    journal_valid=True,
    journal_records=100,
    signals=3,
    instruction_outcomes=3,
    successful_instruction_outcomes=3,
    quote_backed_outcomes=3,
    missed_window_events=0,
    stale_instruction_events=0,
    extended_hours_events=0,
    duplicate_terminal_orders=0,
)
environment = EnvironmentSnapshot(
    paper_state_valid=True,
    journal_valid=True,
    scheduler_installed=True,
    cron_running=True,
    paper_kill_switch=False,
    operations_paused=False,
)
last = sessions[-1]
evaluation_time = datetime.combine(
    last,
    time(18, 0),
    tzinfo=NEW_YORK,
)
result = evaluate_qualification(
    state=state,
    config=config,
    audit=audit,
    environment=environment,
    current=evaluation_time,
)

assert result.status == "PAPER_QUALIFIED"
assert result.expected_sessions == 20
assert result.opening_window_coverage == 1.0
assert result.after_close_coverage == 1.0
assert result.backup_coverage == 1.0
assert result.instruction_processing_rate == 1.0
assert result.live_broker_enabled is False
assert not result.blockers

blocked_audit = AuditMetrics(
    journal_valid=True,
    journal_records=101,
    signals=3,
    instruction_outcomes=3,
    successful_instruction_outcomes=3,
    quote_backed_outcomes=3,
    missed_window_events=0,
    stale_instruction_events=0,
    extended_hours_events=1,
    duplicate_terminal_orders=0,
)
blocked = evaluate_qualification(
    state=state,
    config=config,
    audit=blocked_audit,
    environment=environment,
    current=evaluation_time,
)
assert blocked.status == "BLOCKED"
assert "extended_hours_events" in blocked.blockers

try:
    QualificationConfig(
        **{
            **config.__dict__,
            "live_broker_enabled": True,
        }
    ).validate()
except (AttributeError, ValueError):
    pass
else:
    raise AssertionError(
        "Live broker qualification flag was not rejected."
    )

root = Path(__file__).resolve().parents[1]
session_shell = (
    root / "QPX_TERMUX_SESSION.sh"
).read_text(encoding="utf-8")
daily_shell = (
    root / "QPX_TERMUX_DAILY.sh"
).read_text(encoding="utf-8")

assert (
    "QPX_RUN_QUALIFICATION.py --record-session"
    in " ".join(session_shell.replace("\\\n", " ").split())
)
assert (
    "QPX_RUN_QUALIFICATION.py --record-after-close"
    in " ".join(daily_shell.replace("\\\n", " ").split())
)

print("QPX Bot Paper Execution Qualification PASS")
