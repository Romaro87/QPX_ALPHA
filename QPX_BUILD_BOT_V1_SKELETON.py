#!/usr/bin/env python3
"""
QPX_BUILD_BOT_V1_SKELETON.py

Creates the first permanent, runnable QPX Bot package.

Generated files:
    qpx_bot/__init__.py
    qpx_bot/__main__.py
    qpx_bot/config.py
    qpx_bot/data_loader.py
    qpx_bot/main.py
    qpx_bot/sample_data/sample.csv
    tests/test_qpx_bot_skeleton.py

Existing files are backed up before replacement.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import textwrap


def find_project_root() -> Path:
    """Locate QPX_ALPHA without relying on the current directory."""
    starting_points = [
        Path.cwd().resolve(),
        Path(__file__).resolve().parent,
    ]

    checked: set[Path] = set()

    for start in starting_points:
        for candidate in (start, *start.parents):
            if candidate in checked:
                continue

            checked.add(candidate)

            if (
                (candidate / ".git").exists()
                and (candidate / "core").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA project root was not found.\n"
        "Save this builder inside /storage/emulated/0/QPX_ALPHA "
        "and run it again."
    )


PROJECT_ROOT = find_project_root()
BOT_DIR = PROJECT_ROOT / "qpx_bot"
TESTS_DIR = PROJECT_ROOT / "tests"

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_DIR = (
    PROJECT_ROOT
    / "backups"
    / "qpx_bot_v1_skeleton"
    / TIMESTAMP
)

created: list[str] = []
updated: list[str] = []
backed_up: list[str] = []


def backup_file(path: Path) -> None:
    """Back up an existing file while preserving its relative path."""
    if not path.exists() or not path.is_file():
        return

    relative = path.relative_to(PROJECT_ROOT)
    destination = BACKUP_DIR / relative

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)

    backed_up.append(str(relative))


def write_file(relative_path: str, contents: str) -> None:
    """Safely create or replace a project file."""
    path = PROJECT_ROOT / relative_path
    existed = path.exists()

    if existed:
        backup_file(path)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        textwrap.dedent(contents).strip() + "\n",
        encoding="utf-8",
    )

    if existed:
        updated.append(relative_path)
        print(f"Updated: {relative_path}")
    else:
        created.append(relative_path)
        print(f"Created: {relative_path}")


print("=" * 64)
print("QPX BOT v1 — SKELETON BUILDER")
print("=" * 64)
print(f"Project root: {PROJECT_ROOT}")
print()


write_file(
    "qpx_bot/__init__.py",
    '''
    """
    QPX Bot

    Focused backtesting bot for the Hybrid Dividend + Swing
    investment strategy.
    """

    __version__ = "1.0.0"
    ''',
)


write_file(
    "qpx_bot/config.py",
    '''
    """
    QPX Bot configuration.

    Strategy values are centralized here so they can later be
    optimized without rewriting the trading engine.
    """

    from dataclasses import dataclass


    @dataclass(frozen=True, slots=True)
    class BotConfig:
        """Default Hybrid Dividend + Swing strategy settings."""

        # Capital
        starting_cash: float = 1_300.0
        monthly_contribution: float = 2_000.0

        # Years 1–2 allocation
        dividend_allocation_years_1_2: float = 0.65
        swing_allocation_years_1_2: float = 0.35

        # Year 3 onward allocation
        dividend_allocation_later: float = 0.40
        swing_allocation_later: float = 0.60

        dividend_symbol: str = "QDTE"

        # Trend and momentum
        ema_fast_period: int = 9
        ema_slow_period: int = 21
        rsi_period: int = 14
        rsi_overbought: float = 70.0
        rsi_strength_level: float = 50.0
        sma_trend_period: int = 200

        # Volatility and exits
        atr_period: int = 14
        stop_atr_multiple: float = 2.5
        target_atr_multiple: float = 5.0
        trailing_activation_atr: float = 3.0

        # Liquidity and confirmation
        minimum_average_daily_volume: int = 2_000_000
        average_volume_period: int = 20
        breakout_volume_multiplier: float = 1.20
        maximum_vix_for_entries: float = 28.0

        # Risk
        risk_per_trade: float = 0.01
        maximum_active_portfolio_risk: float = 0.06
        kelly_fraction: float = 0.25

        # Execution
        slippage_rate: float = 0.00075

        # Tax reserve
        annual_tax_reserve_rate: float = 0.37

        def validate(self) -> None:
            """Reject internally inconsistent configuration."""
            allocation_pairs = (
                (
                    self.dividend_allocation_years_1_2,
                    self.swing_allocation_years_1_2,
                ),
                (
                    self.dividend_allocation_later,
                    self.swing_allocation_later,
                ),
            )

            for dividend_weight, swing_weight in allocation_pairs:
                if abs((dividend_weight + swing_weight) - 1.0) > 1e-9:
                    raise ValueError(
                        "Dividend and swing allocations must total 100%."
                    )

            if self.starting_cash <= 0:
                raise ValueError("Starting cash must be positive.")

            if not 0 < self.risk_per_trade <= 1:
                raise ValueError("Risk per trade must be between 0 and 1.")

            if not 0 < self.maximum_active_portfolio_risk <= 1:
                raise ValueError(
                    "Maximum active portfolio risk must be between 0 and 1."
                )

            if self.stop_atr_multiple <= 0:
                raise ValueError("ATR stop multiple must be positive.")

            if self.target_atr_multiple <= self.stop_atr_multiple:
                raise ValueError(
                    "ATR target must be greater than the ATR stop."
                )
    ''',
)


write_file(
    "qpx_bot/data_loader.py",
    '''
    """
    Historical OHLCV CSV loader.
    """

    from __future__ import annotations

    import csv
    from dataclasses import dataclass
    from datetime import date, datetime
    from pathlib import Path
    from typing import Iterable


    REQUIRED_COLUMNS = {
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
    }


    @dataclass(frozen=True, slots=True)
    class Candle:
        """One daily OHLCV market-data bar."""

        date: date
        open: float
        high: float
        low: float
        close: float
        volume: int

        def validate(self) -> None:
            """Validate basic price-bar consistency."""
            if self.open <= 0 or self.close <= 0:
                raise ValueError("Open and close prices must be positive.")

            if self.high < max(self.open, self.close, self.low):
                raise ValueError(
                    f"Invalid high price for candle dated {self.date}."
                )

            if self.low > min(self.open, self.close, self.high):
                raise ValueError(
                    f"Invalid low price for candle dated {self.date}."
                )

            if self.volume < 0:
                raise ValueError("Volume cannot be negative.")


    def _parse_date(raw_value: str) -> date:
        """Parse common ISO-style dates."""
        value = raw_value.strip()

        for date_format in ("%Y-%m-%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue

        raise ValueError(f"Unsupported date format: {raw_value!r}")


    def load_csv(filename: str | Path) -> list[Candle]:
        """Load, validate, sort, and return historical candles."""
        path = Path(filename).expanduser().resolve()

        if not path.exists():
            raise FileNotFoundError(
                f"Market-data file was not found: {path}"
            )

        if not path.is_file():
            raise ValueError(f"Market-data path is not a file: {path}")

        candles: list[Candle] = []

        with path.open(
            mode="r",
            newline="",
            encoding="utf-8-sig",
        ) as file:
            reader = csv.DictReader(file)

            if reader.fieldnames is None:
                raise ValueError("CSV file does not contain a header.")

            missing = REQUIRED_COLUMNS.difference(reader.fieldnames)

            if missing:
                missing_text = ", ".join(sorted(missing))
                raise ValueError(
                    f"CSV file is missing required columns: {missing_text}"
                )

            for line_number, row in enumerate(reader, start=2):
                try:
                    candle = Candle(
                        date=_parse_date(row["Date"]),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(float(row["Volume"])),
                    )
                    candle.validate()
                    candles.append(candle)

                except (TypeError, ValueError, KeyError) as exc:
                    raise ValueError(
                        f"Invalid market data on CSV line "
                        f"{line_number}: {exc}"
                    ) from exc

        if not candles:
            raise ValueError("CSV file contains no market-data rows.")

        candles.sort(key=lambda candle: candle.date)

        dates = [candle.date for candle in candles]

        if len(dates) != len(set(dates)):
            raise ValueError("CSV file contains duplicate dates.")

        return candles


    def closing_prices(candles: Iterable[Candle]) -> list[float]:
        """Return close prices from a candle collection."""
        return [candle.close for candle in candles]
    ''',
)


write_file(
    "qpx_bot/main.py",
    '''
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
    ''',
)


write_file(
    "qpx_bot/__main__.py",
    '''
    """Run QPX Bot with: python -m qpx_bot"""

    from qpx_bot.main import run


    if __name__ == "__main__":
        raise SystemExit(run())
    ''',
)


write_file(
    "qpx_bot/sample_data/sample.csv",
    '''
    Date,Open,High,Low,Close,Volume
    2024-01-02,100.00,101.50,99.20,100.50,2500000
    2024-01-03,100.50,102.30,100.10,101.80,2700000
    2024-01-04,101.80,103.20,101.00,102.20,2900000
    2024-01-05,102.20,104.50,101.90,103.90,3100000
    2024-01-08,103.90,105.20,103.10,104.40,3200000
    2024-01-09,104.40,106.00,103.80,105.60,3400000
    2024-01-10,105.60,107.20,104.90,106.80,3600000
    2024-01-11,106.80,108.10,105.70,107.40,3800000
    2024-01-12,107.40,109.00,106.80,108.50,4000000
    2024-01-16,108.50,110.20,107.90,109.70,4200000
    ''',
)


write_file(
    "tests/test_qpx_bot_skeleton.py",
    '''
    from pathlib import Path

    from qpx_bot.config import BotConfig
    from qpx_bot.data_loader import closing_prices, load_csv


    project_root = Path(__file__).resolve().parents[1]
    sample_file = (
        project_root
        / "qpx_bot"
        / "sample_data"
        / "sample.csv"
    )

    config = BotConfig()
    config.validate()

    candles = load_csv(sample_file)
    prices = closing_prices(candles)

    assert config.starting_cash == 1300.0
    assert len(candles) == 10
    assert candles[0].date < candles[-1].date
    assert len(prices) == len(candles)
    assert prices[0] == 100.50
    assert prices[-1] == 109.70

    print("QPX Bot Skeleton PASS")
    ''',
)


print()
print("=" * 64)
print("QPX BOT v1 SKELETON INSTALLED")
print("=" * 64)

if created:
    print(f"Created files : {len(created)}")

if updated:
    print(f"Updated files : {len(updated)}")

if backed_up:
    print(f"Backed up     : {len(backed_up)}")
    print(f"Backup folder : {BACKUP_DIR}")

print()
print("NEXT COMMANDS")
print("-" * 64)
print("python -m qpx_bot")
print("python tests/run_all_tests.py")
print("=" * 64)