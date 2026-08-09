from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from qpx_bot.scenario_config import (
    load_scenario,
    validate_scenario,
)

ROOT = Path(__file__).resolve().parent

DEFAULT_BASE = (
    ROOT
    / "qpx_bot"
    / "scenarios"
    / "candidate_v1_alpaca.json"
)

RUNNER = ROOT / "QPX_RUN_SCENARIO.py"

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_symbol_screen"
)

RESULT_RE = re.compile(
    r"^\s*Result\s*:\s*(.+?)\s*$",
    re.MULTILINE,
)

FIELDS = (
    "symbol",
    "status",
    "fingerprint",
    "provider",
    "common_bars",
    "sessions",
    "session_coverage",
    "closed_trades",
    "win_rate",
    "profit_factor",
    "realized_swing_pnl",
    "qdte_distributions",
    "net_profit",
    "ending_equity",
    "cagr",
    "maximum_drawdown",
    "risk_rejections",
    "result_json",
    "log_file",
    "error",
)


def safe_name(symbol: str) -> str:
    return re.sub(
        r"[^A-Z0-9._-]+",
        "_",
        symbol.upper(),
    )


def last_error(text: str) -> str:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    return " | ".join(
        lines[-4:]
    )[-1000:]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Screen symbols one at a time "
            "with identical Alpaca SIP "
            "Candidate V1 strategy settings."
        )
    )

    parser.add_argument(
        "--symbols",
        nargs="+",
        required=True,
    )

    parser.add_argument(
        "--start",
        default="2024-08-08",
    )

    parser.add_argument(
        "--end",
        default="2026-08-05",
    )

    parser.add_argument(
        "--base",
        default=str(DEFAULT_BASE),
    )

    args = parser.parse_args()

    base = load_scenario(
        args.base
    )

    if (
        str(
            base.data["provider"]
        ).strip().lower()
        != "alpaca_sip"
    ):
        raise SystemExit(
            "Screener requires an "
            "Alpaca SIP base scenario."
        )

    symbols = []

    for raw in args.symbols:
        symbol = raw.strip().upper()

        if (
            symbol
            and symbol not in symbols
        ):
            symbols.append(symbol)

    if not symbols:
        raise SystemExit(
            "No symbols supplied."
        )

    income_symbol = str(
        base.symbols["income_symbol"]
    ).strip().upper()

    volatility_symbol = str(
        base.symbols[
            "volatility_symbol"
        ]
    ).strip().upper()

    conflicts = [
        symbol
        for symbol in symbols
        if symbol in {
            income_symbol,
            volatility_symbol,
        }
    ]

    if conflicts:
        raise SystemExit(
            "Cannot screen configured "
            "income/volatility symbols: "
            + ", ".join(conflicts)
        )

    run_id = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    output_dir = (
        REPORT_ROOT
        / run_id
    )

    log_dir = (
        output_dir
        / "logs"
    )

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    rows = []

    print("=" * 72)
    print(
        "QPX ONE-SYMBOL "
        "ALPACA SIP SCREEN"
    )
    print("=" * 72)
    print(
        "Symbols : "
        + ", ".join(symbols)
    )
    print(
        f"Range   : "
        f"{args.start} -> {args.end}"
    )
    print(
        "Mode    : EXACT WINDOW / "
        "FAIL CLOSED"
    )
    print("=" * 72)

    with tempfile.TemporaryDirectory(
        prefix="qpx_screen_"
    ) as folder:

        temporary = Path(folder)

        for number, symbol in enumerate(
            symbols,
            start=1,
        ):
            print(
                f"[{number}/{len(symbols)}] "
                f"{symbol}: RUNNING",
                flush=True,
            )

            payload = (
                base.clone_payload()
            )

            name = safe_name(
                symbol
            )

            payload["name"] = (
                "screen_"
                + name.lower()
            )

            payload["description"] = (
                "One-symbol Alpaca SIP "
                f"research screen for {symbol}."
            )

            payload["revision"] = 1

            payload["symbols"][
                "candidate_symbols"
            ] = [symbol]

            payload["symbols"][
                "tradable_symbols"
            ] = [symbol]

            validate_scenario(
                payload
            )

            scenario_path = (
                temporary
                / f"{name}.json"
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

            command = [
                sys.executable,
                str(RUNNER),
                "--scenario",
                str(scenario_path),
                "--start",
                args.start,
                "--end",
                args.end,
            ]

            completed = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

            log_path = (
                log_dir
                / f"{name}.log"
            )

            log_path.write_text(
                "COMMAND:\n"
                + " ".join(command)
                + "\n\nSTDOUT\n"
                + completed.stdout
                + "\n\nSTDERR\n"
                + completed.stderr,
                encoding="utf-8",
            )

            row = {
                "symbol": symbol,
                "fingerprint": (
                    scenario.fingerprint
                ),
                "log_file": str(
                    log_path
                ),
            }

            if (
                completed.returncode
                != 0
            ):
                row.update(
                    status="FAILED",
                    error=last_error(
                        completed.stderr
                        or completed.stdout
                    ),
                )

                rows.append(row)

                print(
                    f"[{number}/{len(symbols)}] "
                    f"{symbol}: FAILED",
                    flush=True,
                )

                continue

            match = RESULT_RE.search(
                completed.stdout
            )

            if not match:
                row.update(
                    status="FAILED",
                    error=(
                        "No result artifact "
                        "was reported."
                    ),
                )

                rows.append(row)

                print(
                    f"{symbol}: "
                    "RESULT NOT FOUND"
                )

                continue

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
                row.update(
                    status="FAILED",
                    result_json=str(
                        result_path
                    ),
                    error=(
                        "Reported result "
                        "JSON is missing."
                    ),
                )

                rows.append(row)
                continue

            result = json.loads(
                result_path.read_text(
                    encoding="utf-8"
                )
            )

            row.update(
                status="COMPLETE",
                provider=result.get(
                    "provider"
                ),
                common_bars=result.get(
                    "common_test_bars"
                ),
                sessions=result.get(
                    "test_sessions"
                ),
                session_coverage=(
                    result.get(
                        "session_coverage"
                    )
                ),
                closed_trades=result.get(
                    "closed_trades"
                ),
                win_rate=result.get(
                    "win_rate"
                ),
                profit_factor=result.get(
                    "profit_factor"
                ),
                realized_swing_pnl=(
                    result.get(
                        "realized_swing_pnl"
                    )
                ),
                qdte_distributions=(
                    result.get(
                        "qdte_distributions_received"
                    )
                ),
                net_profit=result.get(
                    "net_profit"
                ),
                ending_equity=result.get(
                    "ending_equity"
                ),
                cagr=result.get(
                    "flow_adjusted_cagr"
                ),
                maximum_drawdown=(
                    result.get(
                        "maximum_drawdown"
                    )
                ),
                risk_rejections=(
                    result.get(
                        "risk_rejections"
                    )
                ),
                result_json=str(
                    result_path
                ),
                error="",
            )

            rows.append(row)

            print(
                f"[{number}/{len(symbols)}] "
                f"{symbol}: COMPLETE | "
                f"trades="
                f"{row['closed_trades']} | "
                f"swing P&L="
                f"${row['realized_swing_pnl']:,.2f}",
                flush=True,
            )

    csv_path = (
        output_dir
        / "summary.csv"
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:

        writer = csv.DictWriter(
            handle,
            fieldnames=FIELDS,
        )

        writer.writeheader()

        for row in rows:
            writer.writerow(
                row
            )

    json_path = (
        output_dir
        / "summary.json"
    )

    json_path.write_text(
        json.dumps(
            {
                "generated_at_utc": (
                    datetime.now(
                        timezone.utc
                    ).isoformat()
                ),
                "base_scenario": str(
                    base.path
                ),
                "base_fingerprint": (
                    base.fingerprint
                ),
                "start": args.start,
                "end": args.end,
                "symbols": symbols,
                "results": rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print()
    print("=" * 100)
    print(
        "QPX SYMBOL SCREEN SUMMARY"
    )
    print("=" * 100)

    print(
        f"{'SYMBOL':<8} "
        f"{'STATUS':<9} "
        f"{'TRADES':>7} "
        f"{'WIN':>8} "
        f"{'PF':>7} "
        f"{'SWING P&L':>12} "
        f"{'CAGR':>8} "
        f"{'MAX DD':>8}"
    )

    print("-" * 100)

    for row in rows:

        if (
            row["status"]
            != "COMPLETE"
        ):
            print(
                f"{row['symbol']:<8} "
                f"{'FAILED':<9}"
            )

            continue

        pf = (
            "n/a"
            if row["profit_factor"] is None
            else (
                f"{row['profit_factor']:.3f}"
            )
        )

        print(
            f"{row['symbol']:<8} "
            f"{'COMPLETE':<9} "
            f"{row['closed_trades']:>7} "
            f"{row['win_rate']:>7.2%} "
            f"{pf:>7} "
            f"${row['realized_swing_pnl']:>11,.2f} "
            f"{row['cagr']:>7.2%} "
            f"{row['maximum_drawdown']:>7.2%}"
        )

    print("=" * 100)

    print(
        "COMPLETE means exact-window "
        "data validation passed. "
        "It is not a strategy recommendation."
    )

    print()
    print(
        f"CSV  : {csv_path}"
    )
    print(
        f"JSON : {json_path}"
    )
    print(
        f"Logs : {log_dir}"
    )

    return (
        0
        if any(
            row["status"]
            == "COMPLETE"
            for row in rows
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
