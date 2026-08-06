"""Data-driven, symbol-neutral swing-universe ranking."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import fmean, median, pstdev
from typing import Any, Callable, Mapping, Sequence

from qpx_bot.yahoo_data import (
    MarketRow,
    extract_market_rows,
    fetch_chart,
)


@dataclass(frozen=True, slots=True)
class SelectionConfig:
    schema_version: int
    decision_frequency: str
    history_range: str
    candidates: tuple[str, ...]
    minimum_history_bars: int
    minimum_eligible_candidates: int
    minimum_median_dollar_volume: float
    maximum_stale_days: int
    short_return_lookback: int
    long_return_lookback: int
    trend_lookback: int
    volatility_lookback: int
    drawdown_lookback: int
    liquidity_lookback: int
    weights: Mapping[str, float]
    symbol_bonus_policy: str

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported swing-universe schema version."
            )

        if self.decision_frequency != "monthly":
            raise ValueError(
                "Only monthly selection is currently supported."
            )

        normalized = tuple(
            symbol.strip().upper()
            for symbol in self.candidates
            if symbol.strip()
        )

        if len(normalized) < 2:
            raise ValueError(
                "The swing universe needs at least two candidates."
            )

        if len(normalized) != len(set(normalized)):
            raise ValueError(
                "The swing universe contains duplicate symbols."
            )

        if self.minimum_eligible_candidates < 2:
            raise ValueError(
                "At least two eligible candidates are required."
            )

        if (
            self.minimum_eligible_candidates
            > len(normalized)
        ):
            raise ValueError(
                "Minimum eligible candidates exceeds universe size."
            )

        periods = (
            self.minimum_history_bars,
            self.short_return_lookback,
            self.long_return_lookback,
            self.trend_lookback,
            self.volatility_lookback,
            self.drawdown_lookback,
            self.liquidity_lookback,
        )

        if any(period < 2 for period in periods):
            raise ValueError(
                "Selection lookbacks must be at least two bars."
            )

        if self.minimum_median_dollar_volume <= 0:
            raise ValueError(
                "Minimum median dollar volume must be positive."
            )

        if self.maximum_stale_days < 0:
            raise ValueError(
                "Maximum stale days cannot be negative."
            )

        required_weights = {
            "short_return",
            "long_return",
            "trend",
            "liquidity",
            "volatility_penalty",
            "drawdown_penalty",
        }

        if set(self.weights) != required_weights:
            raise ValueError(
                "Selection weights do not match the required fields."
            )

        if any(float(value) < 0 for value in self.weights.values()):
            raise ValueError(
                "Selection weights cannot be negative."
            )

        total_weight = sum(
            float(value)
            for value in self.weights.values()
        )

        if abs(total_weight - 1.0) > 1e-9:
            raise ValueError(
                "Selection weights must total 1.0."
            )

        if self.symbol_bonus_policy != "none":
            raise ValueError(
                "Symbol-specific bonuses are prohibited."
            )


@dataclass(frozen=True, slots=True)
class CandidateMetrics:
    symbol: str
    first_date: date | None
    last_date: date | None
    bars: int
    median_dollar_volume: float
    short_return: float
    long_return: float
    trend_distance: float
    annualized_volatility: float
    maximum_drawdown: float
    eligible: bool
    rejection_reason: str | None
    score: float = 0.0
    rank: int | None = None


@dataclass(frozen=True, slots=True)
class SelectionResult:
    generated_at_utc: str
    latest_market_date: date
    selected_symbol: str
    rankings: tuple[CandidateMetrics, ...]
    failed_downloads: Mapping[str, str]
    methodology: str
    symbol_bonus_policy: str


def load_selection_config(
    filename: str | Path,
) -> SelectionConfig:
    path = Path(filename).expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, Mapping):
        raise ValueError(
            "Swing-universe configuration must be an object."
        )

    config = SelectionConfig(
        schema_version=int(payload["schema_version"]),
        decision_frequency=str(
            payload["decision_frequency"]
        ).strip().lower(),
        history_range=str(payload["history_range"]),
        candidates=tuple(
            str(symbol).strip().upper()
            for symbol in payload["candidates"]
        ),
        minimum_history_bars=int(
            payload["minimum_history_bars"]
        ),
        minimum_eligible_candidates=int(
            payload["minimum_eligible_candidates"]
        ),
        minimum_median_dollar_volume=float(
            payload["minimum_median_dollar_volume"]
        ),
        maximum_stale_days=int(
            payload["maximum_stale_days"]
        ),
        short_return_lookback=int(
            payload["short_return_lookback"]
        ),
        long_return_lookback=int(
            payload["long_return_lookback"]
        ),
        trend_lookback=int(payload["trend_lookback"]),
        volatility_lookback=int(
            payload["volatility_lookback"]
        ),
        drawdown_lookback=int(
            payload["drawdown_lookback"]
        ),
        liquidity_lookback=int(
            payload["liquidity_lookback"]
        ),
        weights={
            str(name): float(value)
            for name, value in payload["weights"].items()
        },
        symbol_bonus_policy=str(
            payload.get("symbol_bonus_policy", "")
        ).strip().lower(),
    )
    config.validate()
    return config


def _required_bars(config: SelectionConfig) -> int:
    return max(
        config.minimum_history_bars,
        config.short_return_lookback + 1,
        config.long_return_lookback + 1,
        config.trend_lookback,
        config.volatility_lookback + 1,
        config.drawdown_lookback,
        config.liquidity_lookback,
    )


def _maximum_drawdown(prices: Sequence[float]) -> float:
    peak = float(prices[0])
    maximum = 0.0

    for price in prices:
        peak = max(peak, float(price))

        if peak > 0:
            maximum = max(
                maximum,
                (peak - float(price)) / peak,
            )

    return maximum


def _candidate_metrics(
    symbol: str,
    rows: Sequence[MarketRow],
    config: SelectionConfig,
) -> CandidateMetrics:
    normalized = symbol.strip().upper()
    ordered = sorted(rows, key=lambda row: row.date)
    required = _required_bars(config)

    if len(ordered) < required:
        return CandidateMetrics(
            symbol=normalized,
            first_date=(
                ordered[0].date
                if ordered
                else None
            ),
            last_date=(
                ordered[-1].date
                if ordered
                else None
            ),
            bars=len(ordered),
            median_dollar_volume=0.0,
            short_return=0.0,
            long_return=0.0,
            trend_distance=0.0,
            annualized_volatility=0.0,
            maximum_drawdown=0.0,
            eligible=False,
            rejection_reason=(
                f"{len(ordered)} bars; {required} required"
            ),
        )

    prices = [
        float(row.adjusted_close)
        for row in ordered
    ]

    if any(price <= 0 for price in prices):
        return CandidateMetrics(
            symbol=normalized,
            first_date=ordered[0].date,
            last_date=ordered[-1].date,
            bars=len(ordered),
            median_dollar_volume=0.0,
            short_return=0.0,
            long_return=0.0,
            trend_distance=0.0,
            annualized_volatility=0.0,
            maximum_drawdown=0.0,
            eligible=False,
            rejection_reason="non-positive adjusted price",
        )

    short_return = (
        prices[-1]
        / prices[-config.short_return_lookback - 1]
        - 1.0
    )
    long_return = (
        prices[-1]
        / prices[-config.long_return_lookback - 1]
        - 1.0
    )
    trend_average = fmean(
        prices[-config.trend_lookback:]
    )
    trend_distance = prices[-1] / trend_average - 1.0

    volatility_prices = prices[
        -config.volatility_lookback - 1:
    ]
    daily_returns = [
        current / previous - 1.0
        for previous, current in zip(
            volatility_prices,
            volatility_prices[1:],
        )
    ]
    annualized_volatility = (
        pstdev(daily_returns) * math.sqrt(252.0)
        if len(daily_returns) > 1
        else 0.0
    )

    drawdown_prices = prices[
        -config.drawdown_lookback:
    ]
    maximum_drawdown = _maximum_drawdown(
        drawdown_prices
    )

    liquidity_rows = ordered[
        -config.liquidity_lookback:
    ]
    median_dollar_volume = median(
        float(row.close) * float(row.volume)
        for row in liquidity_rows
    )
    eligible = (
        median_dollar_volume
        >= config.minimum_median_dollar_volume
    )

    return CandidateMetrics(
        symbol=normalized,
        first_date=ordered[0].date,
        last_date=ordered[-1].date,
        bars=len(ordered),
        median_dollar_volume=median_dollar_volume,
        short_return=short_return,
        long_return=long_return,
        trend_distance=trend_distance,
        annualized_volatility=annualized_volatility,
        maximum_drawdown=maximum_drawdown,
        eligible=eligible,
        rejection_reason=(
            None
            if eligible
            else "median dollar volume below minimum"
        ),
    )


def _z_scores(
    candidates: Sequence[CandidateMetrics],
    attribute: str,
) -> dict[str, float]:
    values = [
        float(getattr(candidate, attribute))
        for candidate in candidates
    ]
    average = fmean(values)
    deviation = (
        pstdev(values)
        if len(values) > 1
        else 0.0
    )

    if deviation <= 1e-15:
        return {
            candidate.symbol: 0.0
            for candidate in candidates
        }

    return {
        candidate.symbol: (
            float(getattr(candidate, attribute))
            - average
        ) / deviation
        for candidate in candidates
    }


def rank_candidates(
    histories: Mapping[str, Sequence[MarketRow]],
    config: SelectionConfig,
    *,
    failed_downloads: Mapping[str, str] | None = None,
) -> SelectionResult:
    """
    Rank all eligible symbols using identical formulas.

    There is no symbol-specific preference, bonus, fallback, or
    tie-break. Equal scores are resolved alphabetically.
    """
    config.validate()
    metrics = [
        _candidate_metrics(symbol, histories.get(symbol, ()), config)
        for symbol in config.candidates
    ]
    dated = [
        candidate.last_date
        for candidate in metrics
        if candidate.last_date is not None
    ]

    if not dated:
        raise RuntimeError(
            "No candidate returned usable daily history."
        )

    latest_market_date = max(dated)
    stale_checked: list[CandidateMetrics] = []

    for candidate in metrics:
        if (
            candidate.eligible
            and candidate.last_date is not None
            and (
                latest_market_date - candidate.last_date
            ).days > config.maximum_stale_days
        ):
            stale_checked.append(
                replace(
                    candidate,
                    eligible=False,
                    rejection_reason=(
                        "history is stale relative to universe"
                    ),
                )
            )
        else:
            stale_checked.append(candidate)

    eligible = [
        candidate
        for candidate in stale_checked
        if candidate.eligible
    ]

    if len(eligible) < config.minimum_eligible_candidates:
        reasons = "; ".join(
            f"{candidate.symbol}: "
            f"{candidate.rejection_reason or 'ineligible'}"
            for candidate in stale_checked
            if not candidate.eligible
        )
        raise RuntimeError(
            "Too few eligible swing candidates: "
            f"{len(eligible)}; "
            f"{config.minimum_eligible_candidates} required. "
            + reasons
        )

    short_z = _z_scores(eligible, "short_return")
    long_z = _z_scores(eligible, "long_return")
    trend_z = _z_scores(eligible, "trend_distance")
    liquidity_values = {
        candidate.symbol: math.log10(
            max(1.0, candidate.median_dollar_volume)
        )
        for candidate in eligible
    }
    liquidity_average = fmean(
        liquidity_values.values()
    )
    liquidity_deviation = (
        pstdev(liquidity_values.values())
        if len(liquidity_values) > 1
        else 0.0
    )
    liquidity_z = {
        symbol: (
            (value - liquidity_average)
            / liquidity_deviation
            if liquidity_deviation > 1e-15
            else 0.0
        )
        for symbol, value in liquidity_values.items()
    }
    volatility_z = _z_scores(
        eligible,
        "annualized_volatility",
    )
    drawdown_z = _z_scores(
        eligible,
        "maximum_drawdown",
    )

    scored: list[CandidateMetrics] = []

    for candidate in eligible:
        score = (
            config.weights["short_return"]
            * short_z[candidate.symbol]
            + config.weights["long_return"]
            * long_z[candidate.symbol]
            + config.weights["trend"]
            * trend_z[candidate.symbol]
            + config.weights["liquidity"]
            * liquidity_z[candidate.symbol]
            - config.weights["volatility_penalty"]
            * volatility_z[candidate.symbol]
            - config.weights["drawdown_penalty"]
            * drawdown_z[candidate.symbol]
        )
        scored.append(replace(candidate, score=score))

    scored.sort(key=lambda item: (-item.score, item.symbol))
    ranked = [
        replace(candidate, rank=index)
        for index, candidate in enumerate(
            scored,
            start=1,
        )
    ]
    rejected = sorted(
        (
            candidate
            for candidate in stale_checked
            if not candidate.eligible
        ),
        key=lambda item: item.symbol,
    )
    complete = tuple([*ranked, *rejected])

    return SelectionResult(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        latest_market_date=latest_market_date,
        selected_symbol=ranked[0].symbol,
        rankings=complete,
        failed_downloads=dict(
            failed_downloads or {}
        ),
        methodology=(
            "Cross-sectional z-score ranking of trailing "
            "adjusted returns, trend distance, and dollar "
            "liquidity, minus volatility and drawdown penalties."
        ),
        symbol_bonus_policy=config.symbol_bonus_policy,
    )


def select_from_provider(
    config: SelectionConfig,
    *,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
) -> SelectionResult:
    histories: dict[str, Sequence[MarketRow]] = {}
    failures: dict[str, str] = {}

    for symbol in config.candidates:
        print(f"Ranking data: {symbol}...")

        try:
            if fetcher is None:
                result = fetch_chart(
                    symbol,
                    range_name=config.history_range,
                    timeout_seconds=20.0,
                    maximum_attempts=3,
                )
            else:
                result = fetcher(symbol)

            histories[symbol] = extract_market_rows(result)
        except Exception as exc:
            failures[symbol] = (
                f"{type(exc).__name__}: {exc}"
            )

    return rank_candidates(
        histories,
        config,
        failed_downloads=failures,
    )


def _candidate_payload(
    candidate: CandidateMetrics,
) -> dict[str, Any]:
    payload = asdict(candidate)
    payload["first_date"] = (
        candidate.first_date.isoformat()
        if candidate.first_date
        else None
    )
    payload["last_date"] = (
        candidate.last_date.isoformat()
        if candidate.last_date
        else None
    )
    return payload


def write_selection_artifacts(
    result: SelectionResult,
    output_directory: str | Path,
) -> dict[str, Path]:
    output = Path(
        output_directory
    ).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    text_path = output / "symbol_selection_report.txt"
    csv_path = output / "symbol_selection_rankings.csv"
    json_path = output / "symbol_selection_result.json"

    lines = [
        "=" * 78,
        "QPX BOT v1.10 — DATA-DRIVEN SWING SYMBOL SELECTION",
        "=" * 78,
        f"Selected symbol          : {result.selected_symbol}",
        f"Latest market date       : {result.latest_market_date}",
        f"Symbol bonus policy      : {result.symbol_bonus_policy}",
        f"Methodology              : {result.methodology}",
        "-" * 78,
    ]

    for candidate in result.rankings:
        if candidate.eligible:
            lines.append(
                (
                    f"{candidate.rank:02d} {candidate.symbol:<6} "
                    f"score {candidate.score:>8.4f} | "
                    f"63d {candidate.short_return:>8.2%} | "
                    f"126d {candidate.long_return:>8.2%} | "
                    f"trend {candidate.trend_distance:>8.2%} | "
                    f"vol {candidate.annualized_volatility:>8.2%} | "
                    f"DD {candidate.maximum_drawdown:>8.2%}"
                )
            )
        else:
            lines.append(
                f"-- {candidate.symbol:<6} REJECTED: "
                f"{candidate.rejection_reason}"
            )

    if result.failed_downloads:
        lines.append("-" * 78)
        lines.append("DOWNLOAD FAILURES")

        for symbol, reason in sorted(
            result.failed_downloads.items()
        ):
            lines.append(f"{symbol}: {reason}")

    lines.extend(
        [
            "=" * 78,
            (
                "Every candidate uses the same score. "
                "No ticker receives a hardcoded preference."
            ),
            (
                "Research selection only. This is not a "
                "recommendation or guarantee."
            ),
        ]
    )
    text_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Rank",
                "Symbol",
                "Eligible",
                "Score",
                "FirstDate",
                "LastDate",
                "Bars",
                "MedianDollarVolume",
                "ShortReturn",
                "LongReturn",
                "TrendDistance",
                "AnnualizedVolatility",
                "MaximumDrawdown",
                "RejectionReason",
            ]
        )

        for candidate in result.rankings:
            writer.writerow(
                [
                    candidate.rank or "",
                    candidate.symbol,
                    candidate.eligible,
                    f"{candidate.score:.10f}",
                    (
                        candidate.first_date.isoformat()
                        if candidate.first_date
                        else ""
                    ),
                    (
                        candidate.last_date.isoformat()
                        if candidate.last_date
                        else ""
                    ),
                    candidate.bars,
                    f"{candidate.median_dollar_volume:.6f}",
                    f"{candidate.short_return:.10f}",
                    f"{candidate.long_return:.10f}",
                    f"{candidate.trend_distance:.10f}",
                    f"{candidate.annualized_volatility:.10f}",
                    f"{candidate.maximum_drawdown:.10f}",
                    candidate.rejection_reason or "",
                ]
            )

    payload = {
        "generated_at_utc": result.generated_at_utc,
        "latest_market_date": (
            result.latest_market_date.isoformat()
        ),
        "selected_symbol": result.selected_symbol,
        "methodology": result.methodology,
        "symbol_bonus_policy": result.symbol_bonus_policy,
        "rankings": [
            _candidate_payload(candidate)
            for candidate in result.rankings
        ],
        "failed_downloads": dict(
            result.failed_downloads
        ),
    }
    json_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "report": text_path,
        "rankings": csv_path,
        "result": json_path,
    }
