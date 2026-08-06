import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.backup import (
    BackupConfig,
    create_backup,
    list_backups,
    restore_backup,
)
from qpx_bot.operations import (
    OperationsState,
    load_operations_state,
    resume_operations,
    resume_restored_paper,
    save_operations_state,
)
from qpx_bot.paper_state import (
    AuditEvent,
    PaperState,
    StateStore,
)


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def paper_state(
    *,
    state_id: str,
    revision: int,
    swing_cash: float = 4_000.0,
) -> PaperState:
    return PaperState(
        state_id=state_id,
        swing_symbol="XLK",
        income_symbol="QDTE",
        start_date=date(2026, 8, 1),
        starting_cash=10_000.0,
        swing_cash=swing_cash,
        tax_reserve_cash=0.0,
        total_contributions=10_000.0,
        realized_pnl=0.0,
        income_shares=150.0,
        income_cost=6_000.0,
        dividends_received=0.0,
        last_processed_date=date(2026, 8, 6),
        revision=revision,
    )


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory)
    operations_runtime = root / "operations_runtime"
    paper_runtime = root / "paper_runtime"
    store = StateStore(paper_runtime)
    store.save(
        paper_state(
            state_id="ownership-test",
            revision=1,
        )
    )
    store.append_events(
        [
            AuditEvent(
                event_id="ownership-initial",
                event_type="INITIALIZED",
                event_date=date(2026, 8, 1),
                details={"mode": "test"},
            )
        ]
    )

    save_operations_state(
        operations_runtime,
        OperationsState(
            consecutive_failures=3,
            paused=True,
            last_status="PAUSED",
            last_message="test circuit breaker",
        ),
    )
    (
        operations_runtime / "OPERATIONS_PAUSED"
    ).write_text(
        "test\n",
        encoding="utf-8",
    )

    store.activate_kill_switch(
        "Independent manual hold",
        owner="manual",
    )
    resumed, message = resume_operations(
        runtime_directory=operations_runtime,
        paper_runtime=paper_runtime,
    )
    assert not resumed
    assert "independent paper kill switch" in message.lower()
    assert store.kill_switch_active()
    details = store.kill_switch_details()
    assert details is not None
    assert details["owner"] == "manual"
    operations_state = load_operations_state(
        operations_runtime
    )
    assert not operations_state.paused
    assert (
        operations_state.last_status
        == "OPERATIONS_RESUMED_PAPER_PAUSED"
    )

    store.deactivate_kill_switch()
    save_operations_state(
        operations_runtime,
        OperationsState(
            consecutive_failures=3,
            paused=True,
            last_status="PAUSED",
            last_message="test circuit breaker",
        ),
    )
    store.activate_kill_switch(
        "QPX automated operations circuit breaker",
        owner="operations_circuit_breaker",
    )
    resumed, message = resume_operations(
        runtime_directory=operations_runtime,
        paper_runtime=paper_runtime,
    )
    assert resumed
    assert "resumed" in message.lower()
    assert not store.kill_switch_active()

    store.kill_switch_path.write_text(
        json.dumps(
            {
                "activated_utc": "2026-08-06T20:00:00+00:00",
                "reason": (
                    "QPX automated operations circuit breaker"
                ),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    legacy = store.kill_switch_details()
    assert legacy is not None
    assert legacy["owner"] == "operations_circuit_breaker"
    resumed, _ = resume_operations(
        runtime_directory=operations_runtime,
        paper_runtime=paper_runtime,
    )
    assert resumed
    assert not store.kill_switch_active()

    store.activate_kill_switch(
        "Restored from verified backup. Manual review required.",
        owner="restore_guard",
    )

    try:
        resume_restored_paper(
            paper_runtime=paper_runtime,
            confirm_resume=False,
        )
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Restore guard cleared without confirmation."
        )

    message = resume_restored_paper(
        paper_runtime=paper_runtime,
        confirm_resume=True,
    )
    assert "restore guard" in message.lower()
    assert not store.kill_switch_active()
    assert store.verify_journal()[2] >= 4


with TemporaryDirectory() as temporary_directory:
    base = Path(temporary_directory)
    root = base / "QPX_ALPHA"
    archive_directory = base / "QPX_ALPHA_BACKUPS"
    backup_runtime = (
        root / "qpx_bot" / "backup_runtime"
    )
    report_directory = (
        root / "reports" / "qpx_backup"
    )
    paper_runtime = (
        root / "qpx_bot" / "paper_runtime"
    )
    store = StateStore(paper_runtime)
    store.save(
        paper_state(
            state_id="restore-test",
            revision=1,
        )
    )
    store.append_events(
        [
            AuditEvent(
                event_id="restore-original",
                event_type="INITIALIZED",
                event_date=date(2026, 8, 1),
                details={"revision": 1},
            )
        ]
    )

    write_json(
        root
        / "qpx_bot"
        / "operations_runtime"
        / "operations_state.json",
        {
            "last_successful_session": "2026-08-06",
            "consecutive_failures": 0,
            "paused": False,
            "last_status": "HEALTHY",
        },
    )
    write_json(
        root
        / "qpx_bot"
        / "selection_runtime"
        / "selection_decision.json",
        {
            "decision_month": "2026-08",
            "selected_symbol": "XLK",
        },
    )
    write_json(
        root / "qpx_bot" / "swing_universe.json",
        {
            "schema_version": 1,
            "candidates": ["XLK", "SPY"],
        },
    )
    write_json(
        root / "qpx_bot" / "operations_config.json",
        {"schema_version": 1},
    )
    write_json(
        root / "qpx_bot" / "backup_config.json",
        {"schema_version": 1},
    )
    write_json(
        root
        / "qpx_bot"
        / "session_execution_config.json",
        {"schema_version": 1},
    )
    write_json(
        root / "qpx_bot" / "qualification_config.json",
        {"schema_version": 1},
    )

    data_directory = root / "qpx_bot" / "data_inputs"
    data_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name in (
        "SWING.csv",
        "QDTE.csv",
        "QDTE_DIVIDENDS.csv",
        "VIX.csv",
    ):
        (data_directory / name).write_text(
            "Date,Value\n2026-08-06,1\n",
            encoding="utf-8",
        )

    write_json(
        data_directory / "DOWNLOAD_MANIFEST.json",
        {"session": "2026-08-06"},
    )

    config = BackupConfig(
        schema_version=1,
        archive_directory_name="QPX_ALPHA_BACKUPS",
        retention_archives=5,
        require_successful_session=True,
        notify_with_termux_api=False,
    )
    original = create_backup(
        project_root=root,
        config=config,
        archive_directory=archive_directory,
        runtime_directory=backup_runtime,
        report_directory=report_directory,
    )
    assert original.created
    assert original.archive_path is not None

    store.save(
        paper_state(
            state_id="restore-test",
            revision=2,
            swing_cash=3_500.0,
        )
    )
    store.append_events(
        [
            AuditEvent(
                event_id="restore-mutation",
                event_type="MUTATED",
                event_date=date(2026, 8, 6),
                details={"revision": 2},
            )
        ]
    )
    write_json(
        root
        / "qpx_bot"
        / "qualification_runtime"
        / "qualification_state.json",
        {
            "schema_version": 1,
            "first_eligible_session": "2026-08-07",
            "sessions": {},
        },
    )

    restored = restore_backup(
        archive_path=original.archive_path,
        project_root=root,
        config=config,
        archive_directory=archive_directory,
        runtime_directory=backup_runtime,
        report_directory=report_directory,
        confirm_restore=True,
    )
    assert restored.paper_revision == 1
    restored_state = store.load()
    assert restored_state.revision == 1
    assert restored_state.swing_cash == 4_000.0
    assert store.verify_journal()[2] == 1
    assert store.kill_switch_active()
    restore_details = store.kill_switch_details()
    assert restore_details is not None
    assert restore_details["owner"] == "restore_guard"
    assert not (
        backup_runtime / "backup.lock"
    ).exists()
    assert len(
        list_backups(archive_directory)
    ) == 2
    assert not (
        root
        / "qpx_bot"
        / "qualification_runtime"
        / "qualification_state.json"
    ).exists()

    resume_restored_paper(
        paper_runtime=paper_runtime,
        confirm_resume=True,
    )
    assert not store.kill_switch_active()
    assert store.verify_journal()[2] == 2

print("QPX Bot Recovery Safety Hardening PASS")
