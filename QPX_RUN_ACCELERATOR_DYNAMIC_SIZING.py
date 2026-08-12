#!/usr/bin/env python3
"""Research runner for reduction-only Dynamic Sizing V1."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import QPX_RUN_CHALLENGER_ACCOUNT_SIZED as account
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
import QPX_RUN_CHALLENGER_25PCT_QUALIFICATION as formal
from qpx_bot.accelerators.base import AcceleratorEntrySnapshot, DynamicSizingContext
from qpx_bot.accelerators.dynamic_sizing import DynamicSizingV1, load_dynamic_sizing_config
from qpx_bot.causal_replay import CausalDataPortal
from qpx_bot.portfolio import Portfolio


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "qpx_bot" / "accelerators" / "configs" / "dynamic_sizing_v1.json"
REPORT_PARENT = ROOT / "reports" / "qpx_dynamic_sizing_v1"
QUALIFIED_LEDGER_SHA256 = {
    "trades.csv": "316c49ab69bf8babdf0a7fd79707e3ee82dc80c1e7a813ca6add19e36cb41edb",
    "equity.csv": "8ef53746573033b0b20f7e788eb309520e07d8779afff005f1eb2b89d6b87571",
    "signals.csv": "ecb1c62aca1d17282254526e13fe09d7ec0dc7eea1a88e9a11529dd2c15a7aa9",
    "allocations.csv": "90ac573027339208ec4af6d91e0d86413a2cef1cf1e4636bf9b264afa84f8d28",
}
QUALIFIED_RESULT_SHA256 = "9bc9d5648e4b8bebabb9fc61f5f5d227bde44fd8d9e2cec88a7f0233c282929a"
QUALIFIED_GATE_SHA256 = "ee436f8c6702c5ad867bf1ddf2e9a3402cbc20c38a892c77338e716c766484fe"
DATASET_FINGERPRINT = "8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8"


def report_root(mode: str) -> Path:
    if mode not in ("disabled", "enabled"):
        raise ValueError(f"Unsupported Dynamic Sizing mode: {mode}")
    return REPORT_PARENT / mode


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def equity_ledger_diagnostics(path: Path) -> dict[str, float]:
    peak = 0.0
    maximum_intraday_drawdown = 0.0
    maximum_active_risk = 0.0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            equity = float(row["TotalEquity"])
            active_risk = float(row["ActiveRisk"])
            peak = max(peak, equity)
            if peak > 0:
                maximum_intraday_drawdown = max(
                    maximum_intraday_drawdown, (peak - equity) / peak
                )
            maximum_active_risk = max(maximum_active_risk, active_risk)
    return {
        "intraday_maximum_drawdown": maximum_intraday_drawdown,
        "maximum_observed_active_portfolio_risk": maximum_active_risk,
    }


@dataclass(slots=True)
class _RunState:
    last_open_symbol: str | None = None
    last_open_timestamp: object | None = None
    candidate_symbol: str | None = None
    candidate_timestamp: object | None = None
    existing_market_value: float = 0.0
    available_cash: float = 0.0
    active_risk: float = 0.0
    open_positions: int = 0
    pending_snapshot: AcceleratorEntrySnapshot | None = None
    decisions: list = field(default_factory=list)
    open_position_snapshots: dict[str, AcceleratorEntrySnapshot] = field(default_factory=dict)


@contextmanager
def output_scope(mode: str):
    destination = report_root(mode)
    with account.account_sized_scope("cap_25pct"):
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


@contextmanager
def enabled_accelerator_scope(accelerator: DynamicSizingV1, config):
    state = _RunState()
    original_open_snapshot = CausalDataPortal.current_open
    original_marks = strict.current_position_marks
    original_cap = strict.apply_notional_cap
    original_open_position = Portfolio.open_position

    def tracked_open(portal, symbol):
        snapshot = original_open_snapshot(portal, symbol)
        if snapshot is not None:
            state.last_open_symbol = snapshot.symbol
            state.last_open_timestamp = snapshot.time
        return snapshot

    def tracked_marks(*, portal, portfolio, last_close):
        state.candidate_symbol = state.last_open_symbol
        state.candidate_timestamp = state.last_open_timestamp
        marks, stale = original_marks(
            portal=portal,
            portfolio=portfolio,
            last_close=last_close,
        )
        state.existing_market_value = sum(
            portfolio.positions[symbol].shares * price
            for symbol, price in marks.items()
        )
        state.available_cash = portfolio.cash
        state.active_risk = portfolio.active_risk()
        state.open_positions = len(portfolio.positions)
        return marks, stale

    def accelerated_cap(*, sizing, account_equity):
        risk_budget_shares = sizing.shares
        qualified, capped, one_share_floor = original_cap(
            sizing=sizing,
            account_equity=account_equity,
        )
        state.pending_snapshot = None
        if not qualified.is_tradeable:
            return qualified, capped, one_share_floor
        if state.candidate_symbol is None or state.candidate_timestamp is None:
            raise RuntimeError("Dynamic Sizing causal entry context is missing.")
        context = DynamicSizingContext(
            decision_timestamp=state.candidate_timestamp,
            symbol=state.candidate_symbol,
            risk_budget_requested_shares=risk_budget_shares,
            base_requested_shares=qualified.shares,
            entry_price=qualified.entry_fill,
            decision_time_total_equity=account_equity,
            available_swing_cash=state.available_cash,
            decision_time_active_portfolio_risk=state.active_risk,
            maximum_active_portfolio_risk=(
                account_equity * config.maximum_active_portfolio_risk
            ),
            risk_per_share=qualified.risk_per_share,
            existing_open_position_count=state.open_positions,
            maximum_open_positions=strict.MAXIMUM_POSITIONS,
            existing_portfolio_exposure=(
                state.existing_market_value / account_equity
                if account_equity > 0 else 0.0
            ),
        )
        decision = accelerator.decide(context)
        state.decisions.append(decision)
        state.pending_snapshot = AcceleratorEntrySnapshot(
            accelerator_name=decision.accelerator_name,
            accelerator_version=decision.accelerator_version,
            configuration_version=decision.configuration_version,
            sizing_decision_id=decision.decision_id,
            sizing_multiplier=decision.sizing_multiplier,
            base_requested_shares=decision.base_requested_shares,
            final_shares=decision.final_requested_shares,
        )
        if decision.final_requested_shares < 1:
            return (
                replace(
                    qualified,
                    shares=0,
                    planned_risk=0.0,
                    blocked_reason="Dynamic Sizing adjusted below one share.",
                ),
                True,
                one_share_floor,
            )
        adjusted = replace(
            qualified,
            shares=decision.final_requested_shares,
            planned_risk=(
                decision.final_requested_shares * qualified.risk_per_share
            ),
        )
        return adjusted, (capped or adjusted.shares != sizing.shares), one_share_floor

    def accelerated_open_position(self, **kwargs):
        snapshot = state.pending_snapshot
        if snapshot is None:
            raise RuntimeError("Dynamic Sizing entry snapshot is missing.")
        try:
            position = original_open_position(self, **kwargs)
            state.open_position_snapshots[position.symbol] = snapshot
            return position
        finally:
            state.pending_snapshot = None

    CausalDataPortal.current_open = tracked_open
    strict.current_position_marks = tracked_marks
    strict.apply_notional_cap = accelerated_cap
    Portfolio.open_position = accelerated_open_position
    try:
        yield state
    finally:
        CausalDataPortal.current_open = original_open_snapshot
        strict.current_position_marks = original_marks
        strict.apply_notional_cap = original_cap
        Portfolio.open_position = original_open_position


DECISION_FIELDS = (
    "accelerator_name", "accelerator_version", "configuration_version",
    "enabled", "decision_timestamp", "symbol", "risk_budget_requested_shares",
    "base_requested_shares", "base_requested_notional", "entry_price",
    "decision_time_total_equity", "available_swing_cash",
    "decision_time_active_portfolio_risk", "maximum_active_portfolio_risk",
    "existing_open_position_count", "existing_portfolio_exposure",
    "risk_utilization", "sizing_multiplier", "final_requested_shares",
    "final_requested_notional", "reason_codes", "decision_id",
)


def write_decisions(path: Path, decisions: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_FIELDS)
        writer.writeheader()
        for decision in decisions:
            row = asdict(decision)
            row["decision_timestamp"] = decision.decision_timestamp.isoformat()
            row["reason_codes"] = "|".join(decision.reason_codes)
            writer.writerow(row)


def run(mode: str) -> dict:
    enabled = mode == "enabled"
    config = load_dynamic_sizing_config(CONFIG_PATH, enabled=enabled)
    accelerator = DynamicSizingV1(config)
    formal.verify_fixed_definition()
    with output_scope(mode) as destination:
        if enabled:
            with enabled_accelerator_scope(accelerator, strict.candidate_config()) as state:
                result, summary = strict.run_strict()
            decisions = state.decisions
        else:
            result, summary = strict.run_strict()
            decisions = []
        decision_path = destination / "dynamic_sizing_decisions.csv"
        write_decisions(decision_path, decisions)
        ledger_hashes = {
            name: sha256_file(destination / name)
            for name in QUALIFIED_LEDGER_SHA256
        }
        result_hash = canonical_sha256(result)
        gate_hash = canonical_sha256(summary["gate"])
        equity_diagnostics = equity_ledger_diagnostics(destination / "equity.csv")
        if summary["dataset_fingerprint"] != DATASET_FINGERPRINT:
            raise RuntimeError("Frozen dataset fingerprint changed.")
        if not enabled:
            failures = []
            if ledger_hashes != QUALIFIED_LEDGER_SHA256:
                failures.append("ledger hashes")
            if result_hash != QUALIFIED_RESULT_SHA256:
                failures.append("summary metrics")
            if gate_hash != QUALIFIED_GATE_SHA256:
                failures.append("causal gates")
            if failures:
                raise RuntimeError(
                    "Disabled Dynamic Sizing differs from qualified fixed-25%: "
                    + ", ".join(failures)
                )
        multipliers = Counter(str(item.sizing_multiplier) for item in decisions)
        record = {
            "schema_version": 1,
            "experiment": "qpx_dynamic_sizing_v1",
            "mode": mode,
            "baseline_commit": "bba0f48273815ede42374015db7c5770bf446962",
            "dataset_fingerprint": summary["dataset_fingerprint"],
            "configuration_fingerprint": config.fingerprint,
            "ledger_sha256": ledger_hashes,
            "qualified_ledger_sha256": QUALIFIED_LEDGER_SHA256,
            "disabled_ledger_equivalence": (
                ledger_hashes == QUALIFIED_LEDGER_SHA256 if not enabled else None
            ),
            "qualified_result_sha256": QUALIFIED_RESULT_SHA256,
            "result_sha256": result_hash,
            "qualified_gate_sha256": QUALIFIED_GATE_SHA256,
            "gate_sha256": gate_hash,
            "causal_gates": summary["gate"],
            "result": result,
            "dynamic_sizing": {
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
                "multiplier_distribution": dict(multipliers),
                "maximum_observed_position_notional_fraction": max(
                    (
                        item.final_requested_notional
                        / item.decision_time_total_equity
                        for item in decisions
                    ),
                    default=0.0,
                ),
                **equity_diagnostics,
            },
        }
        strict.atomic_json(destination / "accelerator.json", record)
        return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=("disabled", "enabled"))
    args = parser.parse_args()
    print(json.dumps(run(args.mode), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
