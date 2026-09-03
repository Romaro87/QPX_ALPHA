"""Candidate V1 entry logic over a scalar causal snapshot.

This module intentionally receives no candle sequence, indicator sequence,
history mapping, replay portal, or future timestamp.  The strategy can only
evaluate information already released by the replay engine at the current
completed bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from qpx_bot.config import BotConfig


@dataclass(frozen=True, slots=True)
class CandidateV1CausalInputs:
    index: int
    current_close: float
    current_volume: int
    current_fast: float
    previous_fast: float
    current_slow: float
    previous_slow: float
    current_rsi: float
    previous_rsi: float
    current_rmi: float
    previous_rmi: float
    current_sma: float
    slope_sma: float
    baseline_volume: float
    current_atr: float
    prior_high: float
    vix: float


@dataclass(frozen=True, slots=True)
class CandidateV1CausalEvaluation:
    index: int
    should_enter: bool
    checks: Mapping[str, bool]
    triggers: tuple[str, ...]
    failed_checks: tuple[str, ...]


def evaluate_candidate_v1_causal(
    *,
    inputs: CandidateV1CausalInputs,
    config: BotConfig,
) -> CandidateV1CausalEvaluation:
    """Evaluate Candidate V1 from current/prior scalar observations only."""
    config.validate()

    ema_cross = (
        inputs.previous_fast <= inputs.previous_slow
        and inputs.current_fast > inputs.current_slow
    )
    rsi_cross = (
        inputs.previous_rsi <= config.rsi_strength_level
        and inputs.current_rsi > config.rsi_strength_level
    )
    rmi_cross = (
        inputs.previous_rmi <= config.rsi_strength_level
        and inputs.current_rmi > config.rsi_strength_level
    )
    triggers = [
        name
        for name, triggered in (
            ("EMA_CROSS", ema_cross),
            ("RSI_CROSS", rsi_cross),
            ("RMI_CROSS", rmi_cross),
        )
        if triggered
    ]

    checks: dict[str, bool] = {
        "data_ready": True,
        "price_above_sma": (
            inputs.current_close > inputs.current_sma
        ),
        "sma_slope_positive": (
            inputs.current_sma > inputs.slope_sma
        ),
        "average_volume": (
            inputs.baseline_volume
            >= config.minimum_average_daily_volume
        ),
        "breakout_volume": (
            inputs.current_volume
            >= (
                inputs.baseline_volume
                * config.breakout_volume_multiplier
            )
        ),
        "price_breakout": (
            inputs.current_close > inputs.prior_high
        ),
        "vix_filter": (
            inputs.vix <= config.maximum_vix_for_entries
        ),
        "rsi_not_overbought": (
            inputs.current_rsi <= config.rsi_overbought
        ),
        "momentum_trigger": bool(triggers),
    }

    failed = tuple(
        name
        for name, passed in checks.items()
        if not passed
    )

    return CandidateV1CausalEvaluation(
        index=inputs.index,
        should_enter=not failed,
        checks=checks,
        triggers=tuple(triggers),
        failed_checks=failed,
    )
