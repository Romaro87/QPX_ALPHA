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
