from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    BASELINE_TAX_RESERVE_PROFILE,
    DEFAULT_NET_TAX_RESERVE_REPORT_ROOT,
    NET_REALIZED_TAX_RESERVE_PROFILE,
    _position_size_rejection_diagnostic,
    _reconcile_net_realized_tax_reserve,
    net_realized_tax_reserve_control_main,
)
from qpx_bot.config import BotConfig
from qpx_bot.portfolio import Portfolio


assert BASELINE_TAX_RESERVE_PROFILE == "PER_WINNING_TRADE"
assert (
    NET_REALIZED_TAX_RESERVE_PROFILE
    == "NET_REALIZED_PNL_RESEARCH"
)
assert DEFAULT_NET_TAX_RESERVE_REPORT_ROOT.name == (
    "qpx_net_realized_tax_reserve_2024_08_06_to_2026_07_28"
)
assert callable(
    net_realized_tax_reserve_control_main
)

config = BotConfig()
portfolio = Portfolio(1_000.0)

# Simulate a gross reserve after +$100 realized P&L.
portfolio.realized_pnl = 100.0
portfolio.cash = 963.0
portfolio.tax_reserve_cash = 37.0
released = _reconcile_net_realized_tax_reserve(
    portfolio=portfolio,
    config=config,
)
assert abs(released) < 1e-9
assert abs(portfolio.tax_reserve_cash - 37.0) < 1e-9

# A later $50 realized loss should release half that reserve.
portfolio.realized_pnl = 50.0
released = _reconcile_net_realized_tax_reserve(
    portfolio=portfolio,
    config=config,
)
assert abs(released - 18.5) < 1e-9
assert abs(portfolio.tax_reserve_cash - 18.5) < 1e-9
assert abs(portfolio.cash - 981.5) < 1e-9

# Net realized loss means no research tax reserve remains.
portfolio.realized_pnl = -10.0
released = _reconcile_net_realized_tax_reserve(
    portfolio=portfolio,
    config=config,
)
assert abs(released - 18.5) < 1e-9
assert abs(portfolio.tax_reserve_cash) < 1e-9
assert abs(portfolio.cash - 1_000.0) < 1e-9

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_NET_REALIZED_TAX_RESERVE_CONTROL_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    'BASELINE_TAX_RESERVE_PROFILE = "PER_WINNING_TRADE"',
    '"NET_REALIZED_PNL_RESEARCH"',
    "_reconcile_net_realized_tax_reserve(",
    "_position_size_rejection_diagnostic(",
    "CASH_BELOW_ONE_SHARE",
    "BASE_RISK_BUDGET_BELOW_ONE_SHARE",
    "ACTIVE_RISK_CAP_BELOW_ONE_SHARE",
    "risk_rejection_diagnostics",
    "tax_reserve_released",
    "realized_swing_pnl",
    "net_realized_tax_reserve_control_main(",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "net_realized_tax_reserve_control_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX Net-Realized Tax Reserve "
    "Research Control PASS"
)
