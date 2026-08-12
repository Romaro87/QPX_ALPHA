#!/usr/bin/env python3
"""Chronological robustness for fixed Dynamic Sizing V1 versus fixed 25%."""

from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from pathlib import Path

import QPX_RUN_ACCELERATOR_DYNAMIC_SIZING as dynamic
import QPX_RUN_CHALLENGER_ACCOUNT_ROBUSTNESS as robustness
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.dynamic_sizing import DynamicSizingV1, load_dynamic_sizing_config


ROOT = Path(__file__).resolve().parent
REPORT_PARENT = ROOT / "reports/qpx_dynamic_sizing_v1_robustness"
SUMMARY_PATH = (
    ROOT
    / "docs/research_results"
    / "DYNAMIC_SIZING_V1_CHRONOLOGICAL_ROBUSTNESS_2026-08-12.json"
)
PERIODS = robustness.PERIODS
CONFIGURATION = "cap_25pct"
ARMS = ("fixed_25pct", "dynamic_sizing_v1")


def report_root(period: str, arm: str) -> Path:
    if period not in PERIODS:
        raise ValueError(f"Unsupported period: {period}")
    if arm not in ARMS:
        raise ValueError(f"Unsupported arm: {arm}")
    return REPORT_PARENT / period / arm


@contextmanager
def output_paths(destination: Path):
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
        yield destination
    finally:
        for name, value in original.items():
            setattr(strict, name, value)


def compact_result(result: dict, *, equity_path: Path) -> dict:
    ledger = dynamic.equity_ledger_diagnostics(equity_path)
    return {
        "starting_qdte_value": robustness.account.STARTING_QDTE_VALUE,
        "starting_swing_cash": robustness.account.STARTING_SWING_CASH,
        "starting_total_equity": robustness.account.STARTING_TOTAL_EQUITY,
        "ending_equity": result["ending_equity"],
        "net_profit": result["net_profit"],
        "total_return": result["flow_adjusted_total_return"],
        "cagr": result["flow_adjusted_cagr"],
        "eod_maximum_drawdown": result["maximum_drawdown"],
        "intraday_maximum_drawdown": ledger["intraday_maximum_drawdown"],
        "sharpe": result["sharpe_ratio"],
        "sortino": result["sortino_ratio"],
        "profit_factor": result["profit_factor"],
        "closed_trades": result["closed_trades"],
        "win_rate": result["win_rate"],
        "risk_rejections": result["risk_rejections"],
        "capacity_deferrals": result["capacity_deferred"],
        "qdte_distributions_received": result["qdte_distributions_received"],
        "qdte_distribution_events": result["qdte_distribution_events"],
        "maximum_observed_active_portfolio_risk": ledger[
            "maximum_observed_active_portfolio_risk"
        ],
    }


def verify_summary(summary: dict) -> None:
    if summary["dataset_fingerprint"] != dynamic.DATASET_FINGERPRINT:
        raise RuntimeError("Frozen dataset fingerprint changed.")
    if summary["gate"] != dynamic.formal.REQUIRED_GATES:
        raise RuntimeError("Strict causal qualification gates changed.")


def run_arm(period: str, arm: str) -> dict:
    dynamic.formal.verify_fixed_definition()
    destination = report_root(period, arm)
    config = load_dynamic_sizing_config(dynamic.CONFIG_PATH, enabled=True)
    accelerator = DynamicSizingV1(config)
    with robustness.account_robustness_scope(period, CONFIGURATION):
        with output_paths(destination):
            if arm == "dynamic_sizing_v1":
                with dynamic.enabled_accelerator_scope(
                    accelerator, strict.candidate_config()
                ) as state:
                    result, summary = strict.run_strict()
                decisions = state.decisions
                dynamic.write_decisions(
                    destination / "dynamic_sizing_decisions.csv", decisions
                )
            else:
                result, summary = strict.run_strict()
                decisions = []
    verify_summary(summary)
    metrics = compact_result(result, equity_path=destination / "equity.csv")
    record = {
        "period": period,
        "start": PERIODS[period][0].isoformat(),
        "end": PERIODS[period][1].isoformat(),
        "arm": arm,
        "dataset_fingerprint": summary["dataset_fingerprint"],
        "configuration_fingerprint": (
            config.fingerprint if arm == "dynamic_sizing_v1" else None
        ),
        "causal_gates": summary["gate"],
        "metrics": metrics,
    }
    if arm == "dynamic_sizing_v1":
        from collections import Counter

        record["dynamic_sizing"] = {
            "decision_count": len(decisions),
            "reduced_count": sum(
                item.final_requested_shares < item.base_requested_shares
                for item in decisions
            ),
            "unchanged_count": sum(
                item.final_requested_shares == item.base_requested_shares
                for item in decisions
            ),
            "prevented_below_one_share": sum(
                "BLOCKED_BELOW_ONE_SHARE" in item.reason_codes
                for item in decisions
            ),
            "multiplier_distribution": dict(
                Counter(str(item.sizing_multiplier) for item in decisions)
            ),
            "maximum_observed_position_notional_fraction": max(
                (
                    item.final_requested_notional / item.decision_time_total_equity
                    for item in decisions
                ),
                default=0.0,
            ),
            "maximum_observed_active_portfolio_risk": metrics[
                "maximum_observed_active_portfolio_risk"
            ],
        }
    strict.atomic_json(destination / "robustness.json", record)
    return record


def compare(reference: dict, challenger: dict) -> dict:
    left = reference["metrics"]
    right = challenger["metrics"]
    return {
        "ending_equity_difference": right["ending_equity"] - left["ending_equity"],
        "total_return_difference": right["total_return"] - left["total_return"],
        "eod_drawdown_difference": (
            right["eod_maximum_drawdown"] - left["eod_maximum_drawdown"]
        ),
        "intraday_drawdown_difference": (
            right["intraday_maximum_drawdown"]
            - left["intraday_maximum_drawdown"]
        ),
        "return_winner": (
            "dynamic_sizing_v1"
            if right["total_return"] > left["total_return"]
            else "fixed_25pct"
        ),
        "eod_drawdown_winner": (
            "dynamic_sizing_v1"
            if right["eod_maximum_drawdown"] < left["eod_maximum_drawdown"]
            else "fixed_25pct"
        ),
        "intraday_drawdown_winner": (
            "dynamic_sizing_v1"
            if right["intraday_maximum_drawdown"]
            < left["intraday_maximum_drawdown"]
            else "fixed_25pct"
        ),
    }


def run_all() -> dict:
    results = {}
    fingerprints = set()
    for period in PERIODS:
        reference = run_arm(period, "fixed_25pct")
        challenger = run_arm(period, "dynamic_sizing_v1")
        fingerprints.add(challenger["configuration_fingerprint"])
        results[period] = {
            "fixed_25pct": reference,
            "dynamic_sizing_v1": challenger,
            "comparison": compare(reference, challenger),
        }
    if len(fingerprints) != 1:
        raise RuntimeError("Dynamic Sizing configuration changed between periods.")
    payload = {
        "schema_version": 1,
        "experiment": "dynamic_sizing_v1_chronological_robustness",
        "accelerator_commit": "ea35e0f90a58f757a5fbd2f4b9171de479e209cf",
        "qualified_reference_commit": "bba0f48273815ede42374015db7c5770bf446962",
        "dataset_fingerprint": dynamic.DATASET_FINGERPRINT,
        "configuration_fingerprint": next(iter(fingerprints)),
        "period_order": list(PERIODS),
        "results": results,
    }
    strict.atomic_json(SUMMARY_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", required=True)
    parser.parse_args()
    print(json.dumps(run_all(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
