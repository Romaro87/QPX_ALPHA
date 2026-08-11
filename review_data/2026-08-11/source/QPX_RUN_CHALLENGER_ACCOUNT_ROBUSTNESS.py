#!/usr/bin/env python3
"""Chronological robustness for the account-sized Candidate V1 experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path

import QPX_RUN_CHALLENGER_ACCOUNT_SIZED as account
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


ROOT = Path(__file__).resolve().parent
REPORT_PARENT = (
    ROOT / "reports" / "qpx_challenger_account_sized_robustness_v1"
)
PERIODS = {
    "p1_2024": (date(2024, 3, 7), date(2024, 12, 31)),
    "p2_2025": (date(2025, 1, 2), date(2025, 12, 31)),
    "p3_2026": (date(2026, 1, 2), date(2026, 8, 7)),
    "e2_through_2025": (date(2024, 3, 7), date(2025, 12, 31)),
}
AUTHENTIC_START = date(2024, 3, 7)
AUTHENTIC_END = date(2026, 8, 7)


def report_root(period: str, configuration: str) -> Path:
    if period not in PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    if configuration not in account.CONFIGURATIONS:
        raise ValueError(f"Unsupported configuration: {configuration}")
    return REPORT_PARENT / period / configuration


@contextmanager
def account_robustness_scope(period: str, configuration: str):
    """Apply account sizing, then change only dates and output paths."""
    start, end = PERIODS[period]
    destination = report_root(period, configuration)
    with account.account_sized_scope(configuration):
        names = (
            "START",
            "END",
            "REPORT_ROOT",
            "SUMMARY_PATH",
            "TRADES_PATH",
            "EQUITY_PATH",
            "SIGNALS_PATH",
            "ALLOCATIONS_PATH",
            "DIAGNOSTICS_PATH",
        )
        original = {name: getattr(strict, name) for name in names}
        original_vix_validation = strict.qpx._validate_vix_daily_coverage

        def validate_frozen_vix_for_period(*, closes, start, end):
            validated = original_vix_validation(
                closes=closes,
                start=AUTHENTIC_START,
                end=AUTHENTIC_END,
            )
            return {day: value for day, value in validated.items() if day <= end}

        strict.START = start
        strict.END = end
        strict.REPORT_ROOT = destination
        strict.SUMMARY_PATH = destination / "summary.json"
        strict.TRADES_PATH = destination / "trades.csv"
        strict.EQUITY_PATH = destination / "equity.csv"
        strict.SIGNALS_PATH = destination / "signals.csv"
        strict.ALLOCATIONS_PATH = destination / "allocations.csv"
        strict.DIAGNOSTICS_PATH = destination / "diagnostics.json"
        strict.qpx._validate_vix_daily_coverage = validate_frozen_vix_for_period
        try:
            yield destination
        finally:
            strict.qpx._validate_vix_daily_coverage = original_vix_validation
            for name, value in original.items():
                setattr(strict, name, value)


def run(period: str, configuration: str) -> dict:
    account.challenger.verify_immutable_baseline()
    start, end = PERIODS[period]
    with account_robustness_scope(period, configuration) as destination:
        result, summary = strict.run_strict()
        record = {
            "schema_version": 1,
            "experiment": "candidate_v1_account_sized_chronological_robustness",
            "baseline_commit": account.challenger.BASELINE_COMMIT,
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "configuration": configuration,
            "maximum_position_notional_fraction": (
                account.CONFIGURATIONS[configuration]
            ),
            "starting_qdte_value": account.STARTING_QDTE_VALUE,
            "starting_swing_cash": account.STARTING_SWING_CASH,
            "starting_total_equity": account.STARTING_TOTAL_EQUITY,
            "dataset_fingerprint": summary["dataset_fingerprint"],
            "strict_summary_fingerprint": summary["summary_fingerprint"],
            "qualification_gate": summary["gate"],
            "created_at": datetime.now().astimezone().isoformat(),
            "result": result,
        }
        core = json.dumps(
            record,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        record["record_fingerprint"] = hashlib.sha256(core).hexdigest()
        strict.atomic_json(destination / "account_robustness.json", record)
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", required=True, choices=tuple(PERIODS))
    parser.add_argument(
        "--configuration",
        required=True,
        choices=tuple(account.CONFIGURATIONS),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    record = run(arguments.period, arguments.configuration)
    result = record["result"]
    print(f"Period                 : {arguments.period}")
    print(f"Configuration          : {arguments.configuration}")
    print(f"Ending equity          : ${result['ending_equity']:,.2f}")
    print(f"Maximum drawdown       : {result['maximum_drawdown']:.2%}")
    print(f"Qualification          : {record['qualification_gate']['OVERALL_PORTFOLIO_QUALIFICATION']}")
    print(f"Report                 : {report_root(arguments.period, arguments.configuration) / 'account_robustness.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
