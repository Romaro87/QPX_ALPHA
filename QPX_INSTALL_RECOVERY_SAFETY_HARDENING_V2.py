#!/usr/bin/env python3
"""Install, test, push, and verify QPX recovery safety hardening."""

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
    / "qpx_recovery_safety_hardening_v2"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.15.0"\n',
    "tests/test_qpx_bot_recovery_safety_hardening.py": 'import json\nfrom datetime import date\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.backup import (\n    BackupConfig,\n    create_backup,\n    list_backups,\n    restore_backup,\n)\nfrom qpx_bot.operations import (\n    OperationsState,\n    load_operations_state,\n    resume_operations,\n    resume_restored_paper,\n    save_operations_state,\n)\nfrom qpx_bot.paper_state import (\n    AuditEvent,\n    PaperState,\n    StateStore,\n)\n\n\ndef write_json(path: Path, payload) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    path.write_text(\n        json.dumps(payload, indent=2) + "\\n",\n        encoding="utf-8",\n    )\n\n\ndef paper_state(\n    *,\n    state_id: str,\n    revision: int,\n    swing_cash: float = 4_000.0,\n) -> PaperState:\n    return PaperState(\n        state_id=state_id,\n        swing_symbol="XLK",\n        income_symbol="QDTE",\n        start_date=date(2026, 8, 1),\n        starting_cash=10_000.0,\n        swing_cash=swing_cash,\n        tax_reserve_cash=0.0,\n        total_contributions=10_000.0,\n        realized_pnl=0.0,\n        income_shares=150.0,\n        income_cost=6_000.0,\n        dividends_received=0.0,\n        last_processed_date=date(2026, 8, 6),\n        revision=revision,\n    )\n\n\nwith TemporaryDirectory() as temporary_directory:\n    root = Path(temporary_directory)\n    operations_runtime = root / "operations_runtime"\n    paper_runtime = root / "paper_runtime"\n    store = StateStore(paper_runtime)\n    store.save(\n        paper_state(\n            state_id="ownership-test",\n            revision=1,\n        )\n    )\n    store.append_events(\n        [\n            AuditEvent(\n                event_id="ownership-initial",\n                event_type="INITIALIZED",\n                event_date=date(2026, 8, 1),\n                details={"mode": "test"},\n            )\n        ]\n    )\n\n    save_operations_state(\n        operations_runtime,\n        OperationsState(\n            consecutive_failures=3,\n            paused=True,\n            last_status="PAUSED",\n            last_message="test circuit breaker",\n        ),\n    )\n    (\n        operations_runtime / "OPERATIONS_PAUSED"\n    ).write_text(\n        "test\\n",\n        encoding="utf-8",\n    )\n\n    store.activate_kill_switch(\n        "Independent manual hold",\n        owner="manual",\n    )\n    resumed, message = resume_operations(\n        runtime_directory=operations_runtime,\n        paper_runtime=paper_runtime,\n    )\n    assert not resumed\n    assert "independent paper kill switch" in message.lower()\n    assert store.kill_switch_active()\n    details = store.kill_switch_details()\n    assert details is not None\n    assert details["owner"] == "manual"\n    operations_state = load_operations_state(\n        operations_runtime\n    )\n    assert not operations_state.paused\n    assert (\n        operations_state.last_status\n        == "OPERATIONS_RESUMED_PAPER_PAUSED"\n    )\n\n    store.deactivate_kill_switch()\n    save_operations_state(\n        operations_runtime,\n        OperationsState(\n            consecutive_failures=3,\n            paused=True,\n            last_status="PAUSED",\n            last_message="test circuit breaker",\n        ),\n    )\n    store.activate_kill_switch(\n        "QPX automated operations circuit breaker",\n        owner="operations_circuit_breaker",\n    )\n    resumed, message = resume_operations(\n        runtime_directory=operations_runtime,\n        paper_runtime=paper_runtime,\n    )\n    assert resumed\n    assert "resumed" in message.lower()\n    assert not store.kill_switch_active()\n\n    store.kill_switch_path.write_text(\n        json.dumps(\n            {\n                "activated_utc": "2026-08-06T20:00:00+00:00",\n                "reason": (\n                    "QPX automated operations circuit breaker"\n                ),\n            }\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    legacy = store.kill_switch_details()\n    assert legacy is not None\n    assert legacy["owner"] == "operations_circuit_breaker"\n    resumed, _ = resume_operations(\n        runtime_directory=operations_runtime,\n        paper_runtime=paper_runtime,\n    )\n    assert resumed\n    assert not store.kill_switch_active()\n\n    store.activate_kill_switch(\n        "Restored from verified backup. Manual review required.",\n        owner="restore_guard",\n    )\n\n    try:\n        resume_restored_paper(\n            paper_runtime=paper_runtime,\n            confirm_resume=False,\n        )\n    except RuntimeError:\n        pass\n    else:\n        raise AssertionError(\n            "Restore guard cleared without confirmation."\n        )\n\n    message = resume_restored_paper(\n        paper_runtime=paper_runtime,\n        confirm_resume=True,\n    )\n    assert "restore guard" in message.lower()\n    assert not store.kill_switch_active()\n    assert store.verify_journal()[2] >= 4\n\n\nwith TemporaryDirectory() as temporary_directory:\n    base = Path(temporary_directory)\n    root = base / "QPX_ALPHA"\n    archive_directory = base / "QPX_ALPHA_BACKUPS"\n    backup_runtime = (\n        root / "qpx_bot" / "backup_runtime"\n    )\n    report_directory = (\n        root / "reports" / "qpx_backup"\n    )\n    paper_runtime = (\n        root / "qpx_bot" / "paper_runtime"\n    )\n    store = StateStore(paper_runtime)\n    store.save(\n        paper_state(\n            state_id="restore-test",\n            revision=1,\n        )\n    )\n    store.append_events(\n        [\n            AuditEvent(\n                event_id="restore-original",\n                event_type="INITIALIZED",\n                event_date=date(2026, 8, 1),\n                details={"revision": 1},\n            )\n        ]\n    )\n\n    write_json(\n        root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations_state.json",\n        {\n            "last_successful_session": "2026-08-06",\n            "consecutive_failures": 0,\n            "paused": False,\n            "last_status": "HEALTHY",\n        },\n    )\n    write_json(\n        root\n        / "qpx_bot"\n        / "selection_runtime"\n        / "selection_decision.json",\n        {\n            "decision_month": "2026-08",\n            "selected_symbol": "XLK",\n        },\n    )\n    write_json(\n        root / "qpx_bot" / "swing_universe.json",\n        {\n            "schema_version": 1,\n            "candidates": ["XLK", "SPY"],\n        },\n    )\n    write_json(\n        root / "qpx_bot" / "operations_config.json",\n        {"schema_version": 1},\n    )\n    write_json(\n        root / "qpx_bot" / "backup_config.json",\n        {"schema_version": 1},\n    )\n    write_json(\n        root\n        / "qpx_bot"\n        / "session_execution_config.json",\n        {"schema_version": 1},\n    )\n    write_json(\n        root / "qpx_bot" / "qualification_config.json",\n        {"schema_version": 1},\n    )\n\n    data_directory = root / "qpx_bot" / "data_inputs"\n    data_directory.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n\n    for name in (\n        "SWING.csv",\n        "QDTE.csv",\n        "QDTE_DIVIDENDS.csv",\n        "VIX.csv",\n    ):\n        (data_directory / name).write_text(\n            "Date,Value\\n2026-08-06,1\\n",\n            encoding="utf-8",\n        )\n\n    write_json(\n        data_directory / "DOWNLOAD_MANIFEST.json",\n        {"session": "2026-08-06"},\n    )\n\n    config = BackupConfig(\n        schema_version=1,\n        archive_directory_name="QPX_ALPHA_BACKUPS",\n        retention_archives=5,\n        require_successful_session=True,\n        notify_with_termux_api=False,\n    )\n    original = create_backup(\n        project_root=root,\n        config=config,\n        archive_directory=archive_directory,\n        runtime_directory=backup_runtime,\n        report_directory=report_directory,\n    )\n    assert original.created\n    assert original.archive_path is not None\n\n    store.save(\n        paper_state(\n            state_id="restore-test",\n            revision=2,\n            swing_cash=3_500.0,\n        )\n    )\n    store.append_events(\n        [\n            AuditEvent(\n                event_id="restore-mutation",\n                event_type="MUTATED",\n                event_date=date(2026, 8, 6),\n                details={"revision": 2},\n            )\n        ]\n    )\n    write_json(\n        root\n        / "qpx_bot"\n        / "qualification_runtime"\n        / "qualification_state.json",\n        {\n            "schema_version": 1,\n            "first_eligible_session": "2026-08-07",\n            "sessions": {},\n        },\n    )\n\n    restored = restore_backup(\n        archive_path=original.archive_path,\n        project_root=root,\n        config=config,\n        archive_directory=archive_directory,\n        runtime_directory=backup_runtime,\n        report_directory=report_directory,\n        confirm_restore=True,\n    )\n    assert restored.paper_revision == 1\n    restored_state = store.load()\n    assert restored_state.revision == 1\n    assert restored_state.swing_cash == 4_000.0\n    assert store.verify_journal()[2] == 1\n    assert store.kill_switch_active()\n    restore_details = store.kill_switch_details()\n    assert restore_details is not None\n    assert restore_details["owner"] == "restore_guard"\n    assert not (\n        backup_runtime / "backup.lock"\n    ).exists()\n    assert len(\n        list_backups(archive_directory)\n    ) == 2\n    assert not (\n        root\n        / "qpx_bot"\n        / "qualification_runtime"\n        / "qualification_state.json"\n    ).exists()\n\n    resume_restored_paper(\n        paper_runtime=paper_runtime,\n        confirm_resume=True,\n    )\n    assert not store.kill_switch_active()\n    assert store.verify_journal()[2] == 2\n\nprint("QPX Bot Recovery Safety Hardening PASS")\n',
    "qpx_bot/RECOVERY_SAFETY_HARDENING_README.txt": 'QPX RECOVERY AND KILL-SWITCH SAFETY HARDENING\n=============================================\n\nThis milestone closes two recovery-control risks.\n\n1. Verified restore locking\n---------------------------\n\nThe restore path already holds the backup lock. Its required\npre-restore safety snapshot now reuses that held lock instead of trying\nto acquire the same non-reentrant lock a second time.\n\nThe restore test performs a complete temporary disaster-recovery cycle:\n\n- create and verify an original archive;\n- mutate the live paper state;\n- create a pre-restore safety snapshot;\n- restore the original archive;\n- verify the restored state checksum and audit chain;\n- verify that the backup lock is released;\n- leave a restore-owned paper kill switch active.\n\nRestore also refuses to run while paper, operations, or qualification\nruntime locks are active.\n\n2. Kill-switch ownership\n------------------------\n\nKILL_SWITCH now records an owner.\n\nRecognized owners:\n\nmanual\n    An independent manual safety hold.\n\noperations_circuit_breaker\n    A hold created by automated operations after repeated failures.\n\nrestore_guard\n    A hold created during verified disaster recovery.\n\nThe operations circuit breaker no longer overwrites an existing manual\nor restore-owned paper kill switch.\n\nThe normal operations resume command:\n\npython QPX_RUN_DAILY_OPERATIONS.py --resume\n\nclears only an operations_circuit_breaker kill switch. An independent\nmanual or restore guard remains active.\n\nAfter a verified restore, review the backup, operations, session, and\nqualification reports. Then explicitly clear only the restore-owned\nguard with:\n\npython QPX_RUN_DAILY_OPERATIONS.py \\\n    --resume-restored-paper \\\n    --confirm-resume-restored-paper\n\nThat command validates the restored paper state and audit chain before\nremoving the restore guard. It refuses to remove a manual or\noperations-owned kill switch.\n\nThis remains simulated paper trading. Broker connectivity is disabled.\n',
}

SIMPLE_PATCHES = {
    "qpx_bot/operations.py": [
        (
            '            paper_store.activate_kill_switch(\n                "QPX automated operations circuit breaker"\n            )\n',
            '            existing_kill_switch = (\n                paper_store.kill_switch_details()\n            )\n\n            if existing_kill_switch is None:\n                paper_store.activate_kill_switch(\n                    "QPX automated operations circuit breaker",\n                    owner="operations_circuit_breaker",\n                )\n',
        ),
        (
            '    parser.add_argument(\n        "--resume",\n        action="store_true",\n        help="Reset the circuit breaker and paper kill switch.",\n    )\n',
            '    parser.add_argument(\n        "--resume",\n        action="store_true",\n        help=(\n            "Reset the operations circuit breaker and clear "\n            "only an operations-owned paper kill switch."\n        ),\n    )\n    parser.add_argument(\n        "--resume-restored-paper",\n        action="store_true",\n        help=(\n            "Clear only a verified restore-owned paper "\n            "kill switch after integrity review."\n        ),\n    )\n    parser.add_argument(\n        "--confirm-resume-restored-paper",\n        action="store_true",\n        help=(\n            "Required confirmation for "\n            "--resume-restored-paper."\n        ),\n    )\n',
        ),
        (
            '    if args.resume:\n        with operations_lock(runtime):\n            resume_operations(\n                runtime_directory=runtime,\n                paper_runtime=paper,\n            )\n        print("QPX automated operations are RESUMED.")\n        return 0\n',
            '    if args.resume:\n        with operations_lock(runtime):\n            fully_resumed, message = resume_operations(\n                runtime_directory=runtime,\n                paper_runtime=paper,\n            )\n        print(message)\n\n        if fully_resumed:\n            print(\n                "QPX automated operations are RESUMED."\n            )\n            return 0\n\n        print(\n            "QPX paper execution remains PAUSED by an "\n            "independent kill switch."\n        )\n        return 4\n\n    if args.resume_restored_paper:\n        with operations_lock(runtime):\n            message = resume_restored_paper(\n                paper_runtime=paper,\n                confirm_resume=(\n                    args.confirm_resume_restored_paper\n                ),\n            )\n        print(message)\n        return 0\n\n    if args.confirm_resume_restored_paper:\n        raise RuntimeError(\n            "--confirm-resume-restored-paper requires "\n            "--resume-restored-paper."\n        )\n',
        ),
    ],
    "qpx_bot/backup.py": [
        (
            'from contextlib import contextmanager\n',
            'from contextlib import contextmanager, nullcontext\n',
        ),
        (
            '    unique: bool = False,\n    reason: str = "scheduled",\n) -> BackupResult:\n',
            '    unique: bool = False,\n    reason: str = "scheduled",\n    _lock_held: bool = False,\n) -> BackupResult:\n',
        ),
        (
            '    archives.mkdir(parents=True, exist_ok=True)\n\n    with backup_lock(runtime):\n',
            '    archives.mkdir(parents=True, exist_ok=True)\n    lock_context = (\n        nullcontext()\n        if _lock_held\n        else backup_lock(runtime)\n    )\n\n    with lock_context:\n',
        ),
        (
            '            unique=True,\n            reason="pre_restore_safety_snapshot",\n        )\n',
            '            unique=True,\n            reason="pre_restore_safety_snapshot",\n            _lock_held=True,\n        )\n',
        ),
        (
            '        project_root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations.lock",\n    ]\n',
            '        project_root\n        / "qpx_bot"\n        / "operations_runtime"\n        / "operations.lock",\n        project_root\n        / "qpx_bot"\n        / "qualification_runtime"\n        / "qualification.lock",\n    ]\n',
        ),
        (
            '        kill_switch = paper_runtime / "KILL_SWITCH"\n        _atomic_text(\n            kill_switch,\n            (\n                "QPX recovery restore in progress. "\n                "Manual resume required.\\n"\n            ),\n        )\n',
            '        restore_store = StateStore(\n            paper_runtime\n        )\n        restore_store.activate_kill_switch(\n            (\n                "QPX recovery restore in progress. "\n                "Manual resume required."\n            ),\n            owner="restore_guard",\n        )\n',
        ),
        (
            '        _atomic_text(\n            paper_runtime / "KILL_SWITCH",\n            (\n                "Restored from verified backup. "\n                "Review health reports, then resume manually.\\n"\n            ),\n        )\n        live_store = StateStore(paper_runtime)\n',
            '        live_store = StateStore(\n            paper_runtime\n        )\n        live_store.activate_kill_switch(\n            (\n                "Restored from verified backup. "\n                "Review health reports, then resume manually."\n            ),\n            owner="restore_guard",\n        )\n',
        ),
        (
            '            "Paper trading remains paused. Review health, then "\n            "run QPX_RUN_DAILY_OPERATIONS.py --resume."\n',
            '            "Paper trading remains paused. Review health, then "\n            "run QPX_RUN_DAILY_OPERATIONS.py "\n            "--resume-restored-paper "\n            "--confirm-resume-restored-paper."\n',
        ),
        *[('"qpx_bot/qualification_config.json",\n', '    "qpx_bot/qualification_config.json",\n'),
        ('"reports/qpx_qualification/latest_qualification.txt",\n', '    "reports/qpx_qualification/latest_qualification.txt",\n'),
        ('"reports/qpx_qualification/latest_qualification.json",\n', '    "reports/qpx_qualification/latest_qualification.json",\n'),
        ('"reports/qpx_qualification/session_ledger.csv",\n', '    "reports/qpx_qualification/session_ledger.csv",\n'),
        ('"qpx_bot/qualification_runtime",\n', '    "qpx_bot/qualification_runtime",\n'),
        ('"qualification.lock",\n', '    "qualification.lock",\n')],
    ],
    "qpx_bot/BACKUP_RECOVERY_README.txt": [
        (
            '- Restore is refused while paper or operations locks are active.\n',
            '- Restore is refused while paper, operations, or qualification locks\n  are active.\n',
        ),
        (
            '- After reviewing reports/qpx_backup/latest_backup.txt and\n  reports/qpx_operations/latest_health.txt, resume with:\n\npython QPX_RUN_DAILY_OPERATIONS.py --resume\n',
            '- After reviewing reports/qpx_backup/latest_backup.txt,\n  reports/qpx_operations/latest_health.txt,\n  reports/qpx_session_execution/latest_session_execution.txt, and\n  reports/qpx_qualification/latest_qualification.txt, clear only the\n  restore-owned guard with:\n\npython QPX_RUN_DAILY_OPERATIONS.py --resume-restored-paper --confirm-resume-restored-paper\n',
        ),
    ],
    "qpx_bot/DAILY_OPERATIONS_README.txt": [
        (
            'python QPX_RUN_DAILY_OPERATIONS.py --resume\npython QPX_SETUP_DAILY_SCHEDULE.py --install\n',
            'python QPX_RUN_DAILY_OPERATIONS.py --resume\npython QPX_RUN_DAILY_OPERATIONS.py --resume-restored-paper --confirm-resume-restored-paper\npython QPX_SETUP_DAILY_SCHEDULE.py --install\n',
        ),
        (
            '- Three consecutive failed sessions activate the operations circuit\n  breaker and the existing paper kill switch.\n- Resume only after reviewing reports/qpx_operations/latest_health.txt:\n  python QPX_RUN_DAILY_OPERATIONS.py --resume\n',
            '- Three consecutive failed sessions activate the operations circuit\n  breaker. If no independent paper kill switch is already active,\n  operations creates an operations-owned paper kill switch.\n- A normal resume clears only an operations-owned kill switch:\n  python QPX_RUN_DAILY_OPERATIONS.py --resume\n- A manual or restore-owned paper kill switch is never cleared by the\n  normal operations resume command.\n',
        ),
    ],
}

REGION_PATCHES = {
    "qpx_bot/paper_state.py": [
        (
            '    def activate_kill_switch(self, reason: str) -> None:\n        self.directory.mkdir(parents=True, exist_ok=True)\n        self.kill_switch_path.write_text(\n            json.dumps(\n                {\n                    "activated_utc": datetime.now(\n                        timezone.utc\n                    ).isoformat(),\n                    "reason": reason.strip() or "manual",\n                },\n                indent=2,\n            )\n            + "\\n",\n            encoding="utf-8",\n        )\n\n    def deactivate_kill_switch(self) -> None:\n        self.kill_switch_path.unlink(missing_ok=True)\n\n    def kill_switch_active(self) -> bool:\n        return self.kill_switch_path.exists()\n',
            '    def activate_kill_switch(\n        self,\n        reason: str,\n        *,\n        owner: str = "manual",\n    ) -> None:\n        normalized_reason = reason.strip() or "manual"\n        normalized_owner = owner.strip() or "manual"\n        self.directory.mkdir(parents=True, exist_ok=True)\n        self.kill_switch_path.write_text(\n            json.dumps(\n                {\n                    "activated_utc": datetime.now(\n                        timezone.utc\n                    ).isoformat(),\n                    "reason": normalized_reason,\n                    "owner": normalized_owner,\n                },\n                indent=2,\n                sort_keys=True,\n            )\n            + "\\n",\n            encoding="utf-8",\n        )\n\n    def kill_switch_details(\n        self,\n    ) -> Mapping[str, Any] | None:\n        if not self.kill_switch_path.exists():\n            return None\n\n        raw = self.kill_switch_path.read_text(\n            encoding="utf-8"\n        ).strip()\n\n        try:\n            payload = json.loads(raw)\n        except json.JSONDecodeError:\n            payload = None\n\n        if isinstance(payload, Mapping):\n            reason = str(\n                payload.get("reason", "")\n            ).strip()\n            owner = str(\n                payload.get("owner", "")\n            ).strip()\n\n            if not owner:\n                if reason == (\n                    "QPX automated operations circuit breaker"\n                ):\n                    owner = "operations_circuit_breaker"\n                elif (\n                    reason.startswith(\n                        "Restored from verified backup"\n                    )\n                    or reason.startswith(\n                        "QPX recovery restore"\n                    )\n                ):\n                    owner = "restore_guard"\n                else:\n                    owner = "manual_or_legacy"\n\n            return {\n                "activated_utc": (\n                    str(payload.get("activated_utc"))\n                    if payload.get("activated_utc")\n                    else None\n                ),\n                "reason": reason or "unspecified",\n                "owner": owner,\n            }\n\n        owner = (\n            "restore_guard"\n            if (\n                raw.startswith(\n                    "Restored from verified backup"\n                )\n                or raw.startswith(\n                    "QPX recovery restore"\n                )\n            )\n            else "manual_or_legacy"\n        )\n        return {\n            "activated_utc": None,\n            "reason": raw or "unspecified",\n            "owner": owner,\n        }\n\n    def deactivate_kill_switch(\n        self,\n        *,\n        expected_owner: str | None = None,\n    ) -> bool:\n        if not self.kill_switch_path.exists():\n            return False\n\n        if expected_owner is not None:\n            details = self.kill_switch_details()\n            actual_owner = (\n                str(details.get("owner"))\n                if details\n                else ""\n            )\n\n            if actual_owner != expected_owner:\n                return False\n\n        self.kill_switch_path.unlink(missing_ok=True)\n        return True\n\n    def kill_switch_active(self) -> bool:\n        return self.kill_switch_path.exists()\n',
        )
    ],
    "qpx_bot/operations.py": [
        (
            'def resume_operations(\n',
            '\ndef run_daily_operations(\n',
            'def resume_operations(\n    *,\n    runtime_directory: Path,\n    paper_runtime: Path,\n) -> tuple[bool, str]:\n    state = load_operations_state(runtime_directory)\n    paper_store = StateStore(paper_runtime)\n\n    with paper_store.locked():\n        kill_switch_cleared = (\n            paper_store.deactivate_kill_switch(\n                expected_owner=(\n                    "operations_circuit_breaker"\n                )\n            )\n        )\n        independent_kill_switch = (\n            paper_store.kill_switch_active()\n        )\n        remaining_details = (\n            paper_store.kill_switch_details()\n        )\n\n        state.paused = False\n        state.consecutive_failures = 0\n        state.last_recovery_utc = datetime.now(\n            timezone.utc\n        ).isoformat()\n\n        if independent_kill_switch:\n            state.last_status = (\n                "OPERATIONS_RESUMED_PAPER_PAUSED"\n            )\n            state.last_message = (\n                "Operations circuit breaker reset; "\n                "an independent paper kill switch "\n                "remains active."\n            )\n        else:\n            state.last_status = "RESUMED"\n            state.last_message = (\n                "QPX automated operations resumed."\n            )\n\n        save_operations_state(\n            runtime_directory,\n            state,\n        )\n        (\n            runtime_directory / "OPERATIONS_PAUSED"\n        ).unlink(missing_ok=True)\n        paper_store.append_events(\n            [\n                _operations_event(\n                    "OPERATIONS_RESUMED",\n                    {\n                        "reason": "manual CLI command",\n                        "operations_owned_kill_switch_cleared": (\n                            kill_switch_cleared\n                        ),\n                        "paper_kill_switch_active": (\n                            independent_kill_switch\n                        ),\n                        "remaining_kill_switch_owner": (\n                            remaining_details.get(\n                                "owner"\n                            )\n                            if remaining_details\n                            else None\n                        ),\n                    },\n                )\n            ]\n        )\n\n    return (\n        not independent_kill_switch,\n        state.last_message,\n    )\n\n\ndef resume_restored_paper(\n    *,\n    paper_runtime: Path,\n    confirm_resume: bool,\n) -> str:\n    if not confirm_resume:\n        raise RuntimeError(\n            "Restored-paper resume requires "\n            "--confirm-resume-restored-paper."\n        )\n\n    paper_store = StateStore(paper_runtime)\n\n    with paper_store.locked():\n        details = paper_store.kill_switch_details()\n\n        if details is None:\n            return (\n                "No paper kill switch is active. "\n                "No restore guard was changed."\n            )\n\n        if details.get("owner") != "restore_guard":\n            raise RuntimeError(\n                "Refusing to clear a non-restore paper "\n                "kill switch. Owner: "\n                f"{details.get(\'owner\')}"\n            )\n\n        state = paper_store.load()\n        _, _, journal_records = (\n            paper_store.verify_journal()\n        )\n        cleared = paper_store.deactivate_kill_switch(\n            expected_owner="restore_guard"\n        )\n\n        if not cleared:\n            raise RuntimeError(\n                "Restore guard changed during resume."\n            )\n\n        paper_store.append_events(\n            [\n                _operations_event(\n                    "PAPER_RESTORE_RESUMED",\n                    {\n                        "state_id": state.state_id,\n                        "revision": state.revision,\n                        "journal_records_before_resume": (\n                            journal_records\n                        ),\n                        "previous_kill_switch_owner": (\n                            "restore_guard"\n                        ),\n                        "reason": (\n                            "explicit confirmed CLI command"\n                        ),\n                    },\n                )\n            ]\n        )\n\n    return (\n        "Verified restored paper state and audit chain; "\n        "the restore guard is cleared."\n    )\n',
        )
    ],
}

TARGETS = [
    *FILES,
    *SIMPLE_PATCHES,
    *REGION_PATCHES,
]
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


def apply_transformations(
    relative: str,
    content: str,
) -> str:
    for old, new in SIMPLE_PATCHES.get(
        relative,
        [],
    ):
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
                f"Expected marker not found in "
                f"{relative}:\n{old}"
            )

    for patch in REGION_PATCHES.get(
        relative,
        [],
    ):
        if len(patch) == 2:
            old, new = patch

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
                    f"Expected region not found in "
                    f"{relative}:\n{old[:300]}"
                )
            continue

        start_marker, end_marker, replacement = patch

        if replacement in content:
            continue

        start = content.find(start_marker)

        if start < 0:
            raise RuntimeError(
                f"Region start marker not found in "
                f"{relative}:\n{start_marker}"
            )

        end = content.find(
            end_marker,
            start + len(start_marker),
        )

        if end < 0:
            raise RuntimeError(
                f"Region end marker not found in "
                f"{relative}:\n{end_marker}"
            )

        content = (
            content[:start]
            + replacement
            + content[end:]
        )

    return content


def validate_patch_markers() -> None:
    failures: list[str] = []

    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        path = ROOT / relative

        if not path.exists():
            failures.append(
                f"{relative}: file not found"
            )
            continue

        try:
            transformed = apply_transformations(
                relative,
                path.read_text(
                    encoding="utf-8"
                ),
            )
            compile(
                transformed,
                relative,
                "exec",
            ) if path.suffix == ".py" else None
        except Exception as exc:
            failures.append(
                f"{relative}: {type(exc).__name__}: {exc}"
            )

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
    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        preserve(relative)
        path = ROOT / relative
        transformed = apply_transformations(
            relative,
            path.read_text(
                encoding="utf-8"
            ),
        )
        path.write_text(
            transformed,
            encoding="utf-8",
        )
        print(f"Updated: {relative}")


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
            "Recovery safety hardening is "
            "already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Harden QPX Bot restore and "
            "kill-switch ownership"
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
        "QPX BOT — RECOVERY SAFETY "
        "HARDENING INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()
    patch_files()

    try:
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_recovery_safety_hardening"
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
        "Creating and drilling a fresh verified backup..."
    )
    print()

    try:
        run([
            sys.executable,
            "QPX_BACKUP_RUNTIME.py",
            "--create",
            "--force",
            "--drill-latest",
        ])
        run([
            sys.executable,
            "QPX_RUN_QUALIFICATION.py",
            "--status",
        ])
    except Exception:
        print()
        print("=" * 78)
        print(
            "QPX RECOVERY SAFETY CODE: "
            "INSTALLED AND PUSHED"
        )
        print(
            "POST-INSTALL BACKUP CHECK: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_BACKUP_RUNTIME.py "
            "--create --force --drill-latest"
        )
        return 2

    print()
    print("=" * 78)
    print(
        "QPX RECOVERY SAFETY HARDENING: COMPLETE"
    )
    print("=" * 78)
    print(
        "Restore locking and kill-switch ownership "
        "are now explicitly tested. Broker "
        "connectivity remains disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
