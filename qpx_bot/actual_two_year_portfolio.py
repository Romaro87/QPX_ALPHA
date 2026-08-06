"""Actual two-year, eight-symbol QPX portfolio backtest."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from qpx_bot.allocation import (
    AllocationRebalance,
    rebalance_income_allocation,
)
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.hybrid import IncomeHolding
from qpx_bot.indicators import IndicatorSet, calculate_indicators
from qpx_bot.market_calendar import NEW_YORK, latest_completed_session
from qpx_bot.performance import ReturnMetrics, metrics_from_returns
from qpx_bot.portfolio import (
    ClosedTrade,
    Portfolio,
    contribution_allocation,
)
from qpx_bot.real_data import sha256_file
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_entry, evaluate_exit
from qpx_bot.symbol_selector import (
    CandidateMetrics,
    SelectionConfig,
    SelectionResult,
    load_selection_config,
    rank_candidates,
)
from qpx_bot.yahoo_data import (
    DividendRow,
    MarketRow,
    extract_dividend_rows,
    extract_market_rows,
    fetch_chart,
)


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
UNIVERSE_CONFIG_PATH = PACKAGE_DIR / "swing_universe.json"
SESSION_CONFIG_PATH = PACKAGE_DIR / "session_execution_config.json"
DEFAULT_DATA_ROOT = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_actual_two_year_eight_symbol"
)
DEFAULT_REPORT_ROOT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_actual_two_year_eight_symbol"
)
REQUIRED_UNIVERSE = (
    "DIA",
    "IWM",
    "QQQ",
    "SPY",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
)
INCOME_SYMBOL = "QDTE"
VIX_SYMBOL = "^VIX"
DOWNLOAD_RANGE = "4y"
MINIMUM_TEST_BARS = 480
MAXIMUM_START_DELAY_DAYS = 10


@dataclass(frozen=True, slots=True)
class PendingSignal:
    symbol: str
    signal_date: date
    signal_atr: float
    prior_close: float


@dataclass(frozen=True, slots=True)
class SelectionSnapshot:
    decision_date: date
    winner: str
    active_symbol: str
    locked: bool
    latest_input_date: date
    rankings: tuple[CandidateMetrics, ...]


@dataclass(frozen=True, slots=True)
class AllocationSnapshot:
    date: date
    event_type: str
    contribution: float
    target_income_weight: float
    action: str
    before_income_weight: float
    after_income_weight: float
    target_fully_reached: bool
    qdte_market_value_traded: float
    realized_pnl: float
    tax_reserved: float


@dataclass(frozen=True, slots=True)
class PortfolioPoint:
    date: date
    total_equity: float
    total_contributions: float
    income_value: float
    swing_equity: float
    swing_cash: float
    swing_market_value: float
    tax_reserve: float
    income_weight: float
    target_income_weight: float
    monthly_winner: str
    active_symbol: str
    position_symbol: str | None


@dataclass(frozen=True, slots=True)
class ActualTwoYearResult:
    generated_at_utc: str
    provider: str
    requested_start: date
    actual_start: date
    actual_end: date
    bars: int
    universe: tuple[str, ...]
    income_symbol: str
    starting_income_cash: float
    starting_swing_cash: float
    starting_total_capital: float
    monthly_contribution: float
    contribution_count: int
    total_contributions: float
    ending_equity: float
    net_profit: float
    return_on_contributed_capital: float
    ending_income_value: float
    ending_swing_equity: float
    ending_swing_cash: float
    ending_tax_reserve: float
    ending_income_weight: float
    total_dividends: float
    dividend_event_count: int
    signal_count: int
    filled_entries: int
    gap_rejections: int
    risk_rejections: int
    closed_trades: int
    win_rate: float
    profit_factor: float | None
    maximum_drawdown: float
    flow_adjusted_total_return: float
    flow_adjusted_cagr: float
    flow_adjusted_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    swing_exposure: float
    selection_months: int
    winner_counts: Mapping[str, int]
    forced_entry_indices: None
    symbol_bonus_policy: str
    live_broker_enabled: bool


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    report: Path
    result: Path
    equity: Path
    trades: Path
    selections: Path
    allocations: Path
    provenance: Path
    manifest: Path


def subtract_years(day: date, years: int) -> date:
    if years < 1:
        raise ValueError("Years must be positive.")

    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(
            year=day.year - years,
            month=2,
            day=28,
        )


def _elapsed_years(start: date, current: date) -> int:
    months = (
        (current.year - start.year) * 12
        + current.month
        - start.month
    )
    return max(0, months // 12)


def _safe_symbol(symbol: str) -> str:
    return symbol.replace("^", "").replace("/", "_")


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_market_rows(
    path: Path,
    rows: Sequence[MarketRow],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "Open",
                "High",
                "Low",
                "Close",
                "AdjClose",
                "Volume",
            )
        )

        for row in rows:
            writer.writerow(
                (
                    row.date.isoformat(),
                    f"{row.open:.8f}",
                    f"{row.high:.8f}",
                    f"{row.low:.8f}",
                    f"{row.close:.8f}",
                    f"{row.adjusted_close:.8f}",
                    row.volume,
                )
            )

    temporary.replace(path)


def _write_dividend_rows(
    path: Path,
    rows: Sequence[DividendRow],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(("Date", "Dividend"))

        for row in rows:
            writer.writerow(
                (
                    row.date.isoformat(),
                    f"{row.amount:.8f}",
                )
            )

    temporary.replace(path)


def _download_actual_inputs(
    *,
    data_directory: Path,
    selection_config: SelectionConfig,
) -> tuple[
    dict[str, list[MarketRow]],
    list[MarketRow],
    list[MarketRow],
    list[DividendRow],
    Path,
]:
    data_directory.mkdir(parents=True, exist_ok=True)
    histories: dict[str, list[MarketRow]] = {}
    paths: dict[str, Path] = {}
    raw_results: dict[str, Mapping[str, Any]] = {}

    symbols = (
        *selection_config.candidates,
        INCOME_SYMBOL,
        VIX_SYMBOL,
    )

    for symbol in symbols:
        print(
            f"Downloading actual daily history: {symbol}"
        )
        raw = fetch_chart(
            symbol,
            range_name=DOWNLOAD_RANGE,
        )
        rows = extract_market_rows(raw)

        if not rows:
            raise RuntimeError(
                f"No valid actual rows were returned for {symbol}."
            )

        raw_results[symbol] = raw
        path = (
            data_directory
            / f"{_safe_symbol(symbol)}.csv"
        )
        _write_market_rows(path, rows)
        paths[symbol] = path

        if symbol in selection_config.candidates:
            histories[symbol] = rows

    income_rows = extract_market_rows(
        raw_results[INCOME_SYMBOL]
    )
    vix_rows = extract_market_rows(
        raw_results[VIX_SYMBOL]
    )
    dividends = extract_dividend_rows(
        raw_results[INCOME_SYMBOL]
    )

    if not dividends:
        raise RuntimeError(
            "The provider returned no actual QDTE "
            "distribution events."
        )

    dividend_path = (
        data_directory / "QDTE_DIVIDENDS.csv"
    )
    _write_dividend_rows(
        dividend_path,
        dividends,
    )
    paths["QDTE_DIVIDENDS"] = dividend_path

    manifest_path = (
        data_directory / "DOWNLOAD_MANIFEST.json"
    )
    manifest = {
        "schema_version": 1,
        "provider": "Yahoo Finance chart endpoint",
        "downloaded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "requested_range": DOWNLOAD_RANGE,
        "interval": "1d",
        "actual_data": True,
        "symbols": {
            "swing_universe": list(
                selection_config.candidates
            ),
            "income": INCOME_SYMBOL,
            "vix": VIX_SYMBOL,
        },
        "rows": {
            symbol: len(
                histories[symbol]
                if symbol in histories
                else (
                    income_rows
                    if symbol == INCOME_SYMBOL
                    else vix_rows
                )
            )
            for symbol in symbols
        },
        "dividend_events": len(dividends),
        "date_ranges": {
            symbol: {
                "first": (
                    histories[symbol][0].date.isoformat()
                    if symbol in histories
                    else (
                        income_rows[0].date.isoformat()
                        if symbol == INCOME_SYMBOL
                        else vix_rows[0].date.isoformat()
                    )
                ),
                "last": (
                    histories[symbol][-1].date.isoformat()
                    if symbol in histories
                    else (
                        income_rows[-1].date.isoformat()
                        if symbol == INCOME_SYMBOL
                        else vix_rows[-1].date.isoformat()
                    )
                ),
            }
            for symbol in symbols
        },
        "files": {
            symbol: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for symbol, path in paths.items()
        },
        "notice": (
            "No synthetic OHLCV, distributions, VIX values, "
            "signals, or forced entries are used."
        ),
    }
    _atomic_json(manifest_path, manifest)

    return (
        histories,
        income_rows,
        vix_rows,
        dividends,
        manifest_path,
    )


def _to_candles(
    rows: Sequence[MarketRow],
) -> list[Candle]:
    return [
        Candle(
            date=row.date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in rows
    ]


def _common_dates(
    histories: Mapping[str, Sequence[MarketRow]],
    income_rows: Sequence[MarketRow],
    vix_rows: Sequence[MarketRow],
) -> list[date]:
    date_sets = [
        {row.date for row in histories[symbol]}
        for symbol in REQUIRED_UNIVERSE
    ]
    date_sets.extend(
        (
            {row.date for row in income_rows},
            {row.date for row in vix_rows},
        )
    )
    common = set.intersection(*date_sets)
    return sorted(common)


def _completed_session() -> date:
    now = datetime.now(tz=NEW_YORK)
    session, _ = latest_completed_session(now)
    return session


def _test_window(
    *,
    common_dates: Sequence[date],
) -> tuple[date, date, date, list[date]]:
    if not common_dates:
        raise RuntimeError(
            "The downloaded histories have no common sessions."
        )

    expected_end = _completed_session()
    eligible = [
        day
        for day in common_dates
        if day <= expected_end
    ]

    if not eligible:
        raise RuntimeError(
            "Actual data does not contain a completed session."
        )

    actual_end = eligible[-1]

    if (expected_end - actual_end).days > 4:
        raise RuntimeError(
            "The common actual-data session is stale. "
            f"Expected near {expected_end}; latest is {actual_end}."
        )

    requested_start = subtract_years(
        actual_end,
        2,
    )
    test_dates = [
        day
        for day in eligible
        if requested_start <= day <= actual_end
    ]

    if not test_dates:
        raise RuntimeError(
            "No common sessions exist in the requested "
            "two-year window."
        )

    actual_start = test_dates[0]

    if (
        actual_start - requested_start
    ).days > MAXIMUM_START_DELAY_DAYS:
        raise RuntimeError(
            "Actual data does not reach the requested "
            "two-year boundary."
        )

    if len(test_dates) < MINIMUM_TEST_BARS:
        raise RuntimeError(
            "Too few common daily sessions for a genuine "
            f"two-year test: {len(test_dates)}; "
            f"{MINIMUM_TEST_BARS} required."
        )

    return (
        requested_start,
        actual_start,
        actual_end,
        test_dates,
    )


def rank_as_of(
    *,
    decision_date: date,
    histories: Mapping[str, Sequence[MarketRow]],
    selection_config: SelectionConfig,
) -> SelectionResult:
    """
    Rank using only observations strictly before the decision date.
    """
    point_in_time = {
        symbol: [
            row
            for row in histories[symbol]
            if row.date < decision_date
        ]
        for symbol in selection_config.candidates
    }
    result = rank_candidates(
        point_in_time,
        selection_config,
    )

    if result.latest_market_date >= decision_date:
        raise RuntimeError(
            "Selection look-ahead guard failed."
        )

    return result


def _selection_snapshot(
    *,
    decision_date: date,
    result: SelectionResult,
    active_symbol: str,
    locked: bool,
) -> SelectionSnapshot:
    return SelectionSnapshot(
        decision_date=decision_date,
        winner=result.selected_symbol,
        active_symbol=active_symbol,
        locked=locked,
        latest_input_date=result.latest_market_date,
        rankings=result.rankings,
    )


def _apply_rebalance(
    *,
    income: IncomeHolding,
    swing_portfolio: Portfolio,
    income_price: float,
    swing_market_value: float,
    target_income_weight: float,
    config: BotConfig,
) -> AllocationRebalance:
    rebalance = rebalance_income_allocation(
        income_shares=income.shares,
        income_cost=income.invested_cost,
        swing_cash=swing_portfolio.cash,
        swing_market_value=swing_market_value,
        income_price=income_price,
        target_income_weight=target_income_weight,
        slippage_rate=config.slippage_rate,
        tax_reserve_rate=config.annual_tax_reserve_rate,
        tolerance=config.allocation_rebalance_tolerance,
        minimum_trade=config.minimum_rebalance_trade,
    )
    income.shares = rebalance.shares_after
    income.invested_cost = (
        rebalance.income_cost_after
    )
    swing_portfolio.cash = (
        rebalance.swing_cash_after
    )
    swing_portfolio.tax_reserve_cash += (
        rebalance.tax_reserved
    )
    swing_portfolio.realized_pnl += (
        rebalance.realized_pnl
    )
    return rebalance


def _flow_adjusted_metrics(
    points: Sequence[PortfolioPoint],
    *,
    starting_capital: float,
) -> tuple[ReturnMetrics, tuple[float, ...]]:
    returns: list[float] = []
    previous_equity = starting_capital
    previous_contributions = starting_capital

    for point in points:
        contribution = (
            point.total_contributions
            - previous_contributions
        )
        daily_return = (
            (
                point.total_equity - contribution
            )
            / previous_equity
            - 1.0
            if previous_equity > 0
            else 0.0
        )
        returns.append(daily_return)
        previous_equity = point.total_equity
        previous_contributions = (
            point.total_contributions
        )

    exposure = (
        sum(
            point.swing_market_value > 0
            for point in points
        )
        / len(points)
        if points
        else 0.0
    )
    return (
        metrics_from_returns(
            returns,
            exposure=exposure,
        ),
        tuple(returns),
    )


def _profit_factor(
    trades: Sequence[ClosedTrade],
) -> float | None:
    gross_profit = sum(
        trade.pnl
        for trade in trades
        if trade.pnl > 0
    )
    gross_loss = -sum(
        trade.pnl
        for trade in trades
        if trade.pnl < 0
    )

    if gross_loss == 0:
        return None if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def _write_equity(
    path: Path,
    points: Sequence[PortfolioPoint],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "TotalEquity",
                "TotalContributions",
                "IncomeValue",
                "SwingEquity",
                "SwingCash",
                "SwingMarketValue",
                "TaxReserve",
                "IncomeWeight",
                "TargetIncomeWeight",
                "MonthlyWinner",
                "ActiveSymbol",
                "PositionSymbol",
            )
        )

        for point in points:
            writer.writerow(
                (
                    point.date.isoformat(),
                    f"{point.total_equity:.8f}",
                    f"{point.total_contributions:.8f}",
                    f"{point.income_value:.8f}",
                    f"{point.swing_equity:.8f}",
                    f"{point.swing_cash:.8f}",
                    f"{point.swing_market_value:.8f}",
                    f"{point.tax_reserve:.8f}",
                    f"{point.income_weight:.10f}",
                    f"{point.target_income_weight:.10f}",
                    point.monthly_winner,
                    point.active_symbol,
                    point.position_symbol or "",
                )
            )


def _write_trades(
    path: Path,
    trades: Sequence[ClosedTrade],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Symbol",
                "EntryDate",
                "ExitDate",
                "Shares",
                "EntryPrice",
                "ExitPrice",
                "PnL",
                "TaxReserved",
                "ExitReason",
                "ResultR",
            )
        )

        for trade in trades:
            writer.writerow(
                (
                    trade.symbol,
                    trade.entry_date.isoformat(),
                    trade.exit_date.isoformat(),
                    trade.shares,
                    f"{trade.entry_price:.8f}",
                    f"{trade.exit_price:.8f}",
                    f"{trade.pnl:.8f}",
                    f"{trade.tax_reserved:.8f}",
                    trade.reason,
                    f"{trade.result_r:.8f}",
                )
            )


def _write_selections(
    path: Path,
    snapshots: Sequence[SelectionSnapshot],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "DecisionDate",
                "LatestInputDate",
                "MonthlyWinner",
                "ActiveSymbol",
                "Locked",
                "Symbol",
                "Rank",
                "Score",
                "Eligible",
                "ShortReturn",
                "LongReturn",
                "TrendDistance",
                "AnnualizedVolatility",
                "MaximumDrawdown",
                "MedianDollarVolume",
                "RejectionReason",
            )
        )

        for snapshot in snapshots:
            for ranking in snapshot.rankings:
                writer.writerow(
                    (
                        snapshot.decision_date.isoformat(),
                        snapshot.latest_input_date.isoformat(),
                        snapshot.winner,
                        snapshot.active_symbol,
                        snapshot.locked,
                        ranking.symbol,
                        ranking.rank or "",
                        f"{ranking.score:.10f}",
                        ranking.eligible,
                        f"{ranking.short_return:.10f}",
                        f"{ranking.long_return:.10f}",
                        f"{ranking.trend_distance:.10f}",
                        (
                            f"{ranking.annualized_volatility:.10f}"
                        ),
                        f"{ranking.maximum_drawdown:.10f}",
                        (
                            f"{ranking.median_dollar_volume:.4f}"
                        ),
                        ranking.rejection_reason or "",
                    )
                )


def _write_allocations(
    path: Path,
    snapshots: Sequence[AllocationSnapshot],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "EventType",
                "Contribution",
                "TargetIncomeWeight",
                "Action",
                "BeforeIncomeWeight",
                "AfterIncomeWeight",
                "TargetFullyReached",
                "QDTEMarketValueTraded",
                "RealizedPnL",
                "TaxReserved",
            )
        )

        for item in snapshots:
            writer.writerow(
                (
                    item.date.isoformat(),
                    item.event_type,
                    f"{item.contribution:.8f}",
                    f"{item.target_income_weight:.10f}",
                    item.action,
                    f"{item.before_income_weight:.10f}",
                    f"{item.after_income_weight:.10f}",
                    item.target_fully_reached,
                    f"{item.qdte_market_value_traded:.8f}",
                    f"{item.realized_pnl:.8f}",
                    f"{item.tax_reserved:.8f}",
                )
            )


def _format_report(
    result: ActualTwoYearResult,
) -> str:
    profit_factor = (
        "∞"
        if result.profit_factor is None
        else f"{result.profit_factor:,.3f}"
    )
    winner_lines = [
        f"  {symbol}: {result.winner_counts.get(symbol, 0)}"
        for symbol in result.universe
    ]

    return "\n".join(
        (
            "=" * 78,
            (
                "QPX BOT v1.18 — ACTUAL TWO-YEAR "
                "EIGHT-SYMBOL PORTFOLIO BACKTEST"
            ),
            "=" * 78,
            (
                "Actual provider            : "
                f"{result.provider}"
            ),
            (
                "Actual period              : "
                f"{result.actual_start} to "
                f"{result.actual_end}"
            ),
            (
                "Common daily sessions      : "
                f"{result.bars}"
            ),
            (
                "Swing universe             : "
                + ", ".join(result.universe)
            ),
            (
                "Income sleeve              : "
                f"{result.income_symbol}"
            ),
            (
                "Initial QDTE seed          : "
                f"${result.starting_income_cash:,.2f}"
            ),
            (
                "Initial swing liquidity    : "
                f"${result.starting_swing_cash:,.2f}"
            ),
            (
                "Initial total capital      : "
                f"${result.starting_total_capital:,.2f}"
            ),
            (
                "Monthly contribution       : "
                f"${result.monthly_contribution:,.2f}"
            ),
            (
                "Monthly contributions made : "
                f"{result.contribution_count}"
            ),
            (
                "Total contributed capital  : "
                f"${result.total_contributions:,.2f}"
            ),
            (
                "Ending account equity      : "
                f"${result.ending_equity:,.2f}"
            ),
            (
                "Net profit                 : "
                f"${result.net_profit:,.2f}"
            ),
            (
                "Return on contributions    : "
                f"{result.return_on_contributed_capital:.2%}"
            ),
            (
                "Flow-adjusted total return : "
                f"{result.flow_adjusted_total_return:.2%}"
            ),
            (
                "Flow-adjusted CAGR         : "
                f"{result.flow_adjusted_cagr:.2%}"
            ),
            (
                "Maximum drawdown           : "
                f"{result.maximum_drawdown:.2%}"
            ),
            (
                "Annualized volatility      : "
                f"{result.flow_adjusted_volatility:.2%}"
            ),
            (
                "Sharpe / Sortino           : "
                f"{result.sharpe_ratio:,.3f} / "
                f"{result.sortino_ratio:,.3f}"
            ),
            (
                "Swing exposure             : "
                f"{result.swing_exposure:.2%}"
            ),
            (
                "Ending QDTE value          : "
                f"${result.ending_income_value:,.2f}"
            ),
            (
                "Ending QDTE weight         : "
                f"{result.ending_income_weight:.2%}"
            ),
            (
                "Ending swing equity        : "
                f"${result.ending_swing_equity:,.2f}"
            ),
            (
                "Ending swing cash          : "
                f"${result.ending_swing_cash:,.2f}"
            ),
            (
                "Tax reserve cash           : "
                f"${result.ending_tax_reserve:,.2f}"
            ),
            (
                "Actual QDTE distributions  : "
                f"${result.total_dividends:,.2f} "
                f"({result.dividend_event_count} events)"
            ),
            (
                "Signals / filled entries   : "
                f"{result.signal_count} / "
                f"{result.filled_entries}"
            ),
            (
                "Gap / risk rejections      : "
                f"{result.gap_rejections} / "
                f"{result.risk_rejections}"
            ),
            (
                "Closed swing trades        : "
                f"{result.closed_trades}"
            ),
            (
                "Win rate / profit factor   : "
                f"{result.win_rate:.2%} / "
                f"{profit_factor}"
            ),
            (
                "Monthly ranking decisions  : "
                f"{result.selection_months}"
            ),
            "Monthly winner counts:",
            *winner_lines,
            "Forced entries              : DISABLED",
            (
                "Symbol-specific bonuses    : "
                f"{result.symbol_bonus_policy}"
            ),
            "Live brokerage              : DISABLED",
            "=" * 78,
            (
                "Downloaded actual daily market data only. "
                "No synthetic prices, distributions, VIX "
                "values, signals, or forced trades."
            ),
            (
                "Historical research does not guarantee "
                "future performance."
            ),
        )
    )


def run_actual_two_year_eight_symbol_backtest(
    *,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    report_root: str | Path = DEFAULT_REPORT_ROOT,
) -> tuple[ActualTwoYearResult, RunArtifacts]:
    config = BotConfig()
    config.validate()
    selection_config = load_selection_config(
        UNIVERSE_CONFIG_PATH
    )

    if selection_config.candidates != REQUIRED_UNIVERSE:
        raise RuntimeError(
            "The configured swing universe is not the "
            "required eight-symbol set."
        )

    if selection_config.symbol_bonus_policy != "none":
        raise RuntimeError(
            "Symbol bonuses are prohibited."
        )

    session_payload = json.loads(
        SESSION_CONFIG_PATH.read_text(
            encoding="utf-8"
        )
    )
    maximum_gap_atr = float(
        session_payload[
            "maximum_gap_atr_multiple"
        ]
    )

    if maximum_gap_atr <= 0:
        raise RuntimeError(
            "Opening-gap ATR limit must be positive."
        )

    run_id = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    data_directory = (
        Path(data_root).expanduser().resolve()
        / run_id
    )
    report_directory = (
        Path(report_root).expanduser().resolve()
        / run_id
    )
    report_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        histories,
        income_rows,
        vix_rows,
        dividend_rows,
        manifest_path,
    ) = _download_actual_inputs(
        data_directory=data_directory,
        selection_config=selection_config,
    )
    common_dates = _common_dates(
        histories,
        income_rows,
        vix_rows,
    )
    (
        requested_start,
        actual_start,
        actual_end,
        test_dates,
    ) = _test_window(
        common_dates=common_dates,
    )

    if income_rows[0].date > actual_start:
        raise RuntimeError(
            "QDTE actual history begins after the "
            "two-year test start."
        )

    selection_probe = rank_as_of(
        decision_date=actual_start,
        histories=histories,
        selection_config=selection_config,
    )

    if (
        selection_probe.latest_market_date
        >= actual_start
    ):
        raise RuntimeError(
            "Initial monthly selection contains future data."
        )

    candles = {
        symbol: _to_candles(histories[symbol])
        for symbol in REQUIRED_UNIVERSE
    }
    indicators: dict[str, IndicatorSet] = {
        symbol: calculate_indicators(
            candles[symbol],
            config,
        )
        for symbol in REQUIRED_UNIVERSE
    }
    row_maps = {
        symbol: {
            row.date: row
            for row in histories[symbol]
        }
        for symbol in REQUIRED_UNIVERSE
    }
    index_maps = {
        symbol: {
            candle.date: index
            for index, candle in enumerate(
                candles[symbol]
            )
        }
        for symbol in REQUIRED_UNIVERSE
    }
    income_map = {
        row.date: row
        for row in income_rows
    }
    vix_map = {
        row.date: row.close
        for row in vix_rows
    }
    dividend_map: dict[date, float] = {}

    for dividend in dividend_rows:
        dividend_map[dividend.date] = (
            dividend_map.get(
                dividend.date,
                0.0,
            )
            + dividend.amount
        )

    first_income = income_map[actual_start]
    income = IncomeHolding(INCOME_SYMBOL)
    income.buy(
        cash_amount=config.starting_cash,
        market_price=first_income.open,
        slippage_rate=config.slippage_rate,
    )
    swing = Portfolio(
        config.starting_swing_cash
    )
    initial_target, _ = contribution_allocation(
        0,
        config,
    )
    initial_rebalance = _apply_rebalance(
        income=income,
        swing_portfolio=swing,
        income_price=first_income.open,
        swing_market_value=0.0,
        target_income_weight=initial_target,
        config=config,
    )
    total_contributions = (
        config.total_starting_capital
    )
    contribution_count = 0
    allocation_snapshots = [
        AllocationSnapshot(
            date=actual_start,
            event_type="INITIAL_REBALANCE",
            contribution=(
                config.total_starting_capital
            ),
            target_income_weight=initial_target,
            action=initial_rebalance.action,
            before_income_weight=(
                initial_rebalance.before_income_weight
            ),
            after_income_weight=(
                initial_rebalance.after_income_weight
            ),
            target_fully_reached=(
                initial_rebalance.target_fully_reached
            ),
            qdte_market_value_traded=(
                initial_rebalance.market_value_traded
            ),
            realized_pnl=(
                initial_rebalance.realized_pnl
            ),
            tax_reserved=(
                initial_rebalance.tax_reserved
            ),
        )
    ]

    initial_selection = selection_probe
    monthly_winner = (
        initial_selection.selected_symbol
    )
    active_symbol = monthly_winner
    current_month = (
        actual_start.year,
        actual_start.month,
    )
    selection_snapshots = [
        _selection_snapshot(
            decision_date=actual_start,
            result=initial_selection,
            active_symbol=active_symbol,
            locked=False,
        )
    ]
    pending: PendingSignal | None = None
    points: list[PortfolioPoint] = []
    signal_count = 0
    filled_entries = 0
    gap_rejections = 0
    risk_rejections = 0
    dividend_event_count = 0

    for day in test_dates:
        income_row = income_map[day]
        current_month_key = (
            day.year,
            day.month,
        )

        dividend_per_share = dividend_map.get(
            day,
            0.0,
        )

        if dividend_per_share > 0:
            dividend_cash = (
                income.receive_dividend(
                    dividend_per_share
                )
            )
            swing.cash += dividend_cash
            dividend_event_count += 1

        if current_month_key != current_month:
            selection = rank_as_of(
                decision_date=day,
                histories=histories,
                selection_config=selection_config,
            )
            monthly_winner = (
                selection.selected_symbol
            )
            locked = (
                bool(swing.positions)
                or pending is not None
            )

            if not locked:
                active_symbol = monthly_winner

            selection_snapshots.append(
                _selection_snapshot(
                    decision_date=day,
                    result=selection,
                    active_symbol=active_symbol,
                    locked=locked,
                )
            )

            swing.deposit(
                config.monthly_contribution
            )
            total_contributions += (
                config.monthly_contribution
            )
            contribution_count += 1
            elapsed = _elapsed_years(
                actual_start,
                day,
            )
            target_income_weight, _ = (
                contribution_allocation(
                    elapsed,
                    config,
                )
            )
            open_position = (
                next(
                    iter(
                        swing.positions.values()
                    ),
                    None,
                )
            )
            swing_market_value_open = (
                open_position.shares
                * row_maps[
                    open_position.symbol
                ][day].open
                if open_position is not None
                else 0.0
            )
            rebalance = _apply_rebalance(
                income=income,
                swing_portfolio=swing,
                income_price=income_row.open,
                swing_market_value=(
                    swing_market_value_open
                ),
                target_income_weight=(
                    target_income_weight
                ),
                config=config,
            )
            allocation_snapshots.append(
                AllocationSnapshot(
                    date=day,
                    event_type=(
                        "MONTHLY_CONTRIBUTION_REBALANCE"
                    ),
                    contribution=(
                        config.monthly_contribution
                    ),
                    target_income_weight=(
                        target_income_weight
                    ),
                    action=rebalance.action,
                    before_income_weight=(
                        rebalance.before_income_weight
                    ),
                    after_income_weight=(
                        rebalance.after_income_weight
                    ),
                    target_fully_reached=(
                        rebalance.target_fully_reached
                    ),
                    qdte_market_value_traded=(
                        rebalance.market_value_traded
                    ),
                    realized_pnl=(
                        rebalance.realized_pnl
                    ),
                    tax_reserved=(
                        rebalance.tax_reserved
                    ),
                )
            )
            current_month = current_month_key

        if pending is not None:
            row = row_maps[pending.symbol][day]
            gap_atr = (
                abs(
                    row.open
                    - pending.prior_close
                )
                / pending.signal_atr
            )

            if gap_atr > maximum_gap_atr:
                gap_rejections += 1
                pending = None
            else:
                combined_equity = (
                    swing.equity({})
                    + income.market_value(
                        income_row.open
                    )
                )
                sizing = calculate_position_size(
                    account_equity=combined_equity,
                    available_cash=swing.cash,
                    entry_price=row.open,
                    atr=pending.signal_atr,
                    active_risk=swing.active_risk(),
                    config=config,
                    trade_results_r=[
                        trade.result_r
                        for trade in swing.closed_trades
                    ],
                )

                if sizing.is_tradeable:
                    swing.open_position(
                        symbol=pending.symbol,
                        sizing=sizing,
                        entry_date=day,
                        entry_atr=(
                            pending.signal_atr
                        ),
                    )
                    active_symbol = (
                        pending.symbol
                    )
                    filled_entries += 1
                else:
                    risk_rejections += 1

                pending = None

            if (
                not swing.positions
                and pending is None
            ):
                active_symbol = monthly_winner

        open_position = next(
            iter(swing.positions.values()),
            None,
        )

        if open_position is not None:
            symbol = open_position.symbol
            index = index_maps[symbol][day]
            current_atr = (
                indicators[symbol].atr[index]
            )

            if current_atr is not None:
                evaluation = evaluate_exit(
                    position=open_position,
                    candle=candles[symbol][index],
                    current_atr=current_atr,
                    config=config,
                )

                if evaluation.should_exit:
                    assert (
                        evaluation.exit_price
                        is not None
                    )
                    swing.close_position(
                        symbol=symbol,
                        exit_price=(
                            evaluation.exit_price
                        ),
                        exit_date=day,
                        reason=(
                            evaluation.reason
                            or "EXIT"
                        ),
                        config=config,
                    )
                    active_symbol = (
                        monthly_winner
                    )
                else:
                    open_position.stop_price = (
                        evaluation.next_stop_price
                    )
                    open_position.highest_price = (
                        evaluation.highest_price
                    )

        if (
            not swing.positions
            and pending is None
            and day != actual_end
        ):
            active_symbol = monthly_winner
            index = index_maps[
                active_symbol
            ][day]
            evaluation = evaluate_entry(
                candles=candles[
                    active_symbol
                ],
                indicators=indicators[
                    active_symbol
                ],
                index=index,
                vix=vix_map[day],
                config=config,
            )

            if evaluation.should_enter:
                signal_atr = indicators[
                    active_symbol
                ].atr[index]

                if (
                    signal_atr is not None
                    and signal_atr > 0
                ):
                    pending = PendingSignal(
                        symbol=active_symbol,
                        signal_date=day,
                        signal_atr=signal_atr,
                        prior_close=row_maps[
                            active_symbol
                        ][day].close,
                    )
                    signal_count += 1

        position = next(
            iter(swing.positions.values()),
            None,
        )
        position_prices = (
            {
                position.symbol: (
                    row_maps[
                        position.symbol
                    ][day].close
                )
            }
            if position is not None
            else {}
        )
        swing_market_value = swing.market_value(
            position_prices
        )
        swing_equity = swing.equity(
            position_prices
        )
        income_value = income.market_value(
            income_row.close
        )
        total_equity = (
            swing_equity + income_value
        )
        elapsed = _elapsed_years(
            actual_start,
            day,
        )
        target_income_weight, _ = (
            contribution_allocation(
                elapsed,
                config,
            )
        )
        investable = (
            income_value
            + swing.cash
            + swing_market_value
        )
        income_weight = (
            income_value / investable
            if investable > 0
            else 0.0
        )
        points.append(
            PortfolioPoint(
                date=day,
                total_equity=total_equity,
                total_contributions=(
                    total_contributions
                ),
                income_value=income_value,
                swing_equity=swing_equity,
                swing_cash=swing.cash,
                swing_market_value=(
                    swing_market_value
                ),
                tax_reserve=(
                    swing.tax_reserve_cash
                ),
                income_weight=income_weight,
                target_income_weight=(
                    target_income_weight
                ),
                monthly_winner=monthly_winner,
                active_symbol=active_symbol,
                position_symbol=(
                    position.symbol
                    if position is not None
                    else None
                ),
            )
        )

    if pending is not None:
        pending = None

    final_position = next(
        iter(swing.positions.values()),
        None,
    )

    if final_position is not None:
        final_row = row_maps[
            final_position.symbol
        ][actual_end]
        swing.close_position(
            symbol=final_position.symbol,
            exit_price=final_row.close,
            exit_date=actual_end,
            reason="END_OF_TEST",
            config=config,
        )

        final_income_value = (
            income.market_value(
                income_map[actual_end].close
            )
        )
        final_swing_equity = swing.equity({})
        final_total = (
            final_income_value
            + final_swing_equity
        )
        elapsed = _elapsed_years(
            actual_start,
            actual_end,
        )
        final_target, _ = (
            contribution_allocation(
                elapsed,
                config,
            )
        )
        investable = (
            final_income_value + swing.cash
        )
        final_weight = (
            final_income_value / investable
            if investable > 0
            else 0.0
        )
        points[-1] = PortfolioPoint(
            date=actual_end,
            total_equity=final_total,
            total_contributions=(
                total_contributions
            ),
            income_value=final_income_value,
            swing_equity=final_swing_equity,
            swing_cash=swing.cash,
            swing_market_value=0.0,
            tax_reserve=swing.tax_reserve_cash,
            income_weight=final_weight,
            target_income_weight=final_target,
            monthly_winner=monthly_winner,
            active_symbol=monthly_winner,
            position_symbol=None,
        )

    metrics, _ = _flow_adjusted_metrics(
        points,
        starting_capital=(
            config.total_starting_capital
        ),
    )
    ending = points[-1]
    ending_equity = ending.total_equity
    net_profit = (
        ending_equity - total_contributions
    )
    trades = tuple(swing.closed_trades)
    winners = sum(
        trade.pnl > 0
        for trade in trades
    )
    profit_factor = _profit_factor(
        trades
    )
    winner_counts = Counter(
        snapshot.winner
        for snapshot in selection_snapshots
    )
    result = ActualTwoYearResult(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        provider=(
            "Yahoo Finance chart endpoint"
        ),
        requested_start=requested_start,
        actual_start=actual_start,
        actual_end=actual_end,
        bars=len(test_dates),
        universe=REQUIRED_UNIVERSE,
        income_symbol=INCOME_SYMBOL,
        starting_income_cash=(
            config.starting_cash
        ),
        starting_swing_cash=(
            config.starting_swing_cash
        ),
        starting_total_capital=(
            config.total_starting_capital
        ),
        monthly_contribution=(
            config.monthly_contribution
        ),
        contribution_count=(
            contribution_count
        ),
        total_contributions=(
            total_contributions
        ),
        ending_equity=ending_equity,
        net_profit=net_profit,
        return_on_contributed_capital=(
            net_profit / total_contributions
            if total_contributions > 0
            else 0.0
        ),
        ending_income_value=(
            ending.income_value
        ),
        ending_swing_equity=(
            ending.swing_equity
        ),
        ending_swing_cash=(
            ending.swing_cash
        ),
        ending_tax_reserve=(
            ending.tax_reserve
        ),
        ending_income_weight=(
            ending.income_weight
        ),
        total_dividends=(
            income.dividends_received
        ),
        dividend_event_count=(
            dividend_event_count
        ),
        signal_count=signal_count,
        filled_entries=filled_entries,
        gap_rejections=gap_rejections,
        risk_rejections=risk_rejections,
        closed_trades=len(trades),
        win_rate=(
            winners / len(trades)
            if trades
            else 0.0
        ),
        profit_factor=profit_factor,
        maximum_drawdown=(
            metrics.maximum_drawdown
        ),
        flow_adjusted_total_return=(
            metrics.total_return
        ),
        flow_adjusted_cagr=metrics.cagr,
        flow_adjusted_volatility=(
            metrics.annualized_volatility
        ),
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        swing_exposure=metrics.exposure,
        selection_months=len(
            selection_snapshots
        ),
        winner_counts={
            symbol: winner_counts.get(
                symbol,
                0,
            )
            for symbol in REQUIRED_UNIVERSE
        },
        forced_entry_indices=None,
        symbol_bonus_policy=(
            selection_config.symbol_bonus_policy
        ),
        live_broker_enabled=False,
    )

    report_path = (
        report_directory
        / "actual_two_year_report.txt"
    )
    result_path = (
        report_directory
        / "actual_two_year_result.json"
    )
    equity_path = (
        report_directory
        / "actual_two_year_equity.csv"
    )
    trades_path = (
        report_directory
        / "actual_two_year_trades.csv"
    )
    selection_path = (
        report_directory
        / "monthly_selection_log.csv"
    )
    allocation_path = (
        report_directory
        / "allocation_rebalance_log.csv"
    )
    provenance_path = (
        report_directory
        / "actual_two_year_provenance.json"
    )

    report_path.write_text(
        _format_report(result) + "\n",
        encoding="utf-8",
    )
    result_payload = asdict(result)
    result_payload["requested_start"] = (
        result.requested_start.isoformat()
    )
    result_payload["actual_start"] = (
        result.actual_start.isoformat()
    )
    result_payload["actual_end"] = (
        result.actual_end.isoformat()
    )
    _atomic_json(
        result_path,
        result_payload,
    )
    _write_equity(
        equity_path,
        points,
    )
    _write_trades(
        trades_path,
        trades,
    )
    _write_selections(
        selection_path,
        selection_snapshots,
    )
    _write_allocations(
        allocation_path,
        allocation_snapshots,
    )
    provenance = {
        "schema_version": 1,
        "generated_at_utc": (
            result.generated_at_utc
        ),
        "actual_data": True,
        "provider": result.provider,
        "requested_download_range": (
            DOWNLOAD_RANGE
        ),
        "requested_backtest_years": 2,
        "requested_start": (
            requested_start.isoformat()
        ),
        "actual_start": (
            actual_start.isoformat()
        ),
        "actual_end": (
            actual_end.isoformat()
        ),
        "common_daily_sessions": len(
            test_dates
        ),
        "swing_universe": list(
            REQUIRED_UNIVERSE
        ),
        "income_symbol": INCOME_SYMBOL,
        "vix_symbol": VIX_SYMBOL,
        "selection_engine": (
            "qpx_bot.symbol_selector.rank_candidates"
        ),
        "entry_engine": (
            "qpx_bot.strategy.evaluate_entry"
        ),
        "exit_engine": (
            "qpx_bot.strategy.evaluate_exit"
        ),
        "position_sizing_engine": (
            "qpx_bot.risk.calculate_position_size"
        ),
        "allocation_engine": (
            "qpx_bot.allocation."
            "rebalance_income_allocation"
        ),
        "portfolio_engine": (
            "qpx_bot.portfolio.Portfolio"
        ),
        "monthly_selection_lookahead": False,
        "selection_rule": (
            "Every monthly decision uses rows with "
            "date strictly before the decision date."
        ),
        "position_lock": True,
        "opening_gap_atr_limit": (
            maximum_gap_atr
        ),
        "forced_entry_indices": None,
        "symbol_bonus_policy": (
            selection_config.symbol_bonus_policy
        ),
        "configuration": asdict(config),
        "selection_configuration": asdict(
            selection_config
        ),
        "download_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(
                manifest_path
            ),
        },
        "outputs": {
            "report": str(report_path),
            "result": str(result_path),
            "equity": str(equity_path),
            "trades": str(trades_path),
            "selections": str(
                selection_path
            ),
            "allocations": str(
                allocation_path
            ),
        },
        "live_broker_enabled": False,
    }
    _atomic_json(
        provenance_path,
        provenance,
    )
    artifacts = RunArtifacts(
        report=report_path,
        result=result_path,
        equity=equity_path,
        trades=trades_path,
        selections=selection_path,
        allocations=allocation_path,
        provenance=provenance_path,
        manifest=manifest_path,
    )
    return result, artifacts


def format_console_summary(
    result: ActualTwoYearResult,
    artifacts: RunArtifacts,
) -> str:
    artifact_lines = [
        f"  {name:<12}: {path}"
        for name, path in asdict(
            artifacts
        ).items()
    ]
    return "\n".join(
        (
            _format_report(result),
            "-" * 78,
            "Artifacts:",
            *artifact_lines,
        )
    )
