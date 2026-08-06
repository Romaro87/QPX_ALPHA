"""Calendar rules shared by QPX allocation engines."""

from __future__ import annotations

from datetime import date


def anniversary_date(start: date, years: int) -> date:
    """Return the calendar anniversary, using Feb 28 for leap-day starts."""
    if years < 0:
        raise ValueError("Anniversary years cannot be negative.")

    target_year = start.year + years

    try:
        return start.replace(year=target_year)
    except ValueError:
        return date(target_year, 2, 28)


def elapsed_complete_years(
    start: date,
    current: date,
) -> int:
    """Count only anniversaries that have actually occurred."""
    if current < start:
        return 0

    years = current.year - start.year
    anniversary = anniversary_date(start, years)

    if current < anniversary:
        years -= 1

    return max(0, years)
