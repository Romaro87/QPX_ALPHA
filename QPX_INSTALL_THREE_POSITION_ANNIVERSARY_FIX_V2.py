#!/usr/bin/env python3
"""Correct exact-anniversary rebalancing in three-position research."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
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
    / "qpx_three_position_anniversary_fix_v2"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.21.1"\n',
    "tests/test_qpx_bot_three_position_anniversary.py": 'from datetime import date\nfrom pathlib import Path\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.portfolio import contribution_allocation\nfrom qpx_bot.time_rules import elapsed_complete_years\n\n\nconfig = BotConfig()\nconfig.validate()\n\nstart = date(2024, 8, 6)\n\nassert elapsed_complete_years(\n    start,\n    date(2026, 8, 5),\n) == 1\nassert elapsed_complete_years(\n    start,\n    date(2026, 8, 6),\n) == 2\n\nbefore = contribution_allocation(\n    elapsed_complete_years(\n        start,\n        date(2026, 8, 5),\n    ),\n    config,\n)\non_anniversary = contribution_allocation(\n    elapsed_complete_years(\n        start,\n        date(2026, 8, 6),\n    ),\n    config,\n)\n\nassert before == (0.65, 0.35)\nassert on_anniversary == (0.40, 0.60)\n\nsource = (\n    Path(__file__).resolve().parents[1]\n    / "qpx_bot"\n    / "actual_two_year_three_position.py"\n).read_text(encoding="utf-8")\n\nfor required in (\n    "allocation_phase_changed = (",\n    "if month_changed or allocation_phase_changed:",\n    \'"ALLOCATION_PHASE_REBALANCE"\',\n    "previous_allocation_years = (",\n    "current_allocation_years",\n    "contribution_amount = 0.0",\n    "maximum_concurrent_positions",\n    "rankings_enabled=False",\n):\n    assert required in source\n\nassert (\n    \'if month_key != current_month:\\n\'\n    \'            swing.deposit(\'\n    not in source\n)\n\nprint(\n    "QPX Bot Three-Position Exact Anniversary PASS"\n)\n',
    "qpx_bot/THREE_POSITION_ANNIVERSARY_FIX_README.txt": 'QPX THREE-POSITION EXACT-ANNIVERSARY FIX\n========================================\n\nProblem corrected\n-----------------\n\nThe unranked three-position research engine previously performed\nallocation rebalancing only when the calendar month changed.\n\nFor a test beginning on August 6, 2024:\n\n- August 3, 2026 was the first processed session of the month.\n- The exact second anniversary was August 6, 2026.\n- Since the month had already changed, the strategy did not perform the\n  required 65/35 to 40/60 allocation-phase rebalance on August 6.\n\nThat caused the test to end near 65% QDTE even though the report claimed\nthe exact-date transition had occurred.\n\nCorrect behavior\n----------------\n\nThe engine now tracks two independent events:\n\n1. calendar-month change;\n2. completed-year allocation-phase change.\n\nA monthly contribution is added only on a month change.\n\nA QDTE/swing rebalance is performed when either event occurs.\n\nWhen the anniversary occurs after the first session of a month, the\nengine performs an ALLOCATION_PHASE_REBALANCE with a zero external\ncontribution.\n\nWhen the anniversary and month change occur on the same session, one\ncombined monthly contribution and allocation rebalance is performed.\n\nPreserved strategy\n------------------\n\n- rankings remain removed;\n- all eight ETFs are scanned daily;\n- maximum three concurrent swing positions;\n- exact same entry filters;\n- exact same ATR exits and trailing stop;\n- exact same slippage and opening-gap rejection;\n- exact same quarter-Kelly and 6% global active-risk cap;\n- actual QDTE distributions and actual VIX;\n- no synthetic data or forced entries;\n- live brokerage disabled.\n\nThe installer runs all tests, commits and pushes the correction, then\ndownloads fresh actual data and reruns the same two-year backtest.\n',
}

TARGET_MODULE = (
    "qpx_bot/actual_two_year_three_position.py"
)
TARGETS = [
    *FILES,
    TARGET_MODULE,
]
originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
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


def _module_patch_state(source: str) -> str:
    exact_markers = (
        "allocation_phase_changed = (",
        "if month_changed or allocation_phase_changed:",
        '"ALLOCATION_PHASE_REBALANCE"',
        "previous_allocation_years = (",
    )

    if all(marker in source for marker in exact_markers):
        return "PATCHED"

    if (
        "        if month_key != current_month:\n"
        in source
        and "ALLOCATION_PHASE_REBALANCE" not in source
    ):
        return "ORIGINAL"

    return "UNKNOWN"


def ensure_targets_are_safe() -> None:
    """
    Protect unrelated module edits while tolerating V1 partial files.

    V1 wrote __init__.py, the focused test, and the README before its
    report-title marker failed. V2 owns those three files and may safely
    replace them. The strategy module is accepted only in the original
    or already-patched structural shape.
    """
    path = ROOT / TARGET_MODULE

    if not path.exists():
        raise RuntimeError(
            f"Required module was not found: {TARGET_MODULE}"
        )

    module_source = path.read_text(
        encoding="utf-8"
    )
    state = _module_patch_state(
        module_source
    )

    if state == "UNKNOWN":
        raise RuntimeError(
            "The three-position module has an unsupported local "
            "shape. V2 did not overwrite it. Commit or restore "
            "unrelated edits, then run this installer again."
        )

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
            "--",
            TARGET_MODULE,
        ],
        cwd=ROOT,
    )

    if staged.returncode != 0 and state != "PATCHED":
        raise RuntimeError(
            "The strategy module has staged local edits and is not "
            "already patched. V2 did not overwrite it."
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


def patch_module() -> None:
    relative = TARGET_MODULE
    preserve(relative)
    path = ROOT / relative
    source = path.read_text(
        encoding="utf-8"
    )

    old_current_month = '    current_month = (\n        actual_start.year,\n        actual_start.month,\n    )\n\n    for day in test_dates:\n'
    new_current_month = '    current_month = (\n        actual_start.year,\n        actual_start.month,\n    )\n    previous_allocation_years = (\n        elapsed_complete_years(\n            actual_start,\n            actual_start,\n        )\n    )\n\n    for day in test_dates:\n'
    new_monthly_block = '        current_allocation_years = (\n            elapsed_complete_years(\n                actual_start,\n                day,\n            )\n        )\n        allocation_phase_changed = (\n            current_allocation_years\n            != previous_allocation_years\n        )\n        month_changed = (\n            month_key != current_month\n        )\n        contribution_amount = 0.0\n\n        if month_changed:\n            swing.deposit(\n                config.monthly_contribution\n            )\n            contribution_amount = (\n                config.monthly_contribution\n            )\n            total_contributions += (\n                contribution_amount\n            )\n            contribution_count += 1\n            current_month = month_key\n\n        if month_changed or allocation_phase_changed:\n            target_income_weight, _ = (\n                contribution_allocation(\n                    current_allocation_years,\n                    config,\n                )\n            )\n            open_prices = (\n                _position_prices(\n                    portfolio=swing,\n                    row_maps=row_maps,\n                    day=day,\n                    field="open",\n                )\n            )\n            rebalance = _apply_rebalance(\n                income=income,\n                swing=swing,\n                income_price=(\n                    income_row.open\n                ),\n                swing_market_value=(\n                    swing.market_value(\n                        open_prices\n                    )\n                ),\n                target_income_weight=(\n                    target_income_weight\n                ),\n                config=config,\n            )\n            allocations.append(\n                AllocationSnapshot(\n                    date=day,\n                    event_type=(\n                        "MONTHLY_CONTRIBUTION_REBALANCE"\n                        if month_changed\n                        else "ALLOCATION_PHASE_REBALANCE"\n                    ),\n                    contribution=(\n                        contribution_amount\n                    ),\n                    target_income_weight=(\n                        target_income_weight\n                    ),\n                    action=rebalance.action,\n                    before_income_weight=(\n                        rebalance.before_income_weight\n                    ),\n                    after_income_weight=(\n                        rebalance.after_income_weight\n                    ),\n                    target_fully_reached=(\n                        rebalance.target_fully_reached\n                    ),\n                    qdte_market_value_traded=(\n                        rebalance.market_value_traded\n                    ),\n                    realized_pnl=(\n                        rebalance.realized_pnl\n                    ),\n                    tax_reserved=(\n                        rebalance.tax_reserved\n                    ),\n                )\n            )\n\n        previous_allocation_years = (\n            current_allocation_years\n        )\n'

    if "previous_allocation_years = (" not in source:
        if old_current_month not in source:
            raise RuntimeError(
                "Could not locate the current-month initialization "
                "needed for the anniversary state tracker."
            )

        source = source.replace(
            old_current_month,
            new_current_month,
            1,
        )

    exact_markers = (
        "allocation_phase_changed = (",
        "if month_changed or allocation_phase_changed:",
        '"ALLOCATION_PHASE_REBALANCE"',
        "previous_allocation_years = (",
    )

    if not all(marker in source for marker in exact_markers):
        start_marker = (
            "        if month_key != current_month:\n"
        )
        end_marker = "        if pending:\n"
        start = source.find(start_marker)

        if start < 0:
            raise RuntimeError(
                "Could not locate the old month-only rebalance block."
            )

        end = source.find(
            end_marker,
            start + len(start_marker),
        )

        if end < 0:
            raise RuntimeError(
                "Could not locate the pending-entry block after "
                "the month-only rebalance block."
            )

        source = (
            source[:start]
            + new_monthly_block
            + source[end:]
        )

    title_pattern = re.compile(
        r'"QPX BOT v[0-9]+(?:\.[0-9]+){1,2} '
        r'— ACTUAL TWO-YEAR "'
    )
    desired_title = (
        '"QPX BOT v1.21.1 — ACTUAL TWO-YEAR "'
    )
    source, title_count = title_pattern.subn(
        desired_title,
        source,
        count=1,
    )

    if title_count == 0 and desired_title not in source:
        print(
            "Report version title was not found; "
            "continuing because title text is non-functional."
        )

    for marker in exact_markers:
        if marker not in source:
            raise RuntimeError(
                "Exact-anniversary patch verification failed: "
                + marker
            )

    compile(
        source,
        relative,
        "exec",
    )
    path.write_text(
        source,
        encoding="utf-8",
    )
    print(
        f"Updated: {relative} "
        "(exact anniversary phase trigger active)"
    )


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
            "Three-position anniversary fix "
            "is already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Fix exact anniversary rebalance "
            "in three-position backtest"
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
        "QPX BOT — THREE-POSITION "
        "EXACT-ANNIVERSARY FIX V2"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()

    try:
        install_files()
        patch_module()
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_three_position_anniversary"
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
        "Downloading fresh actual data and rerunning "
        "the unchanged three-position strategy..."
    )
    print()

    result = run(
        [
            sys.executable,
            "QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py",
        ],
        check=False,
    )

    if result.returncode != 0:
        print()
        print("=" * 78)
        print(
            "QPX ANNIVERSARY FIX: "
            "INSTALLED AND PUSHED"
        )
        print(
            "ACTUAL DATA RUN: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py"
        )
        return result.returncode

    print()
    print("=" * 78)
    print(
        "QPX THREE-POSITION EXACT-ANNIVERSARY "
        "BACKTEST V2: COMPLETE"
    )
    print("=" * 78)
    print(
        "The second-anniversary phase rebalance "
        "now executes independently of month changes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
