#!/usr/bin/env python3
"""Run immutable Candidate V1 with an account-sized starting state."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from types import FunctionType

import QPX_RUN_CHALLENGER_NOTIONAL_CAP as challenger
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


ROOT = Path(__file__).resolve().parent
STARTING_QDTE_VALUE = 1_438.00
STARTING_SWING_CASH = 5.34
STARTING_TOTAL_EQUITY = 1_443.34
CONFIGURATIONS = {
    "baseline": 0.90,
    "cap_60pct": 0.60,
    "cap_40pct": 0.40,
    "cap_25pct": 0.25,
}
REPORT_PARENT = ROOT / "reports" / "qpx_challenger_account_sized_v1"


def report_root(configuration: str) -> Path:
    if configuration not in CONFIGURATIONS:
        raise ValueError(f"Unsupported configuration: {configuration}")
    return REPORT_PARENT / configuration


def account_sized_run_function(original):
    """Clone run_strict with only its $1,300 accounting basis replaced."""
    constants = original.__code__.co_consts
    replacements = sum(value == 1300.0 for value in constants)
    if replacements != 1:
        raise RuntimeError(
            "Unexpected immutable runner starting-capital constant layout."
        )
    code = original.__code__.replace(
        co_consts=tuple(
            STARTING_TOTAL_EQUITY if value == 1300.0 else value
            for value in constants
        )
    )
    cloned = FunctionType(
        code,
        original.__globals__,
        original.__name__,
        original.__defaults__,
        original.__closure__,
    )
    cloned.__kwdefaults__ = original.__kwdefaults__
    return cloned


@contextmanager
def account_sized_scope(configuration: str):
    """Override only starting dollars, cap, and output destinations."""
    cap = CONFIGURATIONS[configuration]
    destination = report_root(configuration)
    names = (
        "candidate_config",
        "run_strict",
        "apply_notional_cap",
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

    def account_config():
        config = replace(
            original["candidate_config"](),
            starting_cash=STARTING_QDTE_VALUE,
            starting_swing_cash=STARTING_SWING_CASH,
        )
        config.validate()
        return config

    def apply_absolute_challenger_cap(*, sizing, account_equity):
        adjusted, changed, one_share_floor = original[
            "apply_notional_cap"
        ](sizing=sizing, account_equity=account_equity)
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

    strict.candidate_config = account_config
    strict.run_strict = account_sized_run_function(original["run_strict"])
    strict.apply_notional_cap = apply_absolute_challenger_cap
    strict.MAXIMUM_NOTIONAL_FRACTION = cap
    strict.REPORT_ROOT = destination
    strict.SUMMARY_PATH = destination / "summary.json"
    strict.TRADES_PATH = destination / "trades.csv"
    strict.EQUITY_PATH = destination / "equity.csv"
    strict.SIGNALS_PATH = destination / "signals.csv"
    strict.ALLOCATIONS_PATH = destination / "allocations.csv"
    strict.DIAGNOSTICS_PATH = destination / "diagnostics.json"
    try:
        yield destination
    finally:
        for name, value in original.items():
            setattr(strict, name, value)


def run(configuration: str) -> dict:
    challenger.verify_immutable_baseline()
    with account_sized_scope(configuration) as destination:
        result, summary = strict.run_strict()
        record = {
            "schema_version": 1,
            "experiment": "candidate_v1_account_sized_notional_cap",
            "baseline_commit": challenger.BASELINE_COMMIT,
            "configuration": configuration,
            "maximum_position_notional_fraction": CONFIGURATIONS[configuration],
            "starting_qdte_value": STARTING_QDTE_VALUE,
            "starting_swing_cash": STARTING_SWING_CASH,
            "starting_total_equity": STARTING_TOTAL_EQUITY,
            "only_varied_inputs": [
                "starting_qdte_value",
                "starting_swing_cash",
                "maximum_position_notional_fraction",
            ],
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
        strict.atomic_json(destination / "account_sized.json", record)
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configuration",
        required=True,
        choices=tuple(CONFIGURATIONS),
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    record = run(arguments.configuration)
    result = record["result"]
    print(f"Configuration          : {arguments.configuration}")
    print(f"Starting QDTE          : ${STARTING_QDTE_VALUE:,.2f}")
    print(f"Starting swing cash    : ${STARTING_SWING_CASH:,.2f}")
    print(f"Ending equity          : ${result['ending_equity']:,.2f}")
    print(f"Maximum drawdown       : {result['maximum_drawdown']:.2%}")
    print(f"Qualification          : {record['qualification_gate']['OVERALL_PORTFOLIO_QUALIFICATION']}")
    print(f"Report                 : {report_root(arguments.configuration) / 'account_sized.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
