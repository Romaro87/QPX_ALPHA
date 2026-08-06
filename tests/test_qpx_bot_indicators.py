from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.indicators import (
    average_true_range,
    calculate_indicators,
    exponential_moving_average,
    relative_momentum_index,
    relative_strength_index,
    simple_moving_average,
)


project_root = Path(__file__).resolve().parents[1]
sample_file = project_root / "qpx_bot" / "sample_data" / "sample.csv"

sma = simple_moving_average([1, 2, 3, 4, 5], 3)
assert sma == [None, None, 2.0, 3.0, 4.0]

ema = exponential_moving_average([1, 2, 3, 4, 5], 3)
assert ema[0] is None
assert ema[1] is None
assert ema[2] == 2.0
assert ema[3] == 3.0
assert ema[4] == 4.0

rising_prices = [float(value) for value in range(1, 40)]
rsi = relative_strength_index(rising_prices, 14)
assert rsi[14] == 100.0
assert rsi[-1] == 100.0

rmi = relative_momentum_index(rising_prices, 14, 5)
assert rmi[18] == 100.0
assert rmi[-1] == 100.0

candles = load_csv(sample_file)
atr = average_true_range(candles, 14)
assert len(atr) == len(candles)
assert atr[12] is None
assert atr[13] is not None
assert atr[-1] is not None
assert atr[-1] > 0

config = BotConfig()
indicators = calculate_indicators(candles, config)
latest_index = indicators.latest_complete_index()

assert len(candles) == 320
assert latest_index == len(candles) - 1
assert indicators.ema_fast[latest_index] is not None
assert indicators.ema_slow[latest_index] is not None
assert indicators.rsi[latest_index] is not None
assert indicators.rmi[latest_index] is not None
assert indicators.atr[latest_index] is not None
assert indicators.sma_trend[latest_index] is not None
assert indicators.average_volume[latest_index] is not None

print("QPX Bot Indicator Engine PASS")
