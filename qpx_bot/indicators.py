"""Deterministic technical-indicator calculations for QPX Bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle


OptionalSeries = list[float | None]


def _validate_period(period: int) -> None:
    if period < 1:
        raise ValueError("Indicator period must be at least 1.")


def simple_moving_average(
    values: Sequence[float],
    period: int,
) -> OptionalSeries:
    """Return a rolling simple moving average."""
    _validate_period(period)
    result: OptionalSeries = [None] * len(values)

    if len(values) < period:
        return result

    rolling_sum = 0.0

    for index, value in enumerate(values):
        rolling_sum += float(value)

        if index >= period:
            rolling_sum -= float(values[index - period])

        if index >= period - 1:
            result[index] = rolling_sum / period

    return result


def exponential_moving_average(
    values: Sequence[float],
    period: int,
) -> OptionalSeries:
    """Return an EMA seeded by the first full-period SMA."""
    _validate_period(period)
    result: OptionalSeries = [None] * len(values)

    if len(values) < period:
        return result

    seed = sum(float(value) for value in values[:period]) / period
    seed_index = period - 1
    result[seed_index] = seed

    multiplier = 2.0 / (period + 1.0)
    previous = seed

    for index in range(period, len(values)):
        current = (
            (float(values[index]) - previous) * multiplier
            + previous
        )
        result[index] = current
        previous = current

    return result


def relative_strength_index(
    values: Sequence[float],
    period: int,
) -> OptionalSeries:
    """Return Wilder's Relative Strength Index."""
    _validate_period(period)
    result: OptionalSeries = [None] * len(values)

    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []

    for index in range(1, period + 1):
        change = float(values[index]) - float(values[index - 1])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    result[period] = _rsi_value(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = float(values[index]) - float(values[index - 1])
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        average_gain = (
            (average_gain * (period - 1)) + gain
        ) / period
        average_loss = (
            (average_loss * (period - 1)) + loss
        ) / period

        result[index] = _rsi_value(average_gain, average_loss)

    return result


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_gain == 0.0 and average_loss == 0.0:
        return 50.0

    if average_loss == 0.0:
        return 100.0

    relative_strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def relative_momentum_index(
    values: Sequence[float],
    period: int,
    momentum: int,
) -> OptionalSeries:
    """Return RMI using momentum changes and Wilder smoothing."""
    _validate_period(period)

    if momentum < 1:
        raise ValueError("RMI momentum must be at least 1.")

    result: OptionalSeries = [None] * len(values)
    seed_index = momentum + period - 1

    if len(values) <= seed_index:
        return result

    gains: list[float] = []
    losses: list[float] = []

    for index in range(momentum, seed_index + 1):
        change = float(values[index]) - float(values[index - momentum])
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period
    result[seed_index] = _rsi_value(average_gain, average_loss)

    for index in range(seed_index + 1, len(values)):
        change = float(values[index]) - float(values[index - momentum])
        gain = max(change, 0.0)
        loss = max(-change, 0.0)

        average_gain = (
            (average_gain * (period - 1)) + gain
        ) / period
        average_loss = (
            (average_loss * (period - 1)) + loss
        ) / period

        result[index] = _rsi_value(average_gain, average_loss)

    return result


def true_range(candles: Sequence[Candle]) -> list[float]:
    """Return daily true range values."""
    if not candles:
        return []

    result = [candles[0].high - candles[0].low]

    for index in range(1, len(candles)):
        candle = candles[index]
        previous_close = candles[index - 1].close
        result.append(
            max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )

    return result


def average_true_range(
    candles: Sequence[Candle],
    period: int,
) -> OptionalSeries:
    """Return Wilder's Average True Range."""
    _validate_period(period)
    ranges = true_range(candles)
    result: OptionalSeries = [None] * len(ranges)

    if len(ranges) < period:
        return result

    seed_index = period - 1
    previous = sum(ranges[:period]) / period
    result[seed_index] = previous

    for index in range(period, len(ranges)):
        current = (
            (previous * (period - 1)) + ranges[index]
        ) / period
        result[index] = current
        previous = current

    return result


def average_daily_volume(
    candles: Sequence[Candle],
    period: int,
) -> OptionalSeries:
    """Return rolling average daily share volume."""
    volumes = [float(candle.volume) for candle in candles]
    return simple_moving_average(volumes, period)


@dataclass(frozen=True, slots=True)
class IndicatorSet:
    """Aligned indicator series for one candle sequence."""

    ema_fast: OptionalSeries
    ema_slow: OptionalSeries
    rsi: OptionalSeries
    rmi: OptionalSeries
    atr: OptionalSeries
    sma_trend: OptionalSeries
    average_volume: OptionalSeries

    def latest_complete_index(self) -> int | None:
        """Return the newest index where every indicator is available."""
        series = (
            self.ema_fast,
            self.ema_slow,
            self.rsi,
            self.rmi,
            self.atr,
            self.sma_trend,
            self.average_volume,
        )

        if not series or not series[0]:
            return None

        for index in range(len(series[0]) - 1, -1, -1):
            if all(values[index] is not None for values in series):
                return index

        return None


def calculate_indicators(
    candles: Sequence[Candle],
    config: BotConfig,
) -> IndicatorSet:
    """Calculate every indicator required by the default strategy."""
    config.validate()
    closes = [candle.close for candle in candles]

    return IndicatorSet(
        ema_fast=exponential_moving_average(
            closes,
            config.ema_fast_period,
        ),
        ema_slow=exponential_moving_average(
            closes,
            config.ema_slow_period,
        ),
        rsi=relative_strength_index(
            closes,
            config.rsi_period,
        ),
        rmi=relative_momentum_index(
            closes,
            config.rmi_period,
            config.rmi_momentum,
        ),
        atr=average_true_range(
            candles,
            config.atr_period,
        ),
        sma_trend=simple_moving_average(
            closes,
            config.sma_trend_period,
        ),
        average_volume=average_daily_volume(
            candles,
            config.average_volume_period,
        ),
    )
