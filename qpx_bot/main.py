"""QPX Bot command-line entry point."""

from __future__ import annotations

from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.indicators import calculate_indicators


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"


def _display_value(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "not ready"
    return f"{value:,.{decimals}f}"


def run(data_file: str | Path | None = None) -> int:
    """Load data and calculate the permanent indicator layer."""
    config = BotConfig()
    config.validate()

    selected_file = (
        Path(data_file).expanduser()
        if data_file is not None
        else DEFAULT_DATA_FILE
    )

    print("=" * 68)
    print("QPX BOT v1.1 — INDICATOR ENGINE")
    print("=" * 68)
    print(f"Starting cash : ${config.starting_cash:,.2f}")
    print(f"Data file     : {selected_file}")
    print()

    candles = load_csv(selected_file)
    indicators = calculate_indicators(candles, config)
    latest_index = indicators.latest_complete_index()

    print(f"Candles loaded: {len(candles)}")
    print(f"First date    : {candles[0].date}")
    print(f"Last date     : {candles[-1].date}")
    print()

    if latest_index is None:
        print("Indicator status: INSUFFICIENT DATA")
        print(
            f"At least {config.sma_trend_period} daily bars are required."
        )
        return 1

    candle = candles[latest_index]

    print(f"Latest complete indicator date: {candle.date}")
    print(f"Close          : ${candle.close:,.2f}")
    print(
        f"EMA {config.ema_fast_period:<3}        : "
        f"{_display_value(indicators.ema_fast[latest_index])}"
    )
    print(
        f"EMA {config.ema_slow_period:<3}        : "
        f"{_display_value(indicators.ema_slow[latest_index])}"
    )
    print(
        f"RSI {config.rsi_period:<3}        : "
        f"{_display_value(indicators.rsi[latest_index])}"
    )
    print(
        f"RMI {config.rmi_period:<3}        : "
        f"{_display_value(indicators.rmi[latest_index])}"
    )
    print(
        f"ATR {config.atr_period:<3}        : "
        f"{_display_value(indicators.atr[latest_index], 4)}"
    )
    print(
        f"SMA {config.sma_trend_period:<3}        : "
        f"{_display_value(indicators.sma_trend[latest_index])}"
    )
    print(
        "Average volume: "
        f"{_display_value(indicators.average_volume[latest_index], 0)}"
    )
    print()
    print("Status         : PASS")
    print("=" * 68)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
