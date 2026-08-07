from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    BASELINE_RISK_PROFILE,
    DEFAULT_RELAXED_NO_KELLY_REPORT_ROOT,
    FIXED_ONE_PERCENT_RISK_PROFILE,
    RELAXED_ENTRY_PROFILE,
    relaxed_swing_no_kelly_control_main,
)


assert BASELINE_RISK_PROFILE == "KELLY_AFTER_20"
assert (
    FIXED_ONE_PERCENT_RISK_PROFILE
    == "FIXED_1PCT_NO_KELLY_RESEARCH"
)
assert (
    RELAXED_ENTRY_PROFILE
    == "RELAXED_FREQUENCY_RESEARCH_V1"
)
assert DEFAULT_RELAXED_NO_KELLY_REPORT_ROOT.name == (
    "qpx_relaxed_swing_no_kelly_2024_08_06_to_2026_07_28"
)
assert callable(
    relaxed_swing_no_kelly_control_main
)

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_RELAXED_SWING_NO_KELLY_CONTROL_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    'BASELINE_RISK_PROFILE = "KELLY_AFTER_20"',
    '"FIXED_1PCT_NO_KELLY_RESEARCH"',
    "risk_profile: str = BASELINE_RISK_PROFILE",
    "kelly_enabled = (",
    "if kelly_enabled",
    "else ()",
    "risk_rejection_reasons",
    "Adaptive Kelly sizing",
    "maximum_active_portfolio_risk",
    "relaxed_swing_no_kelly_control_main(",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "relaxed_swing_no_kelly_control_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX Relaxed Swing No-Kelly "
    "Research Control PASS"
)
