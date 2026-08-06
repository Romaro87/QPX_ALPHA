"""
QPX Bot command-line entry point.
"""

from __future__ import annotations

from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"


def run(data_file: str | Path | None = None) -> int:
    """Run the first QPX Bot validation milestone."""
    config = BotConfig()
    config.validate()

    selected_file = (
        Path(data_file).expanduser()
        if data_file is not None
        else DEFAULT_DATA_FILE
    )

    print("=" * 64)
    print("QPX BOT v1.0")
    print("=" * 64)
    print(f"Starting cash : ${config.starting_cash:,.2f}")
    print(f"Data file     : {selected_file}")
    print()

    candles = load_csv(selected_file)

    first = candles[0]
    last = candles[-1]

    print(f"Candles loaded: {len(candles)}")
    print(f"First date    : {first.date}")
    print(f"Last date     : {last.date}")
    print(f"First close   : ${first.close:,.2f}")
    print(f"Last close    : ${last.close:,.2f}")
    print()
    print("Status        : PASS")
    print("=" * 64)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
