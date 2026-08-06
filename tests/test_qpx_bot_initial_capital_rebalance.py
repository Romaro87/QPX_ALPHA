from qpx_bot.allocation import (
    rebalance_income_allocation,
)
from qpx_bot.config import BotConfig


config = BotConfig()
config.validate()

assert config.starting_cash == 1_300.0
assert config.starting_swing_cash == 1_500.0
assert config.total_starting_capital == 2_800.0

buy = rebalance_income_allocation(
    income_shares=32.5,
    income_cost=1_300.0,
    swing_cash=1_500.0,
    swing_market_value=0.0,
    income_price=40.0,
    target_income_weight=0.65,
    slippage_rate=config.slippage_rate,
    tax_reserve_rate=config.annual_tax_reserve_rate,
    tolerance=config.allocation_rebalance_tolerance,
    minimum_trade=config.minimum_rebalance_trade,
)

assert buy.action == "BUY"
assert buy.shares_after > buy.shares_before
assert buy.swing_cash_after < buy.swing_cash_before
assert abs(buy.after_income_weight - 0.65) < 1e-8
assert buy.tax_reserved == 0.0

sell = rebalance_income_allocation(
    income_shares=100.0,
    income_cost=2_000.0,
    swing_cash=500.0,
    swing_market_value=500.0,
    income_price=50.0,
    target_income_weight=0.40,
    slippage_rate=config.slippage_rate,
    tax_reserve_rate=config.annual_tax_reserve_rate,
    tolerance=config.allocation_rebalance_tolerance,
    minimum_trade=config.minimum_rebalance_trade,
)

assert sell.action == "SELL"
assert sell.shares_after < sell.shares_before
assert sell.swing_cash_after > sell.swing_cash_before
assert sell.realized_pnl > 0
assert sell.tax_reserved > 0
assert abs(sell.after_income_weight - 0.40) < 1e-8

partial = rebalance_income_allocation(
    income_shares=1.0,
    income_cost=40.0,
    swing_cash=10.0,
    swing_market_value=1_000.0,
    income_price=40.0,
    target_income_weight=0.65,
    slippage_rate=config.slippage_rate,
    tax_reserve_rate=config.annual_tax_reserve_rate,
    tolerance=config.allocation_rebalance_tolerance,
    minimum_trade=config.minimum_rebalance_trade,
)

assert partial.action == "PARTIAL_BUY"
assert partial.swing_cash_after == 0.0
assert not partial.target_fully_reached

from pathlib import Path

report_source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "report.py"
).read_text(encoding="utf-8")
backtest_section, hybrid_section = report_source.split(
    "def format_hybrid_report",
    1,
)

assert "result.starting_income_cash" not in backtest_section
assert "result.starting_swing_cash" not in backtest_section
assert "result.starting_income_cash" in hybrid_section
assert "result.starting_swing_cash" in hybrid_section
assert "Initial total capital" in hybrid_section
assert "Monthly rebalances" in hybrid_section

print("QPX Bot Initial Capital and Rebalance PASS")
