"""Strict authoritative Candidate V1 configuration loading.

``QPX_CANDIDATE_V1.json`` is the sole authority for Candidate V1 tunable
semantics. This module deliberately has no Candidate-specific fallback values.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

from qpx_bot.config import BotConfig


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CANDIDATE_V1_CONFIG = ROOT / "QPX_CANDIDATE_V1.json"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Z0-9][A-Z0-9_.-]*$")


class CandidateV1ConfigError(RuntimeError):
    """The governed Candidate V1 configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class CandidateV1ConfigSnapshot:
    """Immutable, validated Candidate V1 configuration at one boundary."""

    bot_config: BotConfig
    maximum_position_notional_fraction: float
    maximum_gap_atr_multiple: float
    kelly_enabled: bool
    rebalance_weekday: int
    forward_starting_capital: float
    canonical_json: str
    fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        """Return a detached canonical JSON object suitable for persistence."""
        payload = json.loads(self.canonical_json)
        if not isinstance(payload, dict):
            raise CandidateV1ConfigError("Canonical Candidate V1 root is invalid.")
        return payload


def _pairs_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateV1ConfigError(
                f"Duplicate Candidate V1 configuration field: {key}"
            )
        result[key] = value
    return result


def _object(value: Any, name: str, expected: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CandidateV1ConfigError(f"{name} must be a JSON object.")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise CandidateV1ConfigError(
            f"{name} fields are invalid; missing={missing}; unknown={unknown}."
        )
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise CandidateV1ConfigError(f"{name} must be a JSON boolean.")
    return value


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        raise CandidateV1ConfigError(f"{name} must be a JSON integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise CandidateV1ConfigError(f"{name} is outside its governed range.")
    return value


def _number(
    value: Any,
    name: str,
    *,
    minimum: float,
    maximum: float | None = None,
    minimum_inclusive: bool = True,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CandidateV1ConfigError(f"{name} must be a JSON number.")
    result = float(value)
    if not math.isfinite(result):
        raise CandidateV1ConfigError(f"{name} must be finite.")
    below = result < minimum if minimum_inclusive else result <= minimum
    if below or (maximum is not None and result > maximum):
        raise CandidateV1ConfigError(f"{name} is outside its governed range.")
    return result


def _identifier(value: Any, name: str, expected: str | None = None) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise CandidateV1ConfigError(f"{name} is not a valid governed identifier.")
    if expected is not None and value != expected:
        raise CandidateV1ConfigError(f"{name} is unsupported: {value}")
    return value


def canonical_candidate_v1_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize a validated JSON-compatible object deterministically."""
    def normalize(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): normalize(child) for key, child in value.items()}
        if isinstance(value, list):
            return [normalize(child) for child in value]
        if isinstance(value, float):
            if value == 0.0:
                return 0
            if value.is_integer():
                return int(value)
        return value

    try:
        return json.dumps(
            normalize(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CandidateV1ConfigError(
            "Candidate V1 configuration is not canonically serializable."
        ) from exc


def _validate_payload(payload: Mapping[str, Any]) -> CandidateV1ConfigSnapshot:
    root = _object(payload, "Candidate V1 configuration", {
        "schema_version", "candidate", "strategy_version", "status",
        "portfolio", "indicators", "entry", "exit", "risk", "execution",
        "tax_reserve",
    })
    if _integer(root["schema_version"], "schema_version", minimum=1) != 1:
        raise CandidateV1ConfigError("Unsupported Candidate V1 schema version.")
    _identifier(root["candidate"], "candidate", "QPX_CANDIDATE_V1")
    _identifier(root["strategy_version"], "strategy_version", "CANDIDATE_V1_CURRENT")
    _identifier(root["status"], "status", "FORWARD_PAPER_VALIDATION_ONLY")

    portfolio = _object(root["portfolio"], "portfolio", {
        "historical_starting_income_cash", "historical_starting_swing_cash",
        "forward_starting_capital", "monthly_external_contribution",
        "income_symbol", "income_allocation_years_1_2",
        "swing_allocation_years_1_2", "income_allocation_later",
        "swing_allocation_later", "rebalance_frequency", "rebalance_weekday",
        "rebalance_tolerance", "minimum_rebalance_trade",
    })
    indicators = _object(root["indicators"], "indicators", {
        "ema_fast_period", "ema_slow_period", "rsi_period",
        "rsi_strength_level", "rmi_period", "rmi_momentum",
        "sma_trend_period", "sma_slope_lookback", "atr_period",
        "average_volume_period",
    })
    entry = _object(root["entry"], "entry", {
        "minimum_average_15m_volume", "breakout_volume_multiplier",
        "breakout_lookback", "maximum_vix", "rsi_overbought",
        "maximum_gap_atr_multiple",
    })
    exit_policy = _object(root["exit"], "exit", {
        "stop_atr_multiple", "target_atr_multiple", "trailing_activation_atr",
    })
    risk = _object(root["risk"], "risk", {
        "maximum_positions", "risk_per_trade", "maximum_active_portfolio_risk",
        "kelly_enabled", "kelly_fraction", "minimum_kelly_trades",
        "maximum_position_notional_fraction",
    })
    execution = _object(root["execution"], "execution", {"slippage_rate"})
    tax = _object(root["tax_reserve"], "tax_reserve", {"annual_rate"})

    frequency = portfolio["rebalance_frequency"]
    if frequency not in {"daily", "weekly", "monthly"}:
        raise CandidateV1ConfigError("portfolio.rebalance_frequency is invalid.")
    income_symbol = _identifier(
        portfolio["income_symbol"], "portfolio.income_symbol", "QDTE"
    )

    bot_values = {
        "starting_cash": _number(portfolio["historical_starting_income_cash"], "portfolio.historical_starting_income_cash", minimum=0.0, minimum_inclusive=False),
        "starting_swing_cash": _number(portfolio["historical_starting_swing_cash"], "portfolio.historical_starting_swing_cash", minimum=0.0),
        "monthly_contribution": _number(portfolio["monthly_external_contribution"], "portfolio.monthly_external_contribution", minimum=0.0),
        "dividend_allocation_years_1_2": _number(portfolio["income_allocation_years_1_2"], "portfolio.income_allocation_years_1_2", minimum=0.0, maximum=1.0),
        "swing_allocation_years_1_2": _number(portfolio["swing_allocation_years_1_2"], "portfolio.swing_allocation_years_1_2", minimum=0.0, maximum=1.0),
        "dividend_allocation_later": _number(portfolio["income_allocation_later"], "portfolio.income_allocation_later", minimum=0.0, maximum=1.0),
        "swing_allocation_later": _number(portfolio["swing_allocation_later"], "portfolio.swing_allocation_later", minimum=0.0, maximum=1.0),
        "allocation_rebalance_frequency": frequency,
        "allocation_rebalance_tolerance": _number(portfolio["rebalance_tolerance"], "portfolio.rebalance_tolerance", minimum=0.0, maximum=0.1),
        "minimum_rebalance_trade": _number(portfolio["minimum_rebalance_trade"], "portfolio.minimum_rebalance_trade", minimum=0.0),
        "dividend_symbol": income_symbol,
        "maximum_swing_positions": _integer(risk["maximum_positions"], "risk.maximum_positions", minimum=1),
        "ema_fast_period": _integer(indicators["ema_fast_period"], "indicators.ema_fast_period", minimum=2),
        "ema_slow_period": _integer(indicators["ema_slow_period"], "indicators.ema_slow_period", minimum=2),
        "rsi_period": _integer(indicators["rsi_period"], "indicators.rsi_period", minimum=2),
        "rsi_overbought": _number(entry["rsi_overbought"], "entry.rsi_overbought", minimum=0.0, maximum=100.0),
        "rsi_strength_level": _number(indicators["rsi_strength_level"], "indicators.rsi_strength_level", minimum=0.0, maximum=100.0),
        "rmi_period": _integer(indicators["rmi_period"], "indicators.rmi_period", minimum=2),
        "rmi_momentum": _integer(indicators["rmi_momentum"], "indicators.rmi_momentum", minimum=1),
        "sma_trend_period": _integer(indicators["sma_trend_period"], "indicators.sma_trend_period", minimum=2),
        "sma_slope_lookback": _integer(indicators["sma_slope_lookback"], "indicators.sma_slope_lookback", minimum=1),
        "atr_period": _integer(indicators["atr_period"], "indicators.atr_period", minimum=2),
        "stop_atr_multiple": _number(exit_policy["stop_atr_multiple"], "exit.stop_atr_multiple", minimum=0.0, minimum_inclusive=False),
        "target_atr_multiple": _number(exit_policy["target_atr_multiple"], "exit.target_atr_multiple", minimum=0.0, minimum_inclusive=False),
        "trailing_activation_atr": _number(exit_policy["trailing_activation_atr"], "exit.trailing_activation_atr", minimum=0.0, minimum_inclusive=False),
        "minimum_average_daily_volume": _integer(entry["minimum_average_15m_volume"], "entry.minimum_average_15m_volume", minimum=0),
        "average_volume_period": _integer(indicators["average_volume_period"], "indicators.average_volume_period", minimum=2),
        "breakout_volume_multiplier": _number(entry["breakout_volume_multiplier"], "entry.breakout_volume_multiplier", minimum=0.0, minimum_inclusive=False),
        "breakout_lookback": _integer(entry["breakout_lookback"], "entry.breakout_lookback", minimum=2),
        "maximum_vix_for_entries": _number(entry["maximum_vix"], "entry.maximum_vix", minimum=0.0),
        "risk_per_trade": _number(risk["risk_per_trade"], "risk.risk_per_trade", minimum=0.0, maximum=1.0, minimum_inclusive=False),
        "maximum_active_portfolio_risk": _number(risk["maximum_active_portfolio_risk"], "risk.maximum_active_portfolio_risk", minimum=0.0, maximum=1.0, minimum_inclusive=False),
        "kelly_fraction": _number(risk["kelly_fraction"], "risk.kelly_fraction", minimum=0.0, maximum=1.0),
        "minimum_kelly_trades": _integer(risk["minimum_kelly_trades"], "risk.minimum_kelly_trades", minimum=1),
        "slippage_rate": _number(execution["slippage_rate"], "execution.slippage_rate", minimum=0.0, maximum=1.0),
        "annual_tax_reserve_rate": _number(tax["annual_rate"], "tax_reserve.annual_rate", minimum=0.0, maximum=1.0),
    }
    if set(bot_values) != {item.name for item in fields(BotConfig)}:
        raise CandidateV1ConfigError(
            "Candidate V1 does not explicitly cover every BotConfig field."
        )
    config = BotConfig(**bot_values)
    try:
        config.validate()
    except ValueError as exc:
        raise CandidateV1ConfigError(str(exc)) from exc

    kelly_enabled = _boolean(risk["kelly_enabled"], "risk.kelly_enabled")
    if kelly_enabled:
        raise CandidateV1ConfigError(
            "Candidate V1 V1 supports only the approved no-Kelly behavior."
        )
    maximum_notional = _number(risk["maximum_position_notional_fraction"], "risk.maximum_position_notional_fraction", minimum=0.0, maximum=1.0, minimum_inclusive=False)
    maximum_gap = _number(entry["maximum_gap_atr_multiple"], "entry.maximum_gap_atr_multiple", minimum=0.0, minimum_inclusive=False)
    rebalance_weekday = _integer(portfolio["rebalance_weekday"], "portfolio.rebalance_weekday", minimum=0, maximum=4)
    forward_capital = _number(portfolio["forward_starting_capital"], "portfolio.forward_starting_capital", minimum=0.0, minimum_inclusive=False)
    canonical = canonical_candidate_v1_bytes(root)
    return CandidateV1ConfigSnapshot(
        bot_config=config,
        maximum_position_notional_fraction=maximum_notional,
        maximum_gap_atr_multiple=maximum_gap,
        kelly_enabled=kelly_enabled,
        rebalance_weekday=rebalance_weekday,
        forward_starting_capital=forward_capital,
        canonical_json=canonical.decode("utf-8"),
        fingerprint=hashlib.sha256(canonical).hexdigest(),
    )


def load_candidate_v1_config(path: Path = DEFAULT_CANDIDATE_V1_CONFIG) -> CandidateV1ConfigSnapshot:
    """Load the complete governed profile; no missing-file fallback exists."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CandidateV1ConfigError(
            f"Cannot load governed Candidate V1 configuration: {path}"
        ) from exc
    try:
        payload = json.loads(text, object_pairs_hook=_pairs_object)
    except CandidateV1ConfigError:
        raise
    except json.JSONDecodeError as exc:
        raise CandidateV1ConfigError("Candidate V1 configuration is invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise CandidateV1ConfigError("Candidate V1 configuration root must be an object.")
    return _validate_payload(payload)


def candidate_v1_config_from_snapshot(
    payload: Mapping[str, Any], expected_fingerprint: str,
) -> CandidateV1ConfigSnapshot:
    """Validate a persisted immutable snapshot and its governed identity."""
    if not _SHA256.fullmatch(expected_fingerprint):
        raise CandidateV1ConfigError("Candidate V1 fingerprint is malformed.")
    snapshot = _validate_payload(payload)
    if snapshot.fingerprint != expected_fingerprint:
        raise CandidateV1ConfigError("Candidate V1 snapshot fingerprint mismatch.")
    return snapshot


def disabled_kelly_trade_history(snapshot: CandidateV1ConfigSnapshot) -> tuple[float, ...]:
    """Return the only approved V1 Kelly input without hidden policy fallback."""
    if snapshot.kelly_enabled:
        raise CandidateV1ConfigError("Enabled Kelly semantics are unsupported.")
    return ()
