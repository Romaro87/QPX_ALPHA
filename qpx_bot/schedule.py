"""Install and manage local Termux schedules for QPX."""

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


def _cron_command(
    script: Path,
    *,
    home: Path,
    prefix: Path,
) -> str:
    return (
        f'HOME="{home}" '
        f'PATH="{prefix / "bin"}:/system/bin" '
        f'"{script}"'
    )


def build_qpx_cron_block(
    script_path: str | Path,
    *,
    home: str | Path,
    prefix: str | Path,
) -> str:
    analysis_script = Path(
        script_path
    ).expanduser().resolve()
    session_script = analysis_script.with_name(
        "QPX_TERMUX_SESSION.sh"
    )
    home_path = Path(
        home
    ).expanduser().resolve()
    prefix_path = Path(
        prefix
    ).expanduser().resolve()
    session_command = _cron_command(
        session_script,
        home=home_path,
        prefix=prefix_path,
    )
    analysis_command = _cron_command(
        analysis_script,
        home=home_path,
        prefix=prefix_path,
    )

    return "\n".join(
        [
            CRON_BEGIN,
            (
                "# Regular-session checks. Python gates "
                "execution to 09:35-10:30 New York time."
            ),
            (
                f"*/15 6-12 * * 1-5 "
                f"{session_command}"
            ),
            (
                "# After-close analysis. This job stages "
                "instructions but cannot fill entries."
            ),
            (
                f"15 16-23 * * 1-5 "
                f"{analysis_command}"
            ),
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
    if (
        shutil.which("crontab")
        and shutil.which("crond")
    ):
        return

    pkg = shutil.which("pkg")

    if pkg is None:
        raise RuntimeError(
            "Termux pkg command was not found; "
            "cannot install cronie."
        )

    subprocess.run(
        [pkg, "install", "-y", "cronie"],
        check=True,
    )

    if (
        not shutil.which("crontab")
        or not shutil.which("crond")
    ):
        raise RuntimeError(
            "cronie installed but cron commands "
            "remain unavailable."
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

    subprocess.run(
        ["crond"],
        check=True,
    )


def _write_boot_script(prefix: Path) -> Path:
    boot_directory = (
        Path.home() / ".termux" / "boot"
    )
    boot_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    path = (
        boot_directory / "qpx-start-crond.sh"
    )
    path.write_text(
        (
            f"#!{prefix / 'bin' / 'sh'}\n"
            f'export PATH="{prefix / "bin"}:'
            '/system/bin:$PATH"\n'
            "pgrep -x crond >/dev/null 2>&1 "
            "|| crond\n"
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
    RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    path = RUNTIME_DIR / "scheduler.json"
    payload = {
        "backend": backend,
        "installed": installed,
        "analysis_script": str(script_path),
        "session_script": str(
            script_path.with_name(
                "QPX_TERMUX_SESSION.sh"
            )
        ),
        "boot_script": (
            str(boot_script)
            if boot_script
            else None
        ),
        "regular_session_schedule": (
            "*/15 6-12 * * 1-5"
        ),
        "regular_session_gate": (
            "09:35-10:30 America/New_York"
        ),
        "extended_hours": False,
        "analysis_schedule": (
            "15 16-23 * * 1-5"
        ),
        "analysis_gate": (
            "17:15 America/New_York"
        ),
        "timezone": "device local time",
        "updated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
    }
    temporary = path.with_suffix(
        ".json.tmp"
    )
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
    script = Path(
        script_path
    ).expanduser().resolve()
    session_script = script.with_name(
        "QPX_TERMUX_SESSION.sh"
    )

    if not script.exists():
        raise FileNotFoundError(script)

    if not session_script.exists():
        raise FileNotFoundError(
            session_script
        )

    script.chmod(0o700)
    session_script.chmod(0o700)
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
    boot_script = _write_boot_script(
        prefix
    )
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
        description=(
            "Install or remove QPX regular-session "
            "and after-close schedules."
        )
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


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)

    if args.remove:
        status = remove_schedule(
            args.script
        )
        print(
            f"QPX schedules removed: {status}"
        )
        return 0

    status = install_schedule(
        args.script
    )
    print(
        f"QPX schedules installed: {status}"
    )
    print(
        "Regular-session checks are gated to "
        "09:35-10:30 New York time. After-close "
        "jobs analyze completed bars only. "
        "Extended-hours execution is disabled."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
