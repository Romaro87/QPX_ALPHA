from datetime import date, timedelta

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import IndicatorSet
from qpx_bot.portfolio import Position
from qpx_bot.strategy import evaluate_entry, evaluate_exit


config = BotConfig()
count = 220
start = date(2024, 1, 2)

candles = []
for index in range(count):
    close = 100.0 + (index * 0.10)
    candles.append(
        Candle(
            date=start + timedelta(days=index),
            open=close - 0.20,
            high=close + 0.50,
            low=close - 0.50,
            close=close,
            volume=2_500_000,
        )
    )

signal_index = count - 1
candles[signal_index] = Candle(
    date=candles[signal_index].date,
    open=126.00,
    high=131.00,
    low=125.50,
    close=130.00,
    volume=3_200_000,
)

empty = [None] * count
ema_fast = empty.copy()
ema_slow = empty.copy()
rsi = empty.copy()
rmi = empty.copy()
atr = empty.copy()
sma = empty.copy()
average_volume = empty.copy()

previous = signal_index - 1
slope_index = signal_index - config.sma_slope_lookback

ema_fast[previous] = 100.0
ema_slow[previous] = 101.0
ema_fast[signal_index] = 103.0
ema_slow[signal_index] = 102.0

rsi[previous] = 49.0
rsi[signal_index] = 55.0
rmi[previous] = 48.0
rmi[signal_index] = 56.0

atr[signal_index] = 2.0
sma[slope_index] = 109.0
sma[signal_index] = 110.0
average_volume[previous] = 2_500_000.0

indicators = IndicatorSet(
    ema_fast=ema_fast,
    ema_slow=ema_slow,
    rsi=rsi,
    rmi=rmi,
    atr=atr,
    sma_trend=sma,
    average_volume=average_volume,
)

entry = evaluate_entry(
    candles=candles,
    indicators=indicators,
    index=signal_index,
    vix=20.0,
    config=config,
)

assert entry.should_enter
assert entry.decision == "ENTER"
assert "EMA_CROSS" in entry.triggers
assert "RSI_CROSS" in entry.triggers
assert "RMI_CROSS" in entry.triggers
assert not entry.failed_checks

blocked_vix = evaluate_entry(
    candles=candles,
    indicators=indicators,
    index=signal_index,
    vix=30.0,
    config=config,
)
assert not blocked_vix.should_enter
assert blocked_vix.failed_checks == ("vix_filter",)

position = Position(
    symbol="TEST",
    shares=10,
    entry_date=date(2024, 1, 1),
    entry_price=100.0,
    entry_atr=2.0,
    stop_price=95.0,
    target_price=110.0,
    highest_price=100.0,
)

both_touched = Candle(
    date=date(2024, 1, 2),
    open=100.0,
    high=111.0,
    low=94.0,
    close=105.0,
    volume=3_000_000,
)
stop_exit = evaluate_exit(
    position=position,
    candle=both_touched,
    current_atr=2.0,
    config=config,
)
assert stop_exit.should_exit
assert stop_exit.reason == "ATR_STOP"
assert stop_exit.exit_price == 95.0

target_bar = Candle(
    date=date(2024, 1, 3),
    open=100.0,
    high=111.0,
    low=96.0,
    close=109.0,
    volume=3_000_000,
)
target_exit = evaluate_exit(
    position=position,
    candle=target_bar,
    current_atr=2.0,
    config=config,
)
assert target_exit.should_exit
assert target_exit.reason == "ATR_TARGET"
assert target_exit.exit_price == 110.0

trail_bar = Candle(
    date=date(2024, 1, 4),
    open=103.0,
    high=108.0,
    low=101.0,
    close=107.0,
    volume=3_000_000,
)
trail = evaluate_exit(
    position=position,
    candle=trail_bar,
    current_atr=2.0,
    config=config,
)
assert not trail.should_exit
assert trail.trailing_active
assert trail.highest_price == 108.0
assert trail.next_stop_price == 103.0

print("QPX Bot Strategy Decision Engine PASS")
