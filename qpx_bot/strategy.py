"""Entry decisions and ATR-based exit management for QPX Bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import IndicatorSet
from qpx_bot.portfolio import Position


@dataclass(frozen=True, slots=True)
class EntryEvaluation:
    """Complete explanation of one potential long entry."""

    index: int
    should_enter: bool
    checks: dict[str, bool]
    triggers: tuple[str, ...]
    failed_checks: tuple[str, ...]

    @property
    def decision(self) -> str:
        return "ENTER" if self.should_enter else "HOLD"


@dataclass(frozen=True, slots=True)
class ExitEvaluation:
    """Exit decision plus the stop state for the next daily bar."""

    should_exit: bool
    reason: str | None
    exit_price: float | None
    next_stop_price: float
    highest_price: float
    trailing_active: bool

    @property
    def decision(self) -> str:
        return "EXIT" if self.should_exit else "HOLD"


def _value(
    series: Sequence[float | None],
    index: int,
) -> float | None:
    if index < 0 or index >= len(series):
        return None
    return series[index]


def _resolve_vix(
    vix: float | Sequence[float],
    index: int,
) -> float:
    if isinstance(vix, (int, float)):
        value = float(vix)
    else:
        if index < 0 or index >= len(vix):
            raise IndexError("VIX series does not cover the requested index.")
        value = float(vix[index])

    if value < 0:
        raise ValueError("VIX cannot be negative.")

    return value


def evaluate_entry(
    *,
    candles: Sequence[Candle],
    indicators: IndicatorSet,
    index: int,
    vix: float | Sequence[float],
    config: BotConfig,
) -> EntryEvaluation:
    """
    Evaluate the configured long-entry rules at one closing bar.

    Every filter must pass. At least one momentum trigger must cross
    bullishly on the current bar. The order is intended for execution
    at the next bar's open by the later backtesting engine.
    """
    config.validate()

    if index < 0 or index >= len(candles):
        raise IndexError("Entry index is outside the candle series.")

    previous_index = index - 1
    slope_index = index - config.sma_slope_lookback
    breakout_start = index - config.breakout_lookback

    if (
        previous_index < 0
        or slope_index < 0
        or breakout_start < 0
    ):
        return EntryEvaluation(
            index=index,
            should_enter=False,
            checks={"data_ready": False},
            triggers=(),
            failed_checks=("data_ready",),
        )

    current_fast = _value(indicators.ema_fast, index)
    previous_fast = _value(indicators.ema_fast, previous_index)
    current_slow = _value(indicators.ema_slow, index)
    previous_slow = _value(indicators.ema_slow, previous_index)
    current_rsi = _value(indicators.rsi, index)
    previous_rsi = _value(indicators.rsi, previous_index)
    current_rmi = _value(indicators.rmi, index)
    previous_rmi = _value(indicators.rmi, previous_index)
    current_sma = _value(indicators.sma_trend, index)
    slope_sma = _value(indicators.sma_trend, slope_index)
    baseline_volume = _value(
        indicators.average_volume,
        previous_index,
    )
    current_atr = _value(indicators.atr, index)

    required_values = (
        current_fast,
        previous_fast,
        current_slow,
        previous_slow,
        current_rsi,
        previous_rsi,
        current_rmi,
        previous_rmi,
        current_sma,
        slope_sma,
        baseline_volume,
        current_atr,
    )

    if any(value is None for value in required_values):
        return EntryEvaluation(
            index=index,
            should_enter=False,
            checks={"data_ready": False},
            triggers=(),
            failed_checks=("data_ready",),
        )

    candle = candles[index]
    prior_high = max(
        prior_candle.high
        for prior_candle in candles[breakout_start:index]
    )
    current_vix = _resolve_vix(vix, index)

    ema_cross = (
        previous_fast <= previous_slow
        and current_fast > current_slow
    )
    rsi_cross = (
        previous_rsi <= config.rsi_strength_level
        and current_rsi > config.rsi_strength_level
    )
    rmi_cross = (
        previous_rmi <= config.rsi_strength_level
        and current_rmi > config.rsi_strength_level
    )

    triggers = tuple(
        name
        for name, triggered in (
            ("EMA_CROSS", ema_cross),
            ("RSI_CROSS", rsi_cross),
            ("RMI_CROSS", rmi_cross),
        )
        if triggered
    )

    checks = {
        "data_ready": True,
        "price_above_sma": candle.close > current_sma,
        "sma_slope_positive": current_sma > slope_sma,
        "average_volume": (
            baseline_volume
            >= config.minimum_average_daily_volume
        ),
        "breakout_volume": (
            candle.volume
            >= (
                baseline_volume
                * config.breakout_volume_multiplier
            )
        ),
        "price_breakout": candle.close > prior_high,
        "vix_filter": (
            current_vix <= config.maximum_vix_for_entries
        ),
        "rsi_not_overbought": (
            current_rsi <= config.rsi_overbought
        ),
        "momentum_trigger": bool(triggers),
    }

    failed = tuple(
        name
        for name, passed in checks.items()
        if not passed
    )

    return EntryEvaluation(
        index=index,
        should_enter=not failed,
        checks=checks,
        triggers=triggers,
        failed_checks=failed,
    )


def scan_entry_signals(
    *,
    candles: Sequence[Candle],
    indicators: IndicatorSet,
    vix: float | Sequence[float],
    config: BotConfig,
) -> list[EntryEvaluation]:
    """Return every qualifying long-entry signal."""
    start_index = max(
        config.sma_trend_period - 1,
        config.breakout_lookback,
        config.sma_slope_lookback,
        1,
    )
    signals: list[EntryEvaluation] = []

    for index in range(start_index, len(candles)):
        evaluation = evaluate_entry(
            candles=candles,
            indicators=indicators,
            index=index,
            vix=vix,
            config=config,
        )
        if evaluation.should_enter:
            signals.append(evaluation)

    return signals


def evaluate_exit(
    *,
    position: Position,
    candle: Candle,
    current_atr: float,
    config: BotConfig,
) -> ExitEvaluation:
    """
    Evaluate stop, target, and trailing-stop behavior.

    Existing stop and target levels are checked before calculating a
    new trailing stop. This prevents using the current bar's high to
    create a stop that is then assumed to have executed earlier inside
    the same bar. When both stop and target are touched, the stop wins.
    """
    config.validate()

    if current_atr <= 0:
        raise ValueError("Current ATR must be positive.")

    stop = position.stop_price
    target = position.target_price

    if candle.open <= stop:
        return ExitEvaluation(
            should_exit=True,
            reason="STOP_GAP",
            exit_price=candle.open,
            next_stop_price=stop,
            highest_price=max(position.highest_price, candle.high),
            trailing_active=False,
        )

    if candle.low <= stop:
        return ExitEvaluation(
            should_exit=True,
            reason="ATR_STOP",
            exit_price=stop,
            next_stop_price=stop,
            highest_price=max(position.highest_price, candle.high),
            trailing_active=False,
        )

    if candle.open >= target:
        return ExitEvaluation(
            should_exit=True,
            reason="TARGET_GAP",
            exit_price=candle.open,
            next_stop_price=stop,
            highest_price=max(position.highest_price, candle.high),
            trailing_active=False,
        )

    if candle.high >= target:
        return ExitEvaluation(
            should_exit=True,
            reason="ATR_TARGET",
            exit_price=target,
            next_stop_price=stop,
            highest_price=max(position.highest_price, candle.high),
            trailing_active=False,
        )

    highest_price = max(position.highest_price, candle.high)

    trailing_activation = (
        position.entry_trailing_activation_atr
        if position.entry_trailing_activation_atr
        is not None
        else config.trailing_activation_atr
    )

    trailing_stop_multiple = (
        position.entry_stop_atr_multiple
        if position.entry_stop_atr_multiple
        is not None
        else config.stop_atr_multiple
    )

    activation_price = (
        position.entry_price
        + (
            position.entry_atr
            * trailing_activation
        )
    )

    trailing_active = (
        highest_price
        >= activation_price
    )

    next_stop = stop

    if trailing_active:
        candidate = (
            highest_price
            - (
                current_atr
                * trailing_stop_multiple
            )
        )
        next_stop = max(stop, candidate)

    return ExitEvaluation(
        should_exit=False,
        reason=None,
        exit_price=None,
        next_stop_price=next_stop,
        highest_price=highest_price,
        trailing_active=trailing_active,
    )
