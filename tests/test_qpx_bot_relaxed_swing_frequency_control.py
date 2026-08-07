from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    BASELINE_ENTRY_PROFILE,
    DEFAULT_RELAXED_SWING_REPORT_ROOT,
    RELAXED_BREAKOUT_LOOKBACK,
    RELAXED_BREAKOUT_VOLUME_MULTIPLIER,
    RELAXED_ENTRY_PROFILE,
    RELAXED_MAXIMUM_GAP_ATR_MULTIPLE,
    RELAXED_MAXIMUM_VIX,
    RELAXED_MINIMUM_AVERAGE_15M_VOLUME,
    RELAXED_MOMENTUM_PERSISTENCE_LEVEL,
    RELAXED_RSI_OVERBOUGHT,
    relaxed_swing_frequency_control_main,
)


assert BASELINE_ENTRY_PROFILE == "BASELINE"
assert (
    RELAXED_ENTRY_PROFILE
    == "RELAXED_FREQUENCY_RESEARCH_V1"
)
assert RELAXED_MINIMUM_AVERAGE_15M_VOLUME == 75_000
assert RELAXED_BREAKOUT_VOLUME_MULTIPLIER == 1.05
assert RELAXED_BREAKOUT_LOOKBACK == 10
assert RELAXED_MAXIMUM_VIX == 32.0
assert RELAXED_RSI_OVERBOUGHT == 75.0
assert RELAXED_MOMENTUM_PERSISTENCE_LEVEL == 52.0
assert RELAXED_MAXIMUM_GAP_ATR_MULTIPLE == 2.0
assert DEFAULT_RELAXED_SWING_REPORT_ROOT.name == (
    "qpx_relaxed_swing_frequency_2024_08_06_to_2026_07_28"
)
assert callable(
    relaxed_swing_frequency_control_main
)

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_RELAXED_SWING_FREQUENCY_CONTROL_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    "RELAXED_FREQUENCY_RESEARCH_V1",
    "RELAXED_MINIMUM_AVERAGE_15M_VOLUME = 75_000",
    "RELAXED_BREAKOUT_VOLUME_MULTIPLIER = 1.05",
    "RELAXED_BREAKOUT_LOOKBACK = 10",
    "RELAXED_MAXIMUM_VIX = 32.0",
    "RELAXED_RSI_OVERBOUGHT = 75.0",
    "RELAXED_MOMENTUM_PERSISTENCE_LEVEL = 52.0",
    "RELAXED_MAXIMUM_GAP_ATR_MULTIPLE = 2.0",
    "_evaluate_entry_relaxed_frequency(",
    "MOMENTUM_PERSISTENCE",
    "entry_profile: str = BASELINE_ENTRY_PROFILE",
    "entry_gap_atr_limit",
    "risk_per_trade",
    "maximum_active_portfolio_risk",
    "stop_atr_multiple",
    "target_atr_multiple",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "relaxed_swing_frequency_control_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX Relaxed Swing Frequency "
    "Research Control PASS"
)
