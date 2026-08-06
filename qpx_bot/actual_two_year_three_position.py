"""Actual-data two-year QPX backtest with three unranked swing slots."""

from __future__ import annotations

import csv
import hashlib
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
from qpx_bot.strategy import EntryEvaluation, evaluate_entry, evaluate_exit
from qpx_bot.time_rules import elapsed_complete_years
from qpx_bot.yahoo_data import (
    DividendRow,
    MarketRow,
    extract_dividend_rows,
    extract_market_rows,
    fetch_chart,
)


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
POLICY_PATH = PACKAGE_DIR / "multi_swing_policy.json"
SESSION_CONFIG_PATH = PACKAGE_DIR / "session_execution_config.json"
DEFAULT_DATA_ROOT = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_actual_two_year_three_position"
)
DEFAULT_REPORT_ROOT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_actual_two_year_three_position"
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
class MultiSwingPolicy:
    schema_version: int
    rankings_enabled: bool
    maximum_concurrent_positions: int
    candidates: tuple[str, ...]
    signal_evaluation: str
    signal_execution: str
    simultaneous_signal_tiebreak: str
    symbol_bonus_policy: str
    live_broker_enabled: bool

    def validate(self) -> None:
        if self.schema_version != 1:
            raise ValueError(
                "Unsupported multi-swing policy schema."
            )

        if self.rankings_enabled:
            raise ValueError(
                "Rankings must remain disabled."
            )

        if self.maximum_concurrent_positions != 3:
            raise ValueError(
                "Exactly three concurrent swing slots are required."
            )

        if self.candidates != REQUIRED_UNIVERSE:
            raise ValueError(
                "The policy does not contain the required eight ETFs."
            )

        if self.signal_evaluation != "all_candidates_daily":
            raise ValueError(
                "All eight candidates must be evaluated daily."
            )

        if (
            self.signal_execution
            != "next_common_session_open"
        ):
            raise ValueError(
                "Signals must execute at the next common session open."
            )

        if (
            self.simultaneous_signal_tiebreak
            != "sha256_of_signal_date_and_symbol"
        ):
            raise ValueError(
                "Unexpected simultaneous-signal tie-break."
            )

        if self.symbol_bonus_policy != "none":
            raise ValueError(
                "Symbol-specific bonuses are prohibited."
            )

        if self.live_broker_enabled:
            raise ValueError(
                "Live brokerage must remain disabled."
            )


@dataclass(frozen=True, slots=True)
class PendingSignal:
    symbol: str
    signal_date: date
    signal_atr: float
    prior_close: float
    tie_key: str


@dataclass(frozen=True, slots=True)
class EntryDiagnostic:
    date: date
    symbol: str
    position_open: bool
    already_pending: bool
    slot_available: bool
    should_enter: bool
    staged: bool
    deferred_for_capacity: bool
    triggers: tuple[str, ...]
    failed_checks: tuple[str, ...]
    checks: Mapping[str, bool]


@dataclass(frozen=True, slots=True)
class SignalDecision:
    signal_date: date
    symbol: str
    action: str
    tie_key: str
    available_slots: int


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
    open_positions: int
    position_symbols: tuple[str, ...]
    pending_signals: int
    active_risk: float


@dataclass(frozen=True, slots=True)
class ThreePositionResult:
    generated_at_utc: str
    provider: str
    requested_start: date
    actual_start: date
    actual_end: date
    bars: int
    universe: tuple[str, ...]
    income_symbol: str
    rankings_enabled: bool
    maximum_concurrent_positions: int
    maximum_observed_positions: int
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
    all_symbol_evaluations: int
    qualifying_bars: int
    qualifying_bars_by_symbol: Mapping[str, int]
    staged_signals: int
    capacity_deferred_signals: int
    filled_entries: int
    gap_rejections: int
    risk_rejections: int
    closed_trades: int
    trades_by_symbol: Mapping[str, int]
    win_rate: float
    profit_factor: float | None
    maximum_drawdown: float
    flow_adjusted_total_return: float
    flow_adjusted_cagr: float
    flow_adjusted_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    swing_exposure: float
    failed_check_counts: Mapping[str, int]
    forced_entry_indices: None
    symbol_bonus_policy: str
    live_broker_enabled: bool


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    report: Path
    result: Path
    equity: Path
    trades: Path
    entry_diagnostics: Path
    signal_decisions: Path
    allocations: Path
    provenance: Path
    manifest: Path


def load_policy(
    filename: str | Path = POLICY_PATH,
) -> MultiSwingPolicy:
    payload = json.loads(
        Path(filename).read_text(
            encoding="utf-8"
        )
    )
    policy = MultiSwingPolicy(
        schema_version=int(
            payload["schema_version"]
        ),
        rankings_enabled=bool(
            payload["rankings_enabled"]
        ),
        maximum_concurrent_positions=int(
            payload[
                "maximum_concurrent_positions"
            ]
        ),
        candidates=tuple(
            str(symbol).strip().upper()
            for symbol in payload["candidates"]
        ),
        signal_evaluation=str(
            payload["signal_evaluation"]
        ),
        signal_execution=str(
            payload["signal_execution"]
        ),
        simultaneous_signal_tiebreak=str(
            payload[
                "simultaneous_signal_tiebreak"
            ]
        ),
        symbol_bonus_policy=str(
            payload["symbol_bonus_policy"]
        ).strip().lower(),
        live_broker_enabled=bool(
            payload["live_broker_enabled"]
        ),
    )
    policy.validate()
    return policy


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


def _safe_symbol(symbol: str) -> str:
    return (
        symbol.replace("^", "")
        .replace("/", "_")
    )


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
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
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

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
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            ("Date", "Dividend")
        )

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
    policy: MultiSwingPolicy,
) -> tuple[
    dict[str, list[MarketRow]],
    list[MarketRow],
    list[MarketRow],
    list[DividendRow],
    Path,
]:
    data_directory.mkdir(
        parents=True,
        exist_ok=True,
    )
    histories: dict[
        str,
        list[MarketRow],
    ] = {}
    paths: dict[str, Path] = {}
    raw_results: dict[
        str,
        Mapping[str, Any],
    ] = {}

    symbols = (
        *policy.candidates,
        INCOME_SYMBOL,
        VIX_SYMBOL,
    )

    for symbol in symbols:
        print(
            f"Downloading actual daily history: "
            f"{symbol}"
        )
        raw = fetch_chart(
            symbol,
            range_name=DOWNLOAD_RANGE,
        )
        rows = extract_market_rows(raw)

        if not rows:
            raise RuntimeError(
                f"No valid actual rows were "
                f"returned for {symbol}."
            )

        raw_results[symbol] = raw
        path = (
            data_directory
            / f"{_safe_symbol(symbol)}.csv"
        )
        _write_market_rows(
            path,
            rows,
        )
        paths[symbol] = path

        if symbol in policy.candidates:
            histories[symbol] = rows

    income_rows = extract_market_rows(
        raw_results[INCOME_SYMBOL]
    )
    vix_rows = extract_market_rows(
        raw_results[VIX_SYMBOL]
    )
    dividend_rows = extract_dividend_rows(
        raw_results[INCOME_SYMBOL]
    )

    if not dividend_rows:
        raise RuntimeError(
            "The provider returned no actual "
            "QDTE distribution events."
        )

    dividend_path = (
        data_directory
        / "QDTE_DIVIDENDS.csv"
    )
    _write_dividend_rows(
        dividend_path,
        dividend_rows,
    )
    paths["QDTE_DIVIDENDS"] = (
        dividend_path
    )
    manifest_path = (
        data_directory
        / "DOWNLOAD_MANIFEST.json"
    )
    manifest = {
        "schema_version": 1,
        "provider": (
            "Yahoo Finance chart endpoint"
        ),
        "downloaded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "requested_range": DOWNLOAD_RANGE,
        "interval": "1d",
        "actual_data": True,
        "rankings_enabled": False,
        "maximum_concurrent_positions": (
            policy.maximum_concurrent_positions
        ),
        "symbols": {
            "swing_universe": list(
                policy.candidates
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
        "dividend_events": len(
            dividend_rows
        ),
        "files": {
            symbol: {
                "path": str(path),
                "sha256": sha256_file(
                    path
                ),
            }
            for symbol, path in paths.items()
        },
        "notice": (
            "No rankings, synthetic OHLCV, "
            "placeholder distributions, forced "
            "entries, or live brokerage are used."
        ),
    }
    _atomic_json(
        manifest_path,
        manifest,
    )

    return (
        histories,
        income_rows,
        vix_rows,
        dividend_rows,
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
    histories: Mapping[
        str,
        Sequence[MarketRow],
    ],
    income_rows: Sequence[MarketRow],
    vix_rows: Sequence[MarketRow],
) -> list[date]:
    date_sets = [
        {
            row.date
            for row in histories[symbol]
        }
        for symbol in REQUIRED_UNIVERSE
    ]
    date_sets.extend(
        (
            {
                row.date
                for row in income_rows
            },
            {
                row.date
                for row in vix_rows
            },
        )
    )
    return sorted(
        set.intersection(*date_sets)
    )


def _completed_session() -> date:
    session, _ = latest_completed_session(
        datetime.now(tz=NEW_YORK)
    )
    return session


def _test_window(
    common_dates: Sequence[date],
) -> tuple[
    date,
    date,
    date,
    list[date],
]:
    if not common_dates:
        raise RuntimeError(
            "Downloaded histories have no "
            "common market sessions."
        )

    expected_end = _completed_session()
    eligible = [
        day
        for day in common_dates
        if day <= expected_end
    ]

    if not eligible:
        raise RuntimeError(
            "No completed common session exists."
        )

    actual_end = eligible[-1]

    if (
        expected_end - actual_end
    ).days > 4:
        raise RuntimeError(
            "The common actual-data session "
            "is stale."
        )

    requested_start = subtract_years(
        actual_end,
        2,
    )
    test_dates = [
        day
        for day in eligible
        if requested_start
        <= day
        <= actual_end
    ]

    if not test_dates:
        raise RuntimeError(
            "The requested two-year window "
            "contains no common sessions."
        )

    actual_start = test_dates[0]

    if (
        actual_start - requested_start
    ).days > MAXIMUM_START_DELAY_DAYS:
        raise RuntimeError(
            "Actual data does not reach the "
            "requested two-year boundary."
        )

    if len(test_dates) < MINIMUM_TEST_BARS:
        raise RuntimeError(
            "Too few common daily sessions "
            f"for a two-year test: "
            f"{len(test_dates)}."
        )

    return (
        requested_start,
        actual_start,
        actual_end,
        test_dates,
    )


def _signal_tie_key(
    signal_date: date,
    symbol: str,
) -> str:
    raw = (
        f"{signal_date.isoformat()}|"
        f"{symbol.strip().upper()}"
    )
    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def choose_signals_without_ranking(
    *,
    signal_date: date,
    qualifying: Sequence[str],
    available_slots: int,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
]:
    """
    Select same-close signals without a market ranking.

    A date-and-symbol hash is only a deterministic collision
    resolver when more qualifying signals exist than open slots.
    It does not use price, return, liquidity, volatility, momentum,
    symbol bonuses, or future data.
    """
    if available_slots < 0:
        raise ValueError(
            "Available slots cannot be negative."
        )

    normalized = sorted(
        {
            symbol.strip().upper()
            for symbol in qualifying
            if symbol.strip()
        },
        key=lambda symbol: (
            _signal_tie_key(
                signal_date,
                symbol,
            ),
            symbol,
        ),
    )
    accepted = tuple(
        normalized[:available_slots]
    )
    deferred = tuple(
        normalized[available_slots:]
    )
    return accepted, deferred


def _position_prices(
    *,
    portfolio: Portfolio,
    row_maps: Mapping[
        str,
        Mapping[date, MarketRow],
    ],
    day: date,
    field: str,
) -> dict[str, float]:
    result: dict[str, float] = {}

    for symbol in portfolio.positions:
        row = row_maps[symbol][day]
        result[symbol] = float(
            getattr(row, field)
        )

    return result


def _apply_rebalance(
    *,
    income: IncomeHolding,
    swing: Portfolio,
    income_price: float,
    swing_market_value: float,
    target_income_weight: float,
    config: BotConfig,
) -> AllocationRebalance:
    rebalance = rebalance_income_allocation(
        income_shares=income.shares,
        income_cost=income.invested_cost,
        swing_cash=swing.cash,
        swing_market_value=(
            swing_market_value
        ),
        income_price=income_price,
        target_income_weight=(
            target_income_weight
        ),
        slippage_rate=(
            config.slippage_rate
        ),
        tax_reserve_rate=(
            config.annual_tax_reserve_rate
        ),
        tolerance=(
            config.allocation_rebalance_tolerance
        ),
        minimum_trade=(
            config.minimum_rebalance_trade
        ),
    )
    income.shares = (
        rebalance.shares_after
    )
    income.invested_cost = (
        rebalance.income_cost_after
    )
    swing.cash = (
        rebalance.swing_cash_after
    )
    swing.tax_reserve_cash += (
        rebalance.tax_reserved
    )
    swing.realized_pnl += (
        rebalance.realized_pnl
    )
    return rebalance


def _flow_metrics(
    points: Sequence[PortfolioPoint],
    *,
    starting_capital: float,
) -> ReturnMetrics:
    returns: list[float] = []
    previous_equity = starting_capital
    previous_contributions = (
        starting_capital
    )

    for point in points:
        contribution = (
            point.total_contributions
            - previous_contributions
        )
        daily_return = (
            (
                point.total_equity
                - contribution
            )
            / previous_equity
            - 1.0
            if previous_equity > 0
            else 0.0
        )
        returns.append(daily_return)
        previous_equity = (
            point.total_equity
        )
        previous_contributions = (
            point.total_contributions
        )

    exposure = (
        sum(
            point.open_positions > 0
            for point in points
        )
        / len(points)
        if points
        else 0.0
    )
    return metrics_from_returns(
        returns,
        exposure=exposure,
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
        return (
            None
            if gross_profit > 0
            else 0.0
        )

    return gross_profit / gross_loss


def _write_equity(
    path: Path,
    points: Sequence[PortfolioPoint],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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
                "OpenPositions",
                "PositionSymbols",
                "PendingSignals",
                "ActiveRisk",
            )
        )

        for point in points:
            writer.writerow(
                (
                    point.date.isoformat(),
                    f"{point.total_equity:.8f}",
                    (
                        f"{point.total_contributions:.8f}"
                    ),
                    f"{point.income_value:.8f}",
                    f"{point.swing_equity:.8f}",
                    f"{point.swing_cash:.8f}",
                    (
                        f"{point.swing_market_value:.8f}"
                    ),
                    f"{point.tax_reserve:.8f}",
                    f"{point.income_weight:.10f}",
                    (
                        f"{point.target_income_weight:.10f}"
                    ),
                    point.open_positions,
                    "|".join(
                        point.position_symbols
                    ),
                    point.pending_signals,
                    f"{point.active_risk:.8f}",
                )
            )


def _write_trades(
    path: Path,
    trades: Sequence[ClosedTrade],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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


def _write_diagnostics(
    path: Path,
    diagnostics: Sequence[
        EntryDiagnostic
    ],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    check_names = (
        "data_ready",
        "price_above_sma",
        "sma_slope_positive",
        "average_volume",
        "breakout_volume",
        "price_breakout",
        "vix_filter",
        "rsi_not_overbought",
        "momentum_trigger",
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "Symbol",
                "PositionOpen",
                "AlreadyPending",
                "SlotAvailable",
                "ShouldEnter",
                "Staged",
                "DeferredForCapacity",
                "Triggers",
                "FailedChecks",
                *check_names,
            )
        )

        for item in diagnostics:
            writer.writerow(
                (
                    item.date.isoformat(),
                    item.symbol,
                    item.position_open,
                    item.already_pending,
                    item.slot_available,
                    item.should_enter,
                    item.staged,
                    item.deferred_for_capacity,
                    "|".join(
                        item.triggers
                    ),
                    "|".join(
                        item.failed_checks
                    ),
                    *(
                        item.checks.get(
                            name,
                            False,
                        )
                        for name in check_names
                    ),
                )
            )


def _write_signal_decisions(
    path: Path,
    decisions: Sequence[
        SignalDecision
    ],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "SignalDate",
                "Symbol",
                "Action",
                "TieKey",
                "AvailableSlots",
            )
        )

        for item in decisions:
            writer.writerow(
                (
                    item.signal_date.isoformat(),
                    item.symbol,
                    item.action,
                    item.tie_key,
                    item.available_slots,
                )
            )


def _write_allocations(
    path: Path,
    snapshots: Sequence[
        AllocationSnapshot
    ],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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
                    (
                        f"{item.target_income_weight:.10f}"
                    ),
                    item.action,
                    (
                        f"{item.before_income_weight:.10f}"
                    ),
                    (
                        f"{item.after_income_weight:.10f}"
                    ),
                    item.target_fully_reached,
                    (
                        f"{item.qdte_market_value_traded:.8f}"
                    ),
                    f"{item.realized_pnl:.8f}",
                    f"{item.tax_reserved:.8f}",
                )
            )


def _format_report(
    result: ThreePositionResult,
) -> str:
    profit_factor = (
        "∞"
        if result.profit_factor is None
        else f"{result.profit_factor:,.3f}"
    )
    qualifying_lines = [
        (
            f"  {symbol}: "
            f"{result.qualifying_bars_by_symbol.get(symbol, 0)}"
        )
        for symbol in result.universe
    ]
    trade_lines = [
        (
            f"  {symbol}: "
            f"{result.trades_by_symbol.get(symbol, 0)}"
        )
        for symbol in result.universe
    ]
    failure_lines = [
        (
            f"  {name}: {count}"
        )
        for name, count in sorted(
            result.failed_check_counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    ]

    return "\n".join(
        (
            "=" * 78,
            (
                "QPX BOT v1.20 — ACTUAL TWO-YEAR "
                "UNRANKED THREE-POSITION BACKTEST"
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
                "Rankings enabled           : "
                f"{result.rankings_enabled}"
            ),
            (
                "Concurrent swing slots     : "
                f"{result.maximum_concurrent_positions}"
            ),
            (
                "Maximum positions observed : "
                f"{result.maximum_observed_positions}"
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
                "All-symbol evaluations     : "
                f"{result.all_symbol_evaluations}"
            ),
            (
                "Qualifying signal bars     : "
                f"{result.qualifying_bars}"
            ),
            (
                "Staged / capacity deferred : "
                f"{result.staged_signals} / "
                f"{result.capacity_deferred_signals}"
            ),
            (
                "Filled entries             : "
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
            "Qualifying bars by symbol:",
            *qualifying_lines,
            "Closed trades by symbol:",
            *trade_lines,
            (
                "Failed checks across all symbols "
                "(counts overlap):"
            ),
            *failure_lines,
            "Allocation anniversary rule : EXACT_DATE",
            "Monthly rankings            : REMOVED",
            (
                "Simultaneous tie-break    : "
                "SHA256_DATE_SYMBOL"
            ),
            "Forced entries              : DISABLED",
            (
                "Symbol-specific bonuses   : "
                f"{result.symbol_bonus_policy}"
            ),
            "Live brokerage              : DISABLED",
            "=" * 78,
            (
                "Downloaded actual daily market data only. "
                "No rankings, synthetic prices, placeholder "
                "distributions, or forced trades."
            ),
            (
                "Historical research does not guarantee "
                "future performance."
            ),
        )
    )


def run_actual_two_year_three_position_backtest(
    *,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    report_root: str | Path = DEFAULT_REPORT_ROOT,
) -> tuple[
    ThreePositionResult,
    RunArtifacts,
]:
    config = BotConfig()
    config.validate()
    policy = load_policy()

    if (
        config.maximum_swing_positions
        != policy.maximum_concurrent_positions
    ):
        raise RuntimeError(
            "Config and multi-swing policy disagree "
            "on the position limit."
        )

    session_config = json.loads(
        SESSION_CONFIG_PATH.read_text(
            encoding="utf-8"
        )
    )
    maximum_gap_atr = float(
        session_config[
            "maximum_gap_atr_multiple"
        ]
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
        policy=policy,
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
        common_dates
    )

    if income_rows[0].date > actual_start:
        raise RuntimeError(
            "QDTE history begins after the test start."
        )

    candles = {
        symbol: _to_candles(
            histories[symbol]
        )
        for symbol in policy.candidates
    }
    indicators: dict[
        str,
        IndicatorSet,
    ] = {
        symbol: calculate_indicators(
            candles[symbol],
            config,
        )
        for symbol in policy.candidates
    }
    row_maps = {
        symbol: {
            row.date: row
            for row in histories[symbol]
        }
        for symbol in policy.candidates
    }
    index_maps = {
        symbol: {
            candle.date: index
            for index, candle in enumerate(
                candles[symbol]
            )
        }
        for symbol in policy.candidates
    }
    income_map = {
        row.date: row
        for row in income_rows
    }
    vix_map = {
        row.date: row.close
        for row in vix_rows
    }
    dividend_map: dict[
        date,
        float,
    ] = {}

    for item in dividend_rows:
        dividend_map[item.date] = (
            dividend_map.get(
                item.date,
                0.0,
            )
            + item.amount
        )

    income = IncomeHolding(
        INCOME_SYMBOL
    )
    first_income = income_map[
        actual_start
    ]
    income.buy(
        cash_amount=config.starting_cash,
        market_price=first_income.open,
        slippage_rate=(
            config.slippage_rate
        ),
    )
    swing = Portfolio(
        config.starting_swing_cash
    )
    initial_target, _ = (
        contribution_allocation(
            0,
            config,
        )
    )
    initial_rebalance = (
        _apply_rebalance(
            income=income,
            swing=swing,
            income_price=(
                first_income.open
            ),
            swing_market_value=0.0,
            target_income_weight=(
                initial_target
            ),
            config=config,
        )
    )
    allocations = [
        AllocationSnapshot(
            date=actual_start,
            event_type="INITIAL_REBALANCE",
            contribution=(
                config.total_starting_capital
            ),
            target_income_weight=(
                initial_target
            ),
            action=(
                initial_rebalance.action
            ),
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
    total_contributions = (
        config.total_starting_capital
    )
    contribution_count = 0
    dividend_event_count = 0
    pending: dict[
        str,
        PendingSignal,
    ] = {}
    diagnostics: list[
        EntryDiagnostic
    ] = []
    decisions: list[
        SignalDecision
    ] = []
    points: list[
        PortfolioPoint
    ] = []
    qualifying_counts = Counter()
    failed_checks = Counter()
    staged_signals = 0
    capacity_deferred = 0
    filled_entries = 0
    gap_rejections = 0
    risk_rejections = 0
    maximum_observed_positions = 0
    current_month = (
        actual_start.year,
        actual_start.month,
    )

    for day in test_dates:
        income_row = income_map[day]
        month_key = (
            day.year,
            day.month,
        )
        dividend_per_share = (
            dividend_map.get(
                day,
                0.0,
            )
        )

        if dividend_per_share > 0:
            swing.cash += (
                income.receive_dividend(
                    dividend_per_share
                )
            )
            dividend_event_count += 1

        if month_key != current_month:
            swing.deposit(
                config.monthly_contribution
            )
            total_contributions += (
                config.monthly_contribution
            )
            contribution_count += 1
            elapsed = (
                elapsed_complete_years(
                    actual_start,
                    day,
                )
            )
            target_income_weight, _ = (
                contribution_allocation(
                    elapsed,
                    config,
                )
            )
            open_prices = (
                _position_prices(
                    portfolio=swing,
                    row_maps=row_maps,
                    day=day,
                    field="open",
                )
            )
            rebalance = _apply_rebalance(
                income=income,
                swing=swing,
                income_price=(
                    income_row.open
                ),
                swing_market_value=(
                    swing.market_value(
                        open_prices
                    )
                ),
                target_income_weight=(
                    target_income_weight
                ),
                config=config,
            )
            allocations.append(
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
            current_month = month_key

        if pending:
            pending_items = sorted(
                pending.values(),
                key=lambda item: (
                    item.tie_key,
                    item.symbol,
                ),
            )
            pending = {}

            for signal in pending_items:
                if (
                    len(swing.positions)
                    >= policy.maximum_concurrent_positions
                ):
                    capacity_deferred += 1
                    decisions.append(
                        SignalDecision(
                            signal_date=(
                                signal.signal_date
                            ),
                            symbol=signal.symbol,
                            action=(
                                "CANCELLED_CAPACITY_AT_OPEN"
                            ),
                            tie_key=(
                                signal.tie_key
                            ),
                            available_slots=0,
                        )
                    )
                    continue

                row = row_maps[
                    signal.symbol
                ][day]
                gap_atr = (
                    abs(
                        row.open
                        - signal.prior_close
                    )
                    / signal.signal_atr
                )

                if (
                    gap_atr
                    > maximum_gap_atr
                ):
                    gap_rejections += 1
                    decisions.append(
                        SignalDecision(
                            signal_date=(
                                signal.signal_date
                            ),
                            symbol=signal.symbol,
                            action=(
                                "REJECTED_OPENING_GAP"
                            ),
                            tie_key=(
                                signal.tie_key
                            ),
                            available_slots=(
                                policy.maximum_concurrent_positions
                                - len(
                                    swing.positions
                                )
                            ),
                        )
                    )
                    continue

                open_prices = (
                    _position_prices(
                        portfolio=swing,
                        row_maps=row_maps,
                        day=day,
                        field="open",
                    )
                )
                combined_equity = (
                    swing.equity(
                        open_prices
                    )
                    + income.market_value(
                        income_row.open
                    )
                )
                sizing = (
                    calculate_position_size(
                        account_equity=(
                            combined_equity
                        ),
                        available_cash=(
                            swing.cash
                        ),
                        entry_price=row.open,
                        atr=(
                            signal.signal_atr
                        ),
                        active_risk=(
                            swing.active_risk()
                        ),
                        config=config,
                        trade_results_r=[
                            trade.result_r
                            for trade in (
                                swing.closed_trades
                            )
                        ],
                    )
                )

                if sizing.is_tradeable:
                    swing.open_position(
                        symbol=signal.symbol,
                        sizing=sizing,
                        entry_date=day,
                        entry_atr=(
                            signal.signal_atr
                        ),
                    )
                    filled_entries += 1
                    decisions.append(
                        SignalDecision(
                            signal_date=(
                                signal.signal_date
                            ),
                            symbol=signal.symbol,
                            action="FILLED",
                            tie_key=(
                                signal.tie_key
                            ),
                            available_slots=(
                                policy.maximum_concurrent_positions
                                - len(
                                    swing.positions
                                )
                            ),
                        )
                    )
                else:
                    risk_rejections += 1
                    decisions.append(
                        SignalDecision(
                            signal_date=(
                                signal.signal_date
                            ),
                            symbol=signal.symbol,
                            action=(
                                "REJECTED_POSITION_SIZING"
                            ),
                            tie_key=(
                                signal.tie_key
                            ),
                            available_slots=(
                                policy.maximum_concurrent_positions
                                - len(
                                    swing.positions
                                )
                            ),
                        )
                    )

        maximum_observed_positions = max(
            maximum_observed_positions,
            len(swing.positions),
        )

        for position in list(
            swing.positions.values()
        ):
            symbol = position.symbol
            index = index_maps[symbol][day]
            current_atr = (
                indicators[symbol].atr[
                    index
                ]
            )

            if current_atr is None:
                continue

            evaluation = evaluate_exit(
                position=position,
                candle=candles[
                    symbol
                ][index],
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
            else:
                position.stop_price = (
                    evaluation.next_stop_price
                )
                position.highest_price = (
                    evaluation.highest_price
                )

        maximum_observed_positions = max(
            maximum_observed_positions,
            len(swing.positions),
        )

        evaluations: dict[
            str,
            EntryEvaluation,
        ] = {}
        qualifying: list[str] = []
        existing_symbols = set(
            swing.positions
        )
        pending_symbols = set(
            pending
        )
        slots_before_staging = max(
            0,
            policy.maximum_concurrent_positions
            - len(existing_symbols)
            - len(pending_symbols),
        )

        for symbol in policy.candidates:
            index = index_maps[
                symbol
            ][day]
            evaluation = evaluate_entry(
                candles=candles[symbol],
                indicators=(
                    indicators[symbol]
                ),
                index=index,
                vix=vix_map[day],
                config=config,
            )
            evaluations[symbol] = (
                evaluation
            )

            for failed in (
                evaluation.failed_checks
            ):
                failed_checks[
                    failed
                ] += 1

            if evaluation.should_enter:
                qualifying_counts[
                    symbol
                ] += 1

                if (
                    symbol
                    not in existing_symbols
                    and symbol
                    not in pending_symbols
                    and day != actual_end
                ):
                    qualifying.append(
                        symbol
                    )

        accepted, deferred = (
            choose_signals_without_ranking(
                signal_date=day,
                qualifying=qualifying,
                available_slots=(
                    slots_before_staging
                ),
            )
        )
        accepted_set = set(
            accepted
        )
        deferred_set = set(
            deferred
        )

        for symbol in accepted:
            index = index_maps[
                symbol
            ][day]
            signal_atr = (
                indicators[symbol].atr[
                    index
                ]
            )

            if (
                signal_atr is None
                or signal_atr <= 0
            ):
                risk_rejections += 1
                continue

            tie_key = _signal_tie_key(
                day,
                symbol,
            )
            pending[symbol] = (
                PendingSignal(
                    symbol=symbol,
                    signal_date=day,
                    signal_atr=(
                        signal_atr
                    ),
                    prior_close=(
                        row_maps[
                            symbol
                        ][day].close
                    ),
                    tie_key=tie_key,
                )
            )
            staged_signals += 1
            decisions.append(
                SignalDecision(
                    signal_date=day,
                    symbol=symbol,
                    action="STAGED",
                    tie_key=tie_key,
                    available_slots=(
                        slots_before_staging
                    ),
                )
            )

        for symbol in deferred:
            capacity_deferred += 1
            decisions.append(
                SignalDecision(
                    signal_date=day,
                    symbol=symbol,
                    action=(
                        "DEFERRED_CAPACITY"
                    ),
                    tie_key=(
                        _signal_tie_key(
                            day,
                            symbol,
                        )
                    ),
                    available_slots=(
                        slots_before_staging
                    ),
                )
            )

        for symbol in policy.candidates:
            evaluation = (
                evaluations[symbol]
            )
            diagnostics.append(
                EntryDiagnostic(
                    date=day,
                    symbol=symbol,
                    position_open=(
                        symbol
                        in existing_symbols
                    ),
                    already_pending=(
                        symbol
                        in pending_symbols
                    ),
                    slot_available=(
                        slots_before_staging
                        > 0
                    ),
                    should_enter=(
                        evaluation.should_enter
                    ),
                    staged=(
                        symbol
                        in accepted_set
                    ),
                    deferred_for_capacity=(
                        symbol
                        in deferred_set
                    ),
                    triggers=(
                        evaluation.triggers
                    ),
                    failed_checks=(
                        evaluation.failed_checks
                    ),
                    checks=(
                        evaluation.checks
                    ),
                )
            )

        close_prices = (
            _position_prices(
                portfolio=swing,
                row_maps=row_maps,
                day=day,
                field="close",
            )
        )
        swing_market_value = (
            swing.market_value(
                close_prices
            )
        )
        swing_equity = swing.equity(
            close_prices
        )
        income_value = (
            income.market_value(
                income_row.close
            )
        )
        total_equity = (
            swing_equity
            + income_value
        )
        elapsed = (
            elapsed_complete_years(
                actual_start,
                day,
            )
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
                total_equity=(
                    total_equity
                ),
                total_contributions=(
                    total_contributions
                ),
                income_value=(
                    income_value
                ),
                swing_equity=(
                    swing_equity
                ),
                swing_cash=swing.cash,
                swing_market_value=(
                    swing_market_value
                ),
                tax_reserve=(
                    swing.tax_reserve_cash
                ),
                income_weight=(
                    income_weight
                ),
                target_income_weight=(
                    target_income_weight
                ),
                open_positions=len(
                    swing.positions
                ),
                position_symbols=tuple(
                    sorted(
                        swing.positions
                    )
                ),
                pending_signals=len(
                    pending
                ),
                active_risk=(
                    swing.active_risk()
                ),
            )
        )

    pending = {}

    for position in list(
        swing.positions.values()
    ):
        final_row = row_maps[
            position.symbol
        ][actual_end]
        swing.close_position(
            symbol=position.symbol,
            exit_price=final_row.close,
            exit_date=actual_end,
            reason="END_OF_TEST",
            config=config,
        )

    final_income_value = (
        income.market_value(
            income_map[
                actual_end
            ].close
        )
    )
    final_swing_equity = (
        swing.equity({})
    )
    final_total = (
        final_income_value
        + final_swing_equity
    )
    final_elapsed = (
        elapsed_complete_years(
            actual_start,
            actual_end,
        )
    )
    final_target, _ = (
        contribution_allocation(
            final_elapsed,
            config,
        )
    )
    final_investable = (
        final_income_value
        + swing.cash
    )
    final_weight = (
        final_income_value
        / final_investable
        if final_investable > 0
        else 0.0
    )
    points[-1] = PortfolioPoint(
        date=actual_end,
        total_equity=final_total,
        total_contributions=(
            total_contributions
        ),
        income_value=(
            final_income_value
        ),
        swing_equity=(
            final_swing_equity
        ),
        swing_cash=swing.cash,
        swing_market_value=0.0,
        tax_reserve=(
            swing.tax_reserve_cash
        ),
        income_weight=(
            final_weight
        ),
        target_income_weight=(
            final_target
        ),
        open_positions=0,
        position_symbols=(),
        pending_signals=0,
        active_risk=0.0,
    )

    metrics = _flow_metrics(
        points,
        starting_capital=(
            config.total_starting_capital
        ),
    )
    trades = tuple(
        swing.closed_trades
    )
    trade_counts = Counter(
        trade.symbol
        for trade in trades
    )
    winners = sum(
        trade.pnl > 0
        for trade in trades
    )
    profit_factor = (
        _profit_factor(
            trades
        )
    )
    net_profit = (
        final_total
        - total_contributions
    )
    result = ThreePositionResult(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        provider=(
            "Yahoo Finance chart endpoint"
        ),
        requested_start=(
            requested_start
        ),
        actual_start=actual_start,
        actual_end=actual_end,
        bars=len(test_dates),
        universe=policy.candidates,
        income_symbol=INCOME_SYMBOL,
        rankings_enabled=False,
        maximum_concurrent_positions=(
            policy.maximum_concurrent_positions
        ),
        maximum_observed_positions=(
            maximum_observed_positions
        ),
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
        ending_equity=final_total,
        net_profit=net_profit,
        return_on_contributed_capital=(
            net_profit
            / total_contributions
            if total_contributions > 0
            else 0.0
        ),
        ending_income_value=(
            final_income_value
        ),
        ending_swing_equity=(
            final_swing_equity
        ),
        ending_swing_cash=(
            swing.cash
        ),
        ending_tax_reserve=(
            swing.tax_reserve_cash
        ),
        ending_income_weight=(
            final_weight
        ),
        total_dividends=(
            income.dividends_received
        ),
        dividend_event_count=(
            dividend_event_count
        ),
        all_symbol_evaluations=(
            len(diagnostics)
        ),
        qualifying_bars=sum(
            qualifying_counts.values()
        ),
        qualifying_bars_by_symbol={
            symbol: qualifying_counts.get(
                symbol,
                0,
            )
            for symbol in policy.candidates
        },
        staged_signals=(
            staged_signals
        ),
        capacity_deferred_signals=(
            capacity_deferred
        ),
        filled_entries=(
            filled_entries
        ),
        gap_rejections=(
            gap_rejections
        ),
        risk_rejections=(
            risk_rejections
        ),
        closed_trades=len(
            trades
        ),
        trades_by_symbol={
            symbol: trade_counts.get(
                symbol,
                0,
            )
            for symbol in policy.candidates
        },
        win_rate=(
            winners / len(trades)
            if trades
            else 0.0
        ),
        profit_factor=(
            profit_factor
        ),
        maximum_drawdown=(
            metrics.maximum_drawdown
        ),
        flow_adjusted_total_return=(
            metrics.total_return
        ),
        flow_adjusted_cagr=(
            metrics.cagr
        ),
        flow_adjusted_volatility=(
            metrics.annualized_volatility
        ),
        sharpe_ratio=(
            metrics.sharpe_ratio
        ),
        sortino_ratio=(
            metrics.sortino_ratio
        ),
        swing_exposure=(
            metrics.exposure
        ),
        failed_check_counts={
            name: count
            for name, count in (
                failed_checks.items()
            )
        },
        forced_entry_indices=None,
        symbol_bonus_policy=(
            policy.symbol_bonus_policy
        ),
        live_broker_enabled=False,
    )

    report_path = (
        report_directory
        / "actual_two_year_three_position_report.txt"
    )
    result_path = (
        report_directory
        / "actual_two_year_three_position_result.json"
    )
    equity_path = (
        report_directory
        / "actual_two_year_three_position_equity.csv"
    )
    trades_path = (
        report_directory
        / "actual_two_year_three_position_trades.csv"
    )
    diagnostic_path = (
        report_directory
        / "entry_filter_diagnostics.csv"
    )
    decisions_path = (
        report_directory
        / "signal_decisions.csv"
    )
    allocation_path = (
        report_directory
        / "allocation_rebalance_log.csv"
    )
    provenance_path = (
        report_directory
        / "actual_two_year_three_position_provenance.json"
    )

    report_path.write_text(
        _format_report(result)
        + "\n",
        encoding="utf-8",
    )
    result_payload = asdict(
        result
    )

    for name in (
        "requested_start",
        "actual_start",
        "actual_end",
    ):
        result_payload[name] = (
            getattr(
                result,
                name,
            ).isoformat()
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
    _write_diagnostics(
        diagnostic_path,
        diagnostics,
    )
    _write_signal_decisions(
        decisions_path,
        decisions,
    )
    _write_allocations(
        allocation_path,
        allocations,
    )
    provenance = {
        "schema_version": 1,
        "generated_at_utc": (
            result.generated_at_utc
        ),
        "actual_data": True,
        "provider": result.provider,
        "requested_backtest_years": 2,
        "requested_download_range": (
            DOWNLOAD_RANGE
        ),
        "actual_start": (
            actual_start.isoformat()
        ),
        "actual_end": (
            actual_end.isoformat()
        ),
        "swing_universe": list(
            policy.candidates
        ),
        "income_symbol": (
            INCOME_SYMBOL
        ),
        "vix_symbol": VIX_SYMBOL,
        "rankings_enabled": False,
        "monthly_selection_engine": None,
        "maximum_concurrent_positions": 3,
        "daily_scan": (
            "all eight ETFs"
        ),
        "simultaneous_signal_tiebreak": (
            policy.simultaneous_signal_tiebreak
        ),
        "tie_break_inputs": (
            "signal date and symbol only"
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
        "portfolio_engine": (
            "qpx_bot.portfolio.Portfolio"
        ),
        "allocation_engine": (
            "qpx_bot.allocation."
            "rebalance_income_allocation"
        ),
        "global_active_risk_cap": (
            config.maximum_active_portfolio_risk
        ),
        "forced_entry_indices": None,
        "symbol_bonus_policy": "none",
        "configuration": asdict(
            config
        ),
        "policy": asdict(
            policy
        ),
        "download_manifest": {
            "path": str(
                manifest_path
            ),
            "sha256": sha256_file(
                manifest_path
            ),
        },
        "outputs": {
            "report": str(
                report_path
            ),
            "result": str(
                result_path
            ),
            "equity": str(
                equity_path
            ),
            "trades": str(
                trades_path
            ),
            "entry_diagnostics": str(
                diagnostic_path
            ),
            "signal_decisions": str(
                decisions_path
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
        entry_diagnostics=(
            diagnostic_path
        ),
        signal_decisions=(
            decisions_path
        ),
        allocations=(
            allocation_path
        ),
        provenance=(
            provenance_path
        ),
        manifest=(
            manifest_path
        ),
    )
    return result, artifacts


def format_console_summary(
    result: ThreePositionResult,
    artifacts: RunArtifacts,
) -> str:
    artifact_lines = [
        f"  {name:<18}: {path}"
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
