"""Install and manage the local Termux cron schedule for QPX."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
RUNTIME_DIR = PACKAGE_DIR / "operations_runtime"
CRON_BEGIN = "# QPX DAILY OPERATIONS BEGIN"
CRON_END = "# QPX DAILY OPERATIONS END"


def remove_qpx_cron_block(content: str) -> str:
    output: list[str] = []
    inside = False

    for line in content.splitlines():
        if line.strip() == CRON_BEGIN:
            inside = True
            continue

        if line.strip() == CRON_END:
            inside = False
            continue

        if not inside:
            output.append(line)

    while output and not output[-1].strip():
        output.pop()

    return "\n".join(output)


def build_qpx_cron_block(
    script_path: str | Path,
    *,
    home: str | Path,
    prefix: str | Path,
) -> str:
    script = Path(script_path).expanduser().resolve()
    home_path = Path(home).expanduser().resolve()
    prefix_path = Path(prefix).expanduser().resolve()
    command = (
        f'HOME="{home_path}" '
        f'PATH="{prefix_path / "bin"}:/system/bin" '
        f'"{script}"'
    )

    return "\n".join(
        [
            CRON_BEGIN,
            (
                "# Hourly evening checks; the Python runner "
                "executes only once per completed market session."
            ),
            f"15 16-23 * * 1-5 {command}",
            CRON_END,
        ]
    )


def _current_crontab() -> str:
    completed = subprocess.run(
        ["crontab", "-l"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )

    if completed.returncode != 0:
        return ""

    return completed.stdout


def _write_crontab(content: str) -> None:
    subprocess.run(
        ["crontab", "-"],
        input=content,
        text=True,
        check=True,
    )


def _ensure_cronie() -> None:
    if shutil.which("crontab") and shutil.which("crond"):
        return

    pkg = shutil.which("pkg")

    if pkg is None:
        raise RuntimeError(
            "Termux pkg command was not found; cannot install cronie."
        )

    subprocess.run(
        [pkg, "install", "-y", "cronie"],
        check=True,
    )

    if not shutil.which("crontab") or not shutil.which("crond"):
        raise RuntimeError(
            "cronie installation completed but cron commands "
            "are still unavailable."
        )


def _start_crond() -> None:
    pgrep = shutil.which("pgrep")

    if pgrep is not None:
        running = subprocess.run(
            [pgrep, "-x", "crond"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if running.returncode == 0:
            return

    subprocess.run(["crond"], check=True)


def _write_boot_script(prefix: Path) -> Path:
    boot_directory = Path.home() / ".termux" / "boot"
    boot_directory.mkdir(parents=True, exist_ok=True)
    path = boot_directory / "qpx-start-crond.sh"
    path.write_text(
        (
            f"#!{prefix / 'bin' / 'sh'}\n"
            f'export PATH="{prefix / "bin"}:/system/bin:$PATH"\n'
            'pgrep -x crond >/dev/null 2>&1 || crond\n'
        ),
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _write_scheduler_status(
    *,
    backend: str,
    installed: bool,
    script_path: Path,
    boot_script: Path | None,
) -> Path:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    path = RUNTIME_DIR / "scheduler.json"
    payload = {
        "backend": backend,
        "installed": installed,
        "script_path": str(script_path),
        "boot_script": (
            str(boot_script)
            if boot_script
            else None
        ),
        "schedule": "15 16-23 * * 1-5",
        "timezone": "device local time",
        "market_gate": "17:15 America/New_York",
        "updated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
    }
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def install_schedule(
    script_path: str | Path,
) -> Path:
    _ensure_cronie()
    script = Path(script_path).expanduser().resolve()

    if not script.exists():
        raise FileNotFoundError(script)

    script.chmod(0o700)
    prefix = Path(
        os.environ.get(
            "PREFIX",
            "/data/data/com.termux/files/usr",
        )
    )
    cleaned = remove_qpx_cron_block(
        _current_crontab()
    )
    block = build_qpx_cron_block(
        script,
        home=Path.home(),
        prefix=prefix,
    )
    updated = (
        (cleaned + "\n\n" if cleaned else "")
        + block
        + "\n"
    )
    _write_crontab(updated)
    _start_crond()
    boot_script = _write_boot_script(prefix)
    return _write_scheduler_status(
        backend="cronie",
        installed=True,
        script_path=script,
        boot_script=boot_script,
    )


def remove_schedule(
    script_path: str | Path,
) -> Path:
    _ensure_cronie()
    cleaned = remove_qpx_cron_block(
        _current_crontab()
    )
    _write_crontab(
        cleaned + ("\n" if cleaned else "")
    )
    return _write_scheduler_status(
        backend="cronie",
        installed=False,
        script_path=Path(
            script_path
        ).expanduser().resolve(),
        boot_script=None,
    )


def _parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Install or remove QPX Termux scheduling."
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--install",
        action="store_true",
    )
    action.add_argument(
        "--remove",
        action="store_true",
    )
    parser.add_argument(
        "--script",
        default=str(
            PROJECT_ROOT / "QPX_TERMUX_DAILY.sh"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.remove:
        status = remove_schedule(args.script)
        print(f"QPX daily schedule removed: {status}")
        return 0

    status = install_schedule(args.script)
    print(f"QPX daily schedule installed: {status}")
    print(
        "Cron checks hourly from 16:15 through 23:15 local "
        "time on weekdays; the market gate and session ledger "
        "prevent early or duplicate paper runs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
