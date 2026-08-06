#!/usr/bin/env python3
"""Install, test, commit, and push the QPX hybrid dividend engine."""

from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    starts = [
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ]

    for start in starts:
        for candidate in (start, *start.parents):
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
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "backups" / "qpx_bot_hybrid_dividend" / STAMP

STATIC_FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nBacktesting bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.5.0"\n',
    "qpx_bot/dividends.py": '"""Dividend-event data models and CSV loading for QPX Bot."""\n\nfrom __future__ import annotations\n\nimport csv\nfrom dataclasses import dataclass\nfrom datetime import date, datetime\nfrom pathlib import Path\nfrom typing import Iterable\n\n\n@dataclass(frozen=True, slots=True)\nclass DividendEvent:\n    """One cash distribution expressed as dollars per share."""\n\n    date: date\n    amount_per_share: float\n\n    def validate(self) -> None:\n        if self.amount_per_share < 0:\n            raise ValueError("Dividend per share cannot be negative.")\n\n\ndef _parse_date(raw_value: str) -> date:\n    value = raw_value.strip()\n\n    for date_format in ("%Y-%m-%d", "%Y/%m/%d"):\n        try:\n            return datetime.strptime(value, date_format).date()\n        except ValueError:\n            continue\n\n    raise ValueError(f"Unsupported date format: {raw_value!r}")\n\n\ndef load_dividend_csv(filename: str | Path) -> list[DividendEvent]:\n    """Load Date/Dividend dividend events from a CSV file."""\n    path = Path(filename).expanduser().resolve()\n\n    if not path.exists():\n        raise FileNotFoundError(f"Dividend file was not found: {path}")\n\n    events: list[DividendEvent] = []\n\n    with path.open("r", newline="", encoding="utf-8-sig") as file:\n        reader = csv.DictReader(file)\n\n        if reader.fieldnames is None:\n            raise ValueError("Dividend CSV does not contain a header.")\n\n        amount_column = None\n\n        for candidate in ("Dividend", "DividendPerShare", "Amount"):\n            if candidate in reader.fieldnames:\n                amount_column = candidate\n                break\n\n        if "Date" not in reader.fieldnames or amount_column is None:\n            raise ValueError(\n                "Dividend CSV requires Date and Dividend columns."\n            )\n\n        for line_number, row in enumerate(reader, start=2):\n            try:\n                event = DividendEvent(\n                    date=_parse_date(row["Date"]),\n                    amount_per_share=float(row[amount_column]),\n                )\n                event.validate()\n                events.append(event)\n            except (TypeError, ValueError, KeyError) as exc:\n                raise ValueError(\n                    f"Invalid dividend data on CSV line "\n                    f"{line_number}: {exc}"\n                ) from exc\n\n    events.sort(key=lambda event: event.date)\n    return events\n\n\ndef dividend_amounts_by_date(\n    events: Iterable[DividendEvent],\n) -> dict[date, float]:\n    """Combine same-day distributions into one per-share amount."""\n    amounts: dict[date, float] = {}\n\n    for event in events:\n        event.validate()\n        amounts[event.date] = (\n            amounts.get(event.date, 0.0)\n            + event.amount_per_share\n        )\n\n    return amounts\n',
    "qpx_bot/hybrid.py": '"""Hybrid dividend-income and swing-trading backtest engine."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom datetime import date\nfrom typing import Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.dividends import DividendEvent, dividend_amounts_by_date\nfrom qpx_bot.indicators import calculate_indicators\nfrom qpx_bot.portfolio import (\n    ClosedTrade,\n    Portfolio,\n    contribution_allocation,\n)\nfrom qpx_bot.risk import buy_fill, calculate_position_size\nfrom qpx_bot.strategy import evaluate_entry, evaluate_exit\n\n\n@dataclass(slots=True)\nclass IncomeHolding:\n    """Fractional-share holding used by the income sleeve."""\n\n    symbol: str\n    shares: float = 0.0\n    invested_cost: float = 0.0\n    dividends_received: float = 0.0\n\n    def buy(\n        self,\n        *,\n        cash_amount: float,\n        market_price: float,\n        slippage_rate: float,\n    ) -> float:\n        """Invest an exact cash amount and return acquired shares."""\n        if cash_amount < 0:\n            raise ValueError("Income investment cannot be negative.")\n\n        if cash_amount == 0:\n            return 0.0\n\n        fill = buy_fill(market_price, slippage_rate)\n        acquired = cash_amount / fill\n        self.shares += acquired\n        self.invested_cost += cash_amount\n        return acquired\n\n    def receive_dividend(self, amount_per_share: float) -> float:\n        """Record and return dividend cash produced by current shares."""\n        if amount_per_share < 0:\n            raise ValueError("Dividend per share cannot be negative.")\n\n        cash = self.shares * amount_per_share\n        self.dividends_received += cash\n        return cash\n\n    def market_value(self, market_price: float) -> float:\n        if market_price <= 0:\n            raise ValueError("Income market price must be positive.")\n        return self.shares * market_price\n\n\n@dataclass(frozen=True, slots=True)\nclass AllocationEvent:\n    """One external contribution and its two-sleeve split."""\n\n    date: date\n    amount: float\n    income_weight: float\n    swing_weight: float\n    income_amount: float\n    swing_amount: float\n\n\n@dataclass(frozen=True, slots=True)\nclass HybridEquityPoint:\n    """One end-of-day combined portfolio valuation."""\n\n    date: date\n    total_equity: float\n    income_value: float\n    swing_equity: float\n    swing_cash: float\n    swing_market_value: float\n    tax_reserve: float\n    income_shares: float\n    cumulative_dividends: float\n    total_contributions: float\n\n\n@dataclass(frozen=True, slots=True)\nclass HybridBacktestResult:\n    """Complete result for the income-plus-swing simulation."""\n\n    swing_symbol: str\n    income_symbol: str\n    start_date: date\n    end_date: date\n    starting_cash: float\n    total_contributions: float\n    ending_equity: float\n    ending_income_value: float\n    ending_income_shares: float\n    ending_swing_equity: float\n    ending_swing_cash: float\n    tax_reserve: float\n    total_dividends: float\n    dividend_event_count: int\n    contribution_count: int\n    signal_count: int\n    rejected_entries: int\n    trades: tuple[ClosedTrade, ...]\n    allocation_events: tuple[AllocationEvent, ...]\n    equity_curve: tuple[HybridEquityPoint, ...]\n\n    @property\n    def net_profit(self) -> float:\n        return self.ending_equity - self.total_contributions\n\n    @property\n    def return_on_contributed_capital(self) -> float:\n        if self.total_contributions <= 0:\n            return 0.0\n        return self.net_profit / self.total_contributions\n\n    @property\n    def win_rate(self) -> float:\n        if not self.trades:\n            return 0.0\n        winners = sum(1 for trade in self.trades if trade.pnl > 0)\n        return winners / len(self.trades)\n\n    @property\n    def profit_factor(self) -> float:\n        gross_profit = sum(\n            trade.pnl for trade in self.trades if trade.pnl > 0\n        )\n        gross_loss = -sum(\n            trade.pnl for trade in self.trades if trade.pnl < 0\n        )\n\n        if gross_loss == 0:\n            return float("inf") if gross_profit > 0 else 0.0\n\n        return gross_profit / gross_loss\n\n    @property\n    def maximum_drawdown(self) -> float:\n        if not self.equity_curve:\n            return 0.0\n\n        peak = self.equity_curve[0].total_equity\n        maximum = 0.0\n\n        for point in self.equity_curve:\n            peak = max(peak, point.total_equity)\n            if peak > 0:\n                drawdown = (\n                    peak - point.total_equity\n                ) / peak\n                maximum = max(maximum, drawdown)\n\n        return maximum\n\n\ndef _validate_candles(\n    candles: Sequence[Candle],\n    label: str,\n) -> None:\n    if not candles:\n        raise ValueError(f"{label} candles cannot be empty.")\n\n    dates = [candle.date for candle in candles]\n\n    if dates != sorted(dates):\n        raise ValueError(f"{label} candles must be sorted by date.")\n\n    if len(dates) != len(set(dates)):\n        raise ValueError(f"{label} candles contain duplicate dates.")\n\n\ndef _swing_prices(\n    portfolio: Portfolio,\n    symbol: str,\n    price: float,\n) -> dict[str, float]:\n    if symbol in portfolio.positions:\n        return {symbol: price}\n    return {}\n\n\ndef _elapsed_years(start: date, current: date) -> int:\n    months = (\n        (current.year - start.year) * 12\n        + current.month\n        - start.month\n    )\n    return max(0, months // 12)\n\n\ndef run_hybrid_backtest(\n    *,\n    swing_candles: Sequence[Candle],\n    income_candles: Sequence[Candle],\n    dividends: Sequence[DividendEvent],\n    swing_symbol: str,\n    config: BotConfig,\n    vix: float | Sequence[float] = 20.0,\n    forced_entry_indices: set[int] | None = None,\n) -> HybridBacktestResult:\n    """\n    Run the configured Hybrid Dividend + Swing strategy.\n\n    The initial capital and every monthly deposit are split between\n    the income and swing sleeves. Years 1–2 use 65/35 and year 3\n    onward uses 40/60. Income distributions are routed into swing\n    cash and are not counted as external contributions.\n\n    Swing signals are evaluated at the close and filled at the next\n    bar\'s open. The income sleeve remains invested at the end.\n    """\n    config.validate()\n    _validate_candles(swing_candles, "Swing")\n    _validate_candles(income_candles, "Income")\n\n    if len(swing_candles) < 2:\n        raise ValueError("At least two swing candles are required.")\n\n    normalized_swing = swing_symbol.strip().upper()\n    normalized_income = config.dividend_symbol.strip().upper()\n\n    if not normalized_swing:\n        raise ValueError("Swing symbol cannot be empty.")\n\n    if not normalized_income:\n        raise ValueError("Income symbol cannot be empty.")\n\n    income_by_date = {\n        candle.date: candle\n        for candle in income_candles\n    }\n    income_dates = [candle.date for candle in income_candles]\n    first_swing_date = swing_candles[0].date\n\n    if income_dates[0] > first_swing_date:\n        raise ValueError(\n            "Income history must begin on or before swing history."\n        )\n\n    dividend_map = dividend_amounts_by_date(dividends)\n    indicators = calculate_indicators(swing_candles, config)\n\n    initial_income_weight, initial_swing_weight = (\n        contribution_allocation(0, config)\n    )\n    initial_income_cash = (\n        config.starting_cash * initial_income_weight\n    )\n    initial_swing_cash = (\n        config.starting_cash * initial_swing_weight\n    )\n\n    income_holding = IncomeHolding(normalized_income)\n    swing_portfolio = Portfolio(initial_swing_cash)\n\n    income_pointer = 0\n    latest_income = income_candles[0]\n\n    while (\n        income_pointer + 1 < len(income_candles)\n        and income_candles[income_pointer + 1].date\n        <= first_swing_date\n    ):\n        income_pointer += 1\n        latest_income = income_candles[income_pointer]\n\n    income_holding.buy(\n        cash_amount=initial_income_cash,\n        market_price=latest_income.open,\n        slippage_rate=config.slippage_rate,\n    )\n\n    total_external_contributions = config.starting_cash\n    contribution_count = 0\n    dividend_event_count = 0\n    signal_count = 0\n    rejected_entries = 0\n    pending_signal_index: int | None = None\n    allocation_events: list[AllocationEvent] = []\n    equity_curve: list[HybridEquityPoint] = []\n\n    previous_month = (\n        first_swing_date.year,\n        first_swing_date.month,\n    )\n\n    for index, swing_candle in enumerate(swing_candles):\n        while (\n            income_pointer + 1 < len(income_candles)\n            and income_candles[income_pointer + 1].date\n            <= swing_candle.date\n        ):\n            income_pointer += 1\n            latest_income = income_candles[income_pointer]\n\n        current_month = (\n            swing_candle.date.year,\n            swing_candle.date.month,\n        )\n\n        dividend_per_share = dividend_map.get(\n            swing_candle.date,\n            0.0,\n        )\n\n        if dividend_per_share > 0:\n            dividend_cash = income_holding.receive_dividend(\n                dividend_per_share\n            )\n            swing_portfolio.cash += dividend_cash\n            dividend_event_count += 1\n\n        if current_month != previous_month:\n            if config.monthly_contribution > 0:\n                elapsed_years = _elapsed_years(\n                    first_swing_date,\n                    swing_candle.date,\n                )\n                income_weight, swing_weight = (\n                    contribution_allocation(\n                        elapsed_years,\n                        config,\n                    )\n                )\n                income_amount = (\n                    config.monthly_contribution\n                    * income_weight\n                )\n                swing_amount = (\n                    config.monthly_contribution\n                    * swing_weight\n                )\n\n                income_holding.buy(\n                    cash_amount=income_amount,\n                    market_price=latest_income.open,\n                    slippage_rate=config.slippage_rate,\n                )\n                swing_portfolio.deposit(swing_amount)\n                total_external_contributions += (\n                    config.monthly_contribution\n                )\n                contribution_count += 1\n                allocation_events.append(\n                    AllocationEvent(\n                        date=swing_candle.date,\n                        amount=config.monthly_contribution,\n                        income_weight=income_weight,\n                        swing_weight=swing_weight,\n                        income_amount=income_amount,\n                        swing_amount=swing_amount,\n                    )\n                )\n\n            previous_month = current_month\n\n        if (\n            pending_signal_index is not None\n            and normalized_swing\n            not in swing_portfolio.positions\n        ):\n            signal_atr = indicators.atr[\n                pending_signal_index\n            ]\n\n            if signal_atr is None or signal_atr <= 0:\n                rejected_entries += 1\n            else:\n                swing_prices = _swing_prices(\n                    swing_portfolio,\n                    normalized_swing,\n                    swing_candle.open,\n                )\n                combined_equity_at_open = (\n                    swing_portfolio.equity(swing_prices)\n                    + income_holding.market_value(\n                        latest_income.open\n                    )\n                )\n                trade_results = [\n                    trade.result_r\n                    for trade in swing_portfolio.closed_trades\n                ]\n                sizing = calculate_position_size(\n                    account_equity=combined_equity_at_open,\n                    available_cash=swing_portfolio.cash,\n                    entry_price=swing_candle.open,\n                    atr=signal_atr,\n                    active_risk=swing_portfolio.active_risk(),\n                    config=config,\n                    trade_results_r=trade_results,\n                )\n\n                if sizing.is_tradeable:\n                    swing_portfolio.open_position(\n                        symbol=normalized_swing,\n                        sizing=sizing,\n                        entry_date=swing_candle.date,\n                        entry_atr=signal_atr,\n                    )\n                else:\n                    rejected_entries += 1\n\n            pending_signal_index = None\n\n        position = swing_portfolio.positions.get(\n            normalized_swing\n        )\n        current_atr = indicators.atr[index]\n\n        if position is not None and current_atr is not None:\n            exit_evaluation = evaluate_exit(\n                position=position,\n                candle=swing_candle,\n                current_atr=current_atr,\n                config=config,\n            )\n\n            if exit_evaluation.should_exit:\n                assert exit_evaluation.exit_price is not None\n                swing_portfolio.close_position(\n                    symbol=normalized_swing,\n                    exit_price=exit_evaluation.exit_price,\n                    exit_date=swing_candle.date,\n                    reason=exit_evaluation.reason or "EXIT",\n                    config=config,\n                )\n            else:\n                position.stop_price = (\n                    exit_evaluation.next_stop_price\n                )\n                position.highest_price = (\n                    exit_evaluation.highest_price\n                )\n\n        if (\n            index < len(swing_candles) - 1\n            and normalized_swing\n            not in swing_portfolio.positions\n            and pending_signal_index is None\n        ):\n            if forced_entry_indices is None:\n                entry_evaluation = evaluate_entry(\n                    candles=swing_candles,\n                    indicators=indicators,\n                    index=index,\n                    vix=vix,\n                    config=config,\n                )\n                should_enter = entry_evaluation.should_enter\n            else:\n                should_enter = (\n                    index in forced_entry_indices\n                )\n\n            if should_enter:\n                signal_count += 1\n                pending_signal_index = index\n\n        swing_prices = _swing_prices(\n            swing_portfolio,\n            normalized_swing,\n            swing_candle.close,\n        )\n        swing_market_value = (\n            swing_portfolio.market_value(swing_prices)\n        )\n        swing_equity = swing_portfolio.equity(\n            swing_prices\n        )\n        income_value = income_holding.market_value(\n            latest_income.close\n        )\n\n        equity_curve.append(\n            HybridEquityPoint(\n                date=swing_candle.date,\n                total_equity=(\n                    swing_equity + income_value\n                ),\n                income_value=income_value,\n                swing_equity=swing_equity,\n                swing_cash=swing_portfolio.cash,\n                swing_market_value=swing_market_value,\n                tax_reserve=(\n                    swing_portfolio.tax_reserve_cash\n                ),\n                income_shares=income_holding.shares,\n                cumulative_dividends=(\n                    income_holding.dividends_received\n                ),\n                total_contributions=(\n                    total_external_contributions\n                ),\n            )\n        )\n\n    final_swing = swing_candles[-1]\n\n    if normalized_swing in swing_portfolio.positions:\n        swing_portfolio.close_position(\n            symbol=normalized_swing,\n            exit_price=final_swing.close,\n            exit_date=final_swing.date,\n            reason="END_OF_TEST",\n            config=config,\n        )\n\n    final_income_value = income_holding.market_value(\n        latest_income.close\n    )\n    final_swing_equity = swing_portfolio.equity({})\n    ending_equity = (\n        final_swing_equity + final_income_value\n    )\n\n    equity_curve[-1] = HybridEquityPoint(\n        date=final_swing.date,\n        total_equity=ending_equity,\n        income_value=final_income_value,\n        swing_equity=final_swing_equity,\n        swing_cash=swing_portfolio.cash,\n        swing_market_value=0.0,\n        tax_reserve=swing_portfolio.tax_reserve_cash,\n        income_shares=income_holding.shares,\n        cumulative_dividends=(\n            income_holding.dividends_received\n        ),\n        total_contributions=total_external_contributions,\n    )\n\n    return HybridBacktestResult(\n        swing_symbol=normalized_swing,\n        income_symbol=normalized_income,\n        start_date=swing_candles[0].date,\n        end_date=swing_candles[-1].date,\n        starting_cash=config.starting_cash,\n        total_contributions=total_external_contributions,\n        ending_equity=ending_equity,\n        ending_income_value=final_income_value,\n        ending_income_shares=income_holding.shares,\n        ending_swing_equity=final_swing_equity,\n        ending_swing_cash=swing_portfolio.cash,\n        tax_reserve=swing_portfolio.tax_reserve_cash,\n        total_dividends=income_holding.dividends_received,\n        dividend_event_count=dividend_event_count,\n        contribution_count=contribution_count,\n        signal_count=signal_count,\n        rejected_entries=rejected_entries,\n        trades=tuple(swing_portfolio.closed_trades),\n        allocation_events=tuple(allocation_events),\n        equity_curve=tuple(equity_curve),\n    )\n',
    "qpx_bot/report.py": '"""Performance reporting and CSV exports for QPX Bot backtests."""\n\nfrom __future__ import annotations\n\nimport csv\nfrom pathlib import Path\n\nfrom qpx_bot.backtest import BacktestResult\nfrom qpx_bot.hybrid import HybridBacktestResult\n\n\ndef _money(value: float) -> str:\n    return f"${value:,.2f}"\n\n\ndef _percent(value: float) -> str:\n    return f"{value * 100.0:,.2f}%"\n\n\ndef _profit_factor(value: float) -> str:\n    return "∞" if value == float("inf") else f"{value:,.2f}"\n\n\ndef format_backtest_report(result: BacktestResult) -> str:\n    """Return a readable text report for one backtest."""\n    lines = [\n        "=" * 72,\n        "QPX BOT v1.4 — HISTORICAL BACKTEST",\n        "=" * 72,\n        f"Symbol                    : {result.symbol}",\n        f"Period                    : {result.start_date} to {result.end_date}",\n        f"Starting cash             : {_money(result.starting_cash)}",\n        f"Monthly deposits made     : {result.contribution_count}",\n        f"Total contributed capital : {_money(result.total_contributions)}",\n        f"Ending equity             : {_money(result.ending_equity)}",\n        f"Net profit                : {_money(result.net_profit)}",\n        (\n            "Return on contributed capital: "\n            f"{_percent(result.return_on_contributed_capital)}"\n        ),\n        f"Signals accepted          : {result.signal_count}",\n        f"Entries rejected by risk  : {result.rejected_entries}",\n        f"Closed trades             : {len(result.trades)}",\n        f"Win rate                  : {_percent(result.win_rate)}",\n        (\n            "Profit factor             : "\n            f"{_profit_factor(result.profit_factor)}"\n        ),\n        (\n            "Maximum drawdown          : "\n            f"{_percent(result.maximum_drawdown)}"\n        ),\n        f"Tax reserve cash          : {_money(result.tax_reserve)}",\n        "=" * 72,\n        "Research simulation only. This is not live trading or advice.",\n    ]\n\n    return "\\n".join(lines)\n\n\ndef format_hybrid_report(\n    result: HybridBacktestResult,\n) -> str:\n    """Return the combined dividend-plus-swing report."""\n    lines = [\n        "=" * 76,\n        "QPX BOT v1.5 — HYBRID DIVIDEND + SWING BACKTEST",\n        "=" * 76,\n        (\n            f"Sleeves                   : "\n            f"{result.income_symbol} income + "\n            f"{result.swing_symbol} swing"\n        ),\n        (\n            f"Period                    : "\n            f"{result.start_date} to {result.end_date}"\n        ),\n        f"Starting cash             : {_money(result.starting_cash)}",\n        f"Monthly deposits made     : {result.contribution_count}",\n        (\n            "Total contributed capital : "\n            f"{_money(result.total_contributions)}"\n        ),\n        f"Ending combined equity    : {_money(result.ending_equity)}",\n        f"Ending income value       : {_money(result.ending_income_value)}",\n        (\n            f"Ending {result.income_symbol} shares"\n            f"    : {result.ending_income_shares:,.6f}"\n        ),\n        f"Ending swing equity       : {_money(result.ending_swing_equity)}",\n        f"Ending swing cash         : {_money(result.ending_swing_cash)}",\n        f"Dividends routed to swing : {_money(result.total_dividends)}",\n        f"Dividend events processed : {result.dividend_event_count}",\n        f"Net profit                : {_money(result.net_profit)}",\n        (\n            "Return on contributed capital: "\n            f"{_percent(result.return_on_contributed_capital)}"\n        ),\n        f"Signals accepted          : {result.signal_count}",\n        f"Entries rejected by risk  : {result.rejected_entries}",\n        f"Closed swing trades       : {len(result.trades)}",\n        f"Win rate                  : {_percent(result.win_rate)}",\n        (\n            "Profit factor             : "\n            f"{_profit_factor(result.profit_factor)}"\n        ),\n        (\n            "Maximum drawdown          : "\n            f"{_percent(result.maximum_drawdown)}"\n        ),\n        f"Tax reserve cash          : {_money(result.tax_reserve)}",\n        "=" * 76,\n        "Synthetic demo data is execution proof, not performance evidence.",\n        "Research simulation only. This is not live trading or advice.",\n    ]\n\n    return "\\n".join(lines)\n\n\ndef write_trade_log(\n    result: BacktestResult | HybridBacktestResult,\n    filename: str | Path,\n) -> Path:\n    """Write completed trades to a CSV file."""\n    path = Path(filename)\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open("w", newline="", encoding="utf-8") as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Symbol",\n                "EntryDate",\n                "ExitDate",\n                "Shares",\n                "EntryPrice",\n                "ExitPrice",\n                "PnL",\n                "TaxReserved",\n                "ExitReason",\n                "ResultR",\n            ]\n        )\n\n        for trade in result.trades:\n            writer.writerow(\n                [\n                    trade.symbol,\n                    trade.entry_date.isoformat(),\n                    trade.exit_date.isoformat(),\n                    trade.shares,\n                    f"{trade.entry_price:.6f}",\n                    f"{trade.exit_price:.6f}",\n                    f"{trade.pnl:.6f}",\n                    f"{trade.tax_reserved:.6f}",\n                    trade.reason,\n                    f"{trade.result_r:.6f}",\n                ]\n            )\n\n    return path\n\n\ndef write_equity_curve(\n    result: BacktestResult,\n    filename: str | Path,\n) -> Path:\n    """Write single-sleeve end-of-day equity observations."""\n    path = Path(filename)\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open("w", newline="", encoding="utf-8") as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Date",\n                "Equity",\n                "Cash",\n                "MarketValue",\n                "TaxReserve",\n            ]\n        )\n\n        for point in result.equity_curve:\n            writer.writerow(\n                [\n                    point.date.isoformat(),\n                    f"{point.equity:.6f}",\n                    f"{point.cash:.6f}",\n                    f"{point.market_value:.6f}",\n                    f"{point.tax_reserve:.6f}",\n                ]\n            )\n\n    return path\n\n\ndef write_hybrid_equity_curve(\n    result: HybridBacktestResult,\n    filename: str | Path,\n) -> Path:\n    """Write combined income and swing equity observations."""\n    path = Path(filename)\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open("w", newline="", encoding="utf-8") as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            [\n                "Date",\n                "TotalEquity",\n                "IncomeValue",\n                "SwingEquity",\n                "SwingCash",\n                "SwingMarketValue",\n                "TaxReserve",\n                "IncomeShares",\n                "CumulativeDividends",\n                "TotalContributions",\n            ]\n        )\n\n        for point in result.equity_curve:\n            writer.writerow(\n                [\n                    point.date.isoformat(),\n                    f"{point.total_equity:.6f}",\n                    f"{point.income_value:.6f}",\n                    f"{point.swing_equity:.6f}",\n                    f"{point.swing_cash:.6f}",\n                    f"{point.swing_market_value:.6f}",\n                    f"{point.tax_reserve:.6f}",\n                    f"{point.income_shares:.8f}",\n                    f"{point.cumulative_dividends:.6f}",\n                    f"{point.total_contributions:.6f}",\n                ]\n            )\n\n    return path\n',
    "qpx_bot/main.py": '"""QPX Bot command-line entry point."""\n\nfrom __future__ import annotations\n\nfrom pathlib import Path\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import load_csv\nfrom qpx_bot.dividends import load_dividend_csv\nfrom qpx_bot.hybrid import run_hybrid_backtest\nfrom qpx_bot.report import format_hybrid_report\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nSAMPLE_DIR = PACKAGE_DIR / "sample_data"\nDEFAULT_SWING_FILE = SAMPLE_DIR / "sample.csv"\nDEFAULT_INCOME_FILE = SAMPLE_DIR / "qdte_sample.csv"\nDEFAULT_DIVIDEND_FILE = SAMPLE_DIR / "qdte_dividends.csv"\nDEMO_VIX = 20.0\n\n\ndef run(\n    swing_file: str | Path | None = None,\n    income_file: str | Path | None = None,\n    dividend_file: str | Path | None = None,\n) -> int:\n    """Run the permanent hybrid dividend-plus-swing milestone."""\n    config = BotConfig()\n    config.validate()\n\n    selected_swing = (\n        Path(swing_file).expanduser()\n        if swing_file is not None\n        else DEFAULT_SWING_FILE\n    )\n    selected_income = (\n        Path(income_file).expanduser()\n        if income_file is not None\n        else DEFAULT_INCOME_FILE\n    )\n    selected_dividends = (\n        Path(dividend_file).expanduser()\n        if dividend_file is not None\n        else DEFAULT_DIVIDEND_FILE\n    )\n\n    swing_candles = load_csv(selected_swing)\n    income_candles = load_csv(selected_income)\n    dividends = load_dividend_csv(selected_dividends)\n\n    result = run_hybrid_backtest(\n        swing_candles=swing_candles,\n        income_candles=income_candles,\n        dividends=dividends,\n        swing_symbol="SWING",\n        config=config,\n        vix=DEMO_VIX,\n    )\n\n    print(format_hybrid_report(result))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(run())\n',
    "tests/test_qpx_bot_hybrid.py": 'from dataclasses import replace\nfrom datetime import date, timedelta\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.dividends import DividendEvent\nfrom qpx_bot.hybrid import run_hybrid_backtest\nfrom qpx_bot.report import (\n    format_hybrid_report,\n    write_hybrid_equity_curve,\n    write_trade_log,\n)\n\n\nconfig = replace(\n    BotConfig(),\n    starting_cash=10_000.0,\n    monthly_contribution=1_000.0,\n    ema_fast_period=2,\n    ema_slow_period=3,\n    rsi_period=3,\n    rmi_period=3,\n    rmi_momentum=2,\n    sma_trend_period=5,\n    sma_slope_lookback=2,\n    atr_period=3,\n    average_volume_period=3,\n    breakout_lookback=3,\n)\n\nstart = date(2022, 1, 3)\nswing_candles = []\nincome_candles = []\n\nfor index in range(800):\n    day = start + timedelta(days=index)\n    swing_close = 100.0 + (index * 0.02)\n    income_close = 40.0 + (index * 0.01)\n\n    swing_high = swing_close + 1.0\n    swing_low = swing_close - 1.0\n\n    if index == 15:\n        swing_high = 130.0\n        swing_low = swing_close - 0.5\n\n    swing_candles.append(\n        Candle(\n            date=day,\n            open=swing_close,\n            high=swing_high,\n            low=swing_low,\n            close=swing_close + 0.10,\n            volume=3_000_000,\n        )\n    )\n    income_candles.append(\n        Candle(\n            date=day,\n            open=income_close,\n            high=income_close + 0.30,\n            low=income_close - 0.30,\n            close=income_close + 0.05,\n            volume=1_500_000,\n        )\n    )\n\ndividends = [\n    DividendEvent(\n        date=swing_candles[index].date,\n        amount_per_share=0.20,\n    )\n    for index in (20, 40, 400, 700)\n]\n\nresult = run_hybrid_backtest(\n    swing_candles=swing_candles,\n    income_candles=income_candles,\n    dividends=dividends,\n    swing_symbol="TEST",\n    config=config,\n    vix=20.0,\n    forced_entry_indices={10},\n)\n\nassert result.swing_symbol == "TEST"\nassert result.income_symbol == "QDTE"\nassert result.contribution_count >= 25\nassert result.total_contributions == (\n    config.starting_cash\n    + (\n        result.contribution_count\n        * config.monthly_contribution\n    )\n)\nassert result.dividend_event_count == 4\nassert result.total_dividends > 0\nassert result.ending_income_shares > 0\nassert result.ending_income_value > 0\nassert result.ending_swing_equity > 0\nassert result.ending_equity > 0\nassert result.signal_count == 1\nassert len(result.trades) == 1\nassert len(result.equity_curve) == len(swing_candles)\nassert result.allocation_events[0].income_weight == 0.65\nassert result.allocation_events[-1].income_weight == 0.40\nassert 0.0 <= result.maximum_drawdown <= 1.0\n\nreport = format_hybrid_report(result)\nassert "HYBRID DIVIDEND + SWING BACKTEST" in report\nassert "Dividends routed to swing" in report\n\nwith TemporaryDirectory() as temporary_directory:\n    directory = Path(temporary_directory)\n    trades = write_trade_log(\n        result,\n        directory / "hybrid_trades.csv",\n    )\n    equity = write_hybrid_equity_curve(\n        result,\n        directory / "hybrid_equity.csv",\n    )\n\n    assert trades.exists()\n    assert equity.exists()\n    assert "EntryDate" in trades.read_text(encoding="utf-8")\n    assert "IncomeValue" in equity.read_text(encoding="utf-8")\n\nprint("QPX Bot Hybrid Dividend Engine PASS")\n',
}

GENERATED_PATHS = [
    "qpx_bot/sample_data/qdte_sample.csv",
    "qpx_bot/sample_data/qdte_dividends.csv",
]

TARGET_PATHS = [*STATIC_FILES, *GENERATED_PATHS]
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


def ensure_target_files_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGET_PATHS:
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files have uncommitted edits and were "
            "not overwritten:\n" + "\n".join(changed)
        )


def preserve(relative: str) -> None:
    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, backup_path)


def write_static_files() -> None:
    for relative, content in STATIC_FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def generate_income_samples() -> None:
    swing_file = ROOT / "qpx_bot/sample_data/sample.csv"

    if not swing_file.exists():
        raise FileNotFoundError(
            "The existing swing sample CSV was not found."
        )

    for relative in GENERATED_PATHS:
        preserve(relative)

    income_file = ROOT / GENERATED_PATHS[0]
    dividend_file = ROOT / GENERATED_PATHS[1]
    income_file.parent.mkdir(parents=True, exist_ok=True)

    with swing_file.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as source:
        rows = list(csv.DictReader(source))

    if not rows:
        raise ValueError("Swing sample CSV contains no rows.")

    income_rows = []
    dividend_rows = []

    for index, row in enumerate(rows):
        base = (
            40.0
            + (index * 0.018)
            + (math.sin(index / 13.0) * 0.35)
        )
        open_price = base
        close_price = base + (math.sin(index / 5.0) * 0.08)
        high_price = max(open_price, close_price) + 0.25
        low_price = min(open_price, close_price) - 0.25

        income_rows.append(
            {
                "Date": row["Date"],
                "Open": f"{open_price:.4f}",
                "High": f"{high_price:.4f}",
                "Low": f"{low_price:.4f}",
                "Close": f"{close_price:.4f}",
                "Volume": "1500000",
            }
        )

        if index >= 4 and index % 5 == 4:
            dividend_rows.append(
                {
                    "Date": row["Date"],
                    "Dividend": "0.1800",
                }
            )

    with income_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Date",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            ],
        )
        writer.writeheader()
        writer.writerows(income_rows)

    with dividend_file.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["Date", "Dividend"],
        )
        writer.writeheader()
        writer.writerows(dividend_rows)

    print(f"Generated: {GENERATED_PATHS[0]}")
    print(f"Generated: {GENERATED_PATHS[1]}")


def restore() -> None:
    print("Restoring the previous working files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGET_PATHS)

    try:
        installer_relative = str(
            Path(__file__).resolve().relative_to(ROOT)
        )
        paths.append(installer_relative)
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("Hybrid dividend engine is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Implement QPX Bot hybrid dividend portfolio engine",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from a detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 72)
    print("QPX BOT — HYBRID DIVIDEND PORTFOLIO INSTALLER")
    print("=" * 72)
    print(f"Project: {ROOT}")

    ensure_target_files_are_safe()
    write_static_files()

    try:
        generate_income_samples()
        run([sys.executable, "-m", "qpx_bot"])
        run([sys.executable, "tests/run_all_tests.py"])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("=" * 72)
    print("QPX BOT HYBRID DIVIDEND PORTFOLIO ENGINE: COMPLETE")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
