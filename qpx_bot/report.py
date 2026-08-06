"""Performance reporting and CSV exports for QPX Bot backtests."""

from __future__ import annotations

import csv
from pathlib import Path

from qpx_bot.backtest import BacktestResult
from qpx_bot.hybrid import HybridBacktestResult


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value * 100.0:,.2f}%"


def _profit_factor(value: float) -> str:
    return "∞" if value == float("inf") else f"{value:,.2f}"


def format_backtest_report(result: BacktestResult) -> str:
    """Return a readable text report for one backtest."""
    lines = [
        "=" * 72,
        "QPX BOT v1.4 — HISTORICAL BACKTEST",
        "=" * 72,
        f"Symbol                    : {result.symbol}",
        f"Period                    : {result.start_date} to {result.end_date}",
        f"Starting cash             : {_money(result.starting_cash)}",
        f"Monthly deposits made     : {result.contribution_count}",
        f"Total contributed capital : {_money(result.total_contributions)}",
        f"Ending equity             : {_money(result.ending_equity)}",
        f"Net profit                : {_money(result.net_profit)}",
        (
            "Return on contributed capital: "
            f"{_percent(result.return_on_contributed_capital)}"
        ),
        f"Signals accepted          : {result.signal_count}",
        f"Entries rejected by risk  : {result.rejected_entries}",
        f"Closed trades             : {len(result.trades)}",
        f"Win rate                  : {_percent(result.win_rate)}",
        (
            "Profit factor             : "
            f"{_profit_factor(result.profit_factor)}"
        ),
        (
            "Maximum drawdown          : "
            f"{_percent(result.maximum_drawdown)}"
        ),
        f"Tax reserve cash          : {_money(result.tax_reserve)}",
        "=" * 72,
        "Research simulation only. This is not live trading or advice.",
    ]

    return "\n".join(lines)


def format_hybrid_report(
    result: HybridBacktestResult,
) -> str:
    """Return the combined dividend-plus-swing report."""
    lines = [
        "=" * 76,
        "QPX BOT v1.5 — HYBRID DIVIDEND + SWING BACKTEST",
        "=" * 76,
        (
            f"Sleeves                   : "
            f"{result.income_symbol} income + "
            f"{result.swing_symbol} swing"
        ),
        (
            f"Period                    : "
            f"{result.start_date} to {result.end_date}"
        ),
        f"Starting cash             : {_money(result.starting_cash)}",
        f"Monthly deposits made     : {result.contribution_count}",
        (
            "Total contributed capital : "
            f"{_money(result.total_contributions)}"
        ),
        f"Ending combined equity    : {_money(result.ending_equity)}",
        f"Ending income value       : {_money(result.ending_income_value)}",
        (
            f"Ending {result.income_symbol} shares"
            f"    : {result.ending_income_shares:,.6f}"
        ),
        f"Ending swing equity       : {_money(result.ending_swing_equity)}",
        f"Ending swing cash         : {_money(result.ending_swing_cash)}",
        f"Dividends routed to swing : {_money(result.total_dividends)}",
        f"Dividend events processed : {result.dividend_event_count}",
        f"Net profit                : {_money(result.net_profit)}",
        (
            "Return on contributed capital: "
            f"{_percent(result.return_on_contributed_capital)}"
        ),
        f"Signals accepted          : {result.signal_count}",
        f"Entries rejected by risk  : {result.rejected_entries}",
        f"Closed swing trades       : {len(result.trades)}",
        f"Win rate                  : {_percent(result.win_rate)}",
        (
            "Profit factor             : "
            f"{_profit_factor(result.profit_factor)}"
        ),
        (
            "Maximum drawdown          : "
            f"{_percent(result.maximum_drawdown)}"
        ),
        f"Tax reserve cash          : {_money(result.tax_reserve)}",
        "=" * 76,
        "Synthetic demo data is execution proof, not performance evidence.",
        "Research simulation only. This is not live trading or advice.",
    ]

    return "\n".join(lines)


def write_trade_log(
    result: BacktestResult | HybridBacktestResult,
    filename: str | Path,
) -> Path:
    """Write completed trades to a CSV file."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
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
            ]
        )

        for trade in result.trades:
            writer.writerow(
                [
                    trade.symbol,
                    trade.entry_date.isoformat(),
                    trade.exit_date.isoformat(),
                    trade.shares,
                    f"{trade.entry_price:.6f}",
                    f"{trade.exit_price:.6f}",
                    f"{trade.pnl:.6f}",
                    f"{trade.tax_reserved:.6f}",
                    trade.reason,
                    f"{trade.result_r:.6f}",
                ]
            )

    return path


def write_equity_curve(
    result: BacktestResult,
    filename: str | Path,
) -> Path:
    """Write single-sleeve end-of-day equity observations."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Date",
                "Equity",
                "Cash",
                "MarketValue",
                "TaxReserve",
            ]
        )

        for point in result.equity_curve:
            writer.writerow(
                [
                    point.date.isoformat(),
                    f"{point.equity:.6f}",
                    f"{point.cash:.6f}",
                    f"{point.market_value:.6f}",
                    f"{point.tax_reserve:.6f}",
                ]
            )

    return path


def write_hybrid_equity_curve(
    result: HybridBacktestResult,
    filename: str | Path,
) -> Path:
    """Write combined income and swing equity observations."""
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "Date",
                "TotalEquity",
                "IncomeValue",
                "SwingEquity",
                "SwingCash",
                "SwingMarketValue",
                "TaxReserve",
                "IncomeShares",
                "CumulativeDividends",
                "TotalContributions",
            ]
        )

        for point in result.equity_curve:
            writer.writerow(
                [
                    point.date.isoformat(),
                    f"{point.total_equity:.6f}",
                    f"{point.income_value:.6f}",
                    f"{point.swing_equity:.6f}",
                    f"{point.swing_cash:.6f}",
                    f"{point.swing_market_value:.6f}",
                    f"{point.tax_reserve:.6f}",
                    f"{point.income_shares:.8f}",
                    f"{point.cumulative_dividends:.6f}",
                    f"{point.total_contributions:.6f}",
                ]
            )

    return path
