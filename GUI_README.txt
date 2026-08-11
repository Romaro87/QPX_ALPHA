QPX WEEKEND GUI V1

QPX_GUI.py
  Local-only browser dashboard/control center on 127.0.0.1:8765.
  Standard library only. Shows bot status/account/logs, edits symbols.json
  while stopped, runs self-test/one cycle, and starts/stops a GUI-managed
  continuous paper launcher. It does not enable live brokerage.

QPX_START_GUI.sh
  Starts the browser GUI.

QPX_WEEKEND_CLEANUP.sh
  Safe cleanup. It archives old untracked root research/install scripts and
  obvious accidental shell artifacts. It deletes nothing. It also ignores
  generated reports/data/logs/backups/archive/gui runtime in Git.

Install these files in the QPX_ALPHA repository root, then:
  python QPX_GUI.py --check
  bash QPX_START_GUI.sh
