#!/usr/bin/env python3
"""Install, test, push, and run the actual two-year portfolio replay."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (
            start,
            *start.parents,
        ):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
BACKUP = (
    ROOT
    / "backups"
    / "qpx_actual_two_year_eight_symbol"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.18.0"\n',
    "qpx_bot/actual_two_year_portfolio.py": '"""Actual two-year, eight-symbol QPX portfolio backtest."""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nfrom collections import Counter\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, timezone\nfrom pathlib import Path\nfrom typing import Any, Mapping, Sequence\n\nfrom qpx_bot.allocation import (\n    AllocationRebalance,\n    rebalance_income_allocation,\n)\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.dividends import DividendEvent\nfrom qpx_bot.hybrid import IncomeHolding\nfrom qpx_bot.indicators import IndicatorSet, calculate_indicators\nfrom qpx_bot.market_calendar import NEW_YORK, latest_completed_session\nfrom qpx_bot.performance import ReturnMetrics, metrics_from_returns\nfrom qpx_bot.portfolio import (\n    ClosedTrade,\n    Portfolio,\n    contribution_allocation,\n)\nfrom qpx_bot.real_data import sha256_file\nfrom qpx_bot.risk import calculate_position_size\nfrom qpx_bot.strategy import evaluate_entry, evaluate_exit\nfrom qpx_bot.symbol_selector import (\n    CandidateMetrics,\n    SelectionConfig,\n    SelectionResult,\n    load_selection_config,\n    rank_candidates,\n)\nfrom qpx_bot.yahoo_data import (\n    DividendRow,\n    MarketRow,\n    extract_dividend_rows,\n    extract_market_rows,\n    fetch_chart,\n)\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nUNIVERSE_CONFIG_PATH = PACKAGE_DIR / "swing_universe.json"\nSESSION_CONFIG_PATH = PACKAGE_DIR / "session_execution_config.json"\nDEFAULT_DATA_ROOT = (\n    PROJECT_ROOT\n    / "research_data"\n    / "qpx_actual_two_year_eight_symbol"\n)\nDEFAULT_REPORT_ROOT = (\n    PROJECT_ROOT\n    / "reports"\n    / "qpx_actual_two_year_eight_symbol"\n)\nREQUIRED_UNIVERSE = (\n    "DIA",\n    "IWM",\n    "QQQ",\n    "SPY",\n    "XLE",\n    "XLF",\n    "XLK",\n    "XLV",\n)\nINCOME_SYMBOL = "QDTE"\nVIX_SYMBOL = "^VIX"\nDOWNLOAD_RANGE = "4y"\nMINIMUM_TEST_BARS = 480\nMAXIMUM_START_DELAY_DAYS = 10\n\n\n@dataclass(frozen=True, slots=True)\nclass PendingSignal:\n    symbol: str\n    signal_date: date\n    signal_atr: float\n    prior_close: float\n\n\n@dataclass(frozen=True, slots=True)\nclass SelectionSnapshot:\n    decision_date: date\n    winner: str\n    active_symbol: str\n    locked: bool\n    latest_input_date: date\n    rankings: tuple[CandidateMetrics, ...]\n\n\n@dataclass(frozen=True, slots=True)\nclass AllocationSnapshot:\n    date: date\n    event_type: str\n    contribution: float\n    target_income_weight: float\n    action: str\n    before_income_weight: float\n    after_income_weight: float\n    target_fully_reached: bool\n    qdte_market_value_traded: float\n    realized_pnl: float\n    tax_reserved: float\n\n\n@dataclass(frozen=True, slots=True)\nclass PortfolioPoint:\n    date: date\n    total_equity: float\n    total_contributions: float\n    income_value: float\n    swing_equity: float\n    swing_cash: float\n    swing_market_value: float\n    tax_reserve: float\n    income_weight: float\n    target_income_weight: float\n    monthly_winner: str\n    active_symbol: str\n    position_symbol: str | None\n\n\n@dataclass(frozen=True, slots=True)\nclass ActualTwoYearResult:\n    generated_at_utc: str\n    provider: str\n    requested_start: date\n    actual_start: date\n    actual_end: date\n    bars: int\n    universe: tuple[str, ...]\n    income_symbol: str\n    starting_income_cash: float\n    starting_swing_cash: float\n    starting_total_capital: float\n    monthly_contribution: float\n    contribution_count: int\n    total_contributions: float\n    ending_equity: float\n    net_profit: float\n    return_on_contributed_capital: float\n    ending_income_value: float\n    ending_swing_equity: float\n    ending_swing_cash: float\n    ending_tax_reserve: float\n    ending_income_weight: float\n    total_dividends: float\n    dividend_event_count: int\n    signal_count: int\n    filled_entries: int\n    gap_rejections: int\n    risk_rejections: int\n    closed_trades: int\n    win_rate: float\n    profit_factor: float | None\n    maximum_drawdown: float\n    flow_adjusted_total_return: float\n    flow_adjusted_cagr: float\n    flow_adjusted_volatility: float\n    sharpe_ratio: float\n    sortino_ratio: float\n    swing_exposure: float\n    selection_months: int\n    winner_counts: Mapping[str, int]\n    forced_entry_indices: None\n    symbol_bonus_policy: str\n    live_broker_enabled: bool\n\n\n@dataclass(frozen=True, slots=True)\nclass RunArtifacts:\n    report: Path\n    result: Path\n    equity: Path\n    trades: Path\n    selections: Path\n    allocations: Path\n    provenance: Path\n    manifest: Path\n\n\ndef subtract_years(day: date, years: int) -> date:\n    if years < 1:\n        raise ValueError("Years must be positive.")\n\n    try:\n        return day.replace(year=day.year - years)\n    except ValueError:\n        return day.replace(\n            year=day.year - years,\n            month=2,\n            day=28,\n        )\n\n\ndef _elapsed_years(start: date, current: date) -> int:\n    months = (\n        (current.year - start.year) * 12\n        + current.month\n        - start.month\n    )\n    return max(0, months // 12)\n\n\ndef _safe_symbol(symbol: str) -> str:\n    return symbol.replace("^", "").replace("/", "_")\n\n\ndef _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n    temporary.write_text(\n        json.dumps(\n            payload,\n            indent=2,\n            sort_keys=True,\n            allow_nan=False,\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n\n\ndef _write_market_rows(\n    path: Path,\n    rows: Sequence[MarketRow],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n\n    with temporary.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Date",\n                "Open",\n                "High",\n                "Low",\n                "Close",\n                "AdjClose",\n                "Volume",\n            )\n        )\n\n        for row in rows:\n            writer.writerow(\n                (\n                    row.date.isoformat(),\n                    f"{row.open:.8f}",\n                    f"{row.high:.8f}",\n                    f"{row.low:.8f}",\n                    f"{row.close:.8f}",\n                    f"{row.adjusted_close:.8f}",\n                    row.volume,\n                )\n            )\n\n    temporary.replace(path)\n\n\ndef _write_dividend_rows(\n    path: Path,\n    rows: Sequence[DividendRow],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(path.suffix + ".tmp")\n\n    with temporary.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(("Date", "Dividend"))\n\n        for row in rows:\n            writer.writerow(\n                (\n                    row.date.isoformat(),\n                    f"{row.amount:.8f}",\n                )\n            )\n\n    temporary.replace(path)\n\n\ndef _download_actual_inputs(\n    *,\n    data_directory: Path,\n    selection_config: SelectionConfig,\n) -> tuple[\n    dict[str, list[MarketRow]],\n    list[MarketRow],\n    list[MarketRow],\n    list[DividendRow],\n    Path,\n]:\n    data_directory.mkdir(parents=True, exist_ok=True)\n    histories: dict[str, list[MarketRow]] = {}\n    paths: dict[str, Path] = {}\n    raw_results: dict[str, Mapping[str, Any]] = {}\n\n    symbols = (\n        *selection_config.candidates,\n        INCOME_SYMBOL,\n        VIX_SYMBOL,\n    )\n\n    for symbol in symbols:\n        print(\n            f"Downloading actual daily history: {symbol}"\n        )\n        raw = fetch_chart(\n            symbol,\n            range_name=DOWNLOAD_RANGE,\n        )\n        rows = extract_market_rows(raw)\n\n        if not rows:\n            raise RuntimeError(\n                f"No valid actual rows were returned for {symbol}."\n            )\n\n        raw_results[symbol] = raw\n        path = (\n            data_directory\n            / f"{_safe_symbol(symbol)}.csv"\n        )\n        _write_market_rows(path, rows)\n        paths[symbol] = path\n\n        if symbol in selection_config.candidates:\n            histories[symbol] = rows\n\n    income_rows = extract_market_rows(\n        raw_results[INCOME_SYMBOL]\n    )\n    vix_rows = extract_market_rows(\n        raw_results[VIX_SYMBOL]\n    )\n    dividends = extract_dividend_rows(\n        raw_results[INCOME_SYMBOL]\n    )\n\n    if not dividends:\n        raise RuntimeError(\n            "The provider returned no actual QDTE "\n            "distribution events."\n        )\n\n    dividend_path = (\n        data_directory / "QDTE_DIVIDENDS.csv"\n    )\n    _write_dividend_rows(\n        dividend_path,\n        dividends,\n    )\n    paths["QDTE_DIVIDENDS"] = dividend_path\n\n    manifest_path = (\n        data_directory / "DOWNLOAD_MANIFEST.json"\n    )\n    manifest = {\n        "schema_version": 1,\n        "provider": "Yahoo Finance chart endpoint",\n        "downloaded_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "requested_range": DOWNLOAD_RANGE,\n        "interval": "1d",\n        "actual_data": True,\n        "symbols": {\n            "swing_universe": list(\n                selection_config.candidates\n            ),\n            "income": INCOME_SYMBOL,\n            "vix": VIX_SYMBOL,\n        },\n        "rows": {\n            symbol: len(\n                histories[symbol]\n                if symbol in histories\n                else (\n                    income_rows\n                    if symbol == INCOME_SYMBOL\n                    else vix_rows\n                )\n            )\n            for symbol in symbols\n        },\n        "dividend_events": len(dividends),\n        "date_ranges": {\n            symbol: {\n                "first": (\n                    histories[symbol][0].date.isoformat()\n                    if symbol in histories\n                    else (\n                        income_rows[0].date.isoformat()\n                        if symbol == INCOME_SYMBOL\n                        else vix_rows[0].date.isoformat()\n                    )\n                ),\n                "last": (\n                    histories[symbol][-1].date.isoformat()\n                    if symbol in histories\n                    else (\n                        income_rows[-1].date.isoformat()\n                        if symbol == INCOME_SYMBOL\n                        else vix_rows[-1].date.isoformat()\n                    )\n                ),\n            }\n            for symbol in symbols\n        },\n        "files": {\n            symbol: {\n                "path": str(path),\n                "sha256": sha256_file(path),\n            }\n            for symbol, path in paths.items()\n        },\n        "notice": (\n            "No synthetic OHLCV, distributions, VIX values, "\n            "signals, or forced entries are used."\n        ),\n    }\n    _atomic_json(manifest_path, manifest)\n\n    return (\n        histories,\n        income_rows,\n        vix_rows,\n        dividends,\n        manifest_path,\n    )\n\n\ndef _to_candles(\n    rows: Sequence[MarketRow],\n) -> list[Candle]:\n    return [\n        Candle(\n            date=row.date,\n            open=row.open,\n            high=row.high,\n            low=row.low,\n            close=row.close,\n            volume=row.volume,\n        )\n        for row in rows\n    ]\n\n\ndef _common_dates(\n    histories: Mapping[str, Sequence[MarketRow]],\n    income_rows: Sequence[MarketRow],\n    vix_rows: Sequence[MarketRow],\n) -> list[date]:\n    date_sets = [\n        {row.date for row in histories[symbol]}\n        for symbol in REQUIRED_UNIVERSE\n    ]\n    date_sets.extend(\n        (\n            {row.date for row in income_rows},\n            {row.date for row in vix_rows},\n        )\n    )\n    common = set.intersection(*date_sets)\n    return sorted(common)\n\n\ndef _completed_session() -> date:\n    now = datetime.now(tz=NEW_YORK)\n    session, _ = latest_completed_session(now)\n    return session\n\n\ndef _test_window(\n    *,\n    common_dates: Sequence[date],\n) -> tuple[date, date, date, list[date]]:\n    if not common_dates:\n        raise RuntimeError(\n            "The downloaded histories have no common sessions."\n        )\n\n    expected_end = _completed_session()\n    eligible = [\n        day\n        for day in common_dates\n        if day <= expected_end\n    ]\n\n    if not eligible:\n        raise RuntimeError(\n            "Actual data does not contain a completed session."\n        )\n\n    actual_end = eligible[-1]\n\n    if (expected_end - actual_end).days > 4:\n        raise RuntimeError(\n            "The common actual-data session is stale. "\n            f"Expected near {expected_end}; latest is {actual_end}."\n        )\n\n    requested_start = subtract_years(\n        actual_end,\n        2,\n    )\n    test_dates = [\n        day\n        for day in eligible\n        if requested_start <= day <= actual_end\n    ]\n\n    if not test_dates:\n        raise RuntimeError(\n            "No common sessions exist in the requested "\n            "two-year window."\n        )\n\n    actual_start = test_dates[0]\n\n    if (\n        actual_start - requested_start\n    ).days > MAXIMUM_START_DELAY_DAYS:\n        raise RuntimeError(\n            "Actual data does not reach the requested "\n            "two-year boundary."\n        )\n\n    if len(test_dates) < MINIMUM_TEST_BARS:\n        raise RuntimeError(\n            "Too few common daily sessions for a genuine "\n            f"two-year test: {len(test_dates)}; "\n            f"{MINIMUM_TEST_BARS} required."\n        )\n\n    return (\n        requested_start,\n        actual_start,\n        actual_end,\n        test_dates,\n    )\n\n\ndef rank_as_of(\n    *,\n    decision_date: date,\n    histories: Mapping[str, Sequence[MarketRow]],\n    selection_config: SelectionConfig,\n) -> SelectionResult:\n    """\n    Rank using only observations strictly before the decision date.\n    """\n    point_in_time = {\n        symbol: [\n            row\n            for row in histories[symbol]\n            if row.date < decision_date\n        ]\n        for symbol in selection_config.candidates\n    }\n    result = rank_candidates(\n        point_in_time,\n        selection_config,\n    )\n\n    if result.latest_market_date >= decision_date:\n        raise RuntimeError(\n            "Selection look-ahead guard failed."\n        )\n\n    return result\n\n\ndef _selection_snapshot(\n    *,\n    decision_date: date,\n    result: SelectionResult,\n    active_symbol: str,\n    locked: bool,\n) -> SelectionSnapshot:\n    return SelectionSnapshot(\n        decision_date=decision_date,\n        winner=result.selected_symbol,\n        active_symbol=active_symbol,\n        locked=locked,\n        latest_input_date=result.latest_market_date,\n        rankings=result.rankings,\n    )\n\n\ndef _apply_rebalance(\n    *,\n    income: IncomeHolding,\n    swing_portfolio: Portfolio,\n    income_price: float,\n    swing_market_value: float,\n    target_income_weight: float,\n    config: BotConfig,\n) -> AllocationRebalance:\n    rebalance = rebalance_income_allocation(\n        income_shares=income.shares,\n        income_cost=income.invested_cost,\n        swing_cash=swing_portfolio.cash,\n        swing_market_value=swing_market_value,\n        income_price=income_price,\n        target_income_weight=target_income_weight,\n        slippage_rate=config.slippage_rate,\n        tax_reserve_rate=config.annual_tax_reserve_rate,\n        tolerance=config.allocation_rebalance_tolerance,\n        minimum_trade=config.minimum_rebalance_trade,\n    )\n    income.shares = rebalance.shares_after\n    income.invested_cost = (\n        rebalance.income_cost_after\n    )\n    swing_portfolio.cash = (\n        rebalance.swing_cash_after\n    )\n    swing_portfolio.tax_reserve_cash += (\n        rebalance.tax_reserved\n    )\n    swing_portfolio.realized_pnl += (\n        rebalance.realized_pnl\n    )\n    return rebalance\n\n\ndef _flow_adjusted_metrics(\n    points: Sequence[PortfolioPoint],\n    *,\n    starting_capital: float,\n) -> tuple[ReturnMetrics, tuple[float, ...]]:\n    returns: list[float] = []\n    previous_equity = starting_capital\n    previous_contributions = starting_capital\n\n    for point in points:\n        contribution = (\n            point.total_contributions\n            - previous_contributions\n        )\n        daily_return = (\n            (\n                point.total_equity - contribution\n            )\n            / previous_equity\n            - 1.0\n            if previous_equity > 0\n            else 0.0\n        )\n        returns.append(daily_return)\n        previous_equity = point.total_equity\n        previous_contributions = (\n            point.total_contributions\n        )\n\n    exposure = (\n        sum(\n            point.swing_market_value > 0\n            for point in points\n        )\n        / len(points)\n        if points\n        else 0.0\n    )\n    return (\n        metrics_from_returns(\n            returns,\n            exposure=exposure,\n        ),\n        tuple(returns),\n    )\n\n\ndef _profit_factor(\n    trades: Sequence[ClosedTrade],\n) -> float | None:\n    gross_profit = sum(\n        trade.pnl\n        for trade in trades\n        if trade.pnl > 0\n    )\n    gross_loss = -sum(\n        trade.pnl\n        for trade in trades\n        if trade.pnl < 0\n    )\n\n    if gross_loss == 0:\n        return None if gross_profit > 0 else 0.0\n\n    return gross_profit / gross_loss\n\n\ndef _write_equity(\n    path: Path,\n    points: Sequence[PortfolioPoint],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Date",\n                "TotalEquity",\n                "TotalContributions",\n                "IncomeValue",\n                "SwingEquity",\n                "SwingCash",\n                "SwingMarketValue",\n                "TaxReserve",\n                "IncomeWeight",\n                "TargetIncomeWeight",\n                "MonthlyWinner",\n                "ActiveSymbol",\n                "PositionSymbol",\n            )\n        )\n\n        for point in points:\n            writer.writerow(\n                (\n                    point.date.isoformat(),\n                    f"{point.total_equity:.8f}",\n                    f"{point.total_contributions:.8f}",\n                    f"{point.income_value:.8f}",\n                    f"{point.swing_equity:.8f}",\n                    f"{point.swing_cash:.8f}",\n                    f"{point.swing_market_value:.8f}",\n                    f"{point.tax_reserve:.8f}",\n                    f"{point.income_weight:.10f}",\n                    f"{point.target_income_weight:.10f}",\n                    point.monthly_winner,\n                    point.active_symbol,\n                    point.position_symbol or "",\n                )\n            )\n\n\ndef _write_trades(\n    path: Path,\n    trades: Sequence[ClosedTrade],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Symbol",\n                "EntryDate",\n                "ExitDate",\n                "Shares",\n                "EntryPrice",\n                "ExitPrice",\n                "PnL",\n                "TaxReserved",\n                "ExitReason",\n                "ResultR",\n            )\n        )\n\n        for trade in trades:\n            writer.writerow(\n                (\n                    trade.symbol,\n                    trade.entry_date.isoformat(),\n                    trade.exit_date.isoformat(),\n                    trade.shares,\n                    f"{trade.entry_price:.8f}",\n                    f"{trade.exit_price:.8f}",\n                    f"{trade.pnl:.8f}",\n                    f"{trade.tax_reserved:.8f}",\n                    trade.reason,\n                    f"{trade.result_r:.8f}",\n                )\n            )\n\n\ndef _write_selections(\n    path: Path,\n    snapshots: Sequence[SelectionSnapshot],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "DecisionDate",\n                "LatestInputDate",\n                "MonthlyWinner",\n                "ActiveSymbol",\n                "Locked",\n                "Symbol",\n                "Rank",\n                "Score",\n                "Eligible",\n                "ShortReturn",\n                "LongReturn",\n                "TrendDistance",\n                "AnnualizedVolatility",\n                "MaximumDrawdown",\n                "MedianDollarVolume",\n                "RejectionReason",\n            )\n        )\n\n        for snapshot in snapshots:\n            for ranking in snapshot.rankings:\n                writer.writerow(\n                    (\n                        snapshot.decision_date.isoformat(),\n                        snapshot.latest_input_date.isoformat(),\n                        snapshot.winner,\n                        snapshot.active_symbol,\n                        snapshot.locked,\n                        ranking.symbol,\n                        ranking.rank or "",\n                        f"{ranking.score:.10f}",\n                        ranking.eligible,\n                        f"{ranking.short_return:.10f}",\n                        f"{ranking.long_return:.10f}",\n                        f"{ranking.trend_distance:.10f}",\n                        (\n                            f"{ranking.annualized_volatility:.10f}"\n                        ),\n                        f"{ranking.maximum_drawdown:.10f}",\n                        (\n                            f"{ranking.median_dollar_volume:.4f}"\n                        ),\n                        ranking.rejection_reason or "",\n                    )\n                )\n\n\ndef _write_allocations(\n    path: Path,\n    snapshots: Sequence[AllocationSnapshot],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Date",\n                "EventType",\n                "Contribution",\n                "TargetIncomeWeight",\n                "Action",\n                "BeforeIncomeWeight",\n                "AfterIncomeWeight",\n                "TargetFullyReached",\n                "QDTEMarketValueTraded",\n                "RealizedPnL",\n                "TaxReserved",\n            )\n        )\n\n        for item in snapshots:\n            writer.writerow(\n                (\n                    item.date.isoformat(),\n                    item.event_type,\n                    f"{item.contribution:.8f}",\n                    f"{item.target_income_weight:.10f}",\n                    item.action,\n                    f"{item.before_income_weight:.10f}",\n                    f"{item.after_income_weight:.10f}",\n                    item.target_fully_reached,\n                    f"{item.qdte_market_value_traded:.8f}",\n                    f"{item.realized_pnl:.8f}",\n                    f"{item.tax_reserved:.8f}",\n                )\n            )\n\n\ndef _format_report(\n    result: ActualTwoYearResult,\n) -> str:\n    profit_factor = (\n        "∞"\n        if result.profit_factor is None\n        else f"{result.profit_factor:,.3f}"\n    )\n    winner_lines = [\n        f"  {symbol}: {result.winner_counts.get(symbol, 0)}"\n        for symbol in result.universe\n    ]\n\n    return "\\n".join(\n        (\n            "=" * 78,\n            (\n                "QPX BOT v1.18 — ACTUAL TWO-YEAR "\n                "EIGHT-SYMBOL PORTFOLIO BACKTEST"\n            ),\n            "=" * 78,\n            (\n                "Actual provider            : "\n                f"{result.provider}"\n            ),\n            (\n                "Actual period              : "\n                f"{result.actual_start} to "\n                f"{result.actual_end}"\n            ),\n            (\n                "Common daily sessions      : "\n                f"{result.bars}"\n            ),\n            (\n                "Swing universe             : "\n                + ", ".join(result.universe)\n            ),\n            (\n                "Income sleeve              : "\n                f"{result.income_symbol}"\n            ),\n            (\n                "Initial QDTE seed          : "\n                f"${result.starting_income_cash:,.2f}"\n            ),\n            (\n                "Initial swing liquidity    : "\n                f"${result.starting_swing_cash:,.2f}"\n            ),\n            (\n                "Initial total capital      : "\n                f"${result.starting_total_capital:,.2f}"\n            ),\n            (\n                "Monthly contribution       : "\n                f"${result.monthly_contribution:,.2f}"\n            ),\n            (\n                "Monthly contributions made : "\n                f"{result.contribution_count}"\n            ),\n            (\n                "Total contributed capital  : "\n                f"${result.total_contributions:,.2f}"\n            ),\n            (\n                "Ending account equity      : "\n                f"${result.ending_equity:,.2f}"\n            ),\n            (\n                "Net profit                 : "\n                f"${result.net_profit:,.2f}"\n            ),\n            (\n                "Return on contributions    : "\n                f"{result.return_on_contributed_capital:.2%}"\n            ),\n            (\n                "Flow-adjusted total return : "\n                f"{result.flow_adjusted_total_return:.2%}"\n            ),\n            (\n                "Flow-adjusted CAGR         : "\n                f"{result.flow_adjusted_cagr:.2%}"\n            ),\n            (\n                "Maximum drawdown           : "\n                f"{result.maximum_drawdown:.2%}"\n            ),\n            (\n                "Annualized volatility      : "\n                f"{result.flow_adjusted_volatility:.2%}"\n            ),\n            (\n                "Sharpe / Sortino           : "\n                f"{result.sharpe_ratio:,.3f} / "\n                f"{result.sortino_ratio:,.3f}"\n            ),\n            (\n                "Swing exposure             : "\n                f"{result.swing_exposure:.2%}"\n            ),\n            (\n                "Ending QDTE value          : "\n                f"${result.ending_income_value:,.2f}"\n            ),\n            (\n                "Ending QDTE weight         : "\n                f"{result.ending_income_weight:.2%}"\n            ),\n            (\n                "Ending swing equity        : "\n                f"${result.ending_swing_equity:,.2f}"\n            ),\n            (\n                "Ending swing cash          : "\n                f"${result.ending_swing_cash:,.2f}"\n            ),\n            (\n                "Tax reserve cash           : "\n                f"${result.ending_tax_reserve:,.2f}"\n            ),\n            (\n                "Actual QDTE distributions  : "\n                f"${result.total_dividends:,.2f} "\n                f"({result.dividend_event_count} events)"\n            ),\n            (\n                "Signals / filled entries   : "\n                f"{result.signal_count} / "\n                f"{result.filled_entries}"\n            ),\n            (\n                "Gap / risk rejections      : "\n                f"{result.gap_rejections} / "\n                f"{result.risk_rejections}"\n            ),\n            (\n                "Closed swing trades        : "\n                f"{result.closed_trades}"\n            ),\n            (\n                "Win rate / profit factor   : "\n                f"{result.win_rate:.2%} / "\n                f"{profit_factor}"\n            ),\n            (\n                "Monthly ranking decisions  : "\n                f"{result.selection_months}"\n            ),\n            "Monthly winner counts:",\n            *winner_lines,\n            "Forced entries              : DISABLED",\n            (\n                "Symbol-specific bonuses    : "\n                f"{result.symbol_bonus_policy}"\n            ),\n            "Live brokerage              : DISABLED",\n            "=" * 78,\n            (\n                "Downloaded actual daily market data only. "\n                "No synthetic prices, distributions, VIX "\n                "values, signals, or forced trades."\n            ),\n            (\n                "Historical research does not guarantee "\n                "future performance."\n            ),\n        )\n    )\n\n\ndef run_actual_two_year_eight_symbol_backtest(\n    *,\n    data_root: str | Path = DEFAULT_DATA_ROOT,\n    report_root: str | Path = DEFAULT_REPORT_ROOT,\n) -> tuple[ActualTwoYearResult, RunArtifacts]:\n    config = BotConfig()\n    config.validate()\n    selection_config = load_selection_config(\n        UNIVERSE_CONFIG_PATH\n    )\n\n    if selection_config.candidates != REQUIRED_UNIVERSE:\n        raise RuntimeError(\n            "The configured swing universe is not the "\n            "required eight-symbol set."\n        )\n\n    if selection_config.symbol_bonus_policy != "none":\n        raise RuntimeError(\n            "Symbol bonuses are prohibited."\n        )\n\n    session_payload = json.loads(\n        SESSION_CONFIG_PATH.read_text(\n            encoding="utf-8"\n        )\n    )\n    maximum_gap_atr = float(\n        session_payload[\n            "maximum_gap_atr_multiple"\n        ]\n    )\n\n    if maximum_gap_atr <= 0:\n        raise RuntimeError(\n            "Opening-gap ATR limit must be positive."\n        )\n\n    run_id = datetime.now().strftime(\n        "%Y%m%d_%H%M%S"\n    )\n    data_directory = (\n        Path(data_root).expanduser().resolve()\n        / run_id\n    )\n    report_directory = (\n        Path(report_root).expanduser().resolve()\n        / run_id\n    )\n    report_directory.mkdir(\n        parents=True,\n        exist_ok=True,\n    )\n\n    (\n        histories,\n        income_rows,\n        vix_rows,\n        dividend_rows,\n        manifest_path,\n    ) = _download_actual_inputs(\n        data_directory=data_directory,\n        selection_config=selection_config,\n    )\n    common_dates = _common_dates(\n        histories,\n        income_rows,\n        vix_rows,\n    )\n    (\n        requested_start,\n        actual_start,\n        actual_end,\n        test_dates,\n    ) = _test_window(\n        common_dates=common_dates,\n    )\n\n    if income_rows[0].date > actual_start:\n        raise RuntimeError(\n            "QDTE actual history begins after the "\n            "two-year test start."\n        )\n\n    selection_probe = rank_as_of(\n        decision_date=actual_start,\n        histories=histories,\n        selection_config=selection_config,\n    )\n\n    if (\n        selection_probe.latest_market_date\n        >= actual_start\n    ):\n        raise RuntimeError(\n            "Initial monthly selection contains future data."\n        )\n\n    candles = {\n        symbol: _to_candles(histories[symbol])\n        for symbol in REQUIRED_UNIVERSE\n    }\n    indicators: dict[str, IndicatorSet] = {\n        symbol: calculate_indicators(\n            candles[symbol],\n            config,\n        )\n        for symbol in REQUIRED_UNIVERSE\n    }\n    row_maps = {\n        symbol: {\n            row.date: row\n            for row in histories[symbol]\n        }\n        for symbol in REQUIRED_UNIVERSE\n    }\n    index_maps = {\n        symbol: {\n            candle.date: index\n            for index, candle in enumerate(\n                candles[symbol]\n            )\n        }\n        for symbol in REQUIRED_UNIVERSE\n    }\n    income_map = {\n        row.date: row\n        for row in income_rows\n    }\n    vix_map = {\n        row.date: row.close\n        for row in vix_rows\n    }\n    dividend_map: dict[date, float] = {}\n\n    for dividend in dividend_rows:\n        dividend_map[dividend.date] = (\n            dividend_map.get(\n                dividend.date,\n                0.0,\n            )\n            + dividend.amount\n        )\n\n    first_income = income_map[actual_start]\n    income = IncomeHolding(INCOME_SYMBOL)\n    income.buy(\n        cash_amount=config.starting_cash,\n        market_price=first_income.open,\n        slippage_rate=config.slippage_rate,\n    )\n    swing = Portfolio(\n        config.starting_swing_cash\n    )\n    initial_target, _ = contribution_allocation(\n        0,\n        config,\n    )\n    initial_rebalance = _apply_rebalance(\n        income=income,\n        swing_portfolio=swing,\n        income_price=first_income.open,\n        swing_market_value=0.0,\n        target_income_weight=initial_target,\n        config=config,\n    )\n    total_contributions = (\n        config.total_starting_capital\n    )\n    contribution_count = 0\n    allocation_snapshots = [\n        AllocationSnapshot(\n            date=actual_start,\n            event_type="INITIAL_REBALANCE",\n            contribution=(\n                config.total_starting_capital\n            ),\n            target_income_weight=initial_target,\n            action=initial_rebalance.action,\n            before_income_weight=(\n                initial_rebalance.before_income_weight\n            ),\n            after_income_weight=(\n                initial_rebalance.after_income_weight\n            ),\n            target_fully_reached=(\n                initial_rebalance.target_fully_reached\n            ),\n            qdte_market_value_traded=(\n                initial_rebalance.market_value_traded\n            ),\n            realized_pnl=(\n                initial_rebalance.realized_pnl\n            ),\n            tax_reserved=(\n                initial_rebalance.tax_reserved\n            ),\n        )\n    ]\n\n    initial_selection = selection_probe\n    monthly_winner = (\n        initial_selection.selected_symbol\n    )\n    active_symbol = monthly_winner\n    current_month = (\n        actual_start.year,\n        actual_start.month,\n    )\n    selection_snapshots = [\n        _selection_snapshot(\n            decision_date=actual_start,\n            result=initial_selection,\n            active_symbol=active_symbol,\n            locked=False,\n        )\n    ]\n    pending: PendingSignal | None = None\n    points: list[PortfolioPoint] = []\n    signal_count = 0\n    filled_entries = 0\n    gap_rejections = 0\n    risk_rejections = 0\n    dividend_event_count = 0\n\n    for day in test_dates:\n        income_row = income_map[day]\n        current_month_key = (\n            day.year,\n            day.month,\n        )\n\n        dividend_per_share = dividend_map.get(\n            day,\n            0.0,\n        )\n\n        if dividend_per_share > 0:\n            dividend_cash = (\n                income.receive_dividend(\n                    dividend_per_share\n                )\n            )\n            swing.cash += dividend_cash\n            dividend_event_count += 1\n\n        if current_month_key != current_month:\n            selection = rank_as_of(\n                decision_date=day,\n                histories=histories,\n                selection_config=selection_config,\n            )\n            monthly_winner = (\n                selection.selected_symbol\n            )\n            locked = (\n                bool(swing.positions)\n                or pending is not None\n            )\n\n            if not locked:\n                active_symbol = monthly_winner\n\n            selection_snapshots.append(\n                _selection_snapshot(\n                    decision_date=day,\n                    result=selection,\n                    active_symbol=active_symbol,\n                    locked=locked,\n                )\n            )\n\n            swing.deposit(\n                config.monthly_contribution\n            )\n            total_contributions += (\n                config.monthly_contribution\n            )\n            contribution_count += 1\n            elapsed = _elapsed_years(\n                actual_start,\n                day,\n            )\n            target_income_weight, _ = (\n                contribution_allocation(\n                    elapsed,\n                    config,\n                )\n            )\n            open_position = (\n                next(\n                    iter(\n                        swing.positions.values()\n                    ),\n                    None,\n                )\n            )\n            swing_market_value_open = (\n                open_position.shares\n                * row_maps[\n                    open_position.symbol\n                ][day].open\n                if open_position is not None\n                else 0.0\n            )\n            rebalance = _apply_rebalance(\n                income=income,\n                swing_portfolio=swing,\n                income_price=income_row.open,\n                swing_market_value=(\n                    swing_market_value_open\n                ),\n                target_income_weight=(\n                    target_income_weight\n                ),\n                config=config,\n            )\n            allocation_snapshots.append(\n                AllocationSnapshot(\n                    date=day,\n                    event_type=(\n                        "MONTHLY_CONTRIBUTION_REBALANCE"\n                    ),\n                    contribution=(\n                        config.monthly_contribution\n                    ),\n                    target_income_weight=(\n                        target_income_weight\n                    ),\n                    action=rebalance.action,\n                    before_income_weight=(\n                        rebalance.before_income_weight\n                    ),\n                    after_income_weight=(\n                        rebalance.after_income_weight\n                    ),\n                    target_fully_reached=(\n                        rebalance.target_fully_reached\n                    ),\n                    qdte_market_value_traded=(\n                        rebalance.market_value_traded\n                    ),\n                    realized_pnl=(\n                        rebalance.realized_pnl\n                    ),\n                    tax_reserved=(\n                        rebalance.tax_reserved\n                    ),\n                )\n            )\n            current_month = current_month_key\n\n        if pending is not None:\n            row = row_maps[pending.symbol][day]\n            gap_atr = (\n                abs(\n                    row.open\n                    - pending.prior_close\n                )\n                / pending.signal_atr\n            )\n\n            if gap_atr > maximum_gap_atr:\n                gap_rejections += 1\n                pending = None\n            else:\n                combined_equity = (\n                    swing.equity({})\n                    + income.market_value(\n                        income_row.open\n                    )\n                )\n                sizing = calculate_position_size(\n                    account_equity=combined_equity,\n                    available_cash=swing.cash,\n                    entry_price=row.open,\n                    atr=pending.signal_atr,\n                    active_risk=swing.active_risk(),\n                    config=config,\n                    trade_results_r=[\n                        trade.result_r\n                        for trade in swing.closed_trades\n                    ],\n                )\n\n                if sizing.is_tradeable:\n                    swing.open_position(\n                        symbol=pending.symbol,\n                        sizing=sizing,\n                        entry_date=day,\n                        entry_atr=(\n                            pending.signal_atr\n                        ),\n                    )\n                    active_symbol = (\n                        pending.symbol\n                    )\n                    filled_entries += 1\n                else:\n                    risk_rejections += 1\n\n                pending = None\n\n            if (\n                not swing.positions\n                and pending is None\n            ):\n                active_symbol = monthly_winner\n\n        open_position = next(\n            iter(swing.positions.values()),\n            None,\n        )\n\n        if open_position is not None:\n            symbol = open_position.symbol\n            index = index_maps[symbol][day]\n            current_atr = (\n                indicators[symbol].atr[index]\n            )\n\n            if current_atr is not None:\n                evaluation = evaluate_exit(\n                    position=open_position,\n                    candle=candles[symbol][index],\n                    current_atr=current_atr,\n                    config=config,\n                )\n\n                if evaluation.should_exit:\n                    assert (\n                        evaluation.exit_price\n                        is not None\n                    )\n                    swing.close_position(\n                        symbol=symbol,\n                        exit_price=(\n                            evaluation.exit_price\n                        ),\n                        exit_date=day,\n                        reason=(\n                            evaluation.reason\n                            or "EXIT"\n                        ),\n                        config=config,\n                    )\n                    active_symbol = (\n                        monthly_winner\n                    )\n                else:\n                    open_position.stop_price = (\n                        evaluation.next_stop_price\n                    )\n                    open_position.highest_price = (\n                        evaluation.highest_price\n                    )\n\n        if (\n            not swing.positions\n            and pending is None\n            and day != actual_end\n        ):\n            active_symbol = monthly_winner\n            index = index_maps[\n                active_symbol\n            ][day]\n            evaluation = evaluate_entry(\n                candles=candles[\n                    active_symbol\n                ],\n                indicators=indicators[\n                    active_symbol\n                ],\n                index=index,\n                vix=vix_map[day],\n                config=config,\n            )\n\n            if evaluation.should_enter:\n                signal_atr = indicators[\n                    active_symbol\n                ].atr[index]\n\n                if (\n                    signal_atr is not None\n                    and signal_atr > 0\n                ):\n                    pending = PendingSignal(\n                        symbol=active_symbol,\n                        signal_date=day,\n                        signal_atr=signal_atr,\n                        prior_close=row_maps[\n                            active_symbol\n                        ][day].close,\n                    )\n                    signal_count += 1\n\n        position = next(\n            iter(swing.positions.values()),\n            None,\n        )\n        position_prices = (\n            {\n                position.symbol: (\n                    row_maps[\n                        position.symbol\n                    ][day].close\n                )\n            }\n            if position is not None\n            else {}\n        )\n        swing_market_value = swing.market_value(\n            position_prices\n        )\n        swing_equity = swing.equity(\n            position_prices\n        )\n        income_value = income.market_value(\n            income_row.close\n        )\n        total_equity = (\n            swing_equity + income_value\n        )\n        elapsed = _elapsed_years(\n            actual_start,\n            day,\n        )\n        target_income_weight, _ = (\n            contribution_allocation(\n                elapsed,\n                config,\n            )\n        )\n        investable = (\n            income_value\n            + swing.cash\n            + swing_market_value\n        )\n        income_weight = (\n            income_value / investable\n            if investable > 0\n            else 0.0\n        )\n        points.append(\n            PortfolioPoint(\n                date=day,\n                total_equity=total_equity,\n                total_contributions=(\n                    total_contributions\n                ),\n                income_value=income_value,\n                swing_equity=swing_equity,\n                swing_cash=swing.cash,\n                swing_market_value=(\n                    swing_market_value\n                ),\n                tax_reserve=(\n                    swing.tax_reserve_cash\n                ),\n                income_weight=income_weight,\n                target_income_weight=(\n                    target_income_weight\n                ),\n                monthly_winner=monthly_winner,\n                active_symbol=active_symbol,\n                position_symbol=(\n                    position.symbol\n                    if position is not None\n                    else None\n                ),\n            )\n        )\n\n    if pending is not None:\n        pending = None\n\n    final_position = next(\n        iter(swing.positions.values()),\n        None,\n    )\n\n    if final_position is not None:\n        final_row = row_maps[\n            final_position.symbol\n        ][actual_end]\n        swing.close_position(\n            symbol=final_position.symbol,\n            exit_price=final_row.close,\n            exit_date=actual_end,\n            reason="END_OF_TEST",\n            config=config,\n        )\n\n        final_income_value = (\n            income.market_value(\n                income_map[actual_end].close\n            )\n        )\n        final_swing_equity = swing.equity({})\n        final_total = (\n            final_income_value\n            + final_swing_equity\n        )\n        elapsed = _elapsed_years(\n            actual_start,\n            actual_end,\n        )\n        final_target, _ = (\n            contribution_allocation(\n                elapsed,\n                config,\n            )\n        )\n        investable = (\n            final_income_value + swing.cash\n        )\n        final_weight = (\n            final_income_value / investable\n            if investable > 0\n            else 0.0\n        )\n        points[-1] = PortfolioPoint(\n            date=actual_end,\n            total_equity=final_total,\n            total_contributions=(\n                total_contributions\n            ),\n            income_value=final_income_value,\n            swing_equity=final_swing_equity,\n            swing_cash=swing.cash,\n            swing_market_value=0.0,\n            tax_reserve=swing.tax_reserve_cash,\n            income_weight=final_weight,\n            target_income_weight=final_target,\n            monthly_winner=monthly_winner,\n            active_symbol=monthly_winner,\n            position_symbol=None,\n        )\n\n    metrics, _ = _flow_adjusted_metrics(\n        points,\n        starting_capital=(\n            config.total_starting_capital\n        ),\n    )\n    ending = points[-1]\n    ending_equity = ending.total_equity\n    net_profit = (\n        ending_equity - total_contributions\n    )\n    trades = tuple(swing.closed_trades)\n    winners = sum(\n        trade.pnl > 0\n        for trade in trades\n    )\n    profit_factor = _profit_factor(\n        trades\n    )\n    winner_counts = Counter(\n        snapshot.winner\n        for snapshot in selection_snapshots\n    )\n    result = ActualTwoYearResult(\n        generated_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        provider=(\n            "Yahoo Finance chart endpoint"\n        ),\n        requested_start=requested_start,\n        actual_start=actual_start,\n        actual_end=actual_end,\n        bars=len(test_dates),\n        universe=REQUIRED_UNIVERSE,\n        income_symbol=INCOME_SYMBOL,\n        starting_income_cash=(\n            config.starting_cash\n        ),\n        starting_swing_cash=(\n            config.starting_swing_cash\n        ),\n        starting_total_capital=(\n            config.total_starting_capital\n        ),\n        monthly_contribution=(\n            config.monthly_contribution\n        ),\n        contribution_count=(\n            contribution_count\n        ),\n        total_contributions=(\n            total_contributions\n        ),\n        ending_equity=ending_equity,\n        net_profit=net_profit,\n        return_on_contributed_capital=(\n            net_profit / total_contributions\n            if total_contributions > 0\n            else 0.0\n        ),\n        ending_income_value=(\n            ending.income_value\n        ),\n        ending_swing_equity=(\n            ending.swing_equity\n        ),\n        ending_swing_cash=(\n            ending.swing_cash\n        ),\n        ending_tax_reserve=(\n            ending.tax_reserve\n        ),\n        ending_income_weight=(\n            ending.income_weight\n        ),\n        total_dividends=(\n            income.dividends_received\n        ),\n        dividend_event_count=(\n            dividend_event_count\n        ),\n        signal_count=signal_count,\n        filled_entries=filled_entries,\n        gap_rejections=gap_rejections,\n        risk_rejections=risk_rejections,\n        closed_trades=len(trades),\n        win_rate=(\n            winners / len(trades)\n            if trades\n            else 0.0\n        ),\n        profit_factor=profit_factor,\n        maximum_drawdown=(\n            metrics.maximum_drawdown\n        ),\n        flow_adjusted_total_return=(\n            metrics.total_return\n        ),\n        flow_adjusted_cagr=metrics.cagr,\n        flow_adjusted_volatility=(\n            metrics.annualized_volatility\n        ),\n        sharpe_ratio=metrics.sharpe_ratio,\n        sortino_ratio=metrics.sortino_ratio,\n        swing_exposure=metrics.exposure,\n        selection_months=len(\n            selection_snapshots\n        ),\n        winner_counts={\n            symbol: winner_counts.get(\n                symbol,\n                0,\n            )\n            for symbol in REQUIRED_UNIVERSE\n        },\n        forced_entry_indices=None,\n        symbol_bonus_policy=(\n            selection_config.symbol_bonus_policy\n        ),\n        live_broker_enabled=False,\n    )\n\n    report_path = (\n        report_directory\n        / "actual_two_year_report.txt"\n    )\n    result_path = (\n        report_directory\n        / "actual_two_year_result.json"\n    )\n    equity_path = (\n        report_directory\n        / "actual_two_year_equity.csv"\n    )\n    trades_path = (\n        report_directory\n        / "actual_two_year_trades.csv"\n    )\n    selection_path = (\n        report_directory\n        / "monthly_selection_log.csv"\n    )\n    allocation_path = (\n        report_directory\n        / "allocation_rebalance_log.csv"\n    )\n    provenance_path = (\n        report_directory\n        / "actual_two_year_provenance.json"\n    )\n\n    report_path.write_text(\n        _format_report(result) + "\\n",\n        encoding="utf-8",\n    )\n    result_payload = asdict(result)\n    result_payload["requested_start"] = (\n        result.requested_start.isoformat()\n    )\n    result_payload["actual_start"] = (\n        result.actual_start.isoformat()\n    )\n    result_payload["actual_end"] = (\n        result.actual_end.isoformat()\n    )\n    _atomic_json(\n        result_path,\n        result_payload,\n    )\n    _write_equity(\n        equity_path,\n        points,\n    )\n    _write_trades(\n        trades_path,\n        trades,\n    )\n    _write_selections(\n        selection_path,\n        selection_snapshots,\n    )\n    _write_allocations(\n        allocation_path,\n        allocation_snapshots,\n    )\n    provenance = {\n        "schema_version": 1,\n        "generated_at_utc": (\n            result.generated_at_utc\n        ),\n        "actual_data": True,\n        "provider": result.provider,\n        "requested_download_range": (\n            DOWNLOAD_RANGE\n        ),\n        "requested_backtest_years": 2,\n        "requested_start": (\n            requested_start.isoformat()\n        ),\n        "actual_start": (\n            actual_start.isoformat()\n        ),\n        "actual_end": (\n            actual_end.isoformat()\n        ),\n        "common_daily_sessions": len(\n            test_dates\n        ),\n        "swing_universe": list(\n            REQUIRED_UNIVERSE\n        ),\n        "income_symbol": INCOME_SYMBOL,\n        "vix_symbol": VIX_SYMBOL,\n        "selection_engine": (\n            "qpx_bot.symbol_selector.rank_candidates"\n        ),\n        "entry_engine": (\n            "qpx_bot.strategy.evaluate_entry"\n        ),\n        "exit_engine": (\n            "qpx_bot.strategy.evaluate_exit"\n        ),\n        "position_sizing_engine": (\n            "qpx_bot.risk.calculate_position_size"\n        ),\n        "allocation_engine": (\n            "qpx_bot.allocation."\n            "rebalance_income_allocation"\n        ),\n        "portfolio_engine": (\n            "qpx_bot.portfolio.Portfolio"\n        ),\n        "monthly_selection_lookahead": False,\n        "selection_rule": (\n            "Every monthly decision uses rows with "\n            "date strictly before the decision date."\n        ),\n        "position_lock": True,\n        "opening_gap_atr_limit": (\n            maximum_gap_atr\n        ),\n        "forced_entry_indices": None,\n        "symbol_bonus_policy": (\n            selection_config.symbol_bonus_policy\n        ),\n        "configuration": asdict(config),\n        "selection_configuration": asdict(\n            selection_config\n        ),\n        "download_manifest": {\n            "path": str(manifest_path),\n            "sha256": sha256_file(\n                manifest_path\n            ),\n        },\n        "outputs": {\n            "report": str(report_path),\n            "result": str(result_path),\n            "equity": str(equity_path),\n            "trades": str(trades_path),\n            "selections": str(\n                selection_path\n            ),\n            "allocations": str(\n                allocation_path\n            ),\n        },\n        "live_broker_enabled": False,\n    }\n    _atomic_json(\n        provenance_path,\n        provenance,\n    )\n    artifacts = RunArtifacts(\n        report=report_path,\n        result=result_path,\n        equity=equity_path,\n        trades=trades_path,\n        selections=selection_path,\n        allocations=allocation_path,\n        provenance=provenance_path,\n        manifest=manifest_path,\n    )\n    return result, artifacts\n\n\ndef format_console_summary(\n    result: ActualTwoYearResult,\n    artifacts: RunArtifacts,\n) -> str:\n    artifact_lines = [\n        f"  {name:<12}: {path}"\n        for name, path in asdict(\n            artifacts\n        ).items()\n    ]\n    return "\\n".join(\n        (\n            _format_report(result),\n            "-" * 78,\n            "Artifacts:",\n            *artifact_lines,\n        )\n    )\n',
    "QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py": '#!/usr/bin/env python3\n"""Run the actual two-year QPX eight-symbol portfolio backtest."""\n\nfrom qpx_bot.actual_two_year_portfolio import (\n    format_console_summary,\n    run_actual_two_year_eight_symbol_backtest,\n)\n\n\nif __name__ == "__main__":\n    result, artifacts = (\n        run_actual_two_year_eight_symbol_backtest()\n    )\n    print(\n        format_console_summary(\n            result,\n            artifacts,\n        )\n    )\n',
    "tests/test_qpx_bot_actual_two_year_portfolio.py": 'from datetime import date\n\nfrom qpx_bot.actual_two_year_portfolio import (\n    REQUIRED_UNIVERSE,\n    rank_as_of,\n    subtract_years,\n)\nfrom qpx_bot.symbol_selector import (\n    SelectionConfig,\n)\nfrom qpx_bot.yahoo_data import MarketRow\n\n\nassert REQUIRED_UNIVERSE == (\n    "DIA",\n    "IWM",\n    "QQQ",\n    "SPY",\n    "XLE",\n    "XLF",\n    "XLK",\n    "XLV",\n)\nassert len(REQUIRED_UNIVERSE) == 8\nassert subtract_years(\n    date(2024, 2, 29),\n    2,\n) == date(2022, 2, 28)\n\nselection_config = SelectionConfig(\n    schema_version=1,\n    decision_frequency="monthly",\n    history_range="4y",\n    candidates=REQUIRED_UNIVERSE,\n    minimum_history_bars=252,\n    minimum_eligible_candidates=3,\n    minimum_median_dollar_volume=50_000_000,\n    maximum_stale_days=4,\n    short_return_lookback=63,\n    long_return_lookback=126,\n    trend_lookback=200,\n    volatility_lookback=63,\n    drawdown_lookback=126,\n    liquidity_lookback=20,\n    weights={\n        "short_return": 0.25,\n        "long_return": 0.30,\n        "trend": 0.15,\n        "liquidity": 0.10,\n        "volatility_penalty": 0.10,\n        "drawdown_penalty": 0.10,\n    },\n    symbol_bonus_policy="none",\n)\n\nhistories = {}\n\nfor symbol_index, symbol in enumerate(\n    REQUIRED_UNIVERSE\n):\n    rows = []\n\n    for index in range(300):\n        day = date.fromordinal(\n            date(2023, 1, 2).toordinal()\n            + index\n        )\n        close = (\n            100.0\n            + index * (\n                0.05\n                + symbol_index * 0.005\n            )\n        )\n        rows.append(\n            MarketRow(\n                date=day,\n                open=close - 0.1,\n                high=close + 0.5,\n                low=close - 0.5,\n                close=close,\n                adjusted_close=close,\n                volume=5_000_000,\n            )\n        )\n\n    histories[symbol] = rows\n\ndecision_date = date.fromordinal(\n    date(2023, 1, 2).toordinal()\n    + 299\n)\nselection = rank_as_of(\n    decision_date=decision_date,\n    histories=histories,\n    selection_config=selection_config,\n)\n\nassert selection.latest_market_date < decision_date\nassert (\n    selection.selected_symbol\n    in REQUIRED_UNIVERSE\n)\nassert selection.symbol_bonus_policy == "none"\n\nfrom pathlib import Path\n\nsource = (\n    Path(__file__).resolve().parents[1]\n    / "qpx_bot"\n    / "actual_two_year_portfolio.py"\n).read_text(encoding="utf-8")\n\nfor required in (\n    "fetch_chart(",\n    "rank_candidates(",\n    "evaluate_entry(",\n    "evaluate_exit(",\n    "calculate_position_size(",\n    "rebalance_income_allocation(",\n    "row.date < decision_date",\n    "forced_entry_indices=None",\n    "No synthetic OHLCV",\n):\n    assert required in source\n\nassert "forced_entry_indices={" not in source\nassert "synthetic_candles" not in source\nassert "CURRENT_SELECTION_DECISION" not in source\n\nprint(\n    "QPX Bot Actual Two-Year Eight-Symbol "\n    "Portfolio Backtest PASS"\n)\n',
    "qpx_bot/ACTUAL_TWO_YEAR_EIGHT_SYMBOL_README.txt": "QPX ACTUAL TWO-YEAR EIGHT-SYMBOL PORTFOLIO BACKTEST\n====================================================\n\nCommand\n-------\n\npython QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py\n\nActual swing universe\n---------------------\n\nDIA\nIWM\nQQQ\nSPY\nXLE\nXLF\nXLK\nXLV\n\nQDTE is separate and remains the income sleeve. ^VIX supplies the\nentry-volatility gate.\n\nPoint-in-time selection\n-----------------------\n\nThe existing qpx_bot.symbol_selector.rank_candidates engine ranks all\neight candidates at the beginning of each month. Every decision uses\nonly rows dated strictly before that decision date.\n\nThe rank weights are loaded from qpx_bot/swing_universe.json:\n\n- 63-day adjusted return: 25%\n- 126-day adjusted return: 30%\n- 200-day trend distance: 15%\n- median dollar liquidity: 10%\n- volatility penalty: 10%\n- drawdown penalty: 10%\n\nThere are no symbol-specific bonuses or preferred fallback symbols.\n\nPosition lock\n-------------\n\nThe monthly winner becomes the active swing ticker only while the swing\naccount is flat and no entry is pending. An open position or staged\nnext-session entry locks its ticker. Once flat, the active ticker moves\nto the current month's winner.\n\nStrategy and execution\n----------------------\n\nThe runner calls the existing QPX components:\n\n- qpx_bot.strategy.evaluate_entry\n- qpx_bot.strategy.evaluate_exit\n- qpx_bot.risk.calculate_position_size\n- qpx_bot.portfolio.Portfolio\n- qpx_bot.allocation.rebalance_income_allocation\n\nSignals are generated at the daily close and staged for the next common\nmarket session. The next open is rejected when its absolute gap exceeds\nthe configured 1.5 ATR limit. Slippage, the 2.5 ATR stop, 5.0 ATR target,\n3.0 ATR trailing activation, quarter-Kelly sizing, VIX 28 gate, 6%\nactive-risk cap, and 37% realized-gain reserve remain active.\n\nCapital and allocation\n----------------------\n\nInitial QDTE seed       : $1,300\nInitial swing liquidity : $1,500\nInitial total capital   : $2,800\nMonthly contribution    : $2,000\n\nThe portfolio rebalances monthly toward 65% QDTE / 35% swing during\nyears 1 and 2 and 40% QDTE / 60% swing from year 3 onward. Open swing\npositions are not sold merely to rebalance.\n\nActual-data controls\n--------------------\n\nThe run downloads true daily data for the eight ETFs, QDTE, and ^VIX\nfrom the Yahoo Finance chart endpoint. Four years are requested to\nprovide the 252-bar ranking warmup. The reported performance window is\nthe latest two completed years of common sessions.\n\nThe run rejects stale or downsampled data, requires at least 480 common\ndaily sessions, hashes every input file, logs every monthly ranking and\nallocation event, and never uses forced entries or fabricated data.\n\nOutputs\n-------\n\nreports/qpx_actual_two_year_eight_symbol/<RUN_ID>/\n    actual_two_year_report.txt\n    actual_two_year_result.json\n    actual_two_year_equity.csv\n    actual_two_year_trades.csv\n    monthly_selection_log.csv\n    allocation_rebalance_log.csv\n    actual_two_year_provenance.json\n\nresearch_data/qpx_actual_two_year_eight_symbol/<RUN_ID>/\n    Actual downloaded symbol files and DOWNLOAD_MANIFEST.json\n\nResearch simulation only. No brokerage connection or live order path.\n",
}

GITIGNORE_APPEND = '# QPX actual two-year eight-symbol research\nresearch_data/qpx_actual_two_year_eight_symbol/\nreports/qpx_actual_two_year_eight_symbol/\n'
TARGETS = [*FILES, ".gitignore"]
originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
    )


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            relative,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )
        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )

        if (
            worktree.returncode != 0
            or staged.returncode != 0
        ):
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and "
            "were not overwritten:\n"
            + "\n".join(changed)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            path,
            backup_path,
        )


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(
                content
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        if path.name.startswith("QPX_"):
            path.chmod(0o700)

        print(f"Installed: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(
        encoding="utf-8"
    )
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print(
        "Restoring previous target files..."
    )

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(
                Path(__file__)
                .resolve()
                .relative_to(ROOT)
            )
        )
    except ValueError:
        pass

    run([
        "git",
        "add",
        "--",
        *paths,
    ])

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print(
            "Two-year eight-symbol runner is "
            "already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Add actual two-year eight-symbol "
            "QPX portfolio backtest"
        ),
    ])

    branch = subprocess.check_output(
        [
            "git",
            "branch",
            "--show-current",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run([
        "git",
        "push",
        "origin",
        branch,
    ])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — ACTUAL TWO-YEAR "
        "EIGHT-SYMBOL BACKTEST INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    install_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_actual_two_year_portfolio"
            ),
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print(
        "Downloading actual data for eight swing ETFs, "
        "QDTE, and VIX..."
    )
    print()

    result = run(
        [
            sys.executable,
            "QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py",
        ],
        check=False,
    )

    if result.returncode != 0:
        print()
        print("=" * 78)
        print(
            "QPX TWO-YEAR PORTFOLIO RUNNER: "
            "INSTALLED AND PUSHED"
        )
        print(
            "ACTUAL DATA RUN: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py"
        )
        return result.returncode

    print()
    print("=" * 78)
    print(
        "QPX ACTUAL TWO-YEAR EIGHT-SYMBOL "
        "BACKTEST: COMPLETE"
    )
    print("=" * 78)
    print(
        "Eight actual swing histories, actual QDTE "
        "distributions, actual VIX, no forced entries, "
        "and no live brokerage."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
