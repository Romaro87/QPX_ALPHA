from datetime import datetime, timedelta
from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.market_calendar import NEW_YORK
from qpx_bot.intraday_six_paper import (
    choose_without_ranking,
    load_policy,
    scan_window_open,
)


policy = load_policy()
config = BotConfig()
config.validate()

assert policy.interval == "15m"
assert policy.maximum_concurrent_positions == 6
assert config.maximum_swing_positions == 6
assert len(policy.candidates) == 8
assert not policy.rankings_enabled
assert not policy.extended_hours_enabled
assert not policy.live_broker_enabled

market = NEW_YORK

assert datetime(
    2026,
    1,
    15,
    12,
    0,
    tzinfo=market,
).utcoffset() == timedelta(hours=-5)
assert datetime(
    2026,
    7,
    15,
    12,
    0,
    tzinfo=market,
).utcoffset() == timedelta(hours=-4)

assert scan_window_open(
    datetime(2026, 8, 6, 9, 45, tzinfo=market),
    policy,
)
assert scan_window_open(
    datetime(2026, 8, 6, 16, 0, tzinfo=market),
    policy,
)
assert not scan_window_open(
    datetime(2026, 8, 6, 9, 30, tzinfo=market),
    policy,
)
assert not scan_window_open(
    datetime(2026, 8, 8, 10, 0, tzinfo=market),
    policy,
)

accepted_a, deferred_a = choose_without_ranking(
    signal_bar=datetime(
        2026,
        8,
        6,
        10,
        0,
        tzinfo=market,
    ),
    qualifying=policy.candidates,
    available_slots=6,
)
accepted_b, deferred_b = choose_without_ranking(
    signal_bar=datetime(
        2026,
        8,
        6,
        10,
        0,
        tzinfo=market,
    ),
    qualifying=tuple(reversed(policy.candidates)),
    available_slots=6,
)

assert accepted_a == accepted_b
assert deferred_a == deferred_b
assert len(accepted_a) == 6
assert len(deferred_a) == 2
assert set((*accepted_a, *deferred_a)) == set(policy.candidates)

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "intraday_six_paper.py"
).read_text(encoding="utf-8")

for required in (
    'interval != "15m"',
    "maximum_concurrent_positions != 6",
    "for symbol in policy.candidates:",
    "evaluate_entry(",
    "evaluate_exit(",
    "calculate_position_size(",
    "portfolio.active_risk()",
    "ENTRY_STAGED_15M",
    "live_broker_enabled",
):
    assert required in source

for prohibited in (
    "rank_candidates(",
    "selected_symbol",
    "monthly_winner",
):
    assert prohibited not in source

wrapper = (
    Path(__file__).resolve().parents[1]
    / "QPX_RUN_AUTO_PAPER.py"
).read_text(encoding="utf-8")
assert "intraday_six_paper" in wrapper
assert "auto_paper" not in wrapper

print(
    "QPX Bot 15-Minute Eight-Ticker "
    "Six-Position Paper PASS"
)
