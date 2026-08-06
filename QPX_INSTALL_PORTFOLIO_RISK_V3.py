#!/usr/bin/env python3
"""
QPX_INSTALL_PORTFOLIO_RISK_V3.py

Installs the permanent QPX Bot portfolio and risk engine, updates the
legacy skeleton test for the 320-bar dataset, runs all tests, commits, and pushes.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


INSTALLER_NAME = "QPX_INSTALL_PORTFOLIO_RISK_V3.py"
COMMIT_MESSAGE = "Implement QPX Bot portfolio and risk engine"


def find_project_root() -> Path:
    candidates = [Path.cwd().resolve(), Path(__file__).resolve().parent]

    for start in candidates:
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").is_dir()
                and (candidate / "tests").is_dir()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Place this installer in "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_project_root()

FILES = {'qpx_bot/__init__.py': '"""\n'
                        'QPX Bot\n'
                        '\n'
                        'Backtesting bot for the Hybrid Dividend + Swing strategy.\n'
                        '"""\n'
                        '\n'
                        '__version__ = "1.2.0"\n',
 'qpx_bot/risk.py': '"""Position sizing, Kelly sizing, risk caps, and slippage."""\n'
                    '\n'
                    'from __future__ import annotations\n'
                    '\n'
                    'from dataclasses import dataclass\n'
                    'from math import floor\n'
                    'from typing import Sequence\n'
                    '\n'
                    'from qpx_bot.config import BotConfig\n'
                    '\n'
                    '\n'
                    '@dataclass(frozen=True, slots=True)\n'
                    'class PositionSize:\n'
                    '    """A fully specified, risk-controlled trade plan."""\n'
                    '\n'
                    '    shares: int\n'
                    '    entry_fill: float\n'
                    '    stop_price: float\n'
                    '    target_price: float\n'
                    '    risk_per_share: float\n'
                    '    planned_risk: float\n'
                    '    risk_fraction: float\n'
                    '    blocked_reason: str | None = None\n'
                    '\n'
                    '    @property\n'
                    '    def is_tradeable(self) -> bool:\n'
                    '        return self.shares > 0 and self.blocked_reason is None\n'
                    '\n'
                    '\n'
                    'def buy_fill(price: float, slippage_rate: float) -> float:\n'
                    '    """Apply adverse slippage to a buy."""\n'
                    '    if price <= 0:\n'
                    '        raise ValueError("Buy price must be positive.")\n'
                    '    if slippage_rate < 0:\n'
                    '        raise ValueError("Slippage cannot be negative.")\n'
                    '    return price * (1.0 + slippage_rate)\n'
                    '\n'
                    '\n'
                    'def sell_fill(price: float, slippage_rate: float) -> float:\n'
                    '    """Apply adverse slippage to a sell."""\n'
                    '    if price <= 0:\n'
                    '        raise ValueError("Sell price must be positive.")\n'
                    '    if slippage_rate < 0:\n'
                    '        raise ValueError("Slippage cannot be negative.")\n'
                    '    return price * (1.0 - slippage_rate)\n'
                    '\n'
                    '\n'
                    'def quarter_kelly_fraction(\n'
                    '    trade_results_r: Sequence[float],\n'
                    '    config: BotConfig,\n'
                    ') -> float:\n'
                    '    """\n'
                    '    Return the configured fraction of full Kelly.\n'
                    '\n'
                    '    Results are expressed in R multiples. Until enough completed\n'
                    '    trades exist, the configured base risk is used.\n'
                    '    """\n'
                    '    config.validate()\n'
                    '\n'
                    '    if len(trade_results_r) < config.minimum_kelly_trades:\n'
                    '        return config.risk_per_trade\n'
                    '\n'
                    '    wins = [value for value in trade_results_r if value > 0]\n'
                    '    losses = [-value for value in trade_results_r if value < 0]\n'
                    '\n'
                    '    if not wins or not losses:\n'
                    '        return config.risk_per_trade if wins else 0.0\n'
                    '\n'
                    '    win_probability = len(wins) / len(trade_results_r)\n'
                    '    average_win = sum(wins) / len(wins)\n'
                    '    average_loss = sum(losses) / len(losses)\n'
                    '    payoff_ratio = average_win / average_loss\n'
                    '\n'
                    '    if payoff_ratio <= 0:\n'
                    '        return 0.0\n'
                    '\n'
                    '    full_kelly = (\n'
                    '        win_probability\n'
                    '        - ((1.0 - win_probability) / payoff_ratio)\n'
                    '    )\n'
                    '    fractional_kelly = max(0.0, full_kelly) * config.kelly_fraction\n'
                    '\n'
                    '    return min(config.risk_per_trade, fractional_kelly)\n'
                    '\n'
                    '\n'
                    'def calculate_position_size(\n'
                    '    *,\n'
                    '    account_equity: float,\n'
                    '    available_cash: float,\n'
                    '    entry_price: float,\n'
                    '    atr: float,\n'
                    '    active_risk: float,\n'
                    '    config: BotConfig,\n'
                    '    trade_results_r: Sequence[float] = (),\n'
                    ') -> PositionSize:\n'
                    '    """Calculate an integer share quantity under every risk limit."""\n'
                    '    config.validate()\n'
                    '\n'
                    '    numeric_values = {\n'
                    '        "account equity": account_equity,\n'
                    '        "available cash": available_cash,\n'
                    '        "entry price": entry_price,\n'
                    '        "ATR": atr,\n'
                    '        "active risk": active_risk,\n'
                    '    }\n'
                    '\n'
                    '    for name, value in numeric_values.items():\n'
                    '        if value < 0:\n'
                    '            raise ValueError(f"{name.capitalize()} cannot be negative.")\n'
                    '\n'
                    '    if account_equity == 0 or available_cash == 0:\n'
                    '        return PositionSize(\n'
                    '            shares=0,\n'
                    '            entry_fill=0.0,\n'
                    '            stop_price=0.0,\n'
                    '            target_price=0.0,\n'
                    '            risk_per_share=0.0,\n'
                    '            planned_risk=0.0,\n'
                    '            risk_fraction=0.0,\n'
                    '            blocked_reason="No available capital.",\n'
                    '        )\n'
                    '\n'
                    '    if entry_price <= 0:\n'
                    '        raise ValueError("Entry price must be positive.")\n'
                    '\n'
                    '    if atr <= 0:\n'
                    '        raise ValueError("ATR must be positive.")\n'
                    '\n'
                    '    risk_fraction = quarter_kelly_fraction(\n'
                    '        trade_results_r,\n'
                    '        config,\n'
                    '    )\n'
                    '\n'
                    '    if risk_fraction <= 0:\n'
                    '        return PositionSize(\n'
                    '            shares=0,\n'
                    '            entry_fill=0.0,\n'
                    '            stop_price=0.0,\n'
                    '            target_price=0.0,\n'
                    '            risk_per_share=0.0,\n'
                    '            planned_risk=0.0,\n'
                    '            risk_fraction=0.0,\n'
                    '            blocked_reason="Kelly sizing blocked the trade.",\n'
                    '        )\n'
                    '\n'
                    '    maximum_total_risk = (\n'
                    '        account_equity\n'
                    '        * config.maximum_active_portfolio_risk\n'
                    '    )\n'
                    '    remaining_risk_capacity = max(\n'
                    '        0.0,\n'
                    '        maximum_total_risk - active_risk,\n'
                    '    )\n'
                    '\n'
                    '    if remaining_risk_capacity <= 0:\n'
                    '        return PositionSize(\n'
                    '            shares=0,\n'
                    '            entry_fill=0.0,\n'
                    '            stop_price=0.0,\n'
                    '            target_price=0.0,\n'
                    '            risk_per_share=0.0,\n'
                    '            planned_risk=0.0,\n'
                    '            risk_fraction=risk_fraction,\n'
                    '            blocked_reason="The 6% active-risk cap is full.",\n'
                    '        )\n'
                    '\n'
                    '    entry_fill = buy_fill(\n'
                    '        entry_price,\n'
                    '        config.slippage_rate,\n'
                    '    )\n'
                    '    risk_per_share = atr * config.stop_atr_multiple\n'
                    '    requested_risk = account_equity * risk_fraction\n'
                    '    risk_budget = min(\n'
                    '        requested_risk,\n'
                    '        remaining_risk_capacity,\n'
                    '    )\n'
                    '\n'
                    '    shares_by_risk = floor(risk_budget / risk_per_share)\n'
                    '    shares_by_cash = floor(available_cash / entry_fill)\n'
                    '    shares = max(0, min(shares_by_risk, shares_by_cash))\n'
                    '\n'
                    '    if shares == 0:\n'
                    '        return PositionSize(\n'
                    '            shares=0,\n'
                    '            entry_fill=entry_fill,\n'
                    '            stop_price=entry_fill - risk_per_share,\n'
                    '            target_price=(\n'
                    '                entry_fill\n'
                    '                + (atr * config.target_atr_multiple)\n'
                    '            ),\n'
                    '            risk_per_share=risk_per_share,\n'
                    '            planned_risk=0.0,\n'
                    '            risk_fraction=risk_fraction,\n'
                    '            blocked_reason=(\n'
                    '                "Risk budget or cash is too small for one share."\n'
                    '            ),\n'
                    '        )\n'
                    '\n'
                    '    return PositionSize(\n'
                    '        shares=shares,\n'
                    '        entry_fill=entry_fill,\n'
                    '        stop_price=entry_fill - risk_per_share,\n'
                    '        target_price=(\n'
                    '            entry_fill\n'
                    '            + (atr * config.target_atr_multiple)\n'
                    '        ),\n'
                    '        risk_per_share=risk_per_share,\n'
                    '        planned_risk=shares * risk_per_share,\n'
                    '        risk_fraction=risk_fraction,\n'
                    '    )\n',
 'qpx_bot/portfolio.py': '"""Cash, positions, realized gains, taxes, and portfolio equity."""\n'
                         '\n'
                         'from __future__ import annotations\n'
                         '\n'
                         'from dataclasses import dataclass, field\n'
                         'from datetime import date\n'
                         'from typing import Mapping\n'
                         '\n'
                         'from qpx_bot.config import BotConfig\n'
                         'from qpx_bot.risk import PositionSize, sell_fill\n'
                         '\n'
                         '\n'
                         '@dataclass(slots=True)\n'
                         'class Position:\n'
                         '    symbol: str\n'
                         '    shares: int\n'
                         '    entry_date: date\n'
                         '    entry_price: float\n'
                         '    entry_atr: float\n'
                         '    stop_price: float\n'
                         '    target_price: float\n'
                         '    highest_price: float\n'
                         '\n'
                         '    @property\n'
                         '    def cost_basis(self) -> float:\n'
                         '        return self.entry_price * self.shares\n'
                         '\n'
                         '    @property\n'
                         '    def active_risk(self) -> float:\n'
                         '        return (\n'
                         '            max(0.0, self.entry_price - self.stop_price)\n'
                         '            * self.shares\n'
                         '        )\n'
                         '\n'
                         '\n'
                         '@dataclass(frozen=True, slots=True)\n'
                         'class ClosedTrade:\n'
                         '    symbol: str\n'
                         '    entry_date: date\n'
                         '    exit_date: date\n'
                         '    shares: int\n'
                         '    entry_price: float\n'
                         '    exit_price: float\n'
                         '    pnl: float\n'
                         '    tax_reserved: float\n'
                         '    reason: str\n'
                         '    result_r: float\n'
                         '\n'
                         '\n'
                         '@dataclass(slots=True)\n'
                         'class Portfolio:\n'
                         '    starting_cash: float\n'
                         '    cash: float = field(init=False)\n'
                         '    tax_reserve_cash: float = 0.0\n'
                         '    total_contributions: float = field(init=False)\n'
                         '    realized_pnl: float = 0.0\n'
                         '    positions: dict[str, Position] = field(default_factory=dict)\n'
                         '    closed_trades: list[ClosedTrade] = field(default_factory=list)\n'
                         '\n'
                         '    def __post_init__(self) -> None:\n'
                         '        if self.starting_cash < 0:\n'
                         '            raise ValueError("Starting cash cannot be negative.")\n'
                         '        self.cash = float(self.starting_cash)\n'
                         '        self.total_contributions = float(self.starting_cash)\n'
                         '\n'
                         '    def deposit(self, amount: float) -> None:\n'
                         '        """Add external capital to the investable cash balance."""\n'
                         '        if amount <= 0:\n'
                         '            raise ValueError("Deposit amount must be positive.")\n'
                         '        self.cash += amount\n'
                         '        self.total_contributions += amount\n'
                         '\n'
                         '    def active_risk(self) -> float:\n'
                         '        return sum(\n'
                         '            position.active_risk\n'
                         '            for position in self.positions.values()\n'
                         '        )\n'
                         '\n'
                         '    def open_position(\n'
                         '        self,\n'
                         '        *,\n'
                         '        symbol: str,\n'
                         '        sizing: PositionSize,\n'
                         '        entry_date: date,\n'
                         '        entry_atr: float,\n'
                         '    ) -> Position:\n'
                         '        """Open one risk-sized position and deduct its full cost."""\n'
                         '        normalized_symbol = symbol.strip().upper()\n'
                         '\n'
                         '        if not normalized_symbol:\n'
                         '            raise ValueError("Symbol cannot be empty.")\n'
                         '\n'
                         '        if normalized_symbol in self.positions:\n'
                         '            raise ValueError(\n'
                         '                f"A position in {normalized_symbol} is already open."\n'
                         '            )\n'
                         '\n'
                         '        if not sizing.is_tradeable:\n'
                         '            raise ValueError(\n'
                         '                sizing.blocked_reason\n'
                         '                or "The position size is not tradeable."\n'
                         '            )\n'
                         '\n'
                         '        total_cost = sizing.entry_fill * sizing.shares\n'
                         '\n'
                         '        if total_cost > self.cash + 1e-9:\n'
                         '            raise ValueError("Insufficient cash for this position.")\n'
                         '\n'
                         '        position = Position(\n'
                         '            symbol=normalized_symbol,\n'
                         '            shares=sizing.shares,\n'
                         '            entry_date=entry_date,\n'
                         '            entry_price=sizing.entry_fill,\n'
                         '            entry_atr=entry_atr,\n'
                         '            stop_price=sizing.stop_price,\n'
                         '            target_price=sizing.target_price,\n'
                         '            highest_price=sizing.entry_fill,\n'
                         '        )\n'
                         '\n'
                         '        self.cash -= total_cost\n'
                         '        self.positions[normalized_symbol] = position\n'
                         '        return position\n'
                         '\n'
                         '    def update_trailing_stop(\n'
                         '        self,\n'
                         '        *,\n'
                         '        symbol: str,\n'
                         '        current_high: float,\n'
                         '        current_atr: float,\n'
                         '        config: BotConfig,\n'
                         '    ) -> float:\n'
                         '        """Activate and raise the ATR trailing stop; never lower it."""\n'
                         '        normalized_symbol = symbol.strip().upper()\n'
                         '        position = self.positions[normalized_symbol]\n'
                         '\n'
                         '        if current_high <= 0 or current_atr <= 0:\n'
                         '            raise ValueError(\n'
                         '                "Current high and ATR must be positive."\n'
                         '            )\n'
                         '\n'
                         '        position.highest_price = max(\n'
                         '            position.highest_price,\n'
                         '            current_high,\n'
                         '        )\n'
                         '\n'
                         '        activation_price = (\n'
                         '            position.entry_price\n'
                         '            + (\n'
                         '                position.entry_atr\n'
                         '                * config.trailing_activation_atr\n'
                         '            )\n'
                         '        )\n'
                         '\n'
                         '        if position.highest_price >= activation_price:\n'
                         '            candidate = (\n'
                         '                position.highest_price\n'
                         '                - (\n'
                         '                    current_atr\n'
                         '                    * config.stop_atr_multiple\n'
                         '                )\n'
                         '            )\n'
                         '            position.stop_price = max(\n'
                         '                position.stop_price,\n'
                         '                candidate,\n'
                         '            )\n'
                         '\n'
                         '        return position.stop_price\n'
                         '\n'
                         '    def close_position(\n'
                         '        self,\n'
                         '        *,\n'
                         '        symbol: str,\n'
                         '        exit_price: float,\n'
                         '        exit_date: date,\n'
                         '        reason: str,\n'
                         '        config: BotConfig,\n'
                         '    ) -> ClosedTrade:\n'
                         '        """Close a position, apply slippage, and reserve gain taxes."""\n'
                         '        normalized_symbol = symbol.strip().upper()\n'
                         '        position = self.positions.pop(normalized_symbol)\n'
                         '        fill = sell_fill(exit_price, config.slippage_rate)\n'
                         '        proceeds = fill * position.shares\n'
                         '        pnl = (\n'
                         '            (fill - position.entry_price)\n'
                         '            * position.shares\n'
                         '        )\n'
                         '        tax_reserved = (\n'
                         '            max(0.0, pnl)\n'
                         '            * config.annual_tax_reserve_rate\n'
                         '        )\n'
                         '\n'
                         '        self.cash += proceeds - tax_reserved\n'
                         '        self.tax_reserve_cash += tax_reserved\n'
                         '        self.realized_pnl += pnl\n'
                         '\n'
                         '        initial_risk = (\n'
                         '            position.entry_atr\n'
                         '            * config.stop_atr_multiple\n'
                         '            * position.shares\n'
                         '        )\n'
                         '        result_r = (\n'
                         '            pnl / initial_risk\n'
                         '            if initial_risk > 0\n'
                         '            else 0.0\n'
                         '        )\n'
                         '\n'
                         '        trade = ClosedTrade(\n'
                         '            symbol=normalized_symbol,\n'
                         '            entry_date=position.entry_date,\n'
                         '            exit_date=exit_date,\n'
                         '            shares=position.shares,\n'
                         '            entry_price=position.entry_price,\n'
                         '            exit_price=fill,\n'
                         '            pnl=pnl,\n'
                         '            tax_reserved=tax_reserved,\n'
                         '            reason=reason,\n'
                         '            result_r=result_r,\n'
                         '        )\n'
                         '        self.closed_trades.append(trade)\n'
                         '        return trade\n'
                         '\n'
                         '    def market_value(\n'
                         '        self,\n'
                         '        prices: Mapping[str, float],\n'
                         '    ) -> float:\n'
                         '        value = 0.0\n'
                         '\n'
                         '        for symbol, position in self.positions.items():\n'
                         '            if symbol not in prices:\n'
                         '                raise KeyError(\n'
                         '                    f"Missing market price for {symbol}."\n'
                         '                )\n'
                         '            value += prices[symbol] * position.shares\n'
                         '\n'
                         '        return value\n'
                         '\n'
                         '    def equity(\n'
                         '        self,\n'
                         '        prices: Mapping[str, float],\n'
                         '    ) -> float:\n'
                         '        """Return investable cash, tax reserve, and open positions."""\n'
                         '        return (\n'
                         '            self.cash\n'
                         '            + self.tax_reserve_cash\n'
                         '            + self.market_value(prices)\n'
                         '        )\n'
                         '\n'
                         '\n'
                         'def contribution_allocation(\n'
                         '    elapsed_years: int,\n'
                         '    config: BotConfig,\n'
                         ') -> tuple[float, float]:\n'
                         '    """Return dividend and swing allocation weights."""\n'
                         '    if elapsed_years < 0:\n'
                         '        raise ValueError("Elapsed years cannot be negative.")\n'
                         '\n'
                         '    if elapsed_years < 2:\n'
                         '        return (\n'
                         '            config.dividend_allocation_years_1_2,\n'
                         '            config.swing_allocation_years_1_2,\n'
                         '        )\n'
                         '\n'
                         '    return (\n'
                         '        config.dividend_allocation_later,\n'
                         '        config.swing_allocation_later,\n'
                         '    )\n',
 'qpx_bot/main.py': '"""QPX Bot command-line entry point."""\n'
                    '\n'
                    'from __future__ import annotations\n'
                    '\n'
                    'from datetime import date\n'
                    'from pathlib import Path\n'
                    '\n'
                    'from qpx_bot.config import BotConfig\n'
                    'from qpx_bot.data_loader import load_csv\n'
                    'from qpx_bot.indicators import calculate_indicators\n'
                    'from qpx_bot.portfolio import Portfolio, contribution_allocation\n'
                    'from qpx_bot.risk import calculate_position_size\n'
                    '\n'
                    '\n'
                    'PACKAGE_DIR = Path(__file__).resolve().parent\n'
                    'DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"\n'
                    '\n'
                    '\n'
                    'def run(data_file: str | Path | None = None) -> int:\n'
                    '    """Validate indicators, risk sizing, and portfolio accounting."""\n'
                    '    config = BotConfig()\n'
                    '    config.validate()\n'
                    '\n'
                    '    selected_file = (\n'
                    '        Path(data_file).expanduser()\n'
                    '        if data_file is not None\n'
                    '        else DEFAULT_DATA_FILE\n'
                    '    )\n'
                    '\n'
                    '    candles = load_csv(selected_file)\n'
                    '    indicators = calculate_indicators(candles, config)\n'
                    '    latest_index = indicators.latest_complete_index()\n'
                    '\n'
                    '    print("=" * 68)\n'
                    '    print("QPX BOT v1.2 — PORTFOLIO + RISK ENGINE")\n'
                    '    print("=" * 68)\n'
                    '    print(f"Data file      : {selected_file}")\n'
                    '    print(f"Candles loaded : {len(candles)}")\n'
                    '\n'
                    '    if latest_index is None:\n'
                    '        print("Status          : INSUFFICIENT DATA")\n'
                    '        return 1\n'
                    '\n'
                    '    candle = candles[latest_index]\n'
                    '    atr = indicators.atr[latest_index]\n'
                    '\n'
                    '    if atr is None:\n'
                    '        print("Status          : ATR NOT READY")\n'
                    '        return 1\n'
                    '\n'
                    '    portfolio = Portfolio(config.starting_cash)\n'
                    '    sizing = calculate_position_size(\n'
                    '        account_equity=portfolio.equity({}),\n'
                    '        available_cash=portfolio.cash,\n'
                    '        entry_price=candle.close,\n'
                    '        atr=atr,\n'
                    '        active_risk=portfolio.active_risk(),\n'
                    '        config=config,\n'
                    '    )\n'
                    '    income_weight, swing_weight = contribution_allocation(\n'
                    '        0,\n'
                    '        config,\n'
                    '    )\n'
                    '\n'
                    '    print(f"Latest date     : {candle.date}")\n'
                    '    print(f"Close           : ${candle.close:,.2f}")\n'
                    '    print(f"ATR             : {atr:,.4f}")\n'
                    '    print(f"Risk fraction   : {sizing.risk_fraction:.2%}")\n'
                    '    print(f"Planned shares  : {sizing.shares}")\n'
                    '    print(f"Planned risk    : ${sizing.planned_risk:,.2f}")\n'
                    '    print(f"Stop price      : ${sizing.stop_price:,.2f}")\n'
                    '    print(f"Target price    : ${sizing.target_price:,.2f}")\n'
                    '    print(\n'
                    '        "Contribution mix: "\n'
                    '        f"{income_weight:.0%} income / "\n'
                    '        f"{swing_weight:.0%} swing"\n'
                    '    )\n'
                    '\n'
                    '    if sizing.is_tradeable:\n'
                    '        portfolio.open_position(\n'
                    '            symbol="DEMO",\n'
                    '            sizing=sizing,\n'
                    '            entry_date=date.today(),\n'
                    '            entry_atr=atr,\n'
                    '        )\n'
                    '        print(\n'
                    '            f"Active risk     : "\n'
                    '            f"${portfolio.active_risk():,.2f}"\n'
                    '        )\n'
                    '        print(f"Cash remaining  : ${portfolio.cash:,.2f}")\n'
                    '    else:\n'
                    '        print(\n'
                    '            f"Trade status    : {sizing.blocked_reason}"\n'
                    '        )\n'
                    '\n'
                    '    print("Tax reserve     : $0.00")\n'
                    '    print("Status          : PASS")\n'
                    '    print("=" * 68)\n'
                    '    return 0\n'
                    '\n'
                    '\n'
                    'if __name__ == "__main__":\n'
                    '    raise SystemExit(run())\n',
 'tests/test_qpx_bot_portfolio_risk.py': 'from datetime import date\n'
                                         '\n'
                                         'from qpx_bot.config import BotConfig\n'
                                         'from qpx_bot.portfolio import (\n'
                                         '    Portfolio,\n'
                                         '    contribution_allocation,\n'
                                         ')\n'
                                         'from qpx_bot.risk import calculate_position_size\n'
                                         '\n'
                                         '\n'
                                         'config = BotConfig()\n'
                                         'config.validate()\n'
                                         '\n'
                                         'sizing = calculate_position_size(\n'
                                         '    account_equity=10_000.0,\n'
                                         '    available_cash=10_000.0,\n'
                                         '    entry_price=100.0,\n'
                                         '    atr=2.0,\n'
                                         '    active_risk=0.0,\n'
                                         '    config=config,\n'
                                         ')\n'
                                         '\n'
                                         'assert sizing.is_tradeable\n'
                                         'assert sizing.shares == 20\n'
                                         'assert abs(sizing.entry_fill - 100.075) < 1e-9\n'
                                         'assert abs(sizing.risk_per_share - 5.0) < 1e-9\n'
                                         'assert abs(sizing.planned_risk - 100.0) < 1e-9\n'
                                         'assert abs(sizing.stop_price - 95.075) < 1e-9\n'
                                         'assert abs(sizing.target_price - 110.075) < 1e-9\n'
                                         '\n'
                                         'capped = calculate_position_size(\n'
                                         '    account_equity=10_000.0,\n'
                                         '    available_cash=10_000.0,\n'
                                         '    entry_price=100.0,\n'
                                         '    atr=2.0,\n'
                                         '    active_risk=600.0,\n'
                                         '    config=config,\n'
                                         ')\n'
                                         '\n'
                                         'assert not capped.is_tradeable\n'
                                         'assert capped.shares == 0\n'
                                         'assert "6%" in (capped.blocked_reason or "")\n'
                                         '\n'
                                         'portfolio = Portfolio(10_000.0)\n'
                                         'position = portfolio.open_position(\n'
                                         '    symbol="TEST",\n'
                                         '    sizing=sizing,\n'
                                         '    entry_date=date(2026, 1, 2),\n'
                                         '    entry_atr=2.0,\n'
                                         ')\n'
                                         '\n'
                                         'assert position.shares == 20\n'
                                         'assert abs(portfolio.active_risk() - 100.0) < 1e-9\n'
                                         'assert portfolio.cash < 10_000.0\n'
                                         '\n'
                                         'original_stop = position.stop_price\n'
                                         'unchanged_stop = portfolio.update_trailing_stop(\n'
                                         '    symbol="TEST",\n'
                                         '    current_high=104.0,\n'
                                         '    current_atr=2.0,\n'
                                         '    config=config,\n'
                                         ')\n'
                                         'assert unchanged_stop == original_stop\n'
                                         '\n'
                                         'raised_stop = portfolio.update_trailing_stop(\n'
                                         '    symbol="TEST",\n'
                                         '    current_high=108.0,\n'
                                         '    current_atr=2.0,\n'
                                         '    config=config,\n'
                                         ')\n'
                                         'assert raised_stop > original_stop\n'
                                         '\n'
                                         'trade = portfolio.close_position(\n'
                                         '    symbol="TEST",\n'
                                         '    exit_price=110.0,\n'
                                         '    exit_date=date(2026, 2, 2),\n'
                                         '    reason="target",\n'
                                         '    config=config,\n'
                                         ')\n'
                                         '\n'
                                         'assert trade.pnl > 0\n'
                                         'assert trade.tax_reserved > 0\n'
                                         'assert portfolio.tax_reserve_cash == trade.tax_reserved\n'
                                         'assert portfolio.realized_pnl == trade.pnl\n'
                                         'assert not portfolio.positions\n'
                                         '\n'
                                         'early = contribution_allocation(0, config)\n'
                                         'later = contribution_allocation(2, config)\n'
                                         '\n'
                                         'assert early == (0.65, 0.35)\n'
                                         'assert later == (0.40, 0.60)\n'
                                         '\n'
                                         'print("QPX Bot Portfolio + Risk PASS")\n',
 'tests/test_qpx_bot_skeleton.py': 'from pathlib import Path\n'
                                   '\n'
                                   'from qpx_bot.config import BotConfig\n'
                                   'from qpx_bot.data_loader import closing_prices, load_csv\n'
                                   '\n'
                                   '\n'
                                   'project_root = Path(__file__).resolve().parents[1]\n'
                                   'sample_file = (\n'
                                   '    project_root\n'
                                   '    / "qpx_bot"\n'
                                   '    / "sample_data"\n'
                                   '    / "sample.csv"\n'
                                   ')\n'
                                   '\n'
                                   'config = BotConfig()\n'
                                   'config.validate()\n'
                                   '\n'
                                   'candles = load_csv(sample_file)\n'
                                   'prices = closing_prices(candles)\n'
                                   '\n'
                                   'assert config.starting_cash == 1300.0\n'
                                   'assert len(candles) >= config.sma_trend_period\n'
                                   'assert candles[0].date < candles[-1].date\n'
                                   'assert len(prices) == len(candles)\n'
                                   'assert all(price > 0 for price in prices)\n'
                                   '\n'
                                   'print("QPX Bot Skeleton PASS")\n'}


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("$", " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        check=check,
    )


def ensure_safe_worktree() -> None:
    """Allow unrelated untracked files while protecting tracked work.

    The installer stages only its own target files. Existing untracked
    files elsewhere in QPX_ALPHA are therefore left untouched.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )

    target_paths = set(FILES)
    installer_names = {
        INSTALLER_NAME,
        "QPX_INSTALL_PORTFOLIO_RISK.py",
        "QPX_INSTALL_PORTFOLIO_RISK_V2.py",
        "QPX_INSTALL_INDICATORS.py",
    }
    unsafe: list[str] = []

    for raw_line in result.stdout.splitlines():
        status = raw_line[:2]
        path = raw_line[3:].strip()
        normalized = path.rstrip("/")

        if normalized in installer_names:
            continue

        if status == "??":
            conflicts_with_target = any(
                target == normalized
                or target.startswith(normalized + "/")
                or normalized.startswith(target + "/")
                for target in target_paths
            )
            if conflicts_with_target:
                unsafe.append(raw_line)
            continue

        unsafe.append(raw_line)

    if unsafe:
        details = "\n".join(unsafe)
        raise RuntimeError(
            "The installer found tracked edits or an untracked file that "
            "would be overwritten.\n"
            "These items were not changed:\n"
            f"{details}"
        )


def write_files(backup_root: Path) -> tuple[list[Path], list[Path]]:
    created: list[Path] = []
    replaced: list[Path] = []

    for relative, source in FILES.items():
        destination = ROOT / relative

        if destination.exists():
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(destination.read_bytes())
            replaced.append(destination)
        else:
            created.append(destination)

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source, encoding="utf-8")
        print(f"Installed: {relative}")

    return created, replaced


def rollback(
    backup_root: Path,
    created: list[Path],
    replaced: list[Path],
) -> None:
    print("Restoring the previous working files...")

    for path in created:
        if path.exists():
            path.unlink()

    for path in replaced:
        relative = path.relative_to(ROOT)
        backup = backup_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(backup.read_bytes())


def commit_and_push() -> None:
    paths = list(FILES)

    installer_path = Path(__file__).resolve()

    if installer_path.parent == ROOT:
        paths.append(INSTALLER_NAME)

    run(["git", "add", "--", *paths])

    diff_result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if diff_result.returncode == 0:
        print("No new Git changes were required.")
        return

    run(["git", "commit", "-m", COMMIT_MESSAGE])
    run(["git", "push"])


def main() -> int:
    print("=" * 68)
    print("QPX BOT — PORTFOLIO + RISK INSTALLER")
    print("=" * 68)
    print(f"Project: {ROOT}")

    ensure_safe_worktree()

    with tempfile.TemporaryDirectory(
        prefix="qpx_portfolio_risk_backup_"
    ) as temporary:
        backup_root = Path(temporary)
        created: list[Path] = []
        replaced: list[Path] = []

        try:
            created, replaced = write_files(backup_root)
            run([sys.executable, "-m", "qpx_bot"])
            run([sys.executable, "tests/run_all_tests.py"])
            commit_and_push()
        except Exception:
            rollback(
                backup_root,
                created,
                replaced,
            )
            raise

    print()
    print("=" * 68)
    print("QPX BOT PORTFOLIO + RISK ENGINE: COMPLETE")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
