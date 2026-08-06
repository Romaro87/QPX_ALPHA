QPX VERIFIED BACKUP AND DISASTER RECOVERY
=========================================

Automatic behavior:

- QPX_TERMUX_DAILY.sh runs a backup after a successful automated
  operations command.
- A backup is skipped until operations records a fully successful
  market session matching the paper account's processed session.
- The same paper revision is never backed up repeatedly.
- Every archive is verified against an external SHA-256 checksum,
  an internal manifest, per-file SHA-256 hashes, ZIP CRC checks,
  the paper-state checksum, and the audit-journal hash chain.
- An isolated recovery drill extracts the archive into a temporary
  directory and loads the recovered paper state without touching the
  live account.
- The newest 30 archives are retained by default.

Backup location:

/storage/emulated/0/QPX_ALPHA_BACKUPS

Important commands:

Create and drill:
python QPX_BACKUP_RUNTIME.py --create --drill-latest

Verify newest:
python QPX_BACKUP_RUNTIME.py --verify-latest

List:
python QPX_BACKUP_RUNTIME.py --list

Run an isolated recovery drill:
python QPX_BACKUP_RUNTIME.py --drill-latest

Restore newest verified backup:
python QPX_BACKUP_RUNTIME.py --restore-latest --confirm-restore

Restore safety:

- Restore is refused while paper, operations, or qualification locks
  are active.
- A pre-restore safety backup is created first.
- The requested archive must pass a full isolated recovery drill.
- The paper kill switch is active during and after restoration.
- After reviewing reports/qpx_backup/latest_backup.txt,
  reports/qpx_operations/latest_health.txt,
  reports/qpx_session_execution/latest_session_execution.txt, and
  reports/qpx_qualification/latest_qualification.txt, clear only the
  restore-owned guard with:

python QPX_RUN_DAILY_OPERATIONS.py --resume-restored-paper --confirm-resume-restored-paper

Backups include simulated runtime state, current market inputs, and
latest reports. They do not contain brokerage credentials because QPX
has no brokerage connection.
