"""QPX Bot command-line entry point."""

from __future__ import annotations

from pathlib import Path

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import load_csv
from qpx_bot.dividends import load_dividend_csv
from qpx_bot.hybrid import run_hybrid_backtest
from qpx_bot.report import format_hybrid_report


PACKAGE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = PACKAGE_DIR / "sample_data"
DEFAULT_SWING_FILE = SAMPLE_DIR / "sample.csv"
DEFAULT_INCOME_FILE = SAMPLE_DIR / "qdte_sample.csv"
DEFAULT_DIVIDEND_FILE = SAMPLE_DIR / "qdte_dividends.csv"
DEMO_VIX = 20.0


def run(
    swing_file: str | Path | None = None,
    income_file: str | Path | None = None,
    dividend_file: str | Path | None = None,
) -> int:
    """Run the permanent hybrid dividend-plus-swing milestone."""
    config = BotConfig()
    config.validate()

    selected_swing = (
        Path(swing_file).expanduser()
        if swing_file is not None
        else DEFAULT_SWING_FILE
    )
    selected_income = (
        Path(income_file).expanduser()
        if income_file is not None
        else DEFAULT_INCOME_FILE
    )
    selected_dividends = (
        Path(dividend_file).expanduser()
        if dividend_file is not None
        else DEFAULT_DIVIDEND_FILE
    )

    swing_candles = load_csv(selected_swing)
    income_candles = load_csv(selected_income)
    dividends = load_dividend_csv(selected_dividends)

    result = run_hybrid_backtest(
        swing_candles=swing_candles,
        income_candles=income_candles,
        dividends=dividends,
        swing_symbol="SWING",
        config=config,
        vix=DEMO_VIX,
    )

    print(format_hybrid_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
