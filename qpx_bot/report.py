"""Performance reporting and CSV exports for QPX Bot backtests."""

from __future__ import annotations

import csv
from pathlib import Path

from qpx_bot.backtest import BacktestResult


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _percent(value: float) -> str:
    return f"{value * 100.0:,.2f}%"


def format_backtest_report(result: BacktestResult) -> str:
    """Return a readable text report for one backtest."""
    profit_factor = (
        "∞"
        if result.profit_factor == float("inf")
        else f"{result.profit_factor:,.2f}"
    )

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
        f"Profit factor             : {profit_factor}",
        f"Maximum drawdown          : {_percent(result.maximum_drawdown)}",
        f"Tax reserve cash          : {_money(result.tax_reserve)}",
        "=" * 72,
        "Research simulation only. This is not live trading or advice.",
    ]

    return "\n".join(lines)


def write_trade_log(
    result: BacktestResult,
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
    """Write end-of-day equity observations to a CSV file."""
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
