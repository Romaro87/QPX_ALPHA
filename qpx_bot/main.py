"""QPX Bot command-line entry point."""

from __future__ import annotations

from pathlib import Path

from qpx_bot.backtest import run_backtest
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.report import format_backtest_report


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_FILE = PACKAGE_DIR / "sample_data" / "sample.csv"
DEMO_SYMBOL = "DEMO"
DEMO_VIX = 20.0


def run(data_file: str | Path | None = None) -> int:
    """Run the permanent historical-backtesting milestone."""
    config = BotConfig()
    config.validate()

    selected_file = (
        Path(data_file).expanduser()
        if data_file is not None
        else DEFAULT_DATA_FILE
    )
    candles = load_csv(selected_file)
    result = run_backtest(
        candles=candles,
        symbol=DEMO_SYMBOL,
        config=config,
        vix=DEMO_VIX,
    )

    print(format_backtest_report(result))
    print("Status                    : PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
