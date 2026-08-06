#!/usr/bin/env python3
"""Fallback quarter-hour daemon when Termux crond is unavailable."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import os
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / "qpx_bot" / "intraday_six_runtime"
PID_PATH = RUNTIME / "daemon.pid"
LOG_PATH = RUNTIME / "daemon.log"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _next_quarter(now: datetime) -> datetime:
    base = now.replace(second=0, microsecond=0)
    minutes = ((base.minute // 15) + 1) * 15

    if minutes >= 60:
        return (
            base.replace(minute=0)
            + timedelta(hours=1)
        )

    return base.replace(minute=minutes)


def main() -> int:
    RUNTIME.mkdir(parents=True, exist_ok=True)

    if PID_PATH.exists():
        try:
            existing = int(
                PID_PATH.read_text(encoding="utf-8").strip()
            )
        except (OSError, ValueError):
            existing = -1

        if existing > 0 and _alive(existing):
            print(
                f"QPX 15-minute daemon is already running "
                f"with PID {existing}."
            )
            return 0

    PID_PATH.write_text(
        str(os.getpid()) + "\n",
        encoding="utf-8",
    )

    try:
        while True:
            now = datetime.now()
            target = _next_quarter(now)
            delay = max(
                1.0,
                (target - now).total_seconds(),
            )
            time.sleep(delay)

            with LOG_PATH.open(
                "a",
                encoding="utf-8",
            ) as log:
                subprocess.run(
                    [
                        sys.executable,
                        str(
                            ROOT / "QPX_RUN_15M_PAPER.py"
                        ),
                    ],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
    finally:
        try:
            PID_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
