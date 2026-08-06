from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.performance import AdjustedBar
from qpx_bot.walk_forward import (
    Candidate,
    format_walk_forward_report,
    run_walk_forward,
    write_walk_forward_json,
    write_walk_forward_windows,
)


config = replace(
    BotConfig(),
    starting_cash=10_000.0,
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

start = date(2022, 1, 3)
swing = []
income = []
adjusted = []

for index in range(360):
    day = start + timedelta(days=index)
    swing_price = 100.0 + (index * 0.08)
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
    adjusted.append(
        AdjustedBar(
            date=day,
            open=swing_price,
            close=swing_price + 0.20,
            adjusted_close=(
                swing_price
                + 0.20
                + (index * 0.01)
            ),
        )
    )

dividends = [
    DividendEvent(
        date=swing[index].date,
        amount_per_share=0.20,
    )
    for index in (30, 90, 150, 210, 270, 330)
]
vix = [20.0] * len(swing)
candidates = (
    Candidate("LOW_VIX", 18.0, 1.20),
    Candidate("BASE_VIX", 28.0, 1.20),
)

result = run_walk_forward(
    swing_candles=swing,
    income_candles=income,
    dividends=dividends,
    vix_values=vix,
    adjusted_bars=adjusted,
    symbol="TEST",
    config=config,
    train_bars=120,
    test_bars=40,
    step_bars=40,
    candidates=candidates,
)

assert result.total_windows == 6
assert len(result.windows) == 6
assert (
    result.out_of_sample_metrics.observation_count
    == 240
)
assert result.benchmark_metrics.exposure == 1.0
assert result.benchmark_uses_adjusted_close
assert result.windows[0].test_start > result.windows[0].train_end
assert (
    "WALK-FORWARD OUT-OF-SAMPLE VALIDATION"
    in format_walk_forward_report(result)
)

with TemporaryDirectory() as temporary_directory:
    directory = Path(temporary_directory)
    windows = write_walk_forward_windows(
        result,
        directory / "windows.csv",
    )
    payload = write_walk_forward_json(
        result,
        directory / "result.json",
    )

    assert windows.exists()
    assert payload.exists()
    assert "CAGRAdvantage" in windows.read_text(encoding="utf-8")
    assert '"total_windows": 6' in payload.read_text(
        encoding="utf-8"
    )

print("QPX Bot Walk-Forward Validation PASS")
