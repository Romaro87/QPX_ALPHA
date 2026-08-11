#!/usr/bin/env python3
"""Run fixed chronological robustness windows for notional-cap Challengers."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

import QPX_RUN_CHALLENGER_NOTIONAL_CAP as challenger
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


ROOT = Path(__file__).resolve().parent
REPORT_PARENT = ROOT / "reports" / "qpx_challenger_notional_robustness_v1"
CONFIGURATIONS = {
    "baseline": 0.90,
    "cap_40pct": 0.40,
    "cap_25pct": 0.25,
}
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
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"Unsupported configuration: {configuration}")
    return REPORT_PARENT / period / configuration


@contextmanager
def robustness_scope(period: str, configuration: str):
    """Override only test dates, notional cap, and output destinations."""
    start, end = PERIODS[period]
    cap = CONFIGURATIONS[configuration]
    destination = report_root(period, configuration)
    names = (
        "START",
        "END",
        "MAXIMUM_NOTIONAL_FRACTION",
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
    original_apply_notional_cap = strict.apply_notional_cap

    def validate_frozen_vix_for_period(*, closes, start, end):
        """Validate the full frozen source, then select the requested period."""
        validated = original_vix_validation(
            closes=closes,
            start=AUTHENTIC_START,
            end=AUTHENTIC_END,
        )
        return {day: value for day, value in validated.items() if day <= end}

    def apply_absolute_challenger_cap(*, sizing, account_equity):
        adjusted, changed, one_share_floor = original_apply_notional_cap(
            sizing=sizing,
            account_equity=account_equity,
        )
        if configuration != "baseline" and one_share_floor:
            return (
                replace(
                    adjusted,
                    shares=0,
                    planned_risk=0.0,
                    blocked_reason=(
                        "Maximum position notional cap is below one share."
                    ),
                ),
                False,
                False,
            )
        return adjusted, changed, one_share_floor

    strict.START = start
    strict.END = end
    strict.MAXIMUM_NOTIONAL_FRACTION = cap
    strict.REPORT_ROOT = destination
    strict.SUMMARY_PATH = destination / "summary.json"
    strict.TRADES_PATH = destination / "trades.csv"
    strict.EQUITY_PATH = destination / "equity.csv"
    strict.SIGNALS_PATH = destination / "signals.csv"
    strict.ALLOCATIONS_PATH = destination / "allocations.csv"
    strict.DIAGNOSTICS_PATH = destination / "diagnostics.json"
    strict.qpx._validate_vix_daily_coverage = validate_frozen_vix_for_period
    strict.apply_notional_cap = apply_absolute_challenger_cap
    try:
        yield destination
    finally:
        strict.qpx._validate_vix_daily_coverage = original_vix_validation
        strict.apply_notional_cap = original_apply_notional_cap
        for name, value in original.items():
            setattr(strict, name, value)


def run(period: str, configuration: str) -> dict:
    challenger.verify_immutable_baseline()
    start, end = PERIODS[period]
    cap = CONFIGURATIONS[configuration]
    with robustness_scope(period, configuration) as destination:
        result, summary = strict.run_strict()
        record = {
            "schema_version": 1,
            "experiment": "candidate_v1_notional_cap_chronological_robustness",
            "baseline_commit": challenger.BASELINE_COMMIT,
            "period": period,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "configuration": configuration,
            "maximum_position_notional_fraction": cap,
            "only_strategy_parameter_varied": (
                "maximum_position_notional_fraction"
            ),
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
        strict.atomic_json(destination / "robustness.json", record)
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", required=True, choices=tuple(PERIODS))
    parser.add_argument(
        "--configuration",
        required=True,
        choices=tuple(CONFIGURATIONS),
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
    print(f"Report                 : {report_root(arguments.period, arguments.configuration) / 'robustness.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
