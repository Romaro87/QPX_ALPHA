from datetime import date
from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.portfolio import contribution_allocation
from qpx_bot.time_rules import elapsed_complete_years


config = BotConfig()
config.validate()

start = date(2024, 8, 6)

assert elapsed_complete_years(
    start,
    date(2026, 8, 5),
) == 1
assert elapsed_complete_years(
    start,
    date(2026, 8, 6),
) == 2

before = contribution_allocation(
    elapsed_complete_years(
        start,
        date(2026, 8, 5),
    ),
    config,
)
on_anniversary = contribution_allocation(
    elapsed_complete_years(
        start,
        date(2026, 8, 6),
    ),
    config,
)

assert before == (0.65, 0.35)
assert on_anniversary == (0.40, 0.60)

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_two_year_three_position.py"
).read_text(encoding="utf-8")

for required in (
    "allocation_phase_changed = (",
    "if month_changed or allocation_phase_changed:",
    '"ALLOCATION_PHASE_REBALANCE"',
    "previous_allocation_years = (",
    "current_allocation_years",
    "contribution_amount = 0.0",
    "maximum_concurrent_positions",
    "rankings_enabled=False",
):
    assert required in source

assert (
    'if month_key != current_month:\n'
    '            swing.deposit('
    not in source
)

print(
    "QPX Bot Three-Position Exact Anniversary PASS"
)
