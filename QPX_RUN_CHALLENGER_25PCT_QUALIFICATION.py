#!/usr/bin/env python3
"""Formal qualification runner for the fixed account-sized 25% Challenger."""

from __future__ import annotations

import argparse
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import QPX_RUN_CHALLENGER_ACCOUNT_ROBUSTNESS as robustness
import QPX_RUN_CHALLENGER_ACCOUNT_SIZED as account
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.qualification_provenance import verify_immutable_provenance


ROOT = Path(__file__).resolve().parent
BASELINE_COMMIT = "7213db1e17fedce9e923889b116775cca121f766"
DATASET_FINGERPRINT = (
    "8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8"
)
CONFIGURATION = "cap_25pct"
MAXIMUM_POSITION_NOTIONAL_FRACTION = 0.25
STARTING_QDTE_VALUE = 1_438.00
STARTING_SWING_CASH = 5.34
STARTING_TOTAL_EQUITY = 1_443.34
REPORT_ROOT = ROOT / "reports" / "qpx_challenger_25pct_qualification_v1"
RUN_IDS = ("run_1", "run_2")
LEDGERS = ("trades.csv", "equity.csv", "signals.csv", "allocations.csv")
REQUIRED_GATES = {
    "LOOKAHEAD_PROTECTION": "PASS",
    "SIMULATION_CLOCK": "STRICT_RECORDED_UNION",
    "FUTURE_BAR_ACCESS": "BLOCKED",
    "CURRENT_OPEN_FULL_OHLCV": "BLOCKED",
    "SYNTHETIC_FUTURE_DATA": "NONE",
    "DECISION_DATA_CUTOFF": "VERIFIED_SWING_STRATEGY_BOUNDARY",
    "EXECUTION_TIMING": "VERIFIED_OPEN_CLOSE_PHASES",
    "MISSING_SYMBOL_BAR_HANDLING": "UNAVAILABLE_SYMBOL_ONLY",
    "INDICATOR_PREFIX_EQUIVALENCE": "PASS",
    "STRATEGY_SEMANTIC_EQUIVALENCE": "PASS",
    "CORPORATE_ACTION_CASH_TIMING": "PASS_LATER_OF_PAYABLE_OR_PROCESS_DATE",
    "DIVIDEND_ENTITLEMENT": "PASS_EX_DATE_OWNERSHIP_SNAPSHOT",
    "OVERALL_PORTFOLIO_QUALIFICATION": "FULL_CAUSAL_ACCOUNTING_PASS",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_fixed_definition() -> None:
    account.challenger.verify_immutable_baseline()
    verify_immutable_provenance()
    if account.challenger.BASELINE_COMMIT != BASELINE_COMMIT:
        raise RuntimeError("Unexpected Candidate V1 baseline commit.")
    if account.CONFIGURATIONS[CONFIGURATION] != MAXIMUM_POSITION_NOTIONAL_FRACTION:
        raise RuntimeError("Fixed Challenger cap differs from 25%.")
    actual = (
        account.STARTING_QDTE_VALUE,
        account.STARTING_SWING_CASH,
        account.STARTING_TOTAL_EQUITY,
    )
    expected = (STARTING_QDTE_VALUE, STARTING_SWING_CASH, STARTING_TOTAL_EQUITY)
    if actual != expected:
        raise RuntimeError("Fixed account-sized starting state differs.")


@contextmanager
def formal_scope(destination: Path):
    """Apply the preserved account-sized 25% variant and redirect artifacts."""
    with account.account_sized_scope(CONFIGURATION):
        names = (
            "REPORT_ROOT",
            "SUMMARY_PATH",
            "TRADES_PATH",
            "EQUITY_PATH",
            "SIGNALS_PATH",
            "ALLOCATIONS_PATH",
            "DIAGNOSTICS_PATH",
        )
        original = {name: getattr(strict, name) for name in names}
        strict.REPORT_ROOT = destination
        strict.SUMMARY_PATH = destination / "summary.json"
        strict.TRADES_PATH = destination / "trades.csv"
        strict.EQUITY_PATH = destination / "equity.csv"
        strict.SIGNALS_PATH = destination / "signals.csv"
        strict.ALLOCATIONS_PATH = destination / "allocations.csv"
        strict.DIAGNOSTICS_PATH = destination / "diagnostics.json"
        try:
            yield
        finally:
            for name, value in original.items():
                setattr(strict, name, value)


def isolation_audit() -> dict:
    before = {
        "candidate_config": strict.candidate_config,
        "run_strict": strict.run_strict,
        "apply_notional_cap": strict.apply_notional_cap,
        "maximum_notional_fraction": strict.MAXIMUM_NOTIONAL_FRACTION,
    }
    with formal_scope(REPORT_ROOT / "isolation_probe"):
        config = strict.candidate_config()
        inside = {
            "starting_qdte_value": config.starting_cash,
            "starting_swing_cash": config.starting_swing_cash,
            "starting_total_equity": config.total_starting_capital,
            "maximum_position_notional_fraction": strict.MAXIMUM_NOTIONAL_FRACTION,
        }
    restored = (
        strict.candidate_config is before["candidate_config"]
        and strict.run_strict is before["run_strict"]
        and strict.apply_notional_cap is before["apply_notional_cap"]
        and strict.MAXIMUM_NOTIONAL_FRACTION
        == before["maximum_notional_fraction"]
    )
    passed = inside == {
        "starting_qdte_value": STARTING_QDTE_VALUE,
        "starting_swing_cash": STARTING_SWING_CASH,
        "starting_total_equity": STARTING_TOTAL_EQUITY,
        "maximum_position_notional_fraction": MAXIMUM_POSITION_NOTIONAL_FRACTION,
    } and restored
    return {
        "status": "PASS" if passed else "FAIL",
        "only_intentional_behavioral_differences": [
            "maximum_position_notional_fraction",
            "starting_qdte_value",
            "starting_swing_cash",
        ],
        "observed": inside,
        "baseline_runner_restored": restored,
    }


def run_full(run_id: str) -> dict:
    if run_id not in RUN_IDS:
        raise ValueError(f"Unsupported run id: {run_id}")
    verify_fixed_definition()
    audit = isolation_audit()
    if audit["status"] != "PASS":
        raise RuntimeError("Challenger isolation audit failed.")
    destination = REPORT_ROOT / "full_replay" / run_id
    with formal_scope(destination):
        result, summary = strict.run_strict()
    if summary["dataset_fingerprint"] != DATASET_FINGERPRINT:
        raise RuntimeError("Frozen dataset fingerprint mismatch.")
    if summary["gate"] != REQUIRED_GATES:
        raise RuntimeError("Strict-causal gate mismatch.")
    ledger_hashes = {name: sha256_file(destination / name) for name in LEDGERS}
    record = {
        "schema_version": 1,
        "experiment": "fixed_25pct_notional_cap_formal_qualification",
        "run_id": run_id,
        "baseline_commit": BASELINE_COMMIT,
        "dataset_fingerprint": DATASET_FINGERPRINT,
        "maximum_position_notional_fraction": MAXIMUM_POSITION_NOTIONAL_FRACTION,
        "starting_qdte_value": STARTING_QDTE_VALUE,
        "starting_swing_cash": STARTING_SWING_CASH,
        "starting_total_equity": STARTING_TOTAL_EQUITY,
        "isolation_audit": audit,
        "causal_gates": summary["gate"],
        "ledger_sha256": ledger_hashes,
        "result": result,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    strict.atomic_json(destination / "formal_run.json", record)
    return record


def run_period(period: str) -> dict:
    verify_fixed_definition()
    if period not in robustness.PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    destination = REPORT_ROOT / "robustness" / period
    with robustness.account_robustness_scope(period, CONFIGURATION):
        names = (
            "REPORT_ROOT", "SUMMARY_PATH", "TRADES_PATH", "EQUITY_PATH",
            "SIGNALS_PATH", "ALLOCATIONS_PATH", "DIAGNOSTICS_PATH",
        )
        original = {name: getattr(strict, name) for name in names}
        strict.REPORT_ROOT = destination
        strict.SUMMARY_PATH = destination / "summary.json"
        strict.TRADES_PATH = destination / "trades.csv"
        strict.EQUITY_PATH = destination / "equity.csv"
        strict.SIGNALS_PATH = destination / "signals.csv"
        strict.ALLOCATIONS_PATH = destination / "allocations.csv"
        strict.DIAGNOSTICS_PATH = destination / "diagnostics.json"
        try:
            result, summary = strict.run_strict()
        finally:
            for name, value in original.items():
                setattr(strict, name, value)
    if summary["dataset_fingerprint"] != DATASET_FINGERPRINT:
        raise RuntimeError("Frozen dataset fingerprint mismatch.")
    if summary["gate"] != REQUIRED_GATES:
        raise RuntimeError("Strict-causal gate mismatch.")
    start, end = robustness.PERIODS[period]
    record = {
        "schema_version": 1,
        "experiment": "fixed_25pct_formal_chronological_robustness",
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "baseline_commit": BASELINE_COMMIT,
        "dataset_fingerprint": DATASET_FINGERPRINT,
        "maximum_position_notional_fraction": MAXIMUM_POSITION_NOTIONAL_FRACTION,
        "starting_qdte_value": STARTING_QDTE_VALUE,
        "starting_swing_cash": STARTING_SWING_CASH,
        "starting_total_equity": STARTING_TOTAL_EQUITY,
        "causal_gates": summary["gate"],
        "ledger_sha256": {name: sha256_file(destination / name) for name in LEDGERS},
        "result": result,
        "created_at": datetime.now().astimezone().isoformat(),
    }
    strict.atomic_json(destination / "formal_robustness.json", record)
    return record


def verify_reproducibility() -> dict:
    records = []
    for run_id in RUN_IDS:
        path = REPORT_ROOT / "full_replay" / run_id / "formal_run.json"
        records.append(json.loads(path.read_text(encoding="utf-8")))
    fields = ("result", "ledger_sha256", "dataset_fingerprint", "causal_gates")
    identical = all(records[0][field] == records[1][field] for field in fields)
    qualification = {
        "schema_version": 1,
        "qualification": "PASS" if identical else "FAIL",
        "baseline_commit": BASELINE_COMMIT,
        "dataset_fingerprint": DATASET_FINGERPRINT,
        "configuration": CONFIGURATION,
        "maximum_position_notional_fraction": MAXIMUM_POSITION_NOTIONAL_FRACTION,
        "starting_qdte_value": STARTING_QDTE_VALUE,
        "starting_swing_cash": STARTING_SWING_CASH,
        "starting_total_equity": STARTING_TOTAL_EQUITY,
        "reproducibility": {
            "summary_metrics_identical": records[0]["result"] == records[1]["result"],
            "ledger_hashes_identical": records[0]["ledger_sha256"] == records[1]["ledger_sha256"],
            "dataset_fingerprint_identical": records[0]["dataset_fingerprint"] == records[1]["dataset_fingerprint"],
            "causal_gates_identical": records[0]["causal_gates"] == records[1]["causal_gates"],
        },
        "run_1_ledger_sha256": records[0]["ledger_sha256"],
        "run_2_ledger_sha256": records[1]["ledger_sha256"],
        "result": records[0]["result"],
        "created_at": datetime.now().astimezone().isoformat(),
    }
    strict.atomic_json(REPORT_ROOT / "qualification.json", qualification)
    if not identical:
        raise RuntimeError("Formal Challenger replays are not deterministic.")
    return qualification


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--full-run", choices=RUN_IDS)
    actions.add_argument("--period", choices=tuple(robustness.PERIODS))
    actions.add_argument("--verify-reproducibility", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.full_run:
        record = run_full(args.full_run)
    elif args.period:
        record = run_period(args.period)
    else:
        record = verify_reproducibility()
    print(json.dumps(record, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
