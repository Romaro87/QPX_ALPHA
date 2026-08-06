from datetime import date, datetime
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    CBOE_VIX_HISTORY_URL,
    CHUNK_DAYS,
    DEFAULT_VIX_CACHE,
    INTERVAL_MINUTES,
    SWING_SYMBOLS,
    VIX_OBSERVATION_POLICY,
    VIX_PROVIDER_SYMBOL,
    IntradayBar,
    chunk_ranges,
    expand_previous_session_vix,
    prepare_cboe_vix_cache,
    subtract_years,
)
from qpx_bot.config import BotConfig
from qpx_bot.intraday_six_paper import load_policy
from qpx_bot.market_calendar import NEW_YORK


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

assert VIX_PROVIDER_SYMBOL == (
    "CBOE_VIX_PREVIOUS_SESSION_CLOSE"
)
assert VIX_OBSERVATION_POLICY == (
    "PREVIOUS_COMPLETED_SESSION_DAILY_CLOSE"
)
assert CBOE_VIX_HISTORY_URL.endswith(
    "/VIX_History.csv"
)
assert DEFAULT_VIX_CACHE.name == (
    "CBOE_VIX_DAILY.csv"
)
assert callable(prepare_cboe_vix_cache)

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

reference = [
    IntradayBar(
        start=datetime(
            2026, 1, 5, 9, 30,
            tzinfo=NEW_YORK,
        ),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000,
    ),
    IntradayBar(
        start=datetime(
            2026, 1, 5, 9, 45,
            tzinfo=NEW_YORK,
        ),
        open=100.5,
        high=101.5,
        low=100.0,
        close=101.0,
        volume=1000,
    ),
    IntradayBar(
        start=datetime(
            2026, 1, 6, 9, 30,
            tzinfo=NEW_YORK,
        ),
        open=101.0,
        high=102.0,
        low=100.5,
        close=101.5,
        volume=1000,
    ),
]
expanded = expand_previous_session_vix(
    reference_bars=reference,
    closes={
        date(2026, 1, 2): 17.25,
        date(2026, 1, 5): 18.50,
    },
    minimum_bars=3,
)

assert len(expanded) == 3
assert expanded[0].close == 17.25
assert expanded[1].close == 17.25
assert expanded[2].close == 18.50
assert all(bar.volume == 0 for bar in expanded)

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_two_year_15m_six.py"
).read_text(encoding="utf-8")

for required in (
    "/v2/aggs/ticker/",
    "INTERVAL_MINUTES}/minute/",
    "/stocks/v1/dividends",
    "CBOE_VIX_HISTORY_URL",
    "VIX_History.csv",
    "PREVIOUS_COMPLETED_SESSION_DAILY_CLOSE",
    "fetch_cboe_vix_daily(",
    "prepare_cboe_vix_cache(",
    "VIX preflight: validating official Cboe",
    "LOCAL_VALIDATED_CBOE_CACHE",
    "CBOE_VIX_DAILY.csv",
    "expand_previous_session_vix(",
    "minimum_bars: int = MINIMUM_TEST_BARS",
    "if len(expanded) < minimum_bars",
    "_find_valid_cached_history(",
    "Reusing validated actual 15-minute cache",
    "evaluate_entry(",
    "evaluate_exit(",
    "calculate_position_size(",
    "portfolio.active_risk()",
    "rebalance_income_allocation(",
    "choose_without_ranking(",
    "vix_values_are_actual",
    "vix_placeholder",
    "placeholder_data=False",
    "synthetic_data=False",
    "forced_entries=False",
):
    assert required in source, required

for prohibited in (
    'VIX_PROVIDER_SYMBOL = "I:VIX"',
    "rank_candidates(",
    "monthly_winner",
    "selected_symbol",
    "synthetic_candles",
    "forced_entry_indices={",
    "yfinance",
    "interpolate(",
):
    assert prohibited not in source, prohibited



run_start = source.index("def run_backtest(")
preflight_index = source.index(
    "prepare_cboe_vix_cache(",
    run_start,
)
provider_loop_index = source.index(
    "for logical_symbol, provider_symbol "
    "in provider_symbols.items():",
    run_start,
)
assert preflight_index < provider_loop_index

print(
    "QPX Bot Actual Two-Year 15-Minute "
    "Cboe-VIX Six-Position Backtest PASS"
)
