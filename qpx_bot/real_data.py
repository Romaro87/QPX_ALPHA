"""Flexible real-market CSV ingestion for QPX Bot."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from qpx_bot.data_loader import Candle


DATE_NAMES = ("date", "time", "datetime", "timestamp")
OPEN_NAMES = ("open",)
HIGH_NAMES = ("high",)
LOW_NAMES = ("low",)
CLOSE_NAMES = ("close", "adj close", "adjusted close")
VOLUME_NAMES = ("volume", "vol")
VIX_NAMES = ("vix", "close", "value")


@dataclass(frozen=True, slots=True)
class VixPoint:
    """One daily VIX closing observation."""

    date: date
    value: float

    def validate(self) -> None:
        if self.value < 0:
            raise ValueError("VIX cannot be negative.")


def _normalized_headers(
    fieldnames: Sequence[str] | None,
) -> dict[str, str]:
    if not fieldnames:
        raise ValueError("CSV file does not contain a header.")

    mapping: dict[str, str] = {}

    for original in fieldnames:
        normalized = original.strip().lower()
        if normalized:
            mapping[normalized] = original

    return mapping


def _find_column(
    headers: Mapping[str, str],
    candidates: Sequence[str],
    label: str,
) -> str:
    for candidate in candidates:
        if candidate in headers:
            return headers[candidate]

    raise ValueError(
        f"CSV file does not contain a {label} column. "
        f"Accepted names: {', '.join(candidates)}"
    )


def _parse_date(raw_value: str) -> date:
    value = str(raw_value).strip()

    if not value:
        raise ValueError("Date value is empty.")

    try:
        numeric = float(value)
    except ValueError:
        numeric = None

    if numeric is not None:
        if numeric > 10_000_000_000:
            numeric /= 1000.0

        return datetime.fromtimestamp(
            numeric,
            tz=timezone.utc,
        ).date()

    iso_candidate = value.replace("Z", "+00:00")

    try:
        return datetime.fromisoformat(iso_candidate).date()
    except ValueError:
        pass

    for date_format in (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    raise ValueError(f"Unsupported date/time value: {raw_value!r}")


def _load_rows(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV file was not found: {path}")

    if not path.is_file():
        raise ValueError(f"CSV path is not a file: {path}")

    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        headers = _normalized_headers(reader.fieldnames)
        rows = list(reader)

    if not rows:
        raise ValueError(f"CSV file contains no data rows: {path}")

    return rows, headers


def load_market_csv(filename: str | Path) -> list[Candle]:
    """
    Load daily OHLCV from TradingView or conventional CSV exports.

    Column matching is case-insensitive. The date/time column may be an
    ISO timestamp, calendar date, Unix seconds, or Unix milliseconds.
    """
    path = Path(filename).expanduser().resolve()
    rows, headers = _load_rows(path)

    date_column = _find_column(headers, DATE_NAMES, "date/time")
    open_column = _find_column(headers, OPEN_NAMES, "open")
    high_column = _find_column(headers, HIGH_NAMES, "high")
    low_column = _find_column(headers, LOW_NAMES, "low")
    close_column = _find_column(headers, CLOSE_NAMES, "close")
    volume_column = _find_column(headers, VOLUME_NAMES, "volume")

    candles: list[Candle] = []

    for line_number, row in enumerate(rows, start=2):
        try:
            candle = Candle(
                date=_parse_date(row[date_column]),
                open=float(row[open_column]),
                high=float(row[high_column]),
                low=float(row[low_column]),
                close=float(row[close_column]),
                volume=int(float(row[volume_column])),
            )
            candle.validate()
            candles.append(candle)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(
                f"Invalid OHLCV data in {path.name} on line "
                f"{line_number}: {exc}"
            ) from exc

    candles.sort(key=lambda candle: candle.date)
    dates = [candle.date for candle in candles]

    if len(dates) != len(set(dates)):
        raise ValueError(
            f"{path.name} contains duplicate calendar dates. "
            "Export one daily bar per date."
        )

    return candles


def load_vix_csv(filename: str | Path) -> list[VixPoint]:
    """
    Load daily VIX values.

    Supports Date,VIX files and TradingView VIX OHLCV exports, where
    the daily close is used.
    """
    path = Path(filename).expanduser().resolve()
    rows, headers = _load_rows(path)

    date_column = _find_column(headers, DATE_NAMES, "date/time")
    value_column = _find_column(headers, VIX_NAMES, "VIX/close")

    points: list[VixPoint] = []

    for line_number, row in enumerate(rows, start=2):
        try:
            point = VixPoint(
                date=_parse_date(row[date_column]),
                value=float(row[value_column]),
            )
            point.validate()
            points.append(point)
        except (TypeError, ValueError, KeyError) as exc:
            raise ValueError(
                f"Invalid VIX data in {path.name} on line "
                f"{line_number}: {exc}"
            ) from exc

    points.sort(key=lambda point: point.date)
    dates = [point.date for point in points]

    if len(dates) != len(set(dates)):
        raise ValueError(
            f"{path.name} contains duplicate VIX dates."
        )

    return points


def align_vix_to_candles(
    candles: Sequence[Candle],
    points: Sequence[VixPoint],
    *,
    maximum_gap_days: int = 7,
) -> list[float]:
    """
    Align VIX closes to swing candles using prior-value carry-forward.

    Carry-forward is limited so missing data cannot silently span a
    large historical gap.
    """
    if not candles:
        raise ValueError("Cannot align VIX to an empty candle series.")

    if not points:
        raise ValueError("VIX series cannot be empty.")

    if maximum_gap_days < 0:
        raise ValueError("Maximum VIX gap cannot be negative.")

    values: list[float] = []
    point_index = 0
    latest: VixPoint | None = None

    for candle in candles:
        while (
            point_index < len(points)
            and points[point_index].date <= candle.date
        ):
            latest = points[point_index]
            point_index += 1

        if latest is None:
            raise ValueError(
                "VIX history begins after the first swing candle."
            )

        gap = (candle.date - latest.date).days

        if gap > maximum_gap_days:
            raise ValueError(
                f"VIX data gap is {gap} days on {candle.date}; "
                f"maximum allowed is {maximum_gap_days}."
            )

        values.append(latest.value)

    return values


def trim_market_history(
    candles: Sequence[Candle],
    *,
    start_date: date,
    end_date: date,
) -> list[Candle]:
    if start_date > end_date:
        raise ValueError("Trim start date is after end date.")

    return [
        candle
        for candle in candles
        if start_date <= candle.date <= end_date
    ]


def sha256_file(filename: str | Path) -> str:
    """Return a reproducibility hash for one input file."""
    path = Path(filename)
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()
