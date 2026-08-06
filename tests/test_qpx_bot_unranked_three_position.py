from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.actual_two_year_three_position import (
    REQUIRED_UNIVERSE,
    choose_signals_without_ranking,
    load_policy,
)
from qpx_bot.config import BotConfig


config = BotConfig()
config.validate()

assert config.maximum_swing_positions == 6
assert REQUIRED_UNIVERSE == (
    "DIA",
    "IWM",
    "QQQ",
    "SPY",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
)

policy = load_policy()
assert not policy.rankings_enabled
assert policy.maximum_concurrent_positions == 6
assert policy.candidates == REQUIRED_UNIVERSE
assert policy.symbol_bonus_policy == "none"
assert not policy.live_broker_enabled

accepted_a, deferred_a = (
    choose_signals_without_ranking(
        signal_date=date(2026, 8, 6),
        qualifying=REQUIRED_UNIVERSE,
        available_slots=6,
    )
)
accepted_b, deferred_b = (
    choose_signals_without_ranking(
        signal_date=date(2026, 8, 6),
        qualifying=tuple(
            reversed(REQUIRED_UNIVERSE)
        ),
        available_slots=6,
    )
)

assert accepted_a == accepted_b
assert deferred_a == deferred_b
assert len(accepted_a) == 6
assert len(deferred_a) == 2
assert set(accepted_a).isdisjoint(
    deferred_a
)
assert set(
    (*accepted_a, *deferred_a)
) == set(REQUIRED_UNIVERSE)

none_accepted, all_deferred = (
    choose_signals_without_ranking(
        signal_date=date(2026, 8, 6),
        qualifying=REQUIRED_UNIVERSE,
        available_slots=0,
    )
)
assert none_accepted == ()
assert set(all_deferred) == set(
    REQUIRED_UNIVERSE
)

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_two_year_three_position.py"
).read_text(encoding="utf-8")

for required in (
    "fetch_chart(",
    "evaluate_entry(",
    "evaluate_exit(",
    "calculate_position_size(",
    "rebalance_income_allocation(",
    "maximum_concurrent_positions",
    "choose_signals_without_ranking(",
    "forced_entry_indices=None",
    "rankings_enabled=False",
):
    assert required in source

for prohibited in (
    "rank_candidates(",
    "selected_symbol",
    "monthly_winner",
    "SelectionResult",
    "symbol_selector",
    "forced_entry_indices={",
    "synthetic_candles",
):
    assert prohibited not in source

print(
    "QPX Bot Unranked Six-Position "
    "Swing PASS"
)
