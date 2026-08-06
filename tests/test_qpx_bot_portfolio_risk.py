from datetime import date

from qpx_bot.config import BotConfig
from qpx_bot.portfolio import (
    Portfolio,
    contribution_allocation,
)
from qpx_bot.risk import calculate_position_size


config = BotConfig()
config.validate()

sizing = calculate_position_size(
    account_equity=10_000.0,
    available_cash=10_000.0,
    entry_price=100.0,
    atr=2.0,
    active_risk=0.0,
    config=config,
)

assert sizing.is_tradeable
assert sizing.shares == 20
assert abs(sizing.entry_fill - 100.075) < 1e-9
assert abs(sizing.risk_per_share - 5.0) < 1e-9
assert abs(sizing.planned_risk - 100.0) < 1e-9
assert abs(sizing.stop_price - 95.075) < 1e-9
assert abs(sizing.target_price - 110.075) < 1e-9

capped = calculate_position_size(
    account_equity=10_000.0,
    available_cash=10_000.0,
    entry_price=100.0,
    atr=2.0,
    active_risk=600.0,
    config=config,
)

assert not capped.is_tradeable
assert capped.shares == 0
assert "6%" in (capped.blocked_reason or "")

portfolio = Portfolio(10_000.0)
position = portfolio.open_position(
    symbol="TEST",
    sizing=sizing,
    entry_date=date(2026, 1, 2),
    entry_atr=2.0,
)

assert position.shares == 20
assert abs(portfolio.active_risk() - 100.0) < 1e-9
assert portfolio.cash < 10_000.0

original_stop = position.stop_price
unchanged_stop = portfolio.update_trailing_stop(
    symbol="TEST",
    current_high=104.0,
    current_atr=2.0,
    config=config,
)
assert unchanged_stop == original_stop

raised_stop = portfolio.update_trailing_stop(
    symbol="TEST",
    current_high=108.0,
    current_atr=2.0,
    config=config,
)
assert raised_stop > original_stop

trade = portfolio.close_position(
    symbol="TEST",
    exit_price=110.0,
    exit_date=date(2026, 2, 2),
    reason="target",
    config=config,
)

assert trade.pnl > 0
assert trade.tax_reserved > 0
assert portfolio.tax_reserve_cash == trade.tax_reserved
assert portfolio.realized_pnl == trade.pnl
assert not portfolio.positions

early = contribution_allocation(0, config)
later = contribution_allocation(2, config)

assert early == (0.65, 0.35)
assert later == (0.40, 0.60)

print("QPX Bot Portfolio + Risk PASS")
