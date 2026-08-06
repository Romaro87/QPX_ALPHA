"""Rolling walk-forward validation for QPX Bot."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.hybrid import HybridBacktestResult, run_hybrid_backtest
from qpx_bot.performance import (
    AdjustedBar,
    BenchmarkResult,
    ReturnMetrics,
    hybrid_metrics,
    metrics_from_returns,
    run_buy_and_hold_benchmark,
)


@dataclass(frozen=True, slots=True)
class Candidate:
    name: str
    maximum_vix_for_entries: float
    breakout_volume_multiplier: float


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    number: int
    train_start: date
    train_end: date
    test_start: date
    test_end: date
    selected_candidate: str
    selected_maximum_vix: float
    selected_breakout_volume: float
    training_score: float
    strategy_metrics: ReturnMetrics
    benchmark_metrics: ReturnMetrics
    strategy_trades: int
    strategy_win_rate: float
    strategy_profit_factor: float
    cagr_advantage: float


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    symbol: str
    train_bars: int
    test_bars: int
    step_bars: int
    windows: tuple[WalkForwardWindow, ...]
    out_of_sample_metrics: ReturnMetrics
    benchmark_metrics: ReturnMetrics
    cagr_advantage: float
    positive_alpha_windows: int
    total_windows: int
    benchmark_uses_adjusted_close: bool


def default_candidates(
    config: BotConfig,
) -> tuple[Candidate, ...]:
    """A small, declared grid to limit parameter-selection bias."""
    values = (
        max(18.0, config.maximum_vix_for_entries - 4.0),
        config.maximum_vix_for_entries,
        config.maximum_vix_for_entries + 4.0,
    )
    unique = tuple(dict.fromkeys(values))

    return tuple(
        Candidate(
            name=f"VIX_{value:g}",
            maximum_vix_for_entries=value,
            breakout_volume_multiplier=(
                config.breakout_volume_multiplier
            ),
        )
        for value in unique
    )


def _candidate_config(
    base: BotConfig,
    candidate: Candidate,
) -> BotConfig:
    return replace(
        base,
        maximum_vix_for_entries=(
            candidate.maximum_vix_for_entries
        ),
        breakout_volume_multiplier=(
            candidate.breakout_volume_multiplier
        ),
    )


def _segment_result(
    *,
    swing_candles: Sequence[Candle],
    income_candles: Sequence[Candle],
    dividends: Sequence[DividendEvent],
    vix_values: Sequence[float],
    symbol: str,
    config: BotConfig,
    start_index: int,
    end_index: int,
) -> HybridBacktestResult:
    warmup = max(
        config.sma_trend_period
        + config.sma_slope_lookback
        + 2,
        config.ema_slow_period + 2,
        config.atr_period + 2,
        config.breakout_lookback + 2,
    )
    context_start = max(0, start_index - warmup)
    context_candles = swing_candles[
        context_start:end_index
    ]
    context_vix = vix_values[context_start:end_index]
    local_start = start_index - context_start
    segment_end_date = swing_candles[end_index - 1].date
    eligible_income = [
        candle
        for candle in income_candles
        if candle.date <= segment_end_date
    ]

    return run_hybrid_backtest(
        swing_candles=context_candles,
        income_candles=eligible_income,
        dividends=dividends,
        swing_symbol=symbol,
        config=config,
        vix=context_vix,
        start_trading_index=local_start,
    )


def _training_score(metrics: ReturnMetrics) -> float:
    """Return-over-drawdown score calculated on training data only."""
    return (
        metrics.cagr
        - (0.75 * metrics.maximum_drawdown)
    )


def run_walk_forward(
    *,
    swing_candles: Sequence[Candle],
    income_candles: Sequence[Candle],
    dividends: Sequence[DividendEvent],
    vix_values: Sequence[float],
    adjusted_bars: Sequence[AdjustedBar],
    symbol: str,
    config: BotConfig,
    train_bars: int = 252,
    test_bars: int = 63,
    step_bars: int = 63,
    candidates: Sequence[Candidate] | None = None,
    benchmark_uses_adjusted_close: bool = True,
) -> WalkForwardResult:
    """
    Select parameters on each rolling training window, then evaluate
    them once on the immediately following unseen test window.
    """
    config.validate()

    if not (
        len(swing_candles)
        == len(vix_values)
    ):
        raise ValueError(
            "Swing candles and aligned VIX values must match."
        )

    if train_bars < 2 or test_bars < 2 or step_bars < 1:
        raise ValueError(
            "Train/test windows must be at least two bars and "
            "step size must be positive."
        )

    required = train_bars + test_bars

    if len(swing_candles) < required:
        raise ValueError(
            f"Walk-forward requires at least {required} swing bars; "
            f"only {len(swing_candles)} are available."
        )

    candidate_list = tuple(
        candidates or default_candidates(config)
    )

    if not candidate_list:
        raise ValueError("At least one candidate is required.")

    adjusted_map = {
        bar.date: bar
        for bar in adjusted_bars
    }
    windows: list[WalkForwardWindow] = []
    all_strategy_returns: list[float] = []
    all_benchmark_returns: list[float] = []
    exposure_weighted = 0.0
    benchmark_exposure_weighted = 0.0
    total_observations = 0
    train_start = 0
    window_number = 1

    while True:
        train_end = train_start + train_bars
        test_start = train_end
        test_end = test_start + test_bars

        if test_end > len(swing_candles):
            break

        scored: list[
            tuple[
                float,
                Candidate,
                BotConfig,
                ReturnMetrics,
            ]
        ] = []

        for candidate in candidate_list:
            candidate_config = _candidate_config(
                config,
                candidate,
            )
            training_result = _segment_result(
                swing_candles=swing_candles,
                income_candles=income_candles,
                dividends=dividends,
                vix_values=vix_values,
                symbol=symbol,
                config=candidate_config,
                start_index=train_start,
                end_index=train_end,
            )
            training_metrics, _ = hybrid_metrics(
                training_result
            )
            scored.append(
                (
                    _training_score(training_metrics),
                    candidate,
                    candidate_config,
                    training_metrics,
                )
            )

        scored.sort(
            key=lambda item: (
                item[0],
                item[3].cagr,
                -item[3].maximum_drawdown,
            ),
            reverse=True,
        )
        (
            best_score,
            best_candidate,
            selected_config,
            _,
        ) = scored[0]

        test_result = _segment_result(
            swing_candles=swing_candles,
            income_candles=income_candles,
            dividends=dividends,
            vix_values=vix_values,
            symbol=symbol,
            config=selected_config,
            start_index=test_start,
            end_index=test_end,
        )
        strategy_metrics, strategy_returns = hybrid_metrics(
            test_result
        )

        test_dates = [
            candle.date
            for candle in swing_candles[test_start:test_end]
        ]

        try:
            benchmark_bars = [
                adjusted_map[test_date]
                for test_date in test_dates
            ]
        except KeyError as exc:
            raise ValueError(
                f"Benchmark adjusted price is missing for {exc.args[0]}."
            ) from exc

        benchmark = run_buy_and_hold_benchmark(
            bars=benchmark_bars,
            symbol=symbol,
            config=selected_config,
            uses_adjusted_close=(
                benchmark_uses_adjusted_close
            ),
        )

        observations = len(strategy_returns)
        all_strategy_returns.extend(strategy_returns)
        all_benchmark_returns.extend(benchmark.returns)
        exposure_weighted += (
            strategy_metrics.exposure * observations
        )
        benchmark_exposure_weighted += (
            benchmark.metrics.exposure * observations
        )
        total_observations += observations

        windows.append(
            WalkForwardWindow(
                number=window_number,
                train_start=swing_candles[
                    train_start
                ].date,
                train_end=swing_candles[
                    train_end - 1
                ].date,
                test_start=swing_candles[
                    test_start
                ].date,
                test_end=swing_candles[
                    test_end - 1
                ].date,
                selected_candidate=best_candidate.name,
                selected_maximum_vix=(
                    best_candidate.maximum_vix_for_entries
                ),
                selected_breakout_volume=(
                    best_candidate.breakout_volume_multiplier
                ),
                training_score=best_score,
                strategy_metrics=strategy_metrics,
                benchmark_metrics=benchmark.metrics,
                strategy_trades=len(test_result.trades),
                strategy_win_rate=test_result.win_rate,
                strategy_profit_factor=(
                    test_result.profit_factor
                ),
                cagr_advantage=(
                    strategy_metrics.cagr
                    - benchmark.metrics.cagr
                ),
            )
        )

        train_start += step_bars
        window_number += 1

    if not windows:
        raise ValueError(
            "The selected walk-forward settings produced no windows."
        )

    strategy_exposure = (
        exposure_weighted / total_observations
        if total_observations
        else 0.0
    )
    benchmark_exposure = (
        benchmark_exposure_weighted / total_observations
        if total_observations
        else 0.0
    )
    strategy_overall = metrics_from_returns(
        all_strategy_returns,
        exposure=strategy_exposure,
    )
    benchmark_overall = metrics_from_returns(
        all_benchmark_returns,
        exposure=benchmark_exposure,
    )

    return WalkForwardResult(
        symbol=symbol.strip().upper(),
        train_bars=train_bars,
        test_bars=test_bars,
        step_bars=step_bars,
        windows=tuple(windows),
        out_of_sample_metrics=strategy_overall,
        benchmark_metrics=benchmark_overall,
        cagr_advantage=(
            strategy_overall.cagr
            - benchmark_overall.cagr
        ),
        positive_alpha_windows=sum(
            1
            for window in windows
            if window.cagr_advantage > 0
        ),
        total_windows=len(windows),
        benchmark_uses_adjusted_close=(
            benchmark_uses_adjusted_close
        ),
    )


def format_walk_forward_report(
    result: WalkForwardResult,
) -> str:
    percent = lambda value: f"{value * 100.0:,.2f}%"
    ratio = lambda value: f"{value:,.2f}"
    benchmark_type = (
        "adjusted-close total return"
        if result.benchmark_uses_adjusted_close
        else "price-return fallback"
    )
    strategy = result.out_of_sample_metrics
    benchmark = result.benchmark_metrics

    lines = [
        "=" * 78,
        "QPX BOT v1.10 — WALK-FORWARD OUT-OF-SAMPLE VALIDATION",
        "=" * 78,
        f"Symbol                    : {result.symbol}",
        f"Training window           : {result.train_bars} bars",
        f"Testing window            : {result.test_bars} bars",
        f"Step size                 : {result.step_bars} bars",
        f"Completed OOS windows     : {result.total_windows}",
        (
            "Positive-alpha windows    : "
            f"{result.positive_alpha_windows}/"
            f"{result.total_windows}"
        ),
        f"Benchmark method          : {benchmark_type}",
        "-" * 78,
        "OUT-OF-SAMPLE AGGREGATE",
        (
            "QPX contribution-adjusted return : "
            f"{percent(strategy.total_return)}"
        ),
        (
            f"{result.symbol} contribution-adjusted "
            f"return : {percent(benchmark.total_return)}"
        ),
        f"QPX CAGR                         : {percent(strategy.cagr)}",
        f"{result.symbol} CAGR                         : {percent(benchmark.cagr)}",
        f"CAGR advantage                   : {percent(result.cagr_advantage)}",
        f"QPX Sharpe                       : {ratio(strategy.sharpe_ratio)}",
        f"{result.symbol} Sharpe                       : {ratio(benchmark.sharpe_ratio)}",
        f"QPX Sortino                      : {ratio(strategy.sortino_ratio)}",
        f"{result.symbol} Sortino                      : {ratio(benchmark.sortino_ratio)}",
        f"QPX maximum drawdown             : {percent(strategy.maximum_drawdown)}",
        f"{result.symbol} maximum drawdown             : {percent(benchmark.maximum_drawdown)}",
        f"QPX swing exposure               : {percent(strategy.exposure)}",
        "-" * 78,
        "WINDOWS",
    ]

    for window in result.windows:
        lines.append(
            (
                f"{window.number:02d} "
                f"train {window.train_start}..{window.train_end} | "
                f"test {window.test_start}..{window.test_end} | "
                f"{window.selected_candidate} | "
                f"QPX CAGR {percent(window.strategy_metrics.cagr)} | "
                f"{result.symbol} CAGR {percent(window.benchmark_metrics.cagr)} | "
                f"alpha {percent(window.cagr_advantage)}"
            )
        )

    lines.extend(
        [
            "=" * 78,
            (
                "Parameter selection uses training windows only; "
                "reported aggregate metrics use unseen test windows."
            ),
            (
                "Research simulation only. Results are not live "
                "trading performance or financial advice."
            ),
        ]
    )
    return "\n".join(lines)


def write_walk_forward_windows(
    result: WalkForwardResult,
    filename: str | Path,
) -> Path:
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Window",
                "TrainStart",
                "TrainEnd",
                "TestStart",
                "TestEnd",
                "Candidate",
                "MaximumVIX",
                "BreakoutVolumeMultiplier",
                "TrainingScore",
                "StrategyReturn",
                "StrategyCAGR",
                "StrategySharpe",
                "StrategySortino",
                "StrategyMaxDrawdown",
                "StrategyExposure",
                "BenchmarkReturn",
                "BenchmarkCAGR",
                "BenchmarkSharpe",
                "BenchmarkSortino",
                "BenchmarkMaxDrawdown",
                "CAGRAdvantage",
                "Trades",
                "WinRate",
                "ProfitFactor",
            ]
        )

        for window in result.windows:
            writer.writerow(
                [
                    window.number,
                    window.train_start.isoformat(),
                    window.train_end.isoformat(),
                    window.test_start.isoformat(),
                    window.test_end.isoformat(),
                    window.selected_candidate,
                    f"{window.selected_maximum_vix:.6f}",
                    f"{window.selected_breakout_volume:.6f}",
                    f"{window.training_score:.10f}",
                    f"{window.strategy_metrics.total_return:.10f}",
                    f"{window.strategy_metrics.cagr:.10f}",
                    f"{window.strategy_metrics.sharpe_ratio:.10f}",
                    f"{window.strategy_metrics.sortino_ratio:.10f}",
                    f"{window.strategy_metrics.maximum_drawdown:.10f}",
                    f"{window.strategy_metrics.exposure:.10f}",
                    f"{window.benchmark_metrics.total_return:.10f}",
                    f"{window.benchmark_metrics.cagr:.10f}",
                    f"{window.benchmark_metrics.sharpe_ratio:.10f}",
                    f"{window.benchmark_metrics.sortino_ratio:.10f}",
                    f"{window.benchmark_metrics.maximum_drawdown:.10f}",
                    f"{window.cagr_advantage:.10f}",
                    window.strategy_trades,
                    f"{window.strategy_win_rate:.10f}",
                    f"{window.strategy_profit_factor:.10f}",
                ]
            )

    return path


def write_walk_forward_json(
    result: WalkForwardResult,
    filename: str | Path,
) -> Path:
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = asdict(result)

    for window in payload["windows"]:
        for key in (
            "train_start",
            "train_end",
            "test_start",
            "test_end",
        ):
            window[key] = window[key].isoformat()

    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return path
