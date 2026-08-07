from dataclasses import replace as dc_replace
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    BASELINE_NOTIONAL_PROFILE,
    DEFAULT_NOTIONAL_CAP_REPORT_ROOT,
    NOTIONAL_CAP_16PCT_PROFILE,
    RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION,
    _apply_position_notional_cap,
    position_notional_cap_control_main,
)
from qpx_bot.risk import PositionSize


assert BASELINE_NOTIONAL_PROFILE == "NO_POSITION_NOTIONAL_CAP"
assert (
    NOTIONAL_CAP_16PCT_PROFILE
    == "MAX_16PCT_ACCOUNT_EQUITY_ONE_SHARE_FLOOR_RESEARCH"
)
assert RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION == 0.16
assert DEFAULT_NOTIONAL_CAP_REPORT_ROOT.name == (
    "qpx_16pct_notional_cap_2024_08_06_to_2026_07_28"
)
assert callable(
    position_notional_cap_control_main
)

base = PositionSize(
    shares=10,
    entry_fill=100.0,
    stop_price=95.0,
    target_price=110.0,
    risk_per_share=5.0,
    planned_risk=50.0,
    risk_fraction=0.01,
)

capped, adjusted, floor_used = _apply_position_notional_cap(
    sizing=base,
    account_equity=2_000.0,
    notional_profile=NOTIONAL_CAP_16PCT_PROFILE,
)
assert adjusted is True
assert floor_used is False
assert capped.shares == 3
assert abs(capped.planned_risk - 15.0) < 1e-9

expensive = dc_replace(
    base,
    shares=2,
    entry_fill=500.0,
    risk_per_share=10.0,
    planned_risk=20.0,
)
capped, adjusted, floor_used = _apply_position_notional_cap(
    sizing=expensive,
    account_equity=2_000.0,
    notional_profile=NOTIONAL_CAP_16PCT_PROFILE,
)
assert adjusted is True
assert floor_used is True
assert capped.shares == 1
assert abs(capped.planned_risk - 10.0) < 1e-9

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_16PCT_POSITION_NOTIONAL_CONTROL_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    'BASELINE_NOTIONAL_PROFILE = "NO_POSITION_NOTIONAL_CAP"',
    '"MAX_16PCT_ACCOUNT_EQUITY_ONE_SHARE_FLOOR_RESEARCH"',
    "RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION = 0.16",
    "_apply_position_notional_cap(",
    "notional_cap_adjustments",
    "one_share_floor_uses",
    "Position notional target",
    "position_notional_cap_control_main(",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "position_notional_cap_control_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX 16% Position Notional "
    "Research Control PASS"
)
