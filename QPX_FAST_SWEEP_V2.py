from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys

from datetime import date
from pathlib import Path

import QPX_FIND_BEST_ALPACA_SWING as sweep

from qpx_bot.alpaca_provider import (
    _qpx_original_sync as raw_alpaca_sync,
    cache_path,
    manifest_path,
    read_cache,
)


PREFLIGHT_END = date(
    2025,
    9,
    5,
)

MINIMUM_BAR_OVERLAP = 0.95

CHILD_PREFIX = (
    sweep.CHILD_PREFIX
)


def patch_profit_factor_output(
    source: str,
) -> str:
    old = (
        'f"{result.profit_factor:.3f}"'
    )

    new = (
        '("N/A" '
        'if result.profit_factor is None '
        'else f"{result.profit_factor:.3f}")'
    )

    if old in source:
        source = source.replace(
            old,
            new,
            1,
        )

    return source


_original_patch = (
    sweep.patch_generated_source
)


def safe_generated_source(
    source: str,
    symbol: str,
) -> str:
    source = _original_patch(
        source,
        symbol,
    )

    return patch_profit_factor_output(
        source
    )


sweep.patch_generated_source = (
    safe_generated_source
)


def format_self_test() -> None:
    source = (
        'print('
        'f"{result.profit_factor:.3f}"'
        ')'
    )

    patched = (
        patch_profit_factor_output(
            source
        )
    )

    if (
        "result.profit_factor is None"
        not in patched
    ):
        raise RuntimeError(
            "Profit-factor format fix "
            "self-test failed."
        )


def qdte_master_times():
    bars = read_cache(
        "QDTE"
    )

    times = {
        bar.start
        for bar in bars.values()
        if (
            sweep.START
            <= bar.start.date()
            <= sweep.END
        )
    }

    if not times:
        raise RuntimeError(
            "QDTE master cache is empty."
        )

    if (
        min(times).date()
        != sweep.START
    ):
        raise RuntimeError(
            "QDTE master does not "
            "reach test start."
        )

    if (
        max(times).date()
        != sweep.END
    ):
        raise RuntimeError(
            "QDTE master does not "
            "reach test end."
        )

    return times


def intraday_preflight(
    symbol: str,
    master_times,
) -> dict:
    required_total = math.ceil(
        len(master_times)
        * MINIMUM_BAR_OVERLAP
    )

    allowed_missing = (
        len(master_times)
        - required_total
    )

    gate_master = {
        timestamp
        for timestamp in master_times
        if (
            sweep.START
            <= timestamp.date()
            <= PREFLIGHT_END
        )
    }

    if not gate_master:
        raise RuntimeError(
            "Intraday preflight "
            "master window is empty."
        )

    raw_alpaca_sync(
        symbols=[
            symbol
        ],
        start=sweep.START,
        end=PREFLIGHT_END,
    )

    bars = read_cache(
        symbol
    )

    candidate_times = {
        bar.start
        for bar in bars.values()
        if (
            sweep.START
            <= bar.start.date()
            <= PREFLIGHT_END
        )
    }

    common = (
        gate_master
        & candidate_times
    )

    missing = (
        len(gate_master)
        - len(common)
    )

    first_day_present = any(
        timestamp.date()
        == sweep.START
        for timestamp in common
    )

    impossible = (
        missing
        > allowed_missing
    )

    if not first_day_present:
        return {
            "eligible": False,
            "reason": (
                "no common real 15-minute "
                "bar on required start date"
            ),
            "gate_bars": len(
                gate_master
            ),
            "common_gate_bars": len(
                common
            ),
            "missing_gate_bars": (
                missing
            ),
            "allowed_full_window_missing": (
                allowed_missing
            ),
        }

    if impossible:
        maximum_possible_common = (
            len(master_times)
            - missing
        )

        maximum_possible_ratio = (
            maximum_possible_common
            / len(master_times)
        )

        return {
            "eligible": False,
            "reason": (
                "already missing "
                f"{missing:,} real bars "
                "inside preflight window; "
                "full-window allowance is only "
                f"{allowed_missing:,}; "
                "maximum possible final coverage "
                f"is {maximum_possible_ratio:.2%}"
            ),
            "gate_bars": len(
                gate_master
            ),
            "common_gate_bars": len(
                common
            ),
            "missing_gate_bars": (
                missing
            ),
            "allowed_full_window_missing": (
                allowed_missing
            ),
        }

    return {
        "eligible": True,
        "reason": "",
        "gate_bars": len(
            gate_master
        ),
        "common_gate_bars": len(
            common
        ),
        "missing_gate_bars": (
            missing
        ),
        "allowed_full_window_missing": (
            allowed_missing
        ),
    }


def preflight_failure_row(
    symbol: str,
    result: dict,
) -> dict:
    return {
        "symbol": symbol,
        "status": "FAILED",
        "failure_stage": (
            "INTRADAY_DENSITY_PREFLIGHT"
        ),
        "qdte_volume_exception": (
            symbol == "QDTE"
        ),
        "preflight_end": (
            PREFLIGHT_END.isoformat()
        ),
        "preflight_gate_bars": (
            result[
                "gate_bars"
            ]
        ),
        "preflight_common_bars": (
            result[
                "common_gate_bars"
            ]
        ),
        "preflight_missing_bars": (
            result[
                "missing_gate_bars"
            ]
        ),
        "full_window_missing_allowance": (
            result[
                "allowed_full_window_missing"
            ]
        ),
        "error": (
            "INTRADAY_PREFILTER: "
            + result[
                "reason"
            ]
        ),
    }


def parse_child(
    completed,
    symbol: str,
) -> dict:
    for line in reversed(
        completed.stdout.splitlines()
    ):
        if line.startswith(
            CHILD_PREFIX
        ):
            return json.loads(
                line[
                    len(
                        CHILD_PREFIX
                    ):
                ]
            )

    return {
        "symbol": symbol,
        "status": "FAILED",
        "qdte_volume_exception": (
            symbol == "QDTE"
        ),
        "error": (
            completed.stderr[-1500:]
            or completed.stdout[-1500:]
            or (
                "Child process returned "
                "no result."
            )
        ),
    }


def retryable_old_failure(
    row: dict,
) -> bool:
    if (
        row.get("status")
        != "FAILED"
    ):
        return False

    error = str(
        row.get(
            "error",
            "",
        )
    )

    return (
        "unsupported format string "
        "passed to NoneType.__format__"
        in error
    )


def cleanup_created_cache(
    *,
    symbol: str,
    had_bar: bool,
    had_manifest: bool,
) -> None:
    if symbol in {
        "QDTE",
        "XLE",
    }:
        return

    if not had_bar:
        try:
            cache_path(
                symbol
            ).unlink()
        except FileNotFoundError:
            pass

    if not had_manifest:
        try:
            manifest_path(
                symbol
            ).unlink()
        except FileNotFoundError:
            pass


def run_child(
    script: Path,
    symbol: str,
) -> dict:
    environment = dict(
        os.environ
    )

    environment[
        "QPX_FAST_SWEEP_CHILD"
    ] = "1"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--single",
            symbol,
        ],
        cwd=sweep.ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    return parse_child(
        completed,
        symbol,
    )


def controls_only() -> int:
    format_self_test()

    master = (
        qdte_master_times()
    )

    print(
        "FAST SWEEP V2 CONTROL TEST"
    )

    print(
        f"QDTE master bars       : "
        f"{len(master):,}"
    )

    required = math.ceil(
        len(master)
        * MINIMUM_BAR_OVERLAP
    )

    allowed = (
        len(master)
        - required
    )

    print(
        f"95% required bars      : "
        f"{required:,}"
    )

    print(
        f"Missing-bar allowance  : "
        f"{allowed:,}"
    )

    print(
        f"Intraday gate          : "
        f"{sweep.START} -> "
        f"{PREFLIGHT_END}"
    )

    for symbol in (
        "XLE",
        "QDTE",
    ):
        result = (
            intraday_preflight(
                symbol,
                master,
            )
        )

        if not result[
            "eligible"
        ]:
            raise RuntimeError(
                f"{symbol} control failed: "
                f"{result['reason']}"
            )

        print(
            f"{symbol:<6} PASS | "
            f"missing "
            f"{result['missing_gate_bars']:,} | "
            f"allowance "
            f"{result['allowed_full_window_missing']:,}"
        )

    print(
        "PROFIT-FACTOR FORMAT FIX: PASS"
    )

    print(
        "FAST SWEEP V2 CONTROLS: PASSED"
    )

    return 0


def parent_run() -> int:
    format_self_test()

    sweep.refresh_vix()

    universe = (
        sweep.alpaca_universe()
    )

    rows = (
        sweep.load_progress()
    )

    retry_symbols = [
        symbol
        for symbol, row
        in rows.items()
        if retryable_old_failure(
            row
        )
    ]

    for symbol in retry_symbols:
        rows.pop(
            symbol,
            None,
        )

    master = (
        qdte_master_times()
    )

    required = math.ceil(
        len(master)
        * MINIMUM_BAR_OVERLAP
    )

    allowed_missing = (
        len(master)
        - required
    )

    script = Path(
        __file__
    ).resolve()

    print(
        "=" * 92
    )
    print(
        "QPX FAST SWEEP V2"
    )
    print(
        "=" * 92
    )
    print(
        f"Universe               : "
        f"{len(universe):,}"
    )
    print(
        f"Existing recorded rows : "
        f"{len(rows):,}"
    )
    print(
        f"Retry format failures  : "
        f"{len(retry_symbols):,}"
    )
    print(
        f"Intraday gate          : "
        f"{sweep.START} -> "
        f"{PREFLIGHT_END}"
    )
    print(
        f"QDTE master bars       : "
        f"{len(master):,}"
    )
    print(
        f"95% missing allowance  : "
        f"{allowed_missing:,}"
    )
    print(
        "Early rejection        : "
        "ONLY WHEN 95% IS MATHEMATICALLY IMPOSSIBLE"
    )
    print(
        "Synthetic bars         : NONE"
    )
    print(
        "Profitability filter   : NONE"
    )
    print(
        "Survivor preflight bars: REUSED BY FULL BACKTEST"
    )
    print(
        "=" * 92
    )

    processed_now = 0

    for number, symbol in enumerate(
        universe,
        start=1,
    ):
        if symbol in rows:
            continue

        print(
            f"[{number}/{len(universe)}] "
            f"{symbol}: PREFLIGHT",
            flush=True,
        )

        bar_path = cache_path(
            symbol
        )

        man_path = manifest_path(
            symbol
        )

        had_bar = (
            bar_path.exists()
        )

        had_manifest = (
            man_path.exists()
        )

        try:
            preflight = (
                intraday_preflight(
                    symbol,
                    master,
                )
            )

        except Exception as exc:
            row = {
                "symbol": symbol,
                "status": "FAILED",
                "failure_stage": (
                    "INTRADAY_PREFLIGHT_ERROR"
                ),
                "qdte_volume_exception": (
                    symbol == "QDTE"
                ),
                "error": (
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
            }

            rows[
                symbol
            ] = row

            sweep.append_progress(
                row
            )

            cleanup_created_cache(
                symbol=symbol,
                had_bar=had_bar,
                had_manifest=had_manifest,
            )

            print(
                f"{symbol}: PREFLIGHT ERROR | "
                f"{row['error'][:260]}",
                flush=True,
            )

            continue

        if not preflight[
            "eligible"
        ]:
            row = (
                preflight_failure_row(
                    symbol,
                    preflight,
                )
            )

            rows[
                symbol
            ] = row

            sweep.append_progress(
                row
            )

            cleanup_created_cache(
                symbol=symbol,
                had_bar=had_bar,
                had_manifest=had_manifest,
            )

            print(
                f"{symbol}: EARLY REJECT | "
                f"{preflight['reason']}",
                flush=True,
            )

            processed_now += 1

        else:
            print(
                f"{symbol}: PREFLIGHT PASS | "
                f"missing "
                f"{preflight['missing_gate_bars']:,}/"
                f"{preflight['allowed_full_window_missing']:,} "
                f"allowed | FULL TEST",
                flush=True,
            )

            row = run_child(
                script,
                symbol,
            )

            rows[
                symbol
            ] = row

            sweep.append_progress(
                row
            )

            cleanup_created_cache(
                symbol=symbol,
                had_bar=had_bar,
                had_manifest=had_manifest,
            )

            processed_now += 1

            if (
                row.get("status")
                == "COMPLETE"
            ):
                print(
                    f"{symbol}: COMPLETE | "
                    f"net/yr "
                    f"${row['net_profit_per_year']:,.2f} | "
                    f"net "
                    f"${row['net_profit']:,.2f} | "
                    f"swing "
                    f"${row['realized_swing_pnl']:,.2f}",
                    flush=True,
                )

            else:
                print(
                    f"{symbol}: FAILED | "
                    f"{row.get('error', '')[:260]}",
                    flush=True,
                )

        if (
            processed_now
            and processed_now % 25
            == 0
        ):
            sweep.write_summary(
                rows,
                universe,
            )

            sweep.print_leaders(
                rows
            )

    sweep.write_summary(
        rows,
        universe,
    )

    sweep.print_leaders(
        rows,
        limit=25,
    )

    print(
        "FAST SWEEP V2 COMPLETE"
    )

    return 0


def main() -> int:
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--single",
        default="",
    )

    parser.add_argument(
        "--controls-only",
        action="store_true",
    )

    args = parser.parse_args()

    if args.controls_only:
        return controls_only()

    if args.single:
        symbol = (
            args.single
            .strip()
            .upper()
        )

        result = (
            sweep.run_one(
                symbol
            )
        )

        print(
            CHILD_PREFIX
            + json.dumps(
                result,
                sort_keys=True,
            )
        )

        return (
            0
            if result[
                "status"
            ]
            == "COMPLETE"
            else 1
        )

    return parent_run()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
