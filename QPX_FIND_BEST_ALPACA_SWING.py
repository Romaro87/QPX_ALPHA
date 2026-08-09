from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

from contextlib import redirect_stdout
from datetime import date
from pathlib import Path

import QPX_RUN_SCENARIO as runner

import qpx_bot.actual_two_year_15m_six as research

from qpx_bot.alpaca_provider import (
    _qpx_original_sync as raw_alpaca_sync,
    cache_path,
    credentials,
    manifest_path,
    read_cache,
)

from qpx_bot.scenario_config import (
    load_scenario,
    validate_scenario,
)


ROOT = Path(__file__).resolve().parent

START = date(2024, 3, 7)
END = date(2026, 8, 7)

BASE = (
    ROOT
    / "qpx_bot"
    / "scenarios"
    / "candidate_v1_alpaca.json"
)

RUN_VERSION = "broad_intersection_v4"

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_best_alpaca_swing_qdte1300_thursday_v3"
)

UNIVERSE_FILE = (
    REPORT_ROOT
    / "universe.json"
)

PROGRESS_FILE = (
    REPORT_ROOT
    / "progress.jsonl"
)

SUMMARY_CSV = (
    REPORT_ROOT
    / "summary.csv"
)

SUMMARY_JSON = (
    REPORT_ROOT
    / "summary.json"
)

CHILD_PREFIX = "QPX_SWEEP_RESULT="

RESULT_RE = re.compile(
    r"^\s*Result\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)


def sweep_alpaca_sync(
    *,
    symbols,
    start,
    end,
    **kwargs,
):
    """
    Broad discovery screen.

    QDTE remains mandatory portfolio data, but
    another ticker no longer has to contain every
    QDTE timestamp.

    Each candidate is evaluated on the real
    timestamp intersection between itself and QDTE.

    No synthetic bars.
    No forward filling.
    No timestamp substitution.

    Broad-screen minimums:
        95% of QDTE real bars
        95% of QDTE real sessions
        coverage must reach both test endpoints

    Finalists will later be rerun on one identical
    frozen timestamp set before a winner is chosen.
    """

    MINIMUM_BAR_OVERLAP = 0.95
    MINIMUM_SESSION_OVERLAP = 0.95

    normalized = []

    for raw in symbols:
        symbol = (
            str(raw)
            .strip()
            .upper()
        )

        if (
            symbol
            and symbol not in normalized
        ):
            normalized.append(
                symbol
            )

    raw_alpaca_sync(
        symbols=normalized,
        start=start,
        end=end,
        **kwargs,
    )

    qdte_bars = read_cache(
        "QDTE"
    )

    qdte_times = {
        bar.start
        for bar in qdte_bars.values()
        if (
            start
            <= bar.start.date()
            <= end
        )
    }

    if not qdte_times:
        raise RuntimeError(
            "QDTE portfolio history is empty."
        )

    qdte_sessions = {
        timestamp.date()
        for timestamp in qdte_times
    }

    qdte_first = min(
        qdte_times
    )

    qdte_last = max(
        qdte_times
    )

    if qdte_first.date() != start:
        raise RuntimeError(
            "QDTE history does not reach "
            f"the requested start {start}."
        )

    if qdte_last.date() != end:
        raise RuntimeError(
            "QDTE history does not reach "
            f"the requested end {end}."
        )

    print(
        "QDTE PORTFOLIO DATA    : "
        f"{len(qdte_times):,} REAL BARS"
    )

    print(
        "QDTE PORTFOLIO SESSIONS: "
        f"{len(qdte_sessions):,}"
    )

    print(
        "Broad-screen rule      : "
        "REAL INTERSECTION >= 95%"
    )

    print(
        "Synthetic bars         : DISABLED"
    )

    for symbol in normalized:
        candidate_bars = read_cache(
            symbol
        )

        candidate_times = {
            bar.start
            for bar
            in candidate_bars.values()
            if (
                start
                <= bar.start.date()
                <= end
            )
        }

        if not candidate_times:
            raise RuntimeError(
                f"{symbol}: no usable "
                "Alpaca bars."
            )

        common_times = (
            qdte_times
            & candidate_times
        )

        if not common_times:
            raise RuntimeError(
                f"{symbol}: has no real "
                "timestamp overlap with QDTE."
            )

        common_sessions = {
            timestamp.date()
            for timestamp
            in common_times
        }

        bar_ratio = (
            len(common_times)
            / len(qdte_times)
        )

        session_ratio = (
            len(common_sessions)
            / len(qdte_sessions)
        )

        first_common = min(
            common_times
        )

        last_common = max(
            common_times
        )

        if (
            first_common.date()
            != start
        ):
            raise RuntimeError(
                f"{symbol}: insufficient "
                "full-window history. "
                f"First common date is "
                f"{first_common.date()}."
            )

        if (
            last_common.date()
            != end
        ):
            raise RuntimeError(
                f"{symbol}: insufficient "
                "full-window history. "
                f"Last common date is "
                f"{last_common.date()}."
            )

        if (
            bar_ratio
            < MINIMUM_BAR_OVERLAP
        ):
            raise RuntimeError(
                f"{symbol}: broad-screen "
                "bar coverage too low. "
                f"{len(common_times):,}/"
                f"{len(qdte_times):,} "
                f"({bar_ratio:.2%}); "
                "minimum is 95%."
            )

        if (
            session_ratio
            < MINIMUM_SESSION_OVERLAP
        ):
            raise RuntimeError(
                f"{symbol}: broad-screen "
                "session coverage too low. "
                f"{len(common_sessions):,}/"
                f"{len(qdte_sessions):,} "
                f"({session_ratio:.2%}); "
                "minimum is 95%."
            )

        missing_count = (
            len(qdte_times)
            - len(common_times)
        )

        print(
            f"{symbol:<8} BROAD SCREEN PASSED | "
            f"{len(common_times):,} bars | "
            f"{bar_ratio:.2%} bar overlap | "
            f"{session_ratio:.2%} sessions | "
            f"{missing_count:,} QDTE timestamps absent"
        )

    return {
        symbol: cache_path(
            symbol
        )
        for symbol in normalized
    }


runner.sync_alpaca = (
    sweep_alpaca_sync
)


def refresh_vix() -> None:
    import csv
    import math
    from datetime import datetime

    target = (
        ROOT
        / "research_data"
        / "qpx_alpaca_sip"
        / "shared"
        / "CBOE_VIX_DAILY.csv"
    )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    request = urllib.request.Request(
        research.CBOE_VIX_HISTORY_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "QPX-ALPACA-SWEEP"
            ),
            "Accept": "text/csv,*/*",
            "Accept-Encoding": "identity",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=30,
    ) as response:
        raw = response.read().decode(
            "utf-8-sig"
        )

    rows = csv.DictReader(
        raw.splitlines()
    )

    closes = {}

    for row in rows:
        raw_day = (
            row.get("DATE")
            or row.get("Date")
            or row.get("date")
        )

        raw_close = (
            row.get("CLOSE")
            or row.get("Close")
            or row.get("close")
        )

        if (
            not raw_day
            or raw_close is None
        ):
            continue

        day = None

        for fmt in (
            "%m/%d/%Y",
            "%Y-%m-%d",
            "%m/%d/%y",
        ):
            try:
                day = datetime.strptime(
                    raw_day.strip(),
                    fmt,
                ).date()
                break
            except ValueError:
                pass

        if day is None:
            continue

        try:
            close = float(
                raw_close
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

        if (
            math.isfinite(close)
            and close >= 0
        ):
            closes[day] = close

    if not closes:
        raise RuntimeError(
            "Cboe VIX download contained "
            "no usable observations."
        )

    temporary = target.with_suffix(
        ".csv.tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.writer(
            handle
        )

        writer.writerow(
            (
                "Date",
                "Close",
                "Source",
                "ObservationPolicy",
            )
        )

        for day in sorted(
            closes
        ):
            writer.writerow(
                (
                    day.isoformat(),
                    closes[day],
                    "OFFICIAL_CBOE",
                    (
                        "PREVIOUS_COMPLETED_"
                        "SESSION_DAILY_CLOSE"
                    ),
                )
            )

    temporary.replace(
        target
    )

    loaded = (
        research._read_vix_daily_cache(
            target
        )
    )

    validated = (
        research._validate_vix_daily_coverage(
            closes=loaded,
            start=START,
            end=END,
        )
    )

    ordered = sorted(
        validated
    )

    print(
        "CBOE VIX NORMALIZED    : "
        f"{len(validated):,} observations"
    )

    print(
        "CBOE VIX RANGE         : "
        f"{ordered[0]} -> "
        f"{ordered[-1]}"
    )

    print(
        "CBOE VIX CACHE         : VALIDATED"
    )

def alpaca_universe() -> list[str]:
    if UNIVERSE_FILE.exists():
        payload = json.loads(
            UNIVERSE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if (
            payload.get("version")
            == RUN_VERSION
        ):
            return list(
                payload["symbols"]
            )

    key, secret = credentials()

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
        "User-Agent": "QPX-ALPACA-SWEEP",
    }

    last_error = None

    for host in (
        "https://paper-api.alpaca.markets",
        "https://api.alpaca.markets",
    ):
        try:
            request = urllib.request.Request(
                (
                    host
                    + "/v2/assets"
                    + "?status=active"
                    + "&asset_class=us_equity"
                ),
                headers=headers,
            )

            with urllib.request.urlopen(
                request,
                timeout=45,
            ) as response:
                assets = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

            if not isinstance(
                assets,
                list,
            ):
                raise RuntimeError(
                    "Malformed Alpaca asset list."
                )

            symbols = []

            for asset in assets:
                if not isinstance(
                    asset,
                    dict,
                ):
                    continue

                if (
                    str(
                        asset.get(
                            "status",
                            "",
                        )
                    ).lower()
                    != "active"
                ):
                    continue

                if (
                    asset.get(
                        "tradable"
                    )
                    is not True
                ):
                    continue

                if (
                    str(
                        asset.get(
                            "class",
                            "",
                        )
                    ).lower()
                    != "us_equity"
                ):
                    continue

                if (
                    str(
                        asset.get(
                            "exchange",
                            "",
                        )
                    ).upper()
                    == "OTC"
                ):
                    continue

                symbol = str(
                    asset.get(
                        "symbol",
                        "",
                    )
                ).strip().upper()

                if (
                    not symbol
                    or symbol.startswith("^")
                ):
                    continue

                if symbol not in symbols:
                    symbols.append(symbol)

            if "XLE" not in symbols:
                raise RuntimeError(
                    "XLE is missing from "
                    "the Alpaca universe."
                )

            if "QDTE" not in symbols:
                raise RuntimeError(
                    "QDTE is missing from "
                    "the Alpaca universe."
                )

            preferred = [
                "XLE",
                "QDTE",
                "AMD",
                "AAPL",
                "MSFT",
                "NVDA",
            ]

            ordered = [
                symbol
                for symbol in preferred
                if symbol in symbols
            ]

            ordered.extend(
                sorted(
                    symbol
                    for symbol in symbols
                    if symbol not in ordered
                )
            )

            REPORT_ROOT.mkdir(
                parents=True,
                exist_ok=True,
            )

            UNIVERSE_FILE.write_text(
                json.dumps(
                    {
                        "version": RUN_VERSION,
                        "start": START.isoformat(),
                        "end": END.isoformat(),
                        "count": len(ordered),
                        "symbols": ordered,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            return ordered

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        "Unable to retrieve Alpaca "
        f"asset universe: {last_error}"
    )


def scenario_payload(
    symbol: str,
) -> dict:
    base = load_scenario(
        BASE
    )

    payload = (
        base.clone_payload()
    )

    safe = re.sub(
        r"[^A-Z0-9]+",
        "_",
        symbol.upper(),
    ).strip("_")

    payload["name"] = (
        "qdte1300_thursday_"
        + safe.lower()
    )

    payload["description"] = (
        "QPX Candidate V1 sweep. "
        "$1300 total starting capital; "
        "$1300 initially QDTE; "
        "$0 initial swing cash; "
        "zero external contributions; "
        "weekly Thursday rebalancing."
    )

    payload["revision"] = 1

    payload["symbols"][
        "candidate_symbols"
    ] = [symbol]

    payload["symbols"][
        "tradable_symbols"
    ] = [symbol]

    payload["capital"][
        "monthly_contribution"
    ] = 0.0

    payload["capital"][
        "starting_total_capital"
    ] = 1300.0

    payload["allocation"][
        "rebalance_frequency"
    ] = "weekly"

    if symbol == "QDTE":
        payload["entry"][
            "minimum_average_15m_volume"
        ] = 0

    validate_scenario(
        payload
    )

    return payload


def patch_generated_source(
    source: str,
    symbol: str,
) -> str:
    source, count = re.subn(
        (
            r"        starting_cash="
            r"[^\n]+,\n"
            r"        starting_swing_cash="
            r"[^\n]+,\n"
        ),
        (
            "        starting_cash=1300.0,\n"
            "        starting_swing_cash=0.0,\n"
        ),
        source,
        count=1,
    )

    if count != 1:
        raise RuntimeError(
            "Could not enforce the exact "
            "$1300 QDTE / $0 swing seed."
        )

    marker = (
        "source = inspect.getsource(\n"
        "    qpx.run_backtest\n"
        ")\n"
    )

    if source.count(marker) != 1:
        raise RuntimeError(
            "Historical engine patch "
            "point was not found."
        )

    init_old = '''    if config.allocation_rebalance_frequency == "daily":
        current_rebalance_key = first_test_time.date()
    elif config.allocation_rebalance_frequency == "weekly":
        iso = first_test_time.isocalendar()
        current_rebalance_key = (
            iso.year,
            iso.week,
        )
    else:
        current_rebalance_key = current_month'''

    init_new = '''    if config.allocation_rebalance_frequency == "daily":
        current_rebalance_key = first_test_time.date()
    elif config.allocation_rebalance_frequency == "weekly":
        iso = first_test_time.isocalendar()
        current_rebalance_key = (
            (iso.year, iso.week)
            if first_test_time.weekday() == 3
            else None
        )
    else:
        current_rebalance_key = current_month'''

    loop_old = '''        if config.allocation_rebalance_frequency == "daily":
            rebalance_key = bar_time.date()
        elif config.allocation_rebalance_frequency == "weekly":
            iso = bar_time.isocalendar()
            rebalance_key = (
                iso.year,
                iso.week,
            )
        else:
            rebalance_key = month_key

        rebalance_changed = (
            rebalance_key != current_rebalance_key
        )
        current_rebalance_key = rebalance_key'''

    loop_new = '''        if config.allocation_rebalance_frequency == "daily":
            rebalance_key = bar_time.date()
            rebalance_changed = (
                rebalance_key != current_rebalance_key
            )
            current_rebalance_key = rebalance_key

        elif config.allocation_rebalance_frequency == "weekly":
            iso = bar_time.isocalendar()
            rebalance_key = (
                iso.year,
                iso.week,
            )

            rebalance_changed = (
                bar_time.weekday() == 3
                and rebalance_key
                != current_rebalance_key
            )

            if rebalance_changed:
                current_rebalance_key = (
                    rebalance_key
                )

        else:
            rebalance_key = month_key

            rebalance_changed = (
                rebalance_key
                != current_rebalance_key
            )

            current_rebalance_key = (
                rebalance_key
            )'''

    phase_old = '''        if (
            not swing_only
            and (rebalance_changed or phase_changed)
        ):'''

    phase_new = '''        if (
            not swing_only
            and rebalance_changed
        ):'''

    injected = (
        marker
        + "\n"
        + "_qpx_init_old = "
        + repr(init_old)
        + "\n"
        + "_qpx_init_new = "
        + repr(init_new)
        + "\n"
        + "_qpx_loop_old = "
        + repr(loop_old)
        + "\n"
        + "_qpx_loop_new = "
        + repr(loop_new)
        + "\n"
        + "_qpx_phase_old = "
        + repr(phase_old)
        + "\n"
        + "_qpx_phase_new = "
        + repr(phase_new)
        + "\n\n"
        + "if source.count(_qpx_init_old) != 1:\n"
        + "    raise RuntimeError("
        + repr(
            "Thursday initialization "
            "patch failed."
        )
        + ")\n"
        + "if source.count(_qpx_loop_old) != 1:\n"
        + "    raise RuntimeError("
        + repr(
            "Thursday weekly "
            "rebalance patch failed."
        )
        + ")\n"
        + "if source.count(_qpx_phase_old) != 1:\n"
        + "    raise RuntimeError("
        + repr(
            "Thursday phase "
            "rebalance patch failed."
        )
        + ")\n"
        + "source = source.replace("
        + "_qpx_init_old, "
        + "_qpx_init_new, 1)\n"
        + "source = source.replace("
        + "_qpx_loop_old, "
        + "_qpx_loop_new, 1)\n"
        + "source = source.replace("
        + "_qpx_phase_old, "
        + "_qpx_phase_new, 1)\n"
    )

    if symbol == "QDTE":
        dividend_old = '''                cash = (
                    income_shares
                    * event.cash_amount
                )'''

        dividend_new = '''                swing_income_shares = (
                    portfolio.positions[
                        INCOME_SYMBOL
                    ].shares
                    if INCOME_SYMBOL
                    in portfolio.positions
                    else 0
                )

                cash = (
                    (
                        income_shares
                        + swing_income_shares
                    )
                    * event.cash_amount
                )'''

        injected += (
            "\n"
            + "_qpx_dividend_old = "
            + repr(dividend_old)
            + "\n"
            + "_qpx_dividend_new = "
            + repr(dividend_new)
            + "\n"
            + "if source.count("
            + "_qpx_dividend_old) != 1:\n"
            + "    raise RuntimeError("
            + repr(
                "QDTE swing dividend "
                "patch failed."
            )
            + ")\n"
            + "source = source.replace("
            + "_qpx_dividend_old, "
            + "_qpx_dividend_new, 1)\n"
        )

    source = source.replace(
        marker,
        injected,
        1,
    )

    return source


def run_one(
    symbol: str,
) -> dict:
    payload = scenario_payload(
        symbol
    )

    output = io.StringIO()

    try:
        with tempfile.TemporaryDirectory(
            prefix="qpx_sweep_"
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

            with redirect_stdout(
                output
            ):
                provider_root, _ = (
                    runner.prepare_scenario_data(
                        scenario,
                        start=START,
                        end=END,
                    )
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
                        provider_root=provider_root,
                    )
                )

                source = (
                    patch_generated_source(
                        source,
                        symbol,
                    )
                )

                namespace = {
                    "__name__": "__main__",
                    "__file__": str(
                        runner.REFERENCE_RUNNER
                    ),
                }

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

            match = RESULT_RE.search(
                text
            )

            if not match:
                raise RuntimeError(
                    "Backtest did not report "
                    "a result artifact."
                )

            result_path = Path(
                match.group(1).strip()
            ).expanduser()

            if not (
                result_path.is_absolute()
            ):
                result_path = (
                    ROOT
                    / result_path
                ).resolve()

            if not result_path.exists():
                raise RuntimeError(
                    "Reported result JSON "
                    "does not exist."
                )

            result = json.loads(
                result_path.read_text(
                    encoding="utf-8"
                )
            )

            actual_start = (
                date.fromisoformat(
                    result[
                        "actual_start"
                    ]
                )
            )

            actual_end = (
                date.fromisoformat(
                    result[
                        "actual_end"
                    ]
                )
            )

            if (
                actual_start != START
                or actual_end != END
            ):
                raise RuntimeError(
                    "Ticker does not have "
                    "the exact common "
                    "comparison window."
                )

            years = (
                (actual_end - actual_start).days
                / 365.2425
            )

            net_profit = float(
                result[
                    "net_profit"
                ]
            )

            swing_pnl = float(
                result[
                    "realized_swing_pnl"
                ]
            )

            return {
                "symbol": symbol,
                "status": "COMPLETE",
                "actual_start": (
                    actual_start.isoformat()
                ),
                "actual_end": (
                    actual_end.isoformat()
                ),
                "years": years,
                "common_bars": int(
                    result[
                        "common_test_bars"
                    ]
                ),
                "sessions": int(
                    result[
                        "test_sessions"
                    ]
                ),
                "qdte_master_bars": len(
                    {
                        bar.start
                        for bar
                        in read_cache(
                            "QDTE"
                        ).values()
                        if (
                            START
                            <= bar.start.date()
                            <= END
                        )
                    }
                ),
                "bar_overlap_pct": (
                    int(
                        result[
                            "common_test_bars"
                        ]
                    )
                    / len(
                        {
                            bar.start
                            for bar
                            in read_cache(
                                "QDTE"
                            ).values()
                            if (
                                START
                                <= bar.start.date()
                                <= END
                            )
                        }
                    )
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
                    result.get(
                        "profit_factor"
                    )
                ),
                "realized_swing_pnl": (
                    swing_pnl
                ),
                "swing_pnl_per_year": (
                    swing_pnl
                    / years
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
                "qdte_volume_exception": (
                    symbol == "QDTE"
                ),
                "fingerprint": (
                    scenario.fingerprint
                ),
                "error": "",
            }

    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "FAILED",
            "qdte_volume_exception": (
                symbol == "QDTE"
            ),
            "error": (
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
        }


def load_progress() -> dict:
    rows = {}

    if not PROGRESS_FILE.exists():
        return rows

    for line in (
        PROGRESS_FILE
        .read_text(
            encoding="utf-8"
        )
        .splitlines()
    ):
        try:
            row = json.loads(
                line
            )
        except json.JSONDecodeError:
            continue

        symbol = row.get(
            "symbol"
        )

        if not symbol:
            continue

        error = str(
            row.get(
                "error",
                "",
            )
        )

        obsolete_failure = (
            row.get("status") == "FAILED"
            and (
                "does not match the QDTE real-bar master clock"
                in error
                or
                "exact XLE/QDTE timestamp/session comparison set"
                in error
                or
                "XLE alignment control has not passed"
                in error
            )
        )

        if obsolete_failure:
            continue

        rows[symbol] = row

    return rows


def append_progress(
    row: dict,
) -> None:
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
            )
            + "\n"
        )


def ranking(
    rows: dict,
) -> list[dict]:
    return sorted(
        [
            row
            for row in rows.values()
            if row.get(
                "status"
            )
            == "COMPLETE"
        ],
        key=lambda row: (
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
            row["symbol"],
        ),
    )


def print_leaders(
    rows: dict,
    limit: int = 15,
) -> None:
    leaders = ranking(
        rows
    )[:limit]

    if not leaders:
        return

    print()
    print(
        "CURRENT LEADERS"
    )
    print(
        "-" * 92
    )

    for rank, row in enumerate(
        leaders,
        start=1,
    ):
        exception = (
            " QDTE-VOL-EXCEPTION"
            if row[
                "qdte_volume_exception"
            ]
            else ""
        )

        print(
            f"{rank:>2}. "
            f"{row['symbol']:<8} "
            f"net/yr "
            f"${row['net_profit_per_year']:>9,.2f} | "
            f"net "
            f"${row['net_profit']:>9,.2f} | "
            f"swing "
            f"${row['realized_swing_pnl']:>9,.2f} | "
            f"CAGR "
            f"{row['cagr']:>7.2%} | "
            f"DD "
            f"{row['maximum_drawdown']:>7.2%}"
            f"{exception}"
        )

    print(
        "-" * 92
    )
    print()


def write_summary(
    rows: dict,
    universe: list[str],
) -> None:
    ranked = ranking(
        rows
    )

    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    fields = [
        "rank",
        "symbol",
        "qdte_volume_exception",
        "net_profit_per_year",
        "net_profit",
        "swing_pnl_per_year",
        "realized_swing_pnl",
        "qdte_distributions",
        "ending_equity",
        "cagr",
        "maximum_drawdown",
        "profit_factor",
        "win_rate",
        "closed_trades",
        "common_bars",
        "qdte_master_bars",
        "bar_overlap_pct",
        "sessions",
        "risk_rejections",
        "actual_start",
        "actual_end",
        "fingerprint",
    ]

    with SUMMARY_CSV.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            extrasaction="ignore",
        )

        writer.writeheader()

        for number, row in enumerate(
            ranked,
            start=1,
        ):
            output = dict(
                row
            )
            output["rank"] = (
                number
            )

            writer.writerow(
                output
            )

    SUMMARY_JSON.write_text(
        json.dumps(
            {
                "version": RUN_VERSION,
                "start": (
                    START.isoformat()
                ),
                "end": (
                    END.isoformat()
                ),
                "starting_total_capital": (
                    1300.0
                ),
                "starting_qdte_cash": (
                    1300.0
                ),
                "starting_swing_cash": (
                    0.0
                ),
                "external_contributions": (
                    0.0
                ),
                "rebalance": (
                    "Thursday only"
                ),
                "strategy": (
                    "Candidate V1"
                ),
                "qdte_exception": (
                    "Absolute average "
                    "15-minute volume "
                    "floor waived for "
                    "QDTE swing entries only"
                ),
                "ranking": (
                    "net portfolio profit "
                    "per calendar year"
                ),
                "universe_count": (
                    len(universe)
                ),
                "recorded_count": (
                    len(rows)
                ),
                "complete_count": (
                    len(ranked)
                ),
                "leaders": (
                    ranked[:100]
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def parse_child_result(
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
            or "Child process returned "
            "no result."
        ),
    }


def parent_run() -> int:
    refresh_vix()

    universe = (
        alpaca_universe()
    )

    rows = load_progress()

    print(
        "=" * 92
    )
    print(
        "QPX FULL ALPACA SWING-TICKER SEARCH"
    )
    print(
        "=" * 92
    )
    print(
        "Initial capital        : $1,300"
    )
    print(
        "Initial QDTE           : $1,300"
    )
    print(
        "Initial swing cash     : $0"
    )
    print(
        "External contributions : $0"
    )
    print(
        "Rebalance              : THURSDAYS ONLY"
    )
    print(
        "Strategy               : CANDIDATE V1"
    )
    print(
        "QDTE volume floor      : WAIVED FOR QDTE ONLY"
    )
    print(
        "Breakout volume rule   : PRESERVED"
    )
    print(
        "Historical provider    : ALPACA SIP"
    )
    print(
        f"Window                 : {START} -> {END}"
    )
    print(
        f"Frozen universe        : {len(universe):,}"
    )
    print(
        "Primary ranking        : NET PROFIT PER YEAR"
    )
    print(
        "Resume                 : ENABLED"
    )
    print(
        "=" * 92
    )

    script = Path(
        __file__
    ).resolve()

    xle_control = rows.get(
        "XLE"
    )

    control_bars = None
    control_sessions = None

    if (
        xle_control
        and xle_control.get(
            "status"
        )
        == "COMPLETE"
    ):
        control_bars = int(
            xle_control[
                "common_bars"
            ]
        )

        control_sessions = int(
            xle_control[
                "sessions"
            ]
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
            f"{symbol}: RUNNING",
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

        environment = dict(
            os.environ
        )

        environment[
            "QPX_SWEEP_CHILD"
        ] = "1"

        completed = subprocess.run(
            [
                sys.executable,
                str(script),
                "--single",
                symbol,
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

        row = parse_child_result(
            completed,
            symbol,
        )

        if (
            row.get("status")
            == "COMPLETE"
        ):
            if symbol == "XLE":
                control_bars = int(
                    row[
                        "common_bars"
                    ]
                )

                control_sessions = int(
                    row[
                        "sessions"
                    ]
                )

            elif (
                control_bars is None
                or control_sessions is None
            ):
                row = {
                    "symbol": symbol,
                    "status": "FAILED",
                    "qdte_volume_exception": (
                        symbol == "QDTE"
                    ),
                    "error": (
                        "XLE control run "
                        "has not completed."
                    ),
                }

        rows[symbol] = row

        append_progress(
            row
        )

        processed_now += 1

        if (
            not had_bar
            and symbol
            not in {
                "QDTE",
                "XLE",
            }
        ):
            try:
                bar_path.unlink()
            except FileNotFoundError:
                pass

        if (
            not had_manifest
            and symbol
            not in {
                "QDTE",
                "XLE",
            }
        ):
            try:
                man_path.unlink()
            except FileNotFoundError:
                pass

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
            processed_now % 25
            == 0
        ):
            write_summary(
                rows,
                universe,
            )

            print_leaders(
                rows
            )

    write_summary(
        rows,
        universe,
    )

    print_leaders(
        rows,
        limit=25,
    )

    print(
        "SWEEP COMPLETE"
    )

    print(
        f"CSV  : {SUMMARY_CSV}"
    )

    print(
        f"JSON : {SUMMARY_JSON}"
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

    args = parser.parse_args()

    if (
        os.environ.get(
            "QPX_SWEEP_CHILD"
        )
        != "1"
    ):
        refresh_vix()

    if args.single:
        symbol = (
            args.single
            .strip()
            .upper()
        )

        result = run_one(
            symbol
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
