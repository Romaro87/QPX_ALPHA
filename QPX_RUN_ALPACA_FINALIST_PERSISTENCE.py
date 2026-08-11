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

from collections import OrderedDict
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import QPX_FIND_BEST_ALPACA_SWING as sweep
import QPX_RUN_ALPACA_FINALISTS as base
import QPX_RUN_SCENARIO as runner

from qpx_bot.scenario_config import (
    load_scenario,
)


ROOT = Path(__file__).resolve().parent

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_finalist_persistence_v1"
)

PROGRESS_FILE = (
    REPORT_ROOT
    / "progress.jsonl"
)

SUMMARY_JSON = (
    REPORT_ROOT
    / "summary.json"
)

PREFIX = "QPX_PERSIST_RESULT="

RUN_VERSION = (
    "candidate_v1_300_session_persistence_v1"
)

EXPECTED_FULL_RESULT_FP = (
    "081674828385c96fb55d4eca6bd6d924"
    "3c983355e60a078f312f6259d9d7abb0"
)

EXPECTED_DATASET_FP = (
    base.EXPECTED_DATASET_FP
)

EXPECTED_FINALIST_FP = (
    base.EXPECTED_FINALIST_FP
)


def atomic_json(
    path: Path,
    payload,
):
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


def hash_clock(
    timestamps,
):
    encoded = "".join(
        value.isoformat() + "\n"
        for value in timestamps
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def validate_full_result():
    if not base.SUMMARY_JSON.exists():
        raise RuntimeError(
            "Full-period finalist summary is missing."
        )

    summary = json.loads(
        base.SUMMARY_JSON.read_text(
            encoding="utf-8"
        )
    )

    if (
        summary.get(
            "result_fingerprint"
        )
        != EXPECTED_FULL_RESULT_FP
    ):
        raise RuntimeError(
            "Full finalist result fingerprint changed."
        )

    if len(summary["rows"]) != 14:
        raise RuntimeError(
            "Full finalist summary no longer has 14 rows."
        )

    return summary


def make_periods():
    finalists, _ = (
        base.load_manifests()
    )

    ordered, _ = (
        base.load_clock(
            finalists
        )
    )

    timestamps = [
        datetime.fromisoformat(
            value
        )
        for value in ordered
    ]

    by_session = OrderedDict()

    for timestamp in timestamps:
        by_session.setdefault(
            timestamp.date(),
            [],
        ).append(timestamp)

    sessions = list(
        by_session
    )

    if len(sessions) != 600:
        raise RuntimeError(
            f"Expected 600 sessions, got {len(sessions)}."
        )

    definitions = {
        "EARLY": sessions[:300],
        "LATE": sessions[300:],
    }

    periods = {}

    for name, days in definitions.items():
        day_set = set(
            days
        )

        clock = [
            timestamp
            for timestamp in timestamps
            if timestamp.date()
            in day_set
        ]

        if len(
            {
                value.date()
                for value in clock
            }
        ) != 300:
            raise RuntimeError(
                f"{name}: session split failed."
            )

        periods[name] = {
            "name": name,
            "start": days[0],
            "end": days[-1],
            "sessions": 300,
            "clock": clock,
            "clock_strings": {
                value.isoformat()
                for value in clock
            },
            "bars": len(clock),
            "clock_sha256": (
                hash_clock(clock)
            ),
            "runtime_root": (
                base.FROZEN_ROOT
                / "persistence_runtime_v1"
                / name.lower()
            ),
        }

    early_days = {
        value.date()
        for value in periods[
            "EARLY"
        ][
            "clock"
        ]
    }

    late_days = {
        value.date()
        for value in periods[
            "LATE"
        ][
            "clock"
        ]
    }

    if early_days & late_days:
        raise RuntimeError(
            "Persistence periods overlap."
        )

    return periods


def runtime_bar_path(
    period,
    symbol,
):
    return (
        period[
            "runtime_root"
        ]
        / "shared"
        / "aggregate_15m"
        / (
            f"{base.safe_symbol(symbol)}"
            "_15M.csv"
        )
    )


def prepare_period_symbol(
    period,
    symbol,
):
    source = (
        base.runtime_bar_path(
            symbol
        )
    )

    if not source.exists():
        raise RuntimeError(
            f"{symbol}: full finalist runtime missing."
        )

    target = runtime_bar_path(
        period,
        symbol,
    )

    metadata = (
        target.with_suffix(
            target.suffix
            + ".persistence.json"
        )
    )

    source_hash = (
        base.sha256(
            source
        )
    )

    if (
        target.exists()
        and metadata.exists()
    ):
        try:
            existing = json.loads(
                metadata.read_text(
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
                == period[
                    "clock_sha256"
                ]
                and existing.get(
                    "bar_count"
                )
                == period["bars"]
                and existing.get(
                    "runtime_sha256"
                )
                == base.sha256(
                    target
                )
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

                if (
                    timestamp
                    not in period[
                        "clock_strings"
                    ]
                ):
                    continue

                if timestamp in seen:
                    raise RuntimeError(
                        f"{period['name']} "
                        f"{symbol}: duplicate timestamp."
                    )

                seen.add(
                    timestamp
                )

                writer.writerow(
                    row
                )

    if len(seen) != period["bars"]:
        temporary.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"{period['name']} {symbol}: "
            f"wrote {len(seen)} bars; "
            f"expected {period['bars']}."
        )

    if (
        seen
        != period[
            "clock_strings"
        ]
    ):
        temporary.unlink(
            missing_ok=True
        )

        raise RuntimeError(
            f"{period['name']} {symbol}: "
            "clock mismatch."
        )

    temporary.replace(
        target
    )

    atomic_json(
        metadata,
        {
            "schema_version": 1,
            "run_version": (
                RUN_VERSION
            ),
            "period": (
                period["name"]
            ),
            "symbol": symbol,
            "source_sha256": (
                source_hash
            ),
            "clock_sha256": (
                period[
                    "clock_sha256"
                ]
            ),
            "bar_count": (
                period["bars"]
            ),
            "runtime_sha256": (
                base.sha256(
                    target
                )
            ),
            "synthetic_data": False,
            "forward_fill": False,
            "timestamp_substitution": False,
        },
    )


def prepare_period_runtime(
    period,
    symbols,
):
    for symbol in symbols:
        prepare_period_symbol(
            period,
            symbol,
        )

    shared = (
        period[
            "runtime_root"
        ]
        / "shared"
    )

    shared.mkdir(
        parents=True,
        exist_ok=True,
    )

    source_shared = (
        base.RUNTIME_ROOT
        / "shared"
    )

    for name in (
        "CBOE_VIX_DAILY.csv",
        "QDTE_DIVIDENDS.csv",
        "QDTE_DIVIDENDS.csv.manifest.json",
    ):
        source = (
            source_shared
            / name
        )

        if not source.exists():
            if name.endswith(
                ".manifest.json"
            ):
                continue

            raise RuntimeError(
                f"Support file missing: {source}"
            )

        target = (
            shared
            / name
        )

        if (
            not target.exists()
            or base.sha256(
                target
            )
            != base.sha256(
                source
            )
        ):
            temporary = target.with_suffix(
                target.suffix + ".tmp"
            )

            shutil.copyfile(
                source,
                temporary,
            )

            temporary.replace(
                target
            )


def setup():
    full = validate_full_result()

    finalists, _ = (
        base.prepare_runtime()
    )

    periods = make_periods()

    symbols = list(
        finalists[
            "comparison_symbols"
        ]
    )

    for period in periods.values():
        prepare_period_runtime(
            period,
            symbols,
        )

    return (
        full,
        finalists,
        periods,
        symbols,
    )


def child_run(
    period_name,
    symbol,
):
    (
        _,
        finalists,
        periods,
        symbols,
    ) = setup()

    if period_name not in periods:
        raise RuntimeError(
            f"Unknown period: {period_name}"
        )

    period = periods[
        period_name
    ]

    symbol = (
        symbol.strip().upper()
    )

    if symbol not in symbols:
        raise RuntimeError(
            f"Unknown symbol: {symbol}"
        )

    payload = (
        sweep.scenario_payload(
            symbol
        )
    )

    output = io.StringIO()

    with tempfile.TemporaryDirectory(
        prefix="qpx_persistence_"
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

        source = runner.build_source(
            scenario,
            start=period["start"],
            end=period["end"],
        )

        source = (
            runner.adapt_source_for_provider(
                source,
                scenario=scenario,
                provider_root=(
                    period[
                        "runtime_root"
                    ]
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
            "qpx_finalist_persistence_v1/"
            + period_name.lower()
            + "/"
            + symbol.lower()
        )

        if source.count(
            old_report
        ) != 1:
            raise RuntimeError(
                "Could not isolate persistence "
                "report folder."
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
        raise RuntimeError(
            f"{period_name} {symbol}: "
            "result artifact missing."
        )

    result_path = Path(
        match.group(1).strip()
    ).expanduser()

    if not result_path.is_absolute():
        result_path = (
            ROOT
            / result_path
        ).resolve()

    result = json.loads(
        result_path.read_text(
            encoding="utf-8"
        )
    )

    if int(
        result[
            "common_test_bars"
        ]
    ) != period["bars"]:
        raise RuntimeError(
            f"{period_name} {symbol}: "
            "bar-count mismatch."
        )

    if int(
        result[
            "test_sessions"
        ]
    ) != 300:
        raise RuntimeError(
            f"{period_name} {symbol}: "
            "session-count mismatch."
        )

    if (
        result[
            "actual_start"
        ]
        != period[
            "start"
        ].isoformat()
        or result[
            "actual_end"
        ]
        != period[
            "end"
        ].isoformat()
    ):
        raise RuntimeError(
            f"{period_name} {symbol}: "
            "date-range mismatch."
        )

    span_days = (
        period["end"]
        - period["start"]
    ).days

    years = (
        span_days
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

    pf = None

    try:
        candidate = float(
            raw_pf
        )

        if math.isfinite(
            candidate
        ):
            pf = candidate

    except (
        TypeError,
        ValueError,
    ):
        pass

    row = {
        "run_version": (
            RUN_VERSION
        ),
        "status": "COMPLETE",
        "period": period_name,
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
        "full_result_fingerprint": (
            EXPECTED_FULL_RESULT_FP
        ),
        "clock_sha256": (
            period[
                "clock_sha256"
            ]
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
            period["bars"]
        ),
        "sessions": 300,
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
        "profit_factor": pf,
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

        key = (
            str(
                row.get(
                    "period",
                    "",
                )
            ),
            str(
                row.get(
                    "symbol",
                    "",
                )
            ).upper(),
        )

        if all(key):
            latest[key] = row

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


def is_current(
    row,
    period,
):
    return (
        row.get("status")
        == "COMPLETE"
        and row.get(
            "run_version"
        )
        == RUN_VERSION
        and row.get(
            "clock_sha256"
        )
        == period[
            "clock_sha256"
        ]
        and int(
            row.get(
                "sessions",
                0,
            )
        )
        == 300
        and int(
            row.get(
                "common_bars",
                0,
            )
        )
        == period["bars"]
    )


def parent_run():
    (
        full,
        finalists,
        periods,
        symbols,
    ) = setup()

    latest = read_progress()

    print(
        "FINALIST PERSISTENCE RUN"
    )
    print(
        "Full-result winner      :",
        full[
            "rows"
        ][0][
            "symbol"
        ],
    )

    for name in (
        "EARLY",
        "LATE",
    ):
        period = periods[
            name
        ]

        print(
            f"{name:<6}                  : "
            f"{period['start']} -> "
            f"{period['end']} | "
            f"{period['bars']:,} bars | "
            "300 sessions"
        )

    print(
        "Network fetch          : DISABLED"
    )
    print()

    total = 28
    counter = 0

    for period_name in (
        "EARLY",
        "LATE",
    ):
        period = periods[
            period_name
        ]

        for symbol in symbols:
            counter += 1

            key = (
                period_name,
                symbol,
            )

            existing = latest.get(
                key
            )

            if (
                existing
                and is_current(
                    existing,
                    period,
                )
            ):
                print(
                    f"[{counter:02d}/{total}] "
                    f"{period_name:<5} "
                    f"{symbol:<6} RESUME HIT"
                )

                continue

            env = dict(
                os.environ
            )

            old = env.get(
                "PYTHONPATH",
                "",
            )

            env[
                "PYTHONPATH"
            ] = (
                str(ROOT)
                if not old
                else (
                    str(ROOT)
                    + os.pathsep
                    + old
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
                    "--child-period",
                    period_name,
                    "--child-symbol",
                    symbol,
                ],
                cwd=ROOT,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            if process.returncode != 0:
                print(
                    f"STOP: {period_name} "
                    f"{symbol} failed."
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
                    "Child result marker missing."
                )

            row = json.loads(
                result_line
            )

            append_progress(
                row
            )

            latest[key] = row

            print(
                f"[{counter:02d}/{total}] "
                f"{period_name:<5} "
                f"{symbol:<6} COMPLETE | "
                f"net/yr "
                f"${row['net_profit_per_year']:,.2f} | "
                f"DD "
                f"{row['maximum_drawdown']:.2%}"
            )

    latest = read_progress()

    full_rows = {
        row["symbol"]: row
        for row in full[
            "rows"
        ]
    }

    records = []

    for full_rank, full_row in enumerate(
        full["rows"],
        start=1,
    ):
        symbol = full_row[
            "symbol"
        ]

        early = latest[
            (
                "EARLY",
                symbol,
            )
        ]

        late = latest[
            (
                "LATE",
                symbol,
            )
        ]

        if (
            not is_current(
                early,
                periods["EARLY"],
            )
            or not is_current(
                late,
                periods["LATE"],
            )
        ):
            raise RuntimeError(
                f"{symbol}: incomplete persistence result."
            )

        if (
            early[
                "net_profit"
            ] > 0
            and late[
                "net_profit"
            ] > 0
        ):
            status = (
                "POSITIVE_BOTH"
            )

        elif (
            early[
                "net_profit"
            ] > 0
        ):
            status = (
                "LATE_NEGATIVE"
            )

        elif (
            late[
                "net_profit"
            ] > 0
        ):
            status = (
                "EARLY_NEGATIVE"
            )

        else:
            status = (
                "NEGATIVE_BOTH"
            )

        records.append(
            {
                "symbol": symbol,
                "role": (
                    full_row["role"]
                ),
                "full_rank": (
                    full_rank
                ),
                "full_net_profit_per_year": (
                    full_row[
                        "net_profit_per_year"
                    ]
                ),
                "full_maximum_drawdown": (
                    full_row[
                        "maximum_drawdown"
                    ]
                ),
                "early": early,
                "late": late,
                "persistence_status": (
                    status
                ),
            }
        )

    core = {
        "schema_version": 1,
        "run_version": (
            RUN_VERSION
        ),
        "status": "COMPLETE",
        "full_result_fingerprint": (
            EXPECTED_FULL_RESULT_FP
        ),
        "dataset_fingerprint": (
            EXPECTED_DATASET_FP
        ),
        "periods": {
            name: {
                "start": (
                    period[
                        "start"
                    ].isoformat()
                ),
                "end": (
                    period[
                        "end"
                    ].isoformat()
                ),
                "bars": (
                    period["bars"]
                ),
                "sessions": 300,
                "clock_sha256": (
                    period[
                        "clock_sha256"
                    ]
                ),
            }
            for name, period
            in periods.items()
        },
        "records": records,
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

    print()
    print(
        "PERSISTENCE SPLIT      : COMPLETE"
    )
    print(
        "EARLY                  :",
        periods["EARLY"]["start"],
        "->",
        periods["EARLY"]["end"],
        "|",
        f"{periods['EARLY']['bars']:,}",
        "bars | 300 sessions",
    )
    print(
        "LATE                   :",
        periods["LATE"]["start"],
        "->",
        periods["LATE"]["end"],
        "|",
        f"{periods['LATE']['bars']:,}",
        "bars | 300 sessions",
    )
    print()

    for record in records:
        early = record["early"]
        late = record["late"]

        print(
            f"{record['full_rank']:>2}. "
            f"{record['symbol']:<6} | "
            f"early "
            f"${early['net_profit_per_year']:>8,.2f}/yr "
            f"DD {early['maximum_drawdown']:>6.2%} | "
            f"late "
            f"${late['net_profit_per_year']:>8,.2f}/yr "
            f"DD {late['maximum_drawdown']:>6.2%} | "
            f"{record['persistence_status']}"
        )

    print()
    print(
        "PERSISTENCE FINGERPRINT:",
        core[
            "result_fingerprint"
        ],
    )
    print(
        "SUMMARY JSON           :",
        SUMMARY_JSON,
    )


def plan():
    full = validate_full_result()

    finalists, _ = (
        base.load_manifests()
    )

    periods = make_periods()

    print(
        "PERSISTENCE PLAN       : PASSED"
    )
    print(
        "RAW FULL WINNER        :",
        full["rows"][0]["symbol"],
    )
    print(
        "SYMBOLS                :",
        len(
            finalists[
                "comparison_symbols"
            ]
        ),
    )

    for name in (
        "EARLY",
        "LATE",
    ):
        period = periods[name]

        print(
            f"{name:<6}                  : "
            f"{period['start']} -> "
            f"{period['end']} | "
            f"{period['bars']:,} bars | "
            "300 sessions"
        )

    print(
        "NETWORK FETCH          : DISABLED"
    )
    print(
        "FRESH CAPITAL EACH HALF: $1,300"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan",
        action="store_true",
    )

    parser.add_argument(
        "--child-period",
    )

    parser.add_argument(
        "--child-symbol",
    )

    args = parser.parse_args()

    if args.plan:
        plan()
        return

    if (
        args.child_period
        and args.child_symbol
    ):
        child_run(
            args.child_period,
            args.child_symbol,
        )

        return

    parent_run()


if __name__ == "__main__":
    main()
