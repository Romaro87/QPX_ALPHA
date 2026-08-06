"""Contribution-adjusted performance and benchmark analytics."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from math import prod, sqrt
from pathlib import Path
from statistics import fmean, stdev
from typing import Iterable, Sequence

from qpx_bot.config import BotConfig
from qpx_bot.hybrid import HybridBacktestResult


TRADING_DAYS_PER_YEAR = 252


@dataclass(frozen=True, slots=True)
class ReturnMetrics:
    observation_count: int
    total_return: float
    cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_drawdown: float
    exposure: float


@dataclass(frozen=True, slots=True)
class AdjustedBar:
    date: date
    open: float
    close: float
    adjusted_close: float

    @property
    def adjustment_factor(self) -> float:
        if self.close <= 0:
            raise ValueError("Benchmark close must be positive.")
        return self.adjusted_close / self.close

    @property
    def adjusted_open(self) -> float:
        return self.open * self.adjustment_factor


@dataclass(frozen=True, slots=True)
class BenchmarkPoint:
    date: date
    equity: float
    total_contributions: float


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    symbol: str
    starting_cash: float
    total_contributions: float
    ending_equity: float
    points: tuple[BenchmarkPoint, ...]
    returns: tuple[float, ...]
    metrics: ReturnMetrics
    uses_adjusted_close: bool


def _parse_date(raw_value: str) -> date:
    value = str(raw_value).strip()

    try:
        numeric = float(value)
    except ValueError:
        numeric = None

    if numeric is not None:
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        return datetime.fromtimestamp(
            numeric,
            tz=timezone.utc,
        ).date()

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).date()
    except ValueError:
        pass

    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported benchmark date: {raw_value!r}")


def load_adjusted_bars(
    filename: str | Path,
) -> tuple[list[AdjustedBar], bool]:
    """
    Load benchmark bars from SWING.csv.

    AdjClose is preferred because it incorporates distributions and
    splits. Close is used only as a transparent price-return fallback.
    """
    path = Path(filename).expanduser().resolve()

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        if not reader.fieldnames:
            raise ValueError("Benchmark CSV does not contain a header.")

        headers = {
            header.strip().lower(): header
            for header in reader.fieldnames
        }

        def column(*names: str) -> str:
            for name in names:
                if name in headers:
                    return headers[name]
            raise ValueError(
                "Benchmark CSV is missing one of: "
                + ", ".join(names)
            )

        date_column = column(
            "date",
            "time",
            "datetime",
            "timestamp",
        )
        open_column = column("open")
        close_column = column(
            "close",
            "adj close",
            "adjusted close",
        )
        adjusted_column = None

        for candidate in (
            "adjclose",
            "adj close",
            "adjusted close",
        ):
            if candidate in headers:
                adjusted_column = headers[candidate]
                break

        uses_adjusted = adjusted_column is not None
        bars: list[AdjustedBar] = []

        for line_number, row in enumerate(reader, start=2):
            try:
                close = float(row[close_column])
                adjusted = (
                    float(row[adjusted_column])
                    if adjusted_column is not None
                    else close
                )
                bar = AdjustedBar(
                    date=_parse_date(row[date_column]),
                    open=float(row[open_column]),
                    close=close,
                    adjusted_close=adjusted,
                )

                if (
                    bar.open <= 0
                    or bar.close <= 0
                    or bar.adjusted_close <= 0
                ):
                    raise ValueError(
                        "benchmark prices must be positive"
                    )

                bars.append(bar)
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(
                    f"Invalid benchmark row {line_number}: {exc}"
                ) from exc

    bars.sort(key=lambda bar: bar.date)
    dates = [bar.date for bar in bars]

    if not bars:
        raise ValueError("Benchmark CSV contains no rows.")

    if len(dates) != len(set(dates)):
        raise ValueError("Benchmark CSV contains duplicate dates.")

    return bars, uses_adjusted


def metrics_from_returns(
    returns: Sequence[float],
    *,
    exposure: float = 0.0,
) -> ReturnMetrics:
    cleaned = [
        float(value)
        for value in returns
        if value > -1.0
    ]

    if not cleaned:
        return ReturnMetrics(
            observation_count=0,
            total_return=0.0,
            cagr=0.0,
            annualized_volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            maximum_drawdown=0.0,
            exposure=max(0.0, min(1.0, exposure)),
        )

    wealth = 1.0
    peak = 1.0
    maximum_drawdown = 0.0

    for value in cleaned:
        wealth *= 1.0 + value
        peak = max(peak, wealth)

        if peak > 0:
            maximum_drawdown = max(
                maximum_drawdown,
                (peak - wealth) / peak,
            )

    total_return = wealth - 1.0
    years = len(cleaned) / TRADING_DAYS_PER_YEAR
    cagr = (
        wealth ** (1.0 / years) - 1.0
        if wealth > 0 and years > 0
        else -1.0
    )

    average = fmean(cleaned)
    volatility = (
        stdev(cleaned) * sqrt(TRADING_DAYS_PER_YEAR)
        if len(cleaned) > 1
        else 0.0
    )
    daily_deviation = (
        stdev(cleaned)
        if len(cleaned) > 1
        else 0.0
    )
    sharpe = (
        average / daily_deviation
        * sqrt(TRADING_DAYS_PER_YEAR)
        if daily_deviation > 0
        else 0.0
    )

    downside_squared = [
        min(0.0, value) ** 2
        for value in cleaned
    ]
    downside_deviation = sqrt(fmean(downside_squared))
    sortino = (
        average / downside_deviation
        * sqrt(TRADING_DAYS_PER_YEAR)
        if downside_deviation > 0
        else 0.0
    )

    return ReturnMetrics(
        observation_count=len(cleaned),
        total_return=total_return,
        cagr=cagr,
        annualized_volatility=volatility,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        maximum_drawdown=maximum_drawdown,
        exposure=max(0.0, min(1.0, exposure)),
    )


def hybrid_flow_adjusted_returns(
    result: HybridBacktestResult,
) -> tuple[float, ...]:
    """Remove external deposits before calculating daily returns."""
    returns: list[float] = []
    previous_equity = result.starting_cash
    previous_contributions = result.starting_cash

    for point in result.equity_curve:
        contribution = (
            point.total_contributions
            - previous_contributions
        )

        if previous_equity <= 0:
            daily_return = 0.0
        else:
            daily_return = (
                point.total_equity
                - contribution
            ) / previous_equity - 1.0

        returns.append(daily_return)
        previous_equity = point.total_equity
        previous_contributions = point.total_contributions

    return tuple(returns)


def hybrid_metrics(
    result: HybridBacktestResult,
) -> tuple[ReturnMetrics, tuple[float, ...]]:
    returns = hybrid_flow_adjusted_returns(result)
    exposure = (
        sum(
            1
            for point in result.equity_curve
            if point.swing_market_value > 0
        )
        / len(result.equity_curve)
        if result.equity_curve
        else 0.0
    )
    return (
        metrics_from_returns(returns, exposure=exposure),
        returns,
    )


def run_buy_and_hold_benchmark(
    *,
    bars: Sequence[AdjustedBar],
    symbol: str,
    config: BotConfig,
    uses_adjusted_close: bool = True,
) -> BenchmarkResult:
    """Fractional-share buy-and-hold with matching monthly deposits."""
    config.validate()

    if not bars:
        raise ValueError("Benchmark bars cannot be empty.")

    shares = 0.0
    total_contributions = config.starting_cash
    cash_to_invest = config.starting_cash
    points: list[BenchmarkPoint] = []
    previous_month = (
        bars[0].date.year,
        bars[0].date.month,
    )

    for index, bar in enumerate(bars):
        current_month = (bar.date.year, bar.date.month)

        if index > 0 and current_month != previous_month:
            cash_to_invest += config.monthly_contribution
            total_contributions += config.monthly_contribution
            previous_month = current_month

        if cash_to_invest > 0:
            fill = (
                bar.adjusted_open
                * (1.0 + config.slippage_rate)
            )
            shares += cash_to_invest / fill
            cash_to_invest = 0.0

        points.append(
            BenchmarkPoint(
                date=bar.date,
                equity=shares * bar.adjusted_close,
                total_contributions=total_contributions,
            )
        )

    returns: list[float] = []
    previous_equity = config.starting_cash
    previous_contributions = config.starting_cash

    for point in points:
        contribution = (
            point.total_contributions
            - previous_contributions
        )
        daily_return = (
            (point.equity - contribution) / previous_equity - 1.0
            if previous_equity > 0
            else 0.0
        )
        returns.append(daily_return)
        previous_equity = point.equity
        previous_contributions = point.total_contributions

    metrics = metrics_from_returns(
        returns,
        exposure=1.0,
    )

    return BenchmarkResult(
        symbol=symbol.strip().upper(),
        starting_cash=config.starting_cash,
        total_contributions=total_contributions,
        ending_equity=points[-1].equity,
        points=tuple(points),
        returns=tuple(returns),
        metrics=metrics,
        uses_adjusted_close=uses_adjusted_close,
    )
