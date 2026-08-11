from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import QPX_FIND_BEST_ALPACA_SWING as sweep
import QPX_RUN_SCENARIO as runner

from qpx_bot.scenario_config import (
    load_scenario,
)


ROOT = Path(__file__).resolve().parent

START = date(2024, 3, 7)
END = date(2026, 8, 7)

FINALIST_MANIFEST = (
    ROOT
    / "qpx_bot"
    / "research_universes"
    / "alpaca_finalists_top10_controls_v1.json"
)

FROZEN_ROOT = (
    ROOT
    / "research_data"
    / "qpx_frozen_alpaca_top100_v1"
)

DATASET_MANIFEST = (
    FROZEN_ROOT
    / "dataset_manifest.json"
)

RUNTIME_ROOT = (
    FROZEN_ROOT
    / "finalist_runtime_top10_controls_v1"
)

RUNTIME_BARS = (
    RUNTIME_ROOT
    / "shared"
    / "aggregate_15m"
)

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_finalist_identical_clock_v1"
)

PROGRESS_FILE = (
    REPORT_ROOT
    / "progress.jsonl"
)

SUMMARY_JSON = (
    REPORT_ROOT
    / "summary.json"
)

SUMMARY_CSV = (
    REPORT_ROOT
    / "summary.csv"
)

PREFIX = "QPX_FINALIST_RESULT="

RUN_VERSION = (
    "identical_clock_candidate_v1_v1"
)

EXPECTED_FINALIST_FP = (
    "7fea07bb3e25695ab5704e5c437c3db8"
    "174671708cf7132560e57c9f560e3d41"
)

EXPECTED_DATASET_FP = (
    "1a0d8d772b02079ee340109811d38678"
    "c73053f9a55e2fb3d3b5b96e484c5007"
)

EXPECTED_CLOCK_SHA = (
    "407101d2ff6469f8434fdff359405b269"
    "20821a8f3d0d1df2147952bd9caf7d4"
)

EXPECTED_BARS = 14527
EXPECTED_SESSIONS = 600


def safe_symbol(
    symbol: str,
) -> str:
    return (
        symbol.strip().upper()
        .replace("^", "")
        .replace(":", "_")
        .replace("/", "_")
    )


def sha256(
    path: Path,
) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(
                1024 * 1024
            ),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def atomic_json(
    path: Path,
    payload,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(path)


def load_manifests():
    finalists = json.loads(
        FINALIST_MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    dataset = json.loads(
        DATASET_MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    if (
        finalists.get(
            "manifest_fingerprint"
        )
        != EXPECTED_FINALIST_FP
    ):
        raise RuntimeError(
            "Finalist manifest fingerprint changed."
        )

    if (
        finalists.get(
            "dataset_fingerprint"
        )
        != EXPECTED_DATASET_FP
    ):
        raise RuntimeError(
            "Finalist dataset fingerprint changed."
        )

    if (
        dataset.get(
            "dataset_fingerprint"
        )
        != EXPECTED_DATASET_FP
    ):
        raise RuntimeError(
            "Frozen dataset fingerprint changed."
        )

    if (
        finalists["clock"]["sha256"]
        != EXPECTED_CLOCK_SHA
    ):
        raise RuntimeError(
            "Finalist clock hash changed."
        )

    if (
        finalists["clock"]["bars"]
        != EXPECTED_BARS
    ):
        raise RuntimeError(
            "Finalist clock bar count changed."
        )

    if (
        finalists["clock"]["sessions"]
        != EXPECTED_SESSIONS
    ):
        raise RuntimeError(
            "Finalist clock session count changed."
        )

    return finalists, dataset


def load_clock(
    finalists,
):
    path = (
        ROOT
        / finalists[
            "clock"
        ][
            "path"
        ]
    )

    if not path.exists():
        raise RuntimeError(
            f"Finalist clock missing: {path}"
        )

    if sha256(path) != EXPECTED_CLOCK_SHA:
        raise RuntimeError(
            "Finalist clock file hash mismatch."
        )

    ordered = []

    with path.open(
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        reader = csv.DictReader(
            handle
        )

        for row in reader:
            value = str(
                row["TimestampMarket"]
            ).strip()

            if value:
                ordered.append(value)

    if len(ordered) != EXPECTED_BARS:
        raise RuntimeError(
            "Finalist clock row count mismatch."
        )

    if len(set(ordered)) != EXPECTED_BARS:
        raise RuntimeError(
            "Finalist clock contains duplicates."
        )

    return ordered, set(ordered)


def source_bar_path(
    symbol: str,
) -> Path:
    return (
        FROZEN_ROOT
        / "bars"
        / f"{safe_symbol(symbol)}_15M.csv"
    )


def runtime_bar_path(
    symbol: str,
) -> Path:
    return (
        RUNTIME_BARS
        / f"{safe_symbol(symbol)}_15M.csv"
    )


def build_runtime_symbol(
    *,
    symbol,
    dataset,
    clock_set,
):
    source = source_bar_path(
        symbol
    )

    metadata = dataset[
        "symbols"
    ][
        symbol
    ]

    if not source.exists():
        raise RuntimeError(
            f"{symbol}: frozen source file missing."
        )

    if (
        sha256(source)
        != metadata["sha256"]
    ):
        raise RuntimeError(
            f"{symbol}: frozen source hash mismatch."
        )

    target = runtime_bar_path(
        symbol
    )

    runtime_manifest = (
        target.with_suffix(
            target.suffix
            + ".runtime.json"
        )
    )

    source_hash = metadata[
        "sha256"
    ]

    if (
        target.exists()
        and runtime_manifest.exists()
    ):
        try:
            existing = json.loads(
                runtime_manifest.read_text(
                    encoding="utf-8"
                )
            )

            if (
                existing.get(
                    "source_sha256"
                )
                == source_hash
                and existing.get(
                    "clock_sha256"
                )
                == EXPECTED_CLOCK_SHA
                and existing.get(
                    "bar_count"
                )
                == EXPECTED_BARS
                and existing.get(
                    "runtime_sha256"
                )
                == sha256(target)
            ):
                return

        except Exception:
            pass

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = target.with_suffix(
        target.suffix + ".tmp"
    )

    seen = set()
    written = 0

    with source.open(
        newline="",
        encoding="utf-8-sig",
    ) as source_handle:
        reader = csv.DictReader(
            source_handle
        )

        fields = list(
            reader.fieldnames or []
        )

        required = {
            "TimestampMarket",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        if not required.issubset(
            set(fields)
        ):
            raise RuntimeError(
                f"{symbol}: invalid frozen columns."
            )

        with temporary.open(
            "w",
            newline="",
            encoding="utf-8",
        ) as target_handle:
            writer = csv.DictWriter(
                target_handle,
                fieldnames=fields,
            )

            writer.writeheader()

            for row in reader:
                timestamp = str(
                    row[
                        "TimestampMarket"
                    ]
                ).strip()

                if timestamp not in clock_set:
                    continue

                if timestamp in seen:
                    raise RuntimeError(
                        f"{symbol}: duplicate clock timestamp."
                    )

                seen.add(
                    timestamp
                )

                writer.writerow(
                    row
                )

                written += 1

    if written != EXPECTED_BARS:
        temporary.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"{symbol}: identical-clock extraction "
            f"produced {written} bars; "
            f"expected {EXPECTED_BARS}."
        )

    if seen != clock_set:
        temporary.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"{symbol}: extracted timestamps "
            "do not exactly equal frozen clock."
        )

    temporary.replace(
        target
    )

    atomic_json(
        runtime_manifest,
        {
            "schema_version": 1,
            "run_version": (
                RUN_VERSION
            ),
            "symbol": symbol,
            "source_sha256": (
                source_hash
            ),
            "clock_sha256": (
                EXPECTED_CLOCK_SHA
            ),
            "bar_count": (
                EXPECTED_BARS
            ),
            "runtime_sha256": (
                sha256(target)
            ),
            "synthetic_data": False,
            "forward_fill": False,
            "timestamp_substitution": False,
        },
    )


def prepare_runtime():
    finalists, dataset = (
        load_manifests()
    )

    _, clock_set = load_clock(
        finalists
    )

    symbols = list(
        finalists[
            "comparison_symbols"
        ]
    )

    if len(symbols) != 14:
        raise RuntimeError(
            "Expected exactly 14 comparison symbols."
        )

    for symbol in symbols:
        build_runtime_symbol(
            symbol=symbol,
            dataset=dataset,
            clock_set=clock_set,
        )

    shared = (
        RUNTIME_ROOT
        / "shared"
    )

    shared.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name in (
        "CBOE_VIX_DAILY.csv",
        "QDTE_DIVIDENDS.csv",
        "QDTE_DIVIDENDS.csv.manifest.json",
    ):
        source = (
            FROZEN_ROOT
            / "support"
            / name
        )

        if not source.exists():
            if name.endswith(
                ".manifest.json"
            ):
                continue

            raise RuntimeError(
                f"Frozen support file missing: {source}"
            )

        target = (
            shared
            / name
        )

        if (
            not target.exists()
            or sha256(target)
            != sha256(source)
        ):
            temporary = (
                target.with_suffix(
                    target.suffix
                    + ".tmp"
                )
            )

            shutil.copyfile(
                source,
                temporary,
            )

            temporary.replace(
                target
            )

    return finalists, dataset


def plan():
    finalists, dataset = (
        load_manifests()
    )

    ordered, clock_set = load_clock(
        finalists
    )

    if len(clock_set) != len(
        ordered
    ):
        raise RuntimeError(
            "Clock uniqueness validation failed."
        )

    for symbol in finalists[
        "comparison_symbols"
    ]:
        source = source_bar_path(
            symbol
        )

        if not source.exists():
            raise RuntimeError(
                f"{symbol}: frozen source missing."
            )

        if (
            sha256(source)
            != dataset[
                "symbols"
            ][
                symbol
            ][
                "sha256"
            ]
        ):
            raise RuntimeError(
                f"{symbol}: source hash mismatch."
            )

    print(
        "FINALIST RUN PLAN      : PASSED"
    )
    print(
        "SYMBOLS                :",
        len(
            finalists[
                "comparison_symbols"
            ]
        ),
    )
    print(
        "CLOCK BARS             :",
        f"{EXPECTED_BARS:,}",
    )
    print(
        "CLOCK SESSIONS         :",
        EXPECTED_SESSIONS,
    )
    print(
        "DATASET FINGERPRINT    :",
        EXPECTED_DATASET_FP,
    )
    print(
        "CLOCK SHA256           :",
        EXPECTED_CLOCK_SHA,
    )
    print(
        "NETWORK DATA FETCH     : DISABLED"
    )
    print(
        "SYNTHETIC DATA         : DISABLED"
    )


def child_run(
    symbol: str,
):
    finalists, _ = (
        prepare_runtime()
    )

    symbol = (
        symbol.strip().upper()
    )

    if symbol not in finalists[
        "comparison_symbols"
    ]:
        raise RuntimeError(
            f"Unknown finalist symbol: {symbol}"
        )

    payload = (
        sweep.scenario_payload(
            symbol
        )
    )

    output = io.StringIO()

    with tempfile.TemporaryDirectory(
        prefix="qpx_finalist_"
    ) as folder:
        scenario_path = (
            Path(folder)
            / "scenario.json"
        )

        scenario_path.write_text(
            json.dumps(
                payload,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        scenario = load_scenario(
            scenario_path
        )

        source = (
            runner.build_source(
                scenario,
                start=START,
                end=END,
            )
        )

        source = (
            runner.adapt_source_for_provider(
                source,
                scenario=scenario,
                provider_root=(
                    RUNTIME_ROOT
                ),
            )
        )

        source = (
            sweep.patch_generated_source(
                source,
                symbol,
            )
        )

        old_report = (
            "qpx_scenario_"
            + runner.safe_name(
                scenario.name
            )
        )

        new_report = (
            "qpx_finalist_identical_clock_v1/"
            + symbol.lower()
        )

        count = source.count(
            old_report
        )

        if count != 1:
            raise RuntimeError(
                "Could not isolate finalist "
                f"report folder for {symbol}. "
                f"Found {count} report markers."
            )

        source = source.replace(
            old_report,
            new_report,
            1,
        )

        namespace = {
            "__name__": "__main__",
            "__file__": str(
                runner.REFERENCE_RUNNER
            ),
        }

        with redirect_stdout(
            output
        ):
            exec(
                compile(
                    source,
                    str(
                        runner.REFERENCE_RUNNER
                    ),
                    "exec",
                ),
                namespace,
            )

    text = output.getvalue()

    match = sweep.RESULT_RE.search(
        text
    )

    if not match:
        tail = "\n".join(
            text.splitlines()[-30:]
        )

        raise RuntimeError(
            "Backtest did not report "
            f"a result artifact for {symbol}.\n"
            + tail
        )

    result_path = Path(
        match.group(1).strip()
    ).expanduser()

    if not result_path.is_absolute():
        result_path = (
            ROOT
            / result_path
        ).resolve()

    if not result_path.exists():
        raise RuntimeError(
            f"{symbol}: result artifact missing."
        )

    result = json.loads(
        result_path.read_text(
            encoding="utf-8"
        )
    )

    if int(
        result[
            "common_test_bars"
        ]
    ) != EXPECTED_BARS:
        raise RuntimeError(
            f"{symbol}: engine used "
            f"{result['common_test_bars']} bars, "
            f"expected {EXPECTED_BARS}."
        )

    if int(
        result[
            "test_sessions"
        ]
    ) != EXPECTED_SESSIONS:
        raise RuntimeError(
            f"{symbol}: engine used "
            f"{result['test_sessions']} sessions, "
            f"expected {EXPECTED_SESSIONS}."
        )

    if (
        result[
            "actual_start"
        ]
        != START.isoformat()
        or result[
            "actual_end"
        ]
        != END.isoformat()
    ):
        raise RuntimeError(
            f"{symbol}: engine date range changed."
        )

    years = (
        (END - START).days
        / 365.2425
    )

    net_profit = float(
        result[
            "net_profit"
        ]
    )

    raw_pf = result.get(
        "profit_factor"
    )

    pf_value = None
    pf_infinite = False

    if raw_pf is not None:
        try:
            candidate_pf = float(
                raw_pf
            )

            if math.isfinite(
                candidate_pf
            ):
                pf_value = (
                    candidate_pf
                )
            elif candidate_pf > 0:
                pf_infinite = True

        except (
            TypeError,
            ValueError,
        ):
            pass

    row = {
        "run_version": RUN_VERSION,
        "status": "COMPLETE",
        "symbol": symbol,
        "role": (
            "CONTROL"
            if symbol
            in finalists["controls"]
            else "FINALIST"
        ),
        "dataset_fingerprint": (
            EXPECTED_DATASET_FP
        ),
        "finalist_manifest_fingerprint": (
            EXPECTED_FINALIST_FP
        ),
        "clock_sha256": (
            EXPECTED_CLOCK_SHA
        ),
        "actual_start": (
            result[
                "actual_start"
            ]
        ),
        "actual_end": (
            result[
                "actual_end"
            ]
        ),
        "common_bars": (
            EXPECTED_BARS
        ),
        "sessions": (
            EXPECTED_SESSIONS
        ),
        "closed_trades": int(
            result[
                "closed_trades"
            ]
        ),
        "win_rate": float(
            result[
                "win_rate"
            ]
        ),
        "profit_factor": (
            pf_value
        ),
        "profit_factor_infinite": (
            pf_infinite
        ),
        "closed_swing_trade_pnl": float(
            result[
                "closed_swing_trade_pnl"
            ]
        ),
        "income_rebalance_realized_pnl": float(
            result[
                "income_rebalance_realized_pnl"
            ]
        ),
        "total_realized_pnl": float(
            result[
                "total_realized_pnl"
            ]
        ),
        "qdte_distributions": float(
            result[
                "qdte_distributions_received"
            ]
        ),
        "net_profit": (
            net_profit
        ),
        "net_profit_per_year": (
            net_profit
            / years
        ),
        "ending_equity": float(
            result[
                "ending_equity"
            ]
        ),
        "cagr": float(
            result[
                "flow_adjusted_cagr"
            ]
        ),
        "maximum_drawdown": float(
            result[
                "maximum_drawdown"
            ]
        ),
        "risk_rejections": int(
            result[
                "risk_rejections"
            ]
        ),
        "notional_adjustments": int(
            result[
                "notional_cap_adjustments"
            ]
        ),
        "result_artifact": str(
            result_path.relative_to(
                ROOT
            )
        ),
    }

    print(
        PREFIX
        + json.dumps(
            row,
            sort_keys=True,
            allow_nan=False,
        )
    )


def read_progress():
    latest = {}

    if not PROGRESS_FILE.exists():
        return latest

    for line in PROGRESS_FILE.read_text(
        encoding="utf-8"
    ).splitlines():
        try:
            row = json.loads(
                line
            )
        except json.JSONDecodeError:
            continue

        symbol = str(
            row.get(
                "symbol",
                "",
            )
        ).strip().upper()

        if symbol:
            latest[
                symbol
            ] = row

    return latest


def append_progress(
    row,
):
    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    with PROGRESS_FILE.open(
        "a",
        encoding="utf-8",
    ) as handle:
        handle.write(
            json.dumps(
                row,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        )

        handle.flush()

        os.fsync(
            handle.fileno()
        )


def row_current(
    row,
):
    return (
        row.get("status")
        == "COMPLETE"
        and row.get(
            "run_version"
        )
        == RUN_VERSION
        and row.get(
            "dataset_fingerprint"
        )
        == EXPECTED_DATASET_FP
        and row.get(
            "clock_sha256"
        )
        == EXPECTED_CLOCK_SHA
        and int(
            row.get(
                "common_bars",
                0,
            )
        )
        == EXPECTED_BARS
    )


def ranking_key(
    row,
):
    return (
        -float(
            row[
                "net_profit_per_year"
            ]
        ),
        -float(
            row[
                "net_profit"
            ]
        ),
        -float(
            row[
                "cagr"
            ]
        ),
        float(
            row[
                "maximum_drawdown"
            ]
        ),
        str(
            row[
                "symbol"
            ]
        ),
    )


def write_summary(
    rows,
):
    ordered = sorted(
        rows,
        key=ranking_key,
    )

    code_commit = (
        subprocess.check_output(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=ROOT,
            text=True,
        ).strip()
    )

    core = {
        "schema_version": 1,
        "run_version": (
            RUN_VERSION
        ),
        "status": (
            "COMPLETE"
        ),
        "dataset_fingerprint": (
            EXPECTED_DATASET_FP
        ),
        "finalist_manifest_fingerprint": (
            EXPECTED_FINALIST_FP
        ),
        "clock_sha256": (
            EXPECTED_CLOCK_SHA
        ),
        "common_bars": (
            EXPECTED_BARS
        ),
        "sessions": (
            EXPECTED_SESSIONS
        ),
        "code_commit": (
            code_commit
        ),
        "ranking_objective": (
            "NET_PORTFOLIO_PROFIT_PER_CALENDAR_YEAR"
        ),
        "rows": ordered,
    }

    encoded = json.dumps(
        core,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    core[
        "result_fingerprint"
    ] = hashlib.sha256(
        encoded
    ).hexdigest()

    atomic_json(
        SUMMARY_JSON,
        core,
    )

    SUMMARY_CSV.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with SUMMARY_CSV.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        fields = [
            "rank",
            "symbol",
            "role",
            "net_profit_per_year",
            "net_profit",
            "ending_equity",
            "closed_swing_trade_pnl",
            "income_rebalance_realized_pnl",
            "qdte_distributions",
            "cagr",
            "maximum_drawdown",
            "closed_trades",
            "win_rate",
            "profit_factor",
            "profit_factor_infinite",
        ]

        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
        )

        writer.writeheader()

        for rank, row in enumerate(
            ordered,
            start=1,
        ):
            writer.writerow(
                {
                    "rank": rank,
                    **{
                        field: row.get(
                            field
                        )
                        for field
                        in fields
                        if field
                        != "rank"
                    },
                }
            )

    return ordered, core


def format_pf(
    row,
):
    if row.get(
        "profit_factor_infinite"
    ):
        return "INF"

    value = row.get(
        "profit_factor"
    )

    if value is None:
        return "N/A"

    return f"{float(value):.3f}"


def parent_run():
    finalists, _ = (
        prepare_runtime()
    )

    symbols = list(
        finalists[
            "comparison_symbols"
        ]
    )

    latest = read_progress()

    print(
        "FINALIST IDENTICAL-CLOCK RUN"
    )
    print(
        "Symbols                :",
        len(symbols),
    )
    print(
        "Bars per instrument    :",
        f"{EXPECTED_BARS:,}",
    )
    print(
        "Sessions               :",
        EXPECTED_SESSIONS,
    )
    print(
        "Network fetch          : DISABLED"
    )
    print()

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):
        existing = latest.get(
            symbol
        )

        if (
            existing is not None
            and row_current(
                existing
            )
        ):
            print(
                f"[{index:02d}/14] "
                f"{symbol:<6} RESUME HIT | "
                f"net "
                f"${existing['net_profit']:,.2f}"
            )

            continue

        env = dict(
            os.environ
        )

        old_path = env.get(
            "PYTHONPATH",
            "",
        )

        env[
            "PYTHONPATH"
        ] = (
            str(ROOT)
            if not old_path
            else (
                str(ROOT)
                + os.pathsep
                + old_path
            )
        )

        process = subprocess.run(
            [
                sys.executable,
                str(
                    Path(
                        __file__
                    ).resolve()
                ),
                "--child",
                symbol,
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if process.returncode != 0:
            failure = {
                "run_version": (
                    RUN_VERSION
                ),
                "status": "FAILED",
                "symbol": symbol,
                "dataset_fingerprint": (
                    EXPECTED_DATASET_FP
                ),
                "clock_sha256": (
                    EXPECTED_CLOCK_SHA
                ),
                "error": (
                    process.stderr[
                        -4000:
                    ]
                    or process.stdout[
                        -4000:
                    ]
                ),
            }

            append_progress(
                failure
            )

            print(
                f"STOP: {symbol} "
                "finalist run failed."
            )

            if process.stderr:
                print(
                    process.stderr[
                        -4000:
                    ]
                )

            if process.stdout:
                print(
                    process.stdout[
                        -4000:
                    ]
                )

            raise SystemExit(1)

        result_line = None

        for line in (
            process.stdout
            .splitlines()
        ):
            if line.startswith(
                PREFIX
            ):
                result_line = (
                    line[
                        len(PREFIX):
                    ]
                )

        if result_line is None:
            raise RuntimeError(
                f"{symbol}: child result marker missing."
            )

        row = json.loads(
            result_line
        )

        append_progress(
            row
        )

        latest[
            symbol
        ] = row

        print(
            f"[{index:02d}/14] "
            f"{symbol:<6} COMPLETE | "
            f"net/yr "
            f"${row['net_profit_per_year']:,.2f} | "
            f"net "
            f"${row['net_profit']:,.2f} | "
            f"DD "
            f"{row['maximum_drawdown']:.2%}"
        )

    latest = read_progress()

    rows = []

    for symbol in symbols:
        row = latest.get(
            symbol
        )

        if (
            row is None
            or not row_current(
                row
            )
        ):
            raise RuntimeError(
                f"{symbol}: no valid COMPLETE result."
            )

        rows.append(
            row
        )

    ordered, summary = (
        write_summary(
            rows
        )
    )

    print()
    print(
        "FINALIST HEAD-TO-HEAD  : COMPLETE"
    )
    print(
        "IDENTICAL CLOCK BARS   :",
        f"{EXPECTED_BARS:,}",
    )
    print(
        "IDENTICAL SESSIONS     :",
        EXPECTED_SESSIONS,
    )
    print(
        "RANKING                : "
        "NET PROFIT PER CALENDAR YEAR"
    )
    print()

    for rank, row in enumerate(
        ordered,
        start=1,
    ):
        print(
            f"{rank:>2}. "
            f"{row['symbol']:<6} "
            f"{row['role']:<8} | "
            f"net/yr "
            f"${row['net_profit_per_year']:>8,.2f} | "
            f"net "
            f"${row['net_profit']:>8,.2f} | "
            f"swing "
            f"${row['closed_swing_trade_pnl']:>8,.2f} | "
            f"CAGR "
            f"{row['cagr']:>7.2%} | "
            f"DD "
            f"{row['maximum_drawdown']:>7.2%} | "
            f"trades "
            f"{row['closed_trades']:>3} | "
            f"PF "
            f"{format_pf(row)}"
        )

    print()
    print(
        "RAW OBJECTIVE WINNER   :",
        ordered[0][
            "symbol"
        ],
    )
    print(
        "RESULT FINGERPRINT     :",
        summary[
            "result_fingerprint"
        ],
    )
    print(
        "SUMMARY JSON           :",
        SUMMARY_JSON,
    )
    print(
        "SUMMARY CSV            :",
        SUMMARY_CSV,
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan",
        action="store_true",
    )

    parser.add_argument(
        "--child",
    )

    args = parser.parse_args()

    if args.plan:
        plan()
        return

    if args.child:
        child_run(
            args.child
        )
        return

    parent_run()


if __name__ == "__main__":
    main()
