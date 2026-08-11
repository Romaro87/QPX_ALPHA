#!/usr/bin/env python3
"""Run predeclared strict-causal Candidate V1 notional-cap Challengers.

The qualified Candidate V1 implementation remains immutable.  This harness
temporarily changes only its module-level maximum per-position notional
fraction and redirects every generated artifact to a Challenger directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


ROOT = Path(__file__).resolve().parent
BASELINE_COMMIT = "7213db1e17fedce9e923889b116775cca121f766"
ALLOWED_CAPS = (0.25, 0.40, 0.60)
BASELINE_PATHS = (
    "QPX_FREEZE_TOP100_ALPACA_DATA.py",
    "QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL.py",
    "qpx_bot/alpaca_dividends.py",
    "qpx_bot/causal_dividends.py",
    "tests/test_causal_dividends.py",
    "docs/CANDIDATE_V1_STRICT_CAUSAL_QUALIFICATION_2026-08-11.md",
)
REPORT_PARENT = ROOT / "reports" / "qpx_challenger_notional_cap_v1"


def _git(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "git",
            "-c",
            "safe.directory=/mnt/sdcard/QPX_ALPHA",
            "-c",
            "safe.directory=/storage/emulated/0/QPX_ALPHA",
            *arguments,
        ),
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def verify_immutable_baseline() -> None:
    """Fail closed if any qualified baseline file differs from its commit."""
    resolved = _git("rev-parse", BASELINE_COMMIT)
    if resolved.returncode != 0 or resolved.stdout.strip() != BASELINE_COMMIT:
        raise RuntimeError("Qualified Candidate V1 baseline commit is missing.")

    comparison = _git(
        "diff",
        "--quiet",
        BASELINE_COMMIT,
        "--",
        *BASELINE_PATHS,
    )
    if comparison.returncode != 0:
        raise RuntimeError(
            "Qualified Candidate V1 baseline files differ from the immutable "
            "baseline commit."
        )


def report_root(cap: float) -> Path:
    if cap not in ALLOWED_CAPS:
        raise ValueError(f"Unsupported cap: {cap!r}")
    return REPORT_PARENT / f"cap_{int(cap * 100):02d}pct"


@contextmanager
def challenger_scope(cap: float):
    """Override only the notional cap and artifact destinations."""
    destination = report_root(cap)
    original = {
        "MAXIMUM_NOTIONAL_FRACTION": strict.MAXIMUM_NOTIONAL_FRACTION,
        "REPORT_ROOT": strict.REPORT_ROOT,
        "SUMMARY_PATH": strict.SUMMARY_PATH,
        "TRADES_PATH": strict.TRADES_PATH,
        "EQUITY_PATH": strict.EQUITY_PATH,
        "SIGNALS_PATH": strict.SIGNALS_PATH,
        "ALLOCATIONS_PATH": strict.ALLOCATIONS_PATH,
        "DIAGNOSTICS_PATH": strict.DIAGNOSTICS_PATH,
    }
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


def run_challenger(cap: float) -> dict:
    verify_immutable_baseline()
    with challenger_scope(cap) as destination:
        result, summary = strict.run_strict()
        record = {
            "schema_version": 1,
            "experiment": "candidate_v1_strict_causal_notional_cap",
            "baseline_commit": BASELINE_COMMIT,
            "only_changed_parameter": "maximum_position_notional_fraction",
            "maximum_position_notional_fraction": cap,
            "qualified_baseline_fraction": 0.90,
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
        strict.atomic_json(destination / "challenger.json", record)
        return record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cap",
        required=True,
        type=float,
        choices=ALLOWED_CAPS,
        help="Predeclared maximum per-position notional fraction.",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    record = run_challenger(arguments.cap)
    result = record["result"]
    print(f"Notional cap           : {arguments.cap:.0%}")
    print(f"Ending equity          : ${result['ending_equity']:,.2f}")
    print(f"Maximum drawdown       : {result['maximum_drawdown']:.2%}")
    print(f"Qualification          : {record['qualification_gate']['OVERALL_PORTFOLIO_QUALIFICATION']}")
    print(f"Report                 : {report_root(arguments.cap) / 'challenger.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
