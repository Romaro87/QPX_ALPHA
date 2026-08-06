QPX AUTOMATED DAILY OPERATIONS
==============================

Primary commands:

python QPX_RUN_DAILY_OPERATIONS.py
python QPX_RUN_DAILY_OPERATIONS.py --check-only
python QPX_RUN_DAILY_OPERATIONS.py --resume
python QPX_RUN_DAILY_OPERATIONS.py --resume-restored-paper --confirm-resume-restored-paper
python QPX_SETUP_DAILY_SCHEDULE.py --install
python QPX_SETUP_DAILY_SCHEDULE.py --remove

Schedule:

- Cron checks at minute 15 of every hour from 16:00 through 23:00
  in the device's local timezone, Monday through Friday.
- The Python market gate waits until 17:15 America/New_York.
- Only one completed market session is processed.
- Weekends and standard United States equity-market holidays are
  recognized.
- A successful session is recorded so later hourly checks do nothing.
- The installer starts crond and creates a Termux:Boot startup script.
  The Termux:Boot Android add-on must be installed for automatic cron
  restart after a full phone reboot.

Safety and recovery:

- The auto paper command is retried twice.
- Downloaded SWING.csv must contain the expected completed session.
- Persistent paper state must process that same session.
- State checksum and audit-journal hash chain are verified.
- Three consecutive failed sessions activate the operations circuit
  breaker. If no independent paper kill switch is already active,
  operations creates an operations-owned paper kill switch.
- A normal resume clears only an operations-owned kill switch:
  python QPX_RUN_DAILY_OPERATIONS.py --resume
- A manual or restore-owned paper kill switch is never cleared by the
  normal operations resume command.
- Optional Termux notifications are sent when the Termux:API command
  is available.
- Every attempt writes a timestamped log and health JSON/TXT report.

This remains simulated paper trading. It has no brokerage connection
and cannot place live orders.
