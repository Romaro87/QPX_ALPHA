from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_SCENARIO = PACKAGE_DIR / "scenarios" / "candidate_v1.json"


@dataclass(frozen=True, slots=True)
class Scenario:
    path: Path
    payload: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.payload["name"])

    @property
    def revision(self) -> int:
        return int(self.payload["revision"])

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(
            self.payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        return hashlib.sha256(
            canonical
        ).hexdigest()

    @property
    def symbols(self) -> dict[str, Any]:
        return self.payload["symbols"]

    @property
    def capital(self) -> dict[str, Any]:
        return self.payload["capital"]

    @property
    def allocation(self) -> dict[str, Any]:
        return self.payload["allocation"]

    @property
    def entry(self) -> dict[str, Any]:
        return self.payload["entry"]

    @property
    def risk(self) -> dict[str, Any]:
        return self.payload["risk"]

    @property
    def exit(self) -> dict[str, Any]:
        return self.payload["exit"]

    @property
    def data(self) -> dict[str, Any]:
        return self.payload["data"]

    def clone_payload(self) -> dict[str, Any]:
        return copy.deepcopy(self.payload)


def _number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be numeric.")

    result = float(value)

    if minimum is not None and result < minimum:
        raise ValueError(f"{name} must be >= {minimum}.")

    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be <= {maximum}.")

    return result


def validate_scenario(payload: dict[str, Any]) -> None:
    if int(payload.get("schema_version", 0)) != 1:
        raise ValueError("Unsupported scenario schema_version.")

    if not str(payload.get("name", "")).strip():
        raise ValueError("Scenario name cannot be empty.")

    revision = payload.get("revision")

    if (
        isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision <= 0
    ):
        raise ValueError(
            "Scenario revision must be a positive integer."
        )

    required = (
        "data",
        "symbols",
        "capital",
        "allocation",
        "entry",
        "risk",
        "exit",
        "execution",
        "tax",
        "safety",
    )

    for key in required:
        if not isinstance(payload.get(key), dict):
            raise ValueError(f"Scenario section {key!r} is required.")

    data = payload["data"]

    provider = str(
        data.get("provider", "")
    ).strip().lower()

    if provider not in {
        "massive_cache",
        "alpaca_sip",
    }:
        raise ValueError(
            "data.provider must be massive_cache or alpaca_sip."
        )

    if data.get("cache") is not True:
        raise ValueError(
            "Scenario market-data caching must remain enabled."
        )

    symbols = payload["symbols"]

    candidates = tuple(
        str(x).strip().upper()
        for x in symbols.get("candidate_symbols", ())
        if str(x).strip()
    )
    tradable = tuple(
        str(x).strip().upper()
        for x in symbols.get("tradable_symbols", ())
        if str(x).strip()
    )

    if not candidates:
        raise ValueError("At least one candidate symbol is required.")

    if len(candidates) != len(set(candidates)):
        raise ValueError("Candidate symbols must be unique.")

    if not tradable:
        raise ValueError("At least one tradable symbol is required.")

    if not set(tradable).issubset(candidates):
        raise ValueError("Tradable symbols must be candidates.")

    if not str(symbols.get("income_symbol", "")).strip():
        raise ValueError("Income symbol is required.")

    if not str(symbols.get("volatility_symbol", "")).strip():
        raise ValueError("Volatility symbol is required.")

    _number(
        payload["capital"].get("monthly_contribution"),
        "monthly_contribution",
        minimum=0.0,
    )

    allocation = payload["allocation"]

    income_12 = _number(
        allocation.get("income_weight_years_1_2"),
        "income_weight_years_1_2",
        minimum=0.0,
        maximum=1.0,
    )
    swing_12 = _number(
        allocation.get("swing_weight_years_1_2"),
        "swing_weight_years_1_2",
        minimum=0.0,
        maximum=1.0,
    )

    income_later = _number(
        allocation.get("income_weight_later"),
        "income_weight_later",
        minimum=0.0,
        maximum=1.0,
    )
    swing_later = _number(
        allocation.get("swing_weight_later"),
        "swing_weight_later",
        minimum=0.0,
        maximum=1.0,
    )

    if abs(income_12 + swing_12 - 1.0) > 1e-9:
        raise ValueError("Years 1-2 allocation must equal 100%.")

    if abs(income_later + swing_later - 1.0) > 1e-9:
        raise ValueError("Later allocation must equal 100%.")

    cadence = str(
        allocation.get("rebalance_frequency", "")
    ).lower()

    if cadence not in {"daily", "weekly", "monthly"}:
        raise ValueError(
            "rebalance_frequency must be daily, weekly, or monthly."
        )

    _number(
        allocation.get("rebalance_tolerance"),
        "rebalance_tolerance",
        minimum=0.0,
        maximum=0.10,
    )

    _number(
        allocation.get("minimum_rebalance_trade"),
        "minimum_rebalance_trade",
        minimum=0.0,
    )

    risk = payload["risk"]

    _number(
        risk.get("risk_per_trade"),
        "risk_per_trade",
        minimum=0.000001,
        maximum=1.0,
    )

    _number(
        risk.get("maximum_active_portfolio_risk"),
        "maximum_active_portfolio_risk",
        minimum=0.000001,
        maximum=1.0,
    )

    _number(
        risk.get("maximum_position_notional"),
        "maximum_position_notional",
        minimum=0.000001,
        maximum=1.0,
    )

    positions = risk.get("maximum_positions")

    if (
        isinstance(positions, bool)
        or not isinstance(positions, int)
        or positions <= 0
    ):
        raise ValueError("maximum_positions must be a positive integer.")

    if not isinstance(risk.get("kelly_enabled"), bool):
        raise ValueError("kelly_enabled must be true or false.")

    entry = payload["entry"]

    _number(
        entry.get("maximum_gap_atr_multiple"),
        "maximum_gap_atr_multiple",
        minimum=0.000001,
    )

    low = _number(
        entry.get("vix_exclusion_low"),
        "vix_exclusion_low",
        minimum=0.0,
    )
    high = _number(
        entry.get("vix_exclusion_high"),
        "vix_exclusion_high",
        minimum=0.0,
    )

    if low >= high:
        raise ValueError(
            "vix_exclusion_low must be below vix_exclusion_high."
        )

    stop = _number(
        payload["exit"].get("stop_atr_multiple"),
        "stop_atr_multiple",
        minimum=0.000001,
    )
    target = _number(
        payload["exit"].get("target_atr_multiple"),
        "target_atr_multiple",
        minimum=0.000001,
    )

    if target <= stop:
        raise ValueError(
            "target_atr_multiple must exceed stop_atr_multiple."
        )

    if payload["safety"].get("live_broker_enabled") is not False:
        raise ValueError(
            "Scenario testing requires live_broker_enabled=false."
        )


def load_scenario(
    filename: str | Path = DEFAULT_SCENARIO,
) -> Scenario:
    path = Path(filename).expanduser().resolve()

    payload = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(payload, dict):
        raise ValueError("Scenario root must be a JSON object.")

    validate_scenario(payload)

    return Scenario(
        path=path,
        payload=payload,
    )
