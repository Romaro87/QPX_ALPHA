from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.indicators import calculate_indicators
from qpx_bot.market_calendar import NEW_YORK
from qpx_bot.paper_engine import (
    create_initial_state,
    process_paper_day,
    reconcile_state,
)
from qpx_bot.paper_state import StateStore
from qpx_bot.session_execution import (
    OpeningQuote,
    SessionExecutionConfig,
    apply_pending_entry_regular_session,
)


config = replace(
    BotConfig(),
    starting_cash=10_000.0,
    starting_swing_cash=5_000.0,
    monthly_contribution=500.0,
    ema_fast_period=2,
    ema_slow_period=3,
    rsi_period=3,
    rmi_period=3,
    rmi_momentum=2,
    sma_trend_period=5,
    sma_slope_lookback=2,
    atr_period=3,
    average_volume_period=3,
    breakout_lookback=3,
    minimum_average_daily_volume=1_000,
)

execution_config = SessionExecutionConfig(
    schema_version=1,
    market_timezone="America/New_York",
    regular_session_open="09:30",
    opening_window_start="09:35",
    opening_window_end="10:30",
    regular_session_close="16:00",
    intraday_interval="1m",
    intraday_range="1d",
    maximum_gap_atr_multiple=10.0,
    maximum_quote_attempts=1,
    quote_timeout_seconds=1.0,
    extended_hours_enabled=False,
)
execution_config.validate()

start = date(2024, 1, 2)
swing = []
income = []

for index in range(80):
    day = start + timedelta(days=index)
    swing_price = 100.0 + (index * 0.10)
    income_price = 40.0 + (index * 0.03)

    swing.append(
        Candle(
            date=day,
            open=swing_price,
            high=swing_price + 1.0,
            low=swing_price - 1.0,
            close=swing_price + 0.20,
            volume=3_000_000,
        )
    )
    income.append(
        Candle(
            date=day,
            open=income_price,
            high=income_price + 0.50,
            low=income_price - 0.50,
            close=income_price + 0.10,
            volume=1_500_000,
        )
    )

vix = [20.0] * len(swing)
dividends = [
    DividendEvent(
        date=swing[21].date,
        amount_per_share=0.20,
    )
]
indicators = calculate_indicators(
    swing,
    config,
)

state, initialized = create_initial_state(
    swing_symbol="TEST",
    income_symbol="QDTE",
    start_date=swing[20].date,
    income_price=income[20].close,
    config=config,
)

events = process_paper_day(
    state=state,
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    indicators=indicators,
    vix_values=vix,
    index=20,
    config=config,
    forced_entry=True,
)

assert state.pending_entry is not None
assert state.position is None
assert any(
    event.event_type == "ENTRY_SIGNAL"
    for event in events
)

quote_time = datetime.combine(
    swing[21].date,
    time(9, 30),
    tzinfo=NEW_YORK,
)
quote = OpeningQuote(
    symbol="TEST",
    session_date=swing[21].date,
    bar_time_market=quote_time,
    observed_at_utc=datetime.now(
        timezone.utc
    ).isoformat(),
    open_price=swing[21].open,
    source="TEST_FIRST_REGULAR_BAR",
    extended_hours=False,
)
fill_outcome = (
    apply_pending_entry_regular_session(
        state,
        quote=quote,
        prior_close=swing[20].close,
        income_price=income[21].open,
        bot_config=config,
        execution_config=execution_config,
    )
)

assert fill_outcome.status == "FILLED"
assert state.pending_entry is None
assert state.position is not None
assert len(state.completed_order_keys) == 1
assert any(
    event.event_type
    == "ENTRY_FILLED_REGULAR_SESSION"
    for event in fill_outcome.events
)
assert all(
    not event.details["extended_hours"]
    for event in fill_outcome.events
)

events = process_paper_day(
    state=state,
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    indicators=indicators,
    vix_values=vix,
    index=21,
    config=config,
    forced_entry=False,
)

assert state.position is not None
assert state.dividends_received > 0
assert not any(
    event.event_type == "ENTRY_FILLED"
    for event in events
)

revision_before_duplicate = state.revision
duplicate_events = process_paper_day(
    state=state,
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    indicators=indicators,
    vix_values=vix,
    index=21,
    config=config,
    forced_entry=True,
)
assert duplicate_events == []
assert state.revision == revision_before_duplicate
assert len(state.completed_order_keys) == 1

assert state.position is not None
target = state.position.target_price
swing[22] = replace(
    swing[22],
    high=target + 1.0,
    close=max(
        swing[22].close,
        target,
    ),
)
indicators = calculate_indicators(
    swing,
    config,
)

events = process_paper_day(
    state=state,
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    indicators=indicators,
    vix_values=vix,
    index=22,
    config=config,
    forced_entry=False,
)

assert state.position is None
assert state.realized_pnl > 0
assert state.tax_reserve_cash > 0
assert len(state.trade_results_r) == 1
assert any(
    event.event_type == "EXIT_FILLED"
    for event in events
)
assert all(
    event.details.get(
        "extended_hours",
        False,
    )
    is False
    for event in events
)

events = process_paper_day(
    state=state,
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    indicators=indicators,
    vix_values=vix,
    index=31,
    config=config,
    forced_entry=False,
)
assert state.total_contributions == (
    config.total_starting_capital
    + config.monthly_contribution
)
assert any(
    event.event_type
    == "MONTHLY_CONTRIBUTION"
    for event in events
)

reconciliation = reconcile_state(
    state,
    swing_price=swing[31].close,
    income_price=income[31].close,
)
assert reconciliation["total_equity"] > 0

with TemporaryDirectory() as temporary_directory:
    store = StateStore(
        Path(temporary_directory)
    )
    store.save(state)
    loaded = store.load()

    assert loaded.state_id == state.state_id
    assert loaded.revision == state.revision
    assert (
        loaded.completed_order_keys
        == state.completed_order_keys
    )

    appended = store.append_events(
        [
            initialized,
            *fill_outcome.events,
            *events,
        ]
    )
    assert appended >= 1
    first_count = (
        store.verify_journal()[2]
    )

    store.append_events(
        [
            initialized,
            *fill_outcome.events,
            *events,
        ]
    )
    assert (
        store.verify_journal()[2]
        == first_count
    )

    store.activate_kill_switch(
        "test"
    )
    assert store.kill_switch_active()
    store.deactivate_kill_switch()
    assert not store.kill_switch_active()

    with store.locked():
        assert store.lock_path.exists()
    assert not store.lock_path.exists()

print(
    "QPX Bot Persistent Paper Trading PASS"
)
