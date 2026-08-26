#!/usr/bin/env python3
"""Paired Candidate V1 QDTE-versus-zero-yield-cash research control."""

from __future__ import annotations

import ast
from contextlib import contextmanager
import csv
from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as qualified


ROOT = Path(__file__).resolve().parent
REPORT_ROOT = ROOT / "reports" / "qpx_qdte_vs_cash_control_2026_08_26"
PAIRED_REPORT = REPORT_ROOT / "paired_report.json"
EVIDENCE_CLASSIFICATION = (
    "CAUSAL ECONOMIC RESEARCH CONDITIONAL ON THE FROZEN DISCOVERY UNIVERSE"
)
ADR_IDENTITY = "61acf4f4c6c57cb0fe90a94d48a4770330b19955"
NON_CLAIMS = (
    "The frozen Top-100 is an intentional historical discovery/control universe.",
    "Universe selection is not being qualified.",
    "Results are not prospective evidence.",
    "Results are not live-universe qualification.",
    "Results are not production/promotion approval.",
    "Candidate V1 existing qualification status is unchanged.",
    "Control B is a zero-yield cash-sleeve counterfactual, not a qualified income implementation.",
    "Later swing-path divergence is permitted only when caused causally by the changed QDTE-versus-cash account state.",
)
PROTECTED_PATHS = (
    "QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL.py",
    "QPX_RUN_FROZEN_TOP100_PORTFOLIO.py",
    "QPX_FREEZE_TOP100_ALPACA_DATA.py",
    "QPX_CANDIDATE_V1.json",
    "qpx_bot/scenarios/candidate_v1.json",
    "qpx_bot/candidate_v1_causal.py",
    "qpx_bot/causal_replay.py",
    "qpx_bot/causal_dividends.py",
    "qpx_bot/config.py",
    "qpx_bot/indicators.py",
    "qpx_bot/strategy.py",
    "qpx_bot/portfolio.py",
    "qpx_bot/risk.py",
    "qpx_bot/allocation.py",
    "qpx_bot/qualification_provenance.json",
    "docs/CANDIDATE_V1_STRICT_CAUSAL_QUALIFICATION_2026-08-11.md",
    "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json",
)
FORBIDDEN_IMPORT_PREFIXES = (
    "QPX_FIND_BEST_ALPACA_SWING",
    "QPX_RUN_ALPACA_FINALISTS",
    "qpx_bot.symbol_selector",
    "qpx_bot.income_role",
    "qpx_bot.income_qualification",
    "qpx_bot.qualification",
)
FORBIDDEN_NETWORK_MODULES = {"requests", "urllib", "http", "socket"}
EXPECTED_CONTROL = {
    "ending_equity_2dp": 17370.70,
    "flow_adjusted_cagr_4dp": 1.9337,
    "maximum_drawdown_4dp": 0.3866,
    "sharpe_ratio_4dp": 2.1671,
    "sortino_ratio_4dp": 4.2198,
    "closed_trades": 1994,
    "qdte_distributions_received_2dp": 552.01,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protected_fingerprints() -> dict[str, str]:
    return {relative: _sha256(ROOT / relative) for relative in PROTECTED_PATHS}


def _canonical_fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _config_payload(config: Any) -> Any:
    return asdict(config) if is_dataclass(config) else dict(vars(config))


def protected_identity() -> dict[str, Any]:
    selection = json.loads(
        qualified.baseline.SELECTION_PATH.read_text(encoding="utf-8")
    )
    dataset = json.loads(
        qualified.baseline.DATASET_MANIFEST.read_text(encoding="utf-8")
    )
    top100 = tuple(str(item).strip().upper() for item in selection["top100"])
    config = qualified.candidate_config()
    return {
        "protected_files": protected_fingerprints(),
        "selection_fingerprint": selection["manifest_fingerprint"],
        "dataset_fingerprint": dataset["dataset_fingerprint"],
        "frozen_top100": top100,
        "frozen_top100_fingerprint": _canonical_fingerprint(top100),
        "candidate_config_fingerprint": _canonical_fingerprint(
            _config_payload(config)
        ),
        "causal_engine_fingerprint": _sha256(ROOT / "qpx_bot/causal_replay.py"),
        "accounting_fingerprint": _canonical_fingerprint(
            {
                name: _sha256(ROOT / name)
                for name in (
                    "qpx_bot/portfolio.py",
                    "qpx_bot/allocation.py",
                    "qpx_bot/causal_dividends.py",
                )
            }
        ),
        "qualification_dependency_fingerprint": _canonical_fingerprint(
            {
                name: _sha256(ROOT / name)
                for name in (
                    "qpx_bot/qualification_provenance.json",
                    "docs/CANDIDATE_V1_STRICT_CAUSAL_QUALIFICATION_2026-08-11.md",
                )
            }
        ),
        "starting_capital": float(config.starting_cash + config.starting_swing_cash),
        "replay_start": qualified.START.isoformat(),
        "replay_end": qualified.END.isoformat(),
    }


def validate_identity_pair(control: dict[str, Any], cash: dict[str, Any]) -> None:
    if control != cash:
        changed = sorted(
            key for key in set(control) | set(cash)
            if control.get(key) != cash.get(key)
        )
        raise RuntimeError(f"Protected experiment identity changed: {changed}")


def validate_run_pair(control: dict[str, Any], cash: dict[str, Any]) -> None:
    if float(control["starting_capital"]) != float(cash["starting_capital"]):
        raise RuntimeError("Control starting capital differs.")
    validate_identity_pair(control["protected_identity"], cash["protected_identity"])


def _assert_wrapper_boundaries() -> None:
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for name in imported:
        if any(name == item or name.startswith(item + ".") for item in FORBIDDEN_IMPORT_PREFIXES):
            raise RuntimeError(f"Forbidden experiment dependency: {name}")
        if name.split(".", 1)[0] in FORBIDDEN_NETWORK_MODULES:
            raise RuntimeError(f"Forbidden network dependency: {name}")
    direct = imported & {"QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL"}
    if direct != {"QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL"}:
        raise RuntimeError("Experiment must depend on exactly the protected strict runner.")


@dataclass(slots=True)
class RebalanceObservation:
    action: str
    shares_before: float
    shares_after: float
    income_cost_after: float
    market_value_traded: float
    trade_cash: float
    realized_pnl: float

    @classmethod
    def from_result(cls, result: Any) -> "RebalanceObservation":
        return cls(
            action=str(result.action),
            shares_before=float(result.shares_before),
            shares_after=float(result.shares_after),
            income_cost_after=float(result.income_cost_after),
            market_value_traded=float(result.market_value_traded),
            trade_cash=float(result.trade_cash),
            realized_pnl=float(result.realized_pnl),
        )


@dataclass(slots=True)
class CashSleeveController:
    reserved_cash: float = 1300.0
    rebalance_observations: list[RebalanceObservation] = field(default_factory=list)
    reserved_cash_by_time: dict[str, float] = field(default_factory=dict)
    conservation_checks: int = 0
    sizing_checks: int = 0
    last_equity_swing_cash: float | None = None

    def rebalance(
        self,
        *,
        portfolio: Any,
        income_shares: float,
        income_cost: float,
        qdte_price: float,
        position_prices: dict[str, float],
        target_income_weight: float,
        config: Any,
    ) -> tuple[float, float, Any]:
        del income_cost, qdte_price
        if abs(float(income_shares)) > 1e-12:
            raise RuntimeError("Cash counterfactual attempted to hold QDTE shares.")
        cash_before = self.reserved_cash + float(portfolio.cash)
        result = qualified.qpx.rebalance_income_allocation(
            income_shares=self.reserved_cash,
            income_cost=self.reserved_cash,
            swing_cash=portfolio.cash,
            swing_market_value=portfolio.market_value(position_prices),
            income_price=1.0,
            target_income_weight=target_income_weight,
            slippage_rate=0.0,
            tax_reserve_rate=0.0,
            tolerance=config.allocation_rebalance_tolerance,
            minimum_trade=config.minimum_rebalance_trade,
        )
        self.reserved_cash = float(result.shares_after)
        portfolio.cash = float(result.swing_cash_after)
        cash_after = self.reserved_cash + float(portfolio.cash)
        if abs(cash_after - cash_before) > 1e-8:
            raise RuntimeError("Cash sleeve created yield or leaked cash during rebalance.")
        self.conservation_checks += 1
        self.rebalance_observations.append(RebalanceObservation.from_result(result))
        return 0.0, 0.0, result

    def observe_equity(self, portfolio: Any) -> None:
        self.last_equity_swing_cash = float(portfolio.cash)

    def validate_sizing_cash(self, available_cash: float) -> None:
        if self.last_equity_swing_cash is None:
            raise RuntimeError("Sizing occurred without a causal equity observation.")
        if abs(float(available_cash) - self.last_equity_swing_cash) > 1e-8:
            raise RuntimeError("Reserved cash leaked into swing available_cash.")
        self.sizing_checks += 1


@dataclass(slots=True)
class RunInstrumentation:
    rebalance_observations: list[RebalanceObservation] = field(default_factory=list)
    reserved_cash_by_time: dict[str, float] = field(default_factory=dict)
    controller: CashSleeveController | None = None


@contextmanager
def _redirect_outputs(directory: Path) -> Iterator[None]:
    if directory.exists():
        raise FileExistsError(f"Experiment output destination already exists: {directory}")
    names = {
        "REPORT_ROOT": directory,
        "SUMMARY_PATH": directory / "summary.json",
        "TRADES_PATH": directory / "trades.csv",
        "EQUITY_PATH": directory / "equity.csv",
        "SIGNALS_PATH": directory / "signals.csv",
        "ALLOCATIONS_PATH": directory / "allocations.csv",
        "DIAGNOSTICS_PATH": directory / "diagnostics.json",
    }
    previous = {name: getattr(qualified, name) for name in names}
    try:
        for name, value in names.items():
            setattr(qualified, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(qualified, name, value)
        if any(getattr(qualified, name) != value for name, value in previous.items()):
            raise RuntimeError("Strict-runner output globals were not restored.")


@contextmanager
def _instrument_rebalances(instrumentation: RunInstrumentation) -> Iterator[None]:
    original = qualified.qpx._apply_rebalance

    def wrapper(**kwargs: Any) -> tuple[float, float, Any]:
        output = original(**kwargs)
        instrumentation.rebalance_observations.append(
            RebalanceObservation.from_result(output[2])
        )
        return output

    qualified.qpx._apply_rebalance = wrapper
    try:
        yield
    finally:
        qualified.qpx._apply_rebalance = original
        if qualified.qpx._apply_rebalance is not original:
            raise RuntimeError("No-op rebalance patch was not restored.")


@contextmanager
def _cash_intervention(instrumentation: RunInstrumentation) -> Iterator[None]:
    config = qualified.candidate_config()
    controller = CashSleeveController(
        reserved_cash=float(config.starting_cash + config.starting_swing_cash)
    )
    instrumentation.controller = controller
    original_rebalance = qualified.qpx._apply_rebalance
    original_equity = qualified.Portfolio.equity
    original_equity_point = qualified.qpx.EquityPoint
    original_buy_fill = qualified.buy_fill
    original_sizing = qualified.calculate_position_size

    def equity(portfolio: Any, prices: dict[str, float]) -> float:
        controller.observe_equity(portfolio)
        return float(original_equity(portfolio, prices)) + controller.reserved_cash

    def sizing(**kwargs: Any) -> Any:
        controller.validate_sizing_cash(float(kwargs["available_cash"]))
        return original_sizing(**kwargs)

    def equity_point(**kwargs: Any) -> Any:
        point = original_equity_point(**kwargs)
        controller.reserved_cash_by_time[point.time.isoformat()] = controller.reserved_cash
        return point

    qualified.qpx._apply_rebalance = controller.rebalance
    qualified.Portfolio.equity = equity
    qualified.qpx.EquityPoint = equity_point
    qualified.buy_fill = lambda price, slippage: float("inf")
    qualified.calculate_position_size = sizing
    try:
        yield
    finally:
        instrumentation.rebalance_observations.extend(controller.rebalance_observations)
        instrumentation.reserved_cash_by_time.update(controller.reserved_cash_by_time)
        qualified.qpx._apply_rebalance = original_rebalance
        qualified.Portfolio.equity = original_equity
        qualified.qpx.EquityPoint = original_equity_point
        qualified.buy_fill = original_buy_fill
        qualified.calculate_position_size = original_sizing
        if not (
            qualified.qpx._apply_rebalance is original_rebalance
            and qualified.Portfolio.equity is original_equity
            and qualified.qpx.EquityPoint is original_equity_point
            and qualified.buy_fill is original_buy_fill
            and qualified.calculate_position_size is original_sizing
        ):
            raise RuntimeError("Cash intervention globals were not restored.")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def _drawdown_details(equity_rows: list[dict[str, str]]) -> dict[str, Any]:
    daily: dict[str, tuple[str, float]] = {}
    for row in equity_rows:
        timestamp = row["TimestampMarket"]
        daily[timestamp[:10]] = (timestamp, float(row["TotalEquity"]))
    peak_value = -1.0
    peak_time: str | None = None
    worst = 0.0
    worst_peak: str | None = None
    worst_time: str | None = None
    for timestamp, value in daily.values():
        if value > peak_value:
            peak_value = value
            peak_time = timestamp
        drawdown = 1.0 - value / peak_value if peak_value > 0 else 0.0
        if drawdown > worst:
            worst = drawdown
            worst_peak = peak_time
            worst_time = timestamp
    return {
        "maximum_drawdown": worst,
        "peak_timestamp": worst_peak,
        "trough_timestamp": worst_time,
    }


def _qdte_attribution(
    observations: list[RebalanceObservation],
    final_income_value: float,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {
            "purchases": 0,
            "sales": 0,
            "maximum_shares_held": 0.0,
            "ending_shares": 0.0,
            "price_trading_contribution": 0.0,
        }
    purchases = int(bool(observations and observations[0].shares_before > 0)) + sum(
        item.shares_after > item.shares_before + 1e-12 for item in observations
    )
    sales = sum(
        item.shares_after < item.shares_before - 1e-12 for item in observations
    )
    maximum_shares = max(
        (value for item in observations for value in (item.shares_before, item.shares_after)),
        default=0.0,
    )
    ending_shares = observations[-1].shares_after if observations else 0.0
    final_cost = observations[-1].income_cost_after if observations else 0.0
    realized = sum(item.realized_pnl for item in observations)
    return {
        "purchases": purchases,
        "sales": sales,
        "maximum_shares_held": maximum_shares,
        "ending_shares": ending_shares,
        "price_trading_contribution": realized + final_income_value - final_cost,
    }


def _summarize_run(
    *,
    label: str,
    result: dict[str, Any],
    summary: dict[str, Any],
    directory: Path,
    instrumentation: RunInstrumentation,
    qdte_enabled: bool,
    identity: dict[str, Any],
) -> dict[str, Any]:
    equity_rows = _read_csv(directory / "equity.csv")
    trade_rows = _read_csv(directory / "trades.csv")
    signal_rows = _read_csv(directory / "signals.csv")
    allocation_rows = _read_csv(directory / "allocations.csv")
    final_row = equity_rows[-1]
    reserved = instrumentation.reserved_cash_by_time
    cash_ratios: list[float] = []
    reserved_values: list[float] = []
    for row in equity_rows:
        timestamp = row["TimestampMarket"]
        reserve = float(reserved.get(timestamp, 0.0))
        equity = float(row["TotalEquity"])
        ordinary_cash = float(row["SwingCash"])
        cash_ratios.append((ordinary_cash + reserve) / equity if equity > 0 else 0.0)
        reserved_values.append(reserve)
    final_reserved = float(reserved.get(final_row["TimestampMarket"], 0.0))
    qdte = _qdte_attribution(
        instrumentation.rebalance_observations,
        float(final_row["IncomeValue"]),
        qdte_enabled,
    )
    if not qdte_enabled and (
        float(result["qdte_distributions_received"]) != 0.0
        or qdte["maximum_shares_held"] != 0.0
    ):
        raise RuntimeError("Cash counterfactual acquired QDTE or QDTE dividends.")
    if not qdte_enabled:
        controller = instrumentation.controller
        if controller is None or controller.conservation_checks < 1:
            raise RuntimeError("Cash counterfactual did not prove zero-yield conservation.")
    decision_keys = [
        (row.get("Symbol"), row.get("EntryTime"), row.get("ExitTime"), row.get("Reason"))
        for row in trade_rows
    ]
    return {
        "label": label,
        "evidence_classification": EVIDENCE_CLASSIFICATION,
        "non_claims": NON_CLAIMS,
        "adr_identity": ADR_IDENTITY,
        "protected_identity": identity,
        "result": result,
        "causal_gates": summary.get("gate", {}),
        "starting_capital": float(result["starting_total_capital"]),
        "ending_equity": float(result["ending_equity"]),
        "net_profit": float(result["net_profit"]),
        "total_return": float(result["flow_adjusted_total_return"]),
        "maximum_drawdown": float(result["maximum_drawdown"]),
        "cagr": float(result["flow_adjusted_cagr"]),
        "sharpe_ratio": float(result["sharpe_ratio"]),
        "sortino_ratio": float(result["sortino_ratio"]),
        "realized_income_dividends": float(result["qdte_distributions_received"]),
        "qdte_dividends": float(result["qdte_distributions_received"]),
        "qdte_price_trading_contribution": qdte["price_trading_contribution"],
        "ending_cash": float(final_row["SwingCash"]) + final_reserved,
        "ending_swing_cash": float(final_row["SwingCash"]),
        "ending_reserved_income_cash": final_reserved,
        "average_cash_exposure": sum(cash_ratios) / len(cash_ratios),
        "average_reserved_income_cash": sum(reserved_values) / len(reserved_values),
        "closed_swing_pnl": float(result["closed_swing_trade_pnl"]),
        "qdte_purchases": qdte["purchases"],
        "qdte_sales": qdte["sales"],
        "maximum_qdte_shares_held": qdte["maximum_shares_held"],
        "ending_qdte_shares": qdte["ending_shares"],
        "swing_trades": int(result["closed_trades"]),
        "worst_drawdown": _drawdown_details(equity_rows),
        "trade_decision_keys": decision_keys,
        "trade_rows_fingerprint": _canonical_fingerprint(trade_rows),
        "signal_rows_fingerprint": _canonical_fingerprint(signal_rows),
        "equity_rows_fingerprint": _canonical_fingerprint(equity_rows),
        "allocation_rows_fingerprint": _canonical_fingerprint(allocation_rows),
        "reserved_cash_path_fingerprint": _canonical_fingerprint(reserved),
        "result_fingerprint": _canonical_fingerprint(result),
    }


def _run_variant(label: str, mode: str) -> dict[str, Any]:
    directory = REPORT_ROOT / label
    identity = protected_identity()
    instrumentation = RunInstrumentation()
    with _redirect_outputs(directory):
        if mode == "control":
            result, summary = qualified.run_strict()
        elif mode == "noop":
            with _instrument_rebalances(instrumentation):
                result, summary = qualified.run_strict()
        elif mode == "cash":
            with _cash_intervention(instrumentation):
                result, summary = qualified.run_strict()
        else:
            raise ValueError(f"Unknown experiment mode: {mode}")
    return _summarize_run(
        label=label,
        result=result,
        summary=summary,
        directory=directory,
        instrumentation=instrumentation,
        qdte_enabled=mode != "cash",
        identity=identity,
    )


def _validate_control(control: dict[str, Any]) -> None:
    result = control["result"]
    observed = {
        "ending_equity_2dp": round(float(result["ending_equity"]), 2),
        "flow_adjusted_cagr_4dp": round(float(result["flow_adjusted_cagr"]), 4),
        "maximum_drawdown_4dp": round(float(result["maximum_drawdown"]), 4),
        "sharpe_ratio_4dp": round(float(result["sharpe_ratio"]), 4),
        "sortino_ratio_4dp": round(float(result["sortino_ratio"]), 4),
        "closed_trades": int(result["closed_trades"]),
        "qdte_distributions_received_2dp": round(
            float(result["qdte_distributions_received"]), 2
        ),
    }
    if observed != EXPECTED_CONTROL:
        raise RuntimeError(f"Qualified control did not reproduce preserved evidence: {observed!r}")


def _delta(control: dict[str, Any], cash: dict[str, Any]) -> dict[str, float]:
    names = (
        "ending_equity",
        "net_profit",
        "total_return",
        "maximum_drawdown",
        "realized_income_dividends",
        "cagr",
        "sharpe_ratio",
        "sortino_ratio",
    )
    return {name: float(control[name]) - float(cash[name]) for name in names}


def run_experiment() -> dict[str, Any]:
    _assert_wrapper_boundaries()
    if REPORT_ROOT.exists():
        raise FileExistsError(f"Experiment output root already exists: {REPORT_ROOT}")
    before = protected_identity()
    control = _run_variant("control_a", "control")
    _validate_control(control)
    noop = _run_variant("control_a_noop", "noop")
    validate_run_pair(control, noop)
    if control["result"] != noop["result"]:
        raise RuntimeError("Disabled experiment harness is not a no-op.")
    cash = _run_variant("control_b_cash", "cash")
    cash_repeat = _run_variant("control_b_cash_repeat", "cash")
    validate_run_pair(control, cash)
    validate_run_pair(cash, cash_repeat)
    if cash["result"] != cash_repeat["result"]:
        raise RuntimeError("Cash counterfactual is not deterministic.")
    after = protected_identity()
    validate_identity_pair(before, after)

    comparison = {
        "schema_version": 2,
        "experiment": "QDTE_SLEEVE_ON_VERSUS_ZERO_YIELD_CASH",
        "evidence_classification": EVIDENCE_CLASSIFICATION,
        "non_claims": NON_CLAIMS,
        "adr_identity": ADR_IDENTITY,
        "status": "RESEARCH_COMPLETE",
        "control_a": control,
        "control_b": cash,
        "delta_control_a_minus_control_b": _delta(control, cash),
        "validation": {
            "qualified_control_reproduced": True,
            "disabled_harness_noop": True,
            "cash_repeat_deterministic": True,
            "no_qdte_shares_control_b": cash["maximum_qdte_shares_held"] == 0.0,
            "no_qdte_dividends_control_b": cash["qdte_dividends"] == 0.0,
            "zero_yield_cash_conservation": True,
            "reserved_cash_excluded_from_sizing": True,
            "protected_identity_unchanged": True,
            "trade_path_divergence_allowed": True,
        },
        "protected_identity": before,
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=False)
    PAIRED_REPORT.write_text(
        json.dumps(comparison, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return comparison


def main() -> int:
    print(EVIDENCE_CLASSIFICATION)
    for statement in NON_CLAIMS:
        print(statement)
    report = run_experiment()
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
