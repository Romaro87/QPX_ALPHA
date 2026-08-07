from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_SWING_ONLY_REPORT_ROOT,
    FIXED_INITIALIZATION_BARS,
    FIXED_WINDOW_END,
    FIXED_WINDOW_START,
    swing_only_control_main,
)


assert callable(swing_only_control_main)
assert DEFAULT_SWING_ONLY_REPORT_ROOT.name == (
    "qpx_swing_only_control_2024_08_06_to_2026_07_28"
)
assert FIXED_INITIALIZATION_BARS == 200

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_SWING_ONLY_CONTROL_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    "swing_only: bool = False",
    "Swing-only control requires fixed local-only mode.",
    "SWING_ONLY_NO_DIVIDEND_INPUT",
    "QDTE bars remain only in the common-timestamp intersection.",
    "SWING_ONLY_INITIAL_CAPITAL",
    "ALL_CAPITAL_TO_SWING_CASH",
    "if swing_only",
    "DISABLED_SWING_ONLY",
    "NOT_APPLICABLE_SWING_ONLY",
    "qdte_used_for_common_timestamp_control",
    "swing_only_control_main(",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "swing_only_control_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print("QPX Swing-Only Fixed Local Control PASS")
