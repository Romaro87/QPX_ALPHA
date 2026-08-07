from datetime import date
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    BASELINE_EXIT_PROFILE,
    BREAK_EVEN_075R_EXIT_PROFILE,
    BREAK_EVEN_1R_EXIT_PROFILE,
    BREAK_EVEN_1R_NO_OVERNIGHT_EXIT_PROFILE,
    DEFAULT_EXIT_MATRIX_REPORT_ROOT,
    EXIT_HYPOTHESIS_PROFILES,
    NO_OVERNIGHT_EXIT_PROFILE,
    _apply_research_break_even_stop,
    _exit_profile_settings,
    exit_hypothesis_matrix_main,
)
from qpx_bot.config import BotConfig
from qpx_bot.portfolio import Position
from qpx_bot.strategy import ExitEvaluation


assert DEFAULT_EXIT_MATRIX_REPORT_ROOT.name == (
    "qpx_exit_hypothesis_matrix_2024_08_06_to_2026_07_28"
)
assert EXIT_HYPOTHESIS_PROFILES == (
    BASELINE_EXIT_PROFILE,
    BREAK_EVEN_1R_EXIT_PROFILE,
    BREAK_EVEN_075R_EXIT_PROFILE,
    NO_OVERNIGHT_EXIT_PROFILE,
    BREAK_EVEN_1R_NO_OVERNIGHT_EXIT_PROFILE,
)
assert _exit_profile_settings(
    BASELINE_EXIT_PROFILE
) == (0.0, False)
assert _exit_profile_settings(
    BREAK_EVEN_1R_EXIT_PROFILE
) == (1.0, False)
assert _exit_profile_settings(
    BREAK_EVEN_075R_EXIT_PROFILE
) == (0.75, False)
assert _exit_profile_settings(
    NO_OVERNIGHT_EXIT_PROFILE
) == (0.0, True)
assert _exit_profile_settings(
    BREAK_EVEN_1R_NO_OVERNIGHT_EXIT_PROFILE
) == (1.0, True)
assert callable(
    exit_hypothesis_matrix_main
)

config = BotConfig()
position = Position(
    symbol="SPY",
    shares=1,
    entry_date=date(2025, 1, 2),
    entry_price=100.0,
    entry_atr=2.0,
    stop_price=95.0,
    target_price=110.0,
    highest_price=100.0,
)
evaluation = ExitEvaluation(
    should_exit=False,
    reason=None,
    exit_price=None,
    next_stop_price=95.0,
    highest_price=105.0,
    trailing_active=False,
)
raised, activated = _apply_research_break_even_stop(
    position=position,
    evaluation=evaluation,
    config=config,
    activation_r=1.0,
)
expected = (
    position.entry_price
    / (
        1.0
        - config.slippage_rate
    )
)
assert activated is True
assert abs(raised - expected) < 1e-9

not_reached = ExitEvaluation(
    should_exit=False,
    reason=None,
    exit_price=None,
    next_stop_price=95.0,
    highest_price=104.99,
    trailing_active=False,
)
unchanged, activated = _apply_research_break_even_stop(
    position=position,
    evaluation=not_reached,
    config=config,
    activation_r=1.0,
)
assert activated is False
assert abs(unchanged - 95.0) < 1e-9

already_above = ExitEvaluation(
    should_exit=False,
    reason=None,
    exit_price=None,
    next_stop_price=101.0,
    highest_price=105.0,
    trailing_active=True,
)
unchanged, activated = _apply_research_break_even_stop(
    position=position,
    evaluation=already_above,
    config=config,
    activation_r=1.0,
)
assert activated is False
assert abs(unchanged - 101.0) < 1e-9

root = Path(__file__).resolve().parents[1]
source = (
    root
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")
runner = (
    root
    / "QPX_RUN_EXIT_HYPOTHESIS_MATRIX_2024_08_06_TO_2026_07_28.py"
).read_text(encoding="utf-8")

for marker in (
    'BASELINE_EXIT_PROFILE = "BASELINE_EXIT"',
    '"BREAKEVEN_AFTER_1R_RESEARCH"',
    '"BREAKEVEN_AFTER_0P75R_RESEARCH"',
    '"NO_OVERNIGHT_RESEARCH"',
    '"BREAKEVEN_AFTER_1R_PLUS_NO_OVERNIGHT_RESEARCH"',
    "_apply_research_break_even_stop(",
    "_assert_v16_baseline_reproduction(",
    "is_last_session_bar",
    'reason="SESSION_CLOSE"',
    "flatten_at_session_close",
    "break_even_stop_activations",
    "session_close_exits",
    "Exit hypothesis profile",
    "exit_hypothesis_matrix_main(",
    "QPX EXIT-HYPOTHESIS RESEARCH MATRIX V18: COMPLETE",
):
    assert marker in source, marker

for prohibited in (
    "synthetic_candles",
    "forced_entry_indices={",
    "interpolate(",
):
    assert prohibited not in source, prohibited

assert "exit_hypothesis_matrix_main" in runner
assert "MASSIVE_API_KEY" not in runner
assert "POLYGON_API_KEY" not in runner
assert "getpass" not in runner

print(
    "QPX Exit Hypothesis Matrix V18 PASS"
)
