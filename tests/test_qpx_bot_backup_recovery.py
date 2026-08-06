import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.backup import (
    BackupConfig,
    collect_source_files,
    create_backup,
    list_backups,
    recovery_drill,
    verify_backup,
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


with TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory) / "QPX_ALPHA"
    archive_directory = (
        Path(temporary_directory)
        / "QPX_ALPHA_BACKUPS"
    )
    runtime_directory = (
        root / "qpx_bot" / "backup_runtime"
    )
    report_directory = (
        root / "reports" / "qpx_backup"
    )
    paper_directory = (
        root / "qpx_bot" / "paper_runtime"
    )
    store = StateStore(paper_directory)
    state = PaperState(
        state_id="test-state",
        swing_symbol="XLK",
        income_symbol="QDTE",
        start_date=date(2026, 8, 1),
        starting_cash=10_000.0,
        swing_cash=4_000.0,
        tax_reserve_cash=0.0,
        total_contributions=10_000.0,
        realized_pnl=0.0,
        income_shares=100.0,
        income_cost=4_000.0,
        dividends_received=0.0,
        last_processed_date=date(2026, 8, 6),
        revision=2,
    )
    store.save(state)
    store.append_events(
        [
            AuditEvent(
                event_id="initial-test-event",
                event_type="INITIALIZED",
                event_date=date(2026, 8, 1),
                details={"mode": "test"},
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
        {"schema_version": 1, "candidates": ["XLK", "SPY"]},
    )
    write_json(
        root / "qpx_bot" / "operations_config.json",
        {"schema_version": 1},
    )
    write_json(
        root / "qpx_bot" / "backup_config.json",
        {"schema_version": 1},
    )

    data_directory = root / "qpx_bot" / "data_inputs"
    data_directory.mkdir(parents=True, exist_ok=True)

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
        retention_archives=3,
        require_successful_session=True,
        notify_with_termux_api=False,
    )
    config.validate()

    files = collect_source_files(root)
    assert any(
        path.name == "paper_state.json"
        for path in files
    )
    assert not any(
        path.name.endswith(".lock")
        for path in files
    )

    result = create_backup(
        project_root=root,
        config=config,
        archive_directory=archive_directory,
        runtime_directory=runtime_directory,
        report_directory=report_directory,
    )
    assert result.created
    assert result.archive_path is not None
    assert result.archive_path.exists()
    assert result.archive_path.with_suffix(
        ".zip.sha256"
    ).exists()

    verification = verify_backup(
        result.archive_path
    )
    assert verification.paper_state_id == "test-state"
    assert verification.paper_revision == 2
    assert verification.journal_records == 1
    assert verification.files >= 10

    drill = recovery_drill(
        result.archive_path
    )
    assert drill.identity == verification.identity

    duplicate = create_backup(
        project_root=root,
        config=config,
        archive_directory=archive_directory,
        runtime_directory=runtime_directory,
        report_directory=report_directory,
    )
    assert not duplicate.created
    assert duplicate.status == "CURRENT"
    assert duplicate.archive_path == result.archive_path
    assert len(list_backups(archive_directory)) == 1

    corrupted = archive_directory / "corrupted.zip"
    corrupted.write_bytes(
        result.archive_path.read_bytes()[:100]
    )

    try:
        verify_backup(corrupted)
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "Truncated backup was not rejected."
        )

print("QPX Bot Verified Backup and Recovery PASS")
