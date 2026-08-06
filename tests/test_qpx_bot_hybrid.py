from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.hybrid import run_hybrid_backtest
from qpx_bot.report import (
    format_hybrid_report,
    write_hybrid_equity_curve,
    write_trade_log,
)


config = replace(
    BotConfig(),
    starting_cash=10_000.0,
    monthly_contribution=1_000.0,
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
)

start = date(2022, 1, 3)
swing_candles = []
income_candles = []

for index in range(800):
    day = start + timedelta(days=index)
    swing_close = 100.0 + (index * 0.02)
    income_close = 40.0 + (index * 0.01)

    swing_high = swing_close + 1.0
    swing_low = swing_close - 1.0

    if index == 15:
        swing_high = 130.0
        swing_low = swing_close - 0.5

    swing_candles.append(
        Candle(
            date=day,
            open=swing_close,
            high=swing_high,
            low=swing_low,
            close=swing_close + 0.10,
            volume=3_000_000,
        )
    )
    income_candles.append(
        Candle(
            date=day,
            open=income_close,
            high=income_close + 0.30,
            low=income_close - 0.30,
            close=income_close + 0.05,
            volume=1_500_000,
        )
    )

dividends = [
    DividendEvent(
        date=swing_candles[index].date,
        amount_per_share=0.20,
    )
    for index in (20, 40, 400, 700)
]

result = run_hybrid_backtest(
    swing_candles=swing_candles,
    income_candles=income_candles,
    dividends=dividends,
    swing_symbol="TEST",
    config=config,
    vix=20.0,
    forced_entry_indices={10},
)

assert result.swing_symbol == "TEST"
assert result.income_symbol == "QDTE"
assert result.contribution_count >= 25
assert result.total_contributions == (
    config.starting_cash
    + (
        result.contribution_count
        * config.monthly_contribution
    )
)
assert result.dividend_event_count == 4
assert result.total_dividends > 0
assert result.ending_income_shares > 0
assert result.ending_income_value > 0
assert result.ending_swing_equity > 0
assert result.ending_equity > 0
assert result.signal_count == 1
assert len(result.trades) == 1
assert len(result.equity_curve) == len(swing_candles)
assert result.allocation_events[0].income_weight == 0.65
assert result.allocation_events[-1].income_weight == 0.40
assert 0.0 <= result.maximum_drawdown <= 1.0

report = format_hybrid_report(result)
assert "HYBRID DIVIDEND + SWING BACKTEST" in report
assert "Dividends routed to swing" in report

with TemporaryDirectory() as temporary_directory:
    directory = Path(temporary_directory)
    trades = write_trade_log(
        result,
        directory / "hybrid_trades.csv",
    )
    equity = write_hybrid_equity_curve(
        result,
        directory / "hybrid_equity.csv",
    )

    assert trades.exists()
    assert equity.exists()
    assert "EntryDate" in trades.read_text(encoding="utf-8")
    assert "IncomeValue" in equity.read_text(encoding="utf-8")

print("QPX Bot Hybrid Dividend Engine PASS")
