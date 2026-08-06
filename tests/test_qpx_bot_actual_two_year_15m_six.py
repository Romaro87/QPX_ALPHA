from datetime import date
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    CHUNK_DAYS,
    INTERVAL_MINUTES,
    SWING_SYMBOLS,
    chunk_ranges,
    subtract_years,
)
from qpx_bot.config import BotConfig
from qpx_bot.intraday_six_paper import load_policy


config = BotConfig()
config.validate()
policy = load_policy()

assert config.maximum_swing_positions == 6
assert INTERVAL_MINUTES == 15
assert policy.interval == "15m"
assert policy.maximum_concurrent_positions == 6
assert policy.candidates == SWING_SYMBOLS
assert not policy.rankings_enabled
assert not policy.extended_hours_enabled
assert not policy.live_broker_enabled

assert subtract_years(
    date(2024, 2, 29),
    2,
) == date(2022, 2, 28)

ranges = chunk_ranges(
    date(2024, 5, 1),
    date(2026, 8, 6),
)
assert ranges
assert ranges[0][0] == date(2024, 5, 1)
assert ranges[-1][1] == date(2026, 8, 6)
assert all(
    (end - start).days + 1 <= CHUNK_DAYS
    for start, end in ranges
)

for left, right in zip(
    ranges,
    ranges[1:],
):
    assert (
        right[0] - left[1]
    ).days == 1

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")

for required in (
    "/v2/aggs/ticker/",
    "/range/",
    "INTERVAL_MINUTES}/minute/",
    "/stocks/v1/dividends",
    'VIX_PROVIDER_SYMBOL = "I:VIX"',
    "evaluate_entry(",
    "evaluate_exit(",
    "calculate_position_size(",
    "portfolio.active_risk()",
    "rebalance_income_allocation(",
    "choose_without_ranking(",
    "common_timestamp_intersection",
    "placeholder_data=False",
    "synthetic_data=False",
    "forced_entries=False",
):
    assert required in source, required

for prohibited in (
    "rank_candidates(",
    "monthly_winner",
    "selected_symbol",
    "synthetic_candles",
    "forced_entry_indices={",
    "Yahoo",
    "yfinance",
    "interpolate(",
):
    assert prohibited not in source

print(
    "QPX Bot Actual Two-Year 15-Minute "
    "Six-Position Backtest PASS"
)
