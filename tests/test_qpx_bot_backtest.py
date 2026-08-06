from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from qpx_bot.backtest import run_backtest
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.report import (
    format_backtest_report,
    write_equity_curve,
    write_trade_log,
)


config = BotConfig(
    starting_cash=10_000.0,
    monthly_contribution=500.0,
)

start = date(2024, 1, 2)
candles = []

for index in range(80):
    day = start + timedelta(days=index)
    base = 100.0 + (index * 0.25)

    if index == 31:
        open_price = 108.0
        high = 109.0
        low = 107.0
        close = 108.5
    elif index == 32:
        open_price = 108.5
        high = 121.0
        low = 108.0
        close = 120.0
    else:
        open_price = base
        high = base + 1.0
        low = base - 1.0
        close = base + 0.25

    candles.append(
        Candle(
            date=day,
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=3_000_000,
        )
    )

result = run_backtest(
    candles=candles,
    symbol="TEST",
    config=config,
    vix=20.0,
    forced_entry_indices={30},
)

assert result.symbol == "TEST"
assert result.signal_count == 1
assert result.contribution_count >= 2
assert result.total_contributions > config.starting_cash
assert len(result.trades) == 1
assert result.trades[0].entry_date == candles[31].date
assert result.trades[0].exit_date >= result.trades[0].entry_date
assert len(result.equity_curve) == len(candles)
assert result.ending_equity > 0
assert 0.0 <= result.maximum_drawdown <= 1.0
assert "HISTORICAL BACKTEST" in format_backtest_report(result)

with TemporaryDirectory() as temporary_directory:
    directory = Path(temporary_directory)
    trade_log = write_trade_log(
        result,
        directory / "trades.csv",
    )
    equity_log = write_equity_curve(
        result,
        directory / "equity.csv",
    )

    assert trade_log.exists()
    assert equity_log.exists()
    assert "EntryDate" in trade_log.read_text(encoding="utf-8")
    assert "MarketValue" in equity_log.read_text(encoding="utf-8")

print("QPX Bot Backtesting Engine PASS")
