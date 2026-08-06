"""QPX Bot command-line entry point."""

from __future__ import annotations

from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import Portfolio
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_entry, scan_entry_signals


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"
DEMO_VIX = 20.0


def _display_value(value: float | None, decimals: int = 2) -> str:
    if value is None:
        return "not ready"
    return f"{value:,.{decimals}f}"


def run(data_file: str | Path | None = None) -> int:
    """Load data and run the strategy-decision milestone."""
    config = BotConfig()
    config.validate()

    selected_file = (
        Path(data_file).expanduser()
        if data_file is not None
        else DEFAULT_DATA_FILE
    )

    print("=" * 70)
    print("QPX BOT v1.3 — STRATEGY DECISION ENGINE")
    print("=" * 70)
    print(f"Data file       : {selected_file}")
    print(f"Starting cash   : ${config.starting_cash:,.2f}")
    print(f"Demo VIX        : {DEMO_VIX:.2f}")
    print()

    candles = load_csv(selected_file)
    indicators = calculate_indicators(candles, config)
    latest_index = indicators.latest_complete_index()

    if latest_index is None:
        print("Status           : INSUFFICIENT DATA")
        return 1

    candle = candles[latest_index]
    atr = indicators.atr[latest_index]

    if atr is None:
        print("Status           : ATR NOT READY")
        return 1

    current = evaluate_entry(
        candles=candles,
        indicators=indicators,
        index=latest_index,
        vix=DEMO_VIX,
        config=config,
    )
    signals = scan_entry_signals(
        candles=candles,
        indicators=indicators,
        vix=DEMO_VIX,
        config=config,
    )

    portfolio = Portfolio(config.starting_cash)
    sizing = calculate_position_size(
        account_equity=config.starting_cash,
        available_cash=portfolio.cash,
        entry_price=candle.close,
        atr=atr,
        active_risk=portfolio.active_risk(),
        config=config,
    )

    print(f"Candles loaded  : {len(candles)}")
    print(f"Latest date     : {candle.date}")
    print(f"Close           : ${candle.close:,.2f}")
    print(f"ATR             : {_display_value(atr, 4)}")
    print(f"Signals found   : {len(signals)}")
    print(f"Latest decision : {current.decision}")

    if current.triggers:
        print(f"Latest triggers : {', '.join(current.triggers)}")
    else:
        print("Latest triggers : none")

    if current.failed_checks:
        print(
            "Blocked by      : "
            + ", ".join(current.failed_checks)
        )
    else:
        print("Blocked by      : none")

    print(f"Planned shares  : {sizing.shares}")
    print(f"Planned risk    : ${sizing.planned_risk:,.2f}")
    print()
    print("Status           : PASS")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
