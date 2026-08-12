#!/usr/bin/env python3
"""Paired fixed/dynamic hard-cap matrix using one immutable sizing algorithm."""

from __future__ import annotations

import argparse
import csv
import json
from contextlib import contextmanager
from dataclasses import asdict, replace
from pathlib import Path

import QPX_RUN_ACCELERATOR_DYNAMIC_SIZING as dynamic
import QPX_RUN_CHALLENGER_ACCOUNT_ROBUSTNESS as robustness
import QPX_RUN_CHALLENGER_ACCOUNT_SIZED as account
import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as dynamic_robustness
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.dynamic_sizing import DynamicSizingV1, load_dynamic_sizing_config


ROOT = Path(__file__).resolve().parent
DEFINITIONS_PATH = (
    ROOT / "qpx_bot/accelerators/configs/dynamic_sizing_v1_paired_caps.json"
)
REPORT_PARENT = ROOT / "reports/qpx_dynamic_sizing_v1_paired_caps"
SUMMARY_PATH = (
    ROOT / "docs/research_results"
    / "DYNAMIC_SIZING_V1_PAIRED_CAP_MATRIX_2026-08-12.json"
)
FULL_PERIOD = "full_2024_2026"
PERIODS = {FULL_PERIOD: (strict.START, strict.END), **robustness.PERIODS}
CAP_ORDER = ("25", "40", "60", "90")
ARM_ORDER = tuple(
    arm for cap in CAP_ORDER for arm in (f"fixed_{cap}", f"dynamic_{cap}")
)


def load_definitions() -> dict:
    payload = json.loads(DEFINITIONS_PATH.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("Unsupported paired-cap definition schema.")
    if tuple(payload.get("caps", {})) != CAP_ORDER:
        raise ValueError("Paired-cap definitions must be exactly 25/40/60/90.")
    expected = {"25": 0.25, "40": 0.40, "60": 0.60, "90": 0.90}
    if {key: value["fraction"] for key, value in payload["caps"].items()} != expected:
        raise ValueError("Unexpected paired-cap fractions.")
    return payload


def experimental_config(cap: str):
    definitions = load_definitions()
    definition = definitions["caps"][cap]
    original = load_dynamic_sizing_config(dynamic.CONFIG_PATH, enabled=True)
    config = replace(
        original,
        configuration_version=definition["configuration_version"],
        maximum_position_notional_fraction=definition["fraction"],
    )
    config.validate()
    return config


def report_root(period: str, arm: str) -> Path:
    if period not in PERIODS or arm not in ARM_ORDER:
        raise ValueError(f"Unsupported paired-cap run: {period}/{arm}")
    return REPORT_PARENT / period / arm


@contextmanager
def run_scope(period: str, cap: str):
    account_configuration = load_definitions()["caps"][cap]["account_configuration"]
    if period == FULL_PERIOD:
        with account.account_sized_scope(account_configuration):
            yield
    else:
        with robustness.account_robustness_scope(period, account_configuration):
            yield


def trade_diagnostics(path: Path, equity_path: Path) -> dict:
    equities = {}
    with equity_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            equities[row["TimestampMarket"]] = float(row["TotalEquity"])
    trades = []
    with path.open(newline="", encoding="utf-8") as handle:
        trades = list(csv.DictReader(handle))
    losses = [row for row in trades if float(row["PnL"]) < 0]
    gaps = [row for row in losses if row["ExitReason"] == "STOP_GAP"]

    def compact(row):
        if row is None:
            return None
        return {
            "symbol": row["Symbol"],
            "pnl": float(row["PnL"]),
            "entry_timestamp": row["EntryTimestampMarket"],
            "exit_timestamp": row["ExitTimestampMarket"],
            "shares": int(row["Shares"]),
            "entry_price": float(row["EntryPrice"]),
            "exit_price": float(row["ExitPrice"]),
            "exit_reason": row["ExitReason"],
        }

    exposure = []
    for row in trades:
        equity = equities.get(row["EntryTimestampMarket"])
        if equity and equity > 0:
            exposure.append((
                int(row["Shares"]) * float(row["EntryPrice"]) / equity,
                row["Symbol"],
                row["EntryTimestampMarket"],
            ))
    maximum = max(exposure, default=(0.0, None, None))
    return {
        "largest_trade_loss": compact(min(losses, key=lambda row: float(row["PnL"]), default=None)),
        "largest_overnight_gap_loss": compact(min(gaps, key=lambda row: float(row["PnL"]), default=None)),
        "maximum_single_name_exposure_fraction": maximum[0],
        "maximum_single_name_exposure_symbol": maximum[1],
        "maximum_single_name_exposure_timestamp": maximum[2],
    }


def sizing_cash_rejections(result: dict) -> dict:
    diagnostics = result.get("risk_rejection_diagnostics", {})
    selected = {
        key: value
        for key, value in diagnostics.items()
        if "CASH" in key.upper()
        or "CAPITAL" in key.upper()
        or "SHARE" in key.upper()
        or "SIZING" in key.upper()
    }
    return {"count": sum(selected.values()), "diagnostics": selected}


def run_arm(period: str, arm: str) -> dict:
    dynamic.formal.verify_fixed_definition()
    treatment, cap = arm.split("_", 1)
    config = experimental_config(cap)
    accelerator = DynamicSizingV1(config)
    destination = report_root(period, arm)
    with run_scope(period, cap):
        with dynamic_robustness.output_paths(destination):
            if treatment == "dynamic":
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
    dynamic_robustness.verify_summary(summary)
    metrics = dynamic_robustness.compact_result(
        result, equity_path=destination / "equity.csv"
    )
    diagnostics = trade_diagnostics(
        destination / "trades.csv", destination / "equity.csv"
    )
    diagnostics["sizing_cash_rejections"] = sizing_cash_rejections(result)
    metrics["maximum_observed_position_notional_fraction"] = diagnostics[
        "maximum_single_name_exposure_fraction"
    ]
    record = {
        "period": period,
        "start": PERIODS[period][0].isoformat(),
        "end": PERIODS[period][1].isoformat(),
        "arm": arm,
        "treatment": treatment,
        "hard_cap": config.maximum_position_notional_fraction,
        "starting_state": {
            "qdte_value": account.STARTING_QDTE_VALUE,
            "swing_cash": account.STARTING_SWING_CASH,
            "total_equity": account.STARTING_TOTAL_EQUITY,
        },
        "algorithm": {
            "accelerator_name": "dynamic_sizing",
            "accelerator_version": config.accelerator_version,
            "configuration_version": config.configuration_version,
            "risk_tiers": [asdict(tier) for tier in config.risk_tiers],
            "configuration_fingerprint": config.fingerprint,
        },
        "dataset_fingerprint": summary["dataset_fingerprint"],
        "causal_gates": summary["gate"],
        "metrics": metrics,
        "loss_exposure_diagnostics": diagnostics,
    }
    if treatment == "dynamic":
        from collections import Counter

        reduced = sum(
            item.final_requested_shares < item.base_requested_shares
            for item in decisions
        )
        if any(item.final_requested_shares > item.base_requested_shares for item in decisions):
            raise RuntimeError("Dynamic sizing increased matching fixed-cap base shares.")
        exact_maximum_notional = max(
            (item.final_requested_notional / item.decision_time_total_equity for item in decisions),
            default=0.0,
        )
        metrics["maximum_observed_position_notional_fraction"] = exact_maximum_notional
        record["dynamic_sizing"] = {
            "decision_count": len(decisions),
            "reduced_count": reduced,
            "unchanged_count": len(decisions) - reduced,
            "percent_reduced": reduced / len(decisions) if decisions else 0.0,
            "prevented_below_one_share": sum(
                "BLOCKED_BELOW_ONE_SHARE" in item.reason_codes for item in decisions
            ),
            "multiplier_distribution": dict(
                Counter(str(item.sizing_multiplier) for item in decisions)
            ),
            "maximum_observed_position_notional_fraction": exact_maximum_notional,
            "maximum_observed_active_portfolio_risk": metrics[
                "maximum_observed_active_portfolio_risk"
            ],
        }
    strict.atomic_json(destination / "paired_cap.json", record)
    return record


def compare(fixed: dict, challenger: dict) -> dict:
    left, right = fixed["metrics"], challenger["metrics"]
    return {
        "ending_equity_difference": right["ending_equity"] - left["ending_equity"],
        "total_return_difference": right["total_return"] - left["total_return"],
        "eod_drawdown_difference": right["eod_maximum_drawdown"] - left["eod_maximum_drawdown"],
        "intraday_drawdown_difference": right["intraday_maximum_drawdown"] - left["intraday_maximum_drawdown"],
        "return_winner": "dynamic" if right["total_return"] > left["total_return"] else "fixed",
        "eod_drawdown_winner": "dynamic" if right["eod_maximum_drawdown"] < left["eod_maximum_drawdown"] else "fixed",
        "intraday_drawdown_winner": "dynamic" if right["intraday_maximum_drawdown"] < left["intraday_maximum_drawdown"] else "fixed",
    }


def run_all() -> dict:
    matrix = {}
    algorithm_tiers = set()
    for period in PERIODS:
        matrix[period] = {}
        for cap in CAP_ORDER:
            fixed = run_arm(period, f"fixed_{cap}")
            challenger = run_arm(period, f"dynamic_{cap}")
            algorithm_tiers.add(json.dumps(challenger["algorithm"]["risk_tiers"], sort_keys=True))
            matrix[period][cap] = {
                "fixed": fixed,
                "dynamic": challenger,
                "comparison": compare(fixed, challenger),
            }
    if len(algorithm_tiers) != 1:
        raise RuntimeError("Dynamic algorithm tiers differ between caps.")
    payload = {
        "schema_version": 1,
        "experiment": "dynamic_sizing_v1_paired_hard_cap_matrix",
        "source_dynamic_commit": "ea35e0f90a58f757a5fbd2f4b9171de479e209cf",
        "source_robustness_commit": "73f6dc8fd4bac9bf4f0eeb6056697d79160599a8",
        "qualified_reference_commit": "bba0f48273815ede42374015db7c5770bf446962",
        "dataset_fingerprint": dynamic.DATASET_FINGERPRINT,
        "period_order": list(PERIODS),
        "cap_order": list(CAP_ORDER),
        "identical_algorithm_tiers": json.loads(next(iter(algorithm_tiers))),
        "matrix": matrix,
    }
    strict.atomic_json(SUMMARY_PATH, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", required=True)
    parser.parse_args()
    result = run_all()
    print(f"Completed {len(PERIODS) * len(ARM_ORDER)} paired-cap runs.")
    print(f"Summary: {SUMMARY_PATH}")
    print(json.dumps({
        period: {
            cap: result["matrix"][period][cap]["comparison"]
            for cap in CAP_ORDER
        }
        for period in PERIODS
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
