from datetime import date
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_FIXED_REPORT_ROOT,
    FIXED_INITIALIZATION_BARS,
    FIXED_MINIMUM_COMMON_BARS,
    FIXED_WINDOW_END,
    FIXED_WINDOW_START,
    fixed_window_main,
    run_backtest,
)


assert FIXED_WINDOW_START == date(2024, 8, 6)
assert FIXED_WINDOW_END == date(2026, 7, 28)
assert (
    FIXED_WINDOW_END - FIXED_WINDOW_START
).days == 721
assert FIXED_INITIALIZATION_BARS == 200
assert FIXED_MINIMUM_COMMON_BARS == 11_500
assert DEFAULT_FIXED_REPORT_ROOT.name == (
    "qpx_fixed_2024_08_06_to_2026_07_28"
)
assert callable(run_backtest)
assert callable(fixed_window_main)

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_FIXED_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    "fixed_start: date | None = None",
    "fixed_end: date | None = None",
    "local_only: bool = False",
    "initialization_bars: int = 0",
    "FIXED_WINDOW_START = date(2024, 8, 6)",
    "FIXED_WINDOW_END = date(2026, 7, 28)",
    "FIXED_MINIMUM_COMMON_BARS = 11_500",
    "_find_valid_cached_dividends(",
    "LOCAL_VALIDATED_MASSIVE_POLYGON_DIVIDEND_CACHE",
    "Fixed-window local cache:",
    "if bar_time >= entry_eligible_time:",
    'action="INITIALIZATION_ONLY"',
    "fixed_window=fixed_window",
    "local_only=local_only",
    "QPX FIXED 2024-08-06 TO 2026-07-28",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "fixed_window_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX Fixed 2024-08-06 to 2026-07-28 "
    "Local Backtest PASS"
)
