"""Dividend-event data models and CSV loading for QPX Bot."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class DividendEvent:
    """One cash distribution expressed as dollars per share."""

    date: date
    amount_per_share: float

    def validate(self) -> None:
        if self.amount_per_share < 0:
            raise ValueError("Dividend per share cannot be negative.")


def _parse_date(raw_value: str) -> date:
    value = raw_value.strip()

    for date_format in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported date format: {raw_value!r}")


def load_dividend_csv(filename: str | Path) -> list[DividendEvent]:
    """Load Date/Dividend dividend events from a CSV file."""
    path = Path(filename).expanduser().resolve()

    if not path.exists():
        raise FileNotFoundError(f"Dividend file was not found: {path}")

    events: list[DividendEvent] = []

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        if reader.fieldnames is None:
            raise ValueError("Dividend CSV does not contain a header.")

        amount_column = None

        for candidate in ("Dividend", "DividendPerShare", "Amount"):
            if candidate in reader.fieldnames:
                amount_column = candidate
                break

        if "Date" not in reader.fieldnames or amount_column is None:
            raise ValueError(
                "Dividend CSV requires Date and Dividend columns."
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                event = DividendEvent(
                    date=_parse_date(row["Date"]),
                    amount_per_share=float(row[amount_column]),
                )
                event.validate()
                events.append(event)
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(
                    f"Invalid dividend data on CSV line "
                    f"{line_number}: {exc}"
                ) from exc

    events.sort(key=lambda event: event.date)
    return events


def dividend_amounts_by_date(
    events: Iterable[DividendEvent],
) -> dict[date, float]:
    """Combine same-day distributions into one per-share amount."""
    amounts: dict[date, float] = {}

    for event in events:
        event.validate()
        amounts[event.date] = (
            amounts.get(event.date, 0.0)
            + event.amount_per_share
        )

    return amounts
