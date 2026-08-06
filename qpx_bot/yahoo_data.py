"""Dependency-free Yahoo chart data acquisition for QPX Bot."""

from __future__ import annotations

import csv
import json
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import median
from pathlib import Path
from typing import Any

from qpx_bot.real_data import sha256_file


YAHOO_HOSTS = (
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
)


class YahooDataError(RuntimeError):
    """Raised when a complete, valid chart response cannot be obtained."""


@dataclass(frozen=True, slots=True)
class MarketRow:
    date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int


@dataclass(frozen=True, slots=True)
class DividendRow:
    date: date
    amount: float


@dataclass(frozen=True, slots=True)
class DownloadSummary:
    provider: str
    swing_symbol: str
    income_symbol: str
    vix_symbol: str
    swing_rows: int
    income_rows: int
    vix_rows: int
    dividend_events: int
    common_first_date: date
    common_last_date: date
    input_directory: Path
    manifest_path: Path



def _daily_period_bounds(
    range_name: str,
) -> tuple[int, int, str]:
    """
    Convert a requested range into a bounded daily-data window.

    Yahoo can silently downgrade ``range=max`` requests to weekly or
    monthly bars. QPX therefore requests explicit Unix timestamps.
    Five years stays inside the provider's daily-history limits while
    fully covering QDTE's available history.
    """
    normalized = range_name.strip().lower()
    years = 5

    if normalized not in {"", "max", "daily"}:
        if normalized.endswith("y") and normalized[:-1].isdigit():
            years = int(normalized[:-1])
        else:
            raise ValueError(
                "History range must be max, daily, or a value such "
                "as 3y, 5y, or 8y."
            )

    years = max(1, min(years, 8))
    end = datetime.now(timezone.utc) + timedelta(days=2)
    start = end - timedelta(days=366 * years)

    return (
        int(start.timestamp()),
        int(end.timestamp()),
        f"{years}y-daily",
    )


def _chart_url(
    host: str,
    symbol: str,
    *,
    range_name: str,
) -> str:
    encoded_symbol = urllib.parse.quote(symbol, safe="")
    period1, period2, _ = _daily_period_bounds(range_name)
    query = urllib.parse.urlencode(
        {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
            "includePrePost": "false",
            "includeAdjustedClose": "true",
        }
    )
    return (
        f"https://{host}/v8/finance/chart/"
        f"{encoded_symbol}?{query}"
    )



def _open_json(url: str, timeout_seconds: float) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 14) "
                "AppleWebKit/537.36 QPXBot/1.8"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout_seconds,
    ) as response:
        raw = response.read()

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise YahooDataError(
            "The provider returned a non-JSON response."
        ) from exc

    chart = payload.get("chart")

    if not isinstance(chart, Mapping):
        raise YahooDataError("Chart response is missing.")

    provider_error = chart.get("error")

    if provider_error:
        raise YahooDataError(
            f"Provider error: {provider_error}"
        )

    results = chart.get("result")

    if not isinstance(results, list) or not results:
        raise YahooDataError("Chart response contains no result.")

    result = results[0]

    if not isinstance(result, Mapping):
        raise YahooDataError("Chart result has an invalid shape.")

    return result



def _validate_daily_result(
    result: Mapping[str, Any],
    symbol: str,
) -> None:
    """Reject provider responses that were silently downsampled."""
    meta = result.get("meta")
    granularity = None

    if isinstance(meta, Mapping):
        raw_granularity = meta.get("dataGranularity")
        if raw_granularity is not None:
            granularity = str(raw_granularity).strip().lower()

    if granularity and granularity != "1d":
        raise YahooDataError(
            f"{symbol} returned {granularity} bars instead of "
            "required 1d bars."
        )

    timestamps = _sequence(result, "timestamp")

    if len(timestamps) < 2:
        raise YahooDataError(
            f"{symbol} returned too few observations."
        )

    dates = [
        datetime.fromtimestamp(
            float(timestamp),
            tz=timezone.utc,
        ).date()
        for timestamp in timestamps
        if timestamp is not None
    ]

    if len(dates) < 2:
        raise YahooDataError(
            f"{symbol} returned too few valid timestamps."
        )

    gaps = [
        (current - previous).days
        for previous, current in zip(dates, dates[1:])
        if current > previous
    ]

    if not gaps:
        raise YahooDataError(
            f"{symbol} returned no increasing daily dates."
        )

    typical_gap = float(median(gaps))

    if typical_gap > 4.0:
        raise YahooDataError(
            f"{symbol} appears downsampled; median bar gap is "
            f"{typical_gap:.1f} days."
        )


def fetch_chart(
    symbol: str,
    *,
    range_name: str = "max",
    timeout_seconds: float = 30.0,
    maximum_attempts: int = 6,
) -> Mapping[str, Any]:
    """Fetch one true daily chart with host failover and backoff."""
    normalized = symbol.strip().upper()

    if not normalized:
        raise ValueError("Ticker symbol cannot be empty.")

    if maximum_attempts < 1:
        raise ValueError("Maximum attempts must be positive.")

    errors: list[str] = []

    for attempt in range(1, maximum_attempts + 1):
        host = YAHOO_HOSTS[(attempt - 1) % len(YAHOO_HOSTS)]
        url = _chart_url(
            host,
            normalized,
            range_name=range_name,
        )

        try:
            result = _open_json(url, timeout_seconds)
            _validate_daily_result(result, normalized)
            return result
        except (
            YahooDataError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            OSError,
        ) as exc:
            errors.append(
                f"attempt {attempt} via {host}: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < maximum_attempts:
                delay = min(12.0, 1.5 * attempt)
                print(
                    f"Provider retry {attempt}/"
                    f"{maximum_attempts} in {delay:.1f}s..."
                )
                time.sleep(delay)

    raise YahooDataError(
        f"Unable to download true daily {normalized} data after "
        f"{maximum_attempts} attempts.\n"
        + "\n".join(errors)
    )



def _sequence(
    mapping: Mapping[str, Any],
    name: str,
) -> Sequence[Any]:
    value = mapping.get(name, ())

    if isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes),
    ):
        return value

    return ()


def extract_market_rows(
    result: Mapping[str, Any],
) -> list[MarketRow]:
    """Convert a Yahoo chart result into validated daily rows."""
    meta = result.get("meta")
    symbol = "UNKNOWN"

    if isinstance(meta, Mapping):
        symbol = str(meta.get("symbol") or symbol)

    _validate_daily_result(result, symbol)
    timestamps = _sequence(result, "timestamp")
    indicators = result.get("indicators")

    if not isinstance(indicators, Mapping):
        raise YahooDataError("Chart indicators are missing.")

    quotes = indicators.get("quote")

    if not isinstance(quotes, list) or not quotes:
        raise YahooDataError("Chart quote arrays are missing.")

    quote = quotes[0]

    if not isinstance(quote, Mapping):
        raise YahooDataError("Chart quote data is invalid.")

    opens = _sequence(quote, "open")
    highs = _sequence(quote, "high")
    lows = _sequence(quote, "low")
    closes = _sequence(quote, "close")
    volumes = _sequence(quote, "volume")
    adjusted_groups = indicators.get("adjclose")
    adjusted_closes: Sequence[Any] = ()

    if (
        isinstance(adjusted_groups, list)
        and adjusted_groups
        and isinstance(adjusted_groups[0], Mapping)
    ):
        adjusted_closes = _sequence(
            adjusted_groups[0],
            "adjclose",
        )

    rows: list[MarketRow] = []

    for index, timestamp in enumerate(timestamps):
        try:
            open_price = opens[index]
            high_price = highs[index]
            low_price = lows[index]
            close_price = closes[index]
        except IndexError:
            continue

        if any(
            value is None
            for value in (
                timestamp,
                open_price,
                high_price,
                low_price,
                close_price,
            )
        ):
            continue

        volume_value = (
            volumes[index]
            if index < len(volumes)
            and volumes[index] is not None
            else 0
        )
        adjusted_value = (
            adjusted_closes[index]
            if index < len(adjusted_closes)
            and adjusted_closes[index] is not None
            else close_price
        )

        row = MarketRow(
            date=datetime.fromtimestamp(
                float(timestamp),
                tz=timezone.utc,
            ).date(),
            open=float(open_price),
            high=float(high_price),
            low=float(low_price),
            close=float(close_price),
            adjusted_close=float(adjusted_value),
            volume=max(0, int(float(volume_value))),
        )

        if (
            row.open <= 0
            or row.close <= 0
            or row.adjusted_close <= 0
        ):
            continue

        if row.high < max(row.open, row.close, row.low):
            continue

        if row.low > min(row.open, row.close, row.high):
            continue

        rows.append(row)

    rows.sort(key=lambda row: row.date)

    deduplicated: dict[date, MarketRow] = {
        row.date: row
        for row in rows
    }
    rows = [
        deduplicated[day]
        for day in sorted(deduplicated)
    ]

    if not rows:
        raise YahooDataError(
            "No valid daily market rows were returned."
        )

    return rows


def extract_dividend_rows(
    result: Mapping[str, Any],
) -> list[DividendRow]:
    """Extract and combine cash distributions by calendar date."""
    events = result.get("events")

    if not isinstance(events, Mapping):
        return []

    dividends = events.get("dividends")

    if not isinstance(dividends, Mapping):
        return []

    amounts: dict[date, float] = {}

    for event in dividends.values():
        if not isinstance(event, Mapping):
            continue

        timestamp = event.get("date")
        amount = event.get("amount")

        if timestamp is None or amount is None:
            continue

        event_date = datetime.fromtimestamp(
            float(timestamp),
            tz=timezone.utc,
        ).date()
        numeric_amount = float(amount)

        if numeric_amount < 0:
            raise YahooDataError(
                "Negative dividend amount was returned."
            )

        amounts[event_date] = (
            amounts.get(event_date, 0.0)
            + numeric_amount
        )

    return [
        DividendRow(date=event_date, amount=amounts[event_date])
        for event_date in sorted(amounts)
    ]


def _atomic_csv(
    path: Path,
    header: Sequence[str],
    rows: Sequence[Sequence[Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)

    temporary.replace(path)


def _write_market(path: Path, rows: Sequence[MarketRow]) -> None:
    _atomic_csv(
        path,
        (
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "AdjClose",
            "Volume",
        ),
        [
            (
                row.date.isoformat(),
                f"{row.open:.8f}",
                f"{row.high:.8f}",
                f"{row.low:.8f}",
                f"{row.close:.8f}",
                f"{row.adjusted_close:.8f}",
                row.volume,
            )
            for row in rows
        ],
    )


def _write_vix(path: Path, rows: Sequence[MarketRow]) -> None:
    _atomic_csv(
        path,
        ("Date", "VIX"),
        [
            (
                row.date.isoformat(),
                f"{row.close:.8f}",
            )
            for row in rows
        ],
    )


def _write_dividends(
    path: Path,
    rows: Sequence[DividendRow],
) -> None:
    _atomic_csv(
        path,
        ("Date", "Dividend"),
        [
            (
                row.date.isoformat(),
                f"{row.amount:.8f}",
            )
            for row in rows
        ],
    )


def _backup_existing_files(
    paths: Sequence[Path],
    backup_directory: Path | None,
) -> None:
    if backup_directory is None:
        return

    existing = [path for path in paths if path.exists()]

    if not existing:
        return

    backup_directory.mkdir(parents=True, exist_ok=True)

    for path in existing:
        shutil.copy2(path, backup_directory / path.name)

    print(f"Previous input files backed up: {backup_directory}")


def download_real_dataset(
    *,
    swing_symbol: str,
    input_directory: str | Path,
    income_symbol: str = "QDTE",
    vix_symbol: str = "^VIX",
    range_name: str = "max",
    backup_directory: str | Path | None = None,
    fetcher: Callable[[str], Mapping[str, Any]] | None = None,
) -> DownloadSummary:
    """
    Download swing, income, dividend, and VIX data atomically.

    The default fetcher uses Yahoo's public chart endpoint. A custom
    fetcher is accepted so the conversion path can be tested without
    network access.
    """
    normalized_swing = swing_symbol.strip().upper()
    normalized_income = income_symbol.strip().upper()
    normalized_vix = vix_symbol.strip().upper()

    if not normalized_swing:
        raise ValueError("Swing symbol cannot be empty.")

    directory = Path(input_directory).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    if fetcher is None:
        def selected_fetcher(symbol: str) -> Mapping[str, Any]:
            return fetch_chart(symbol, range_name=range_name)
    else:
        selected_fetcher = fetcher

    print(f"Downloading {normalized_swing} daily history...")
    swing_result = selected_fetcher(normalized_swing)

    print(f"Downloading {normalized_income} daily history...")
    income_result = selected_fetcher(normalized_income)

    print(f"Downloading {normalized_vix} daily history...")
    vix_result = selected_fetcher(normalized_vix)

    swing_rows = extract_market_rows(swing_result)
    income_rows = extract_market_rows(income_result)
    vix_rows = extract_market_rows(vix_result)
    dividend_rows = extract_dividend_rows(income_result)

    if not dividend_rows:
        raise YahooDataError(
            f"No dividend events were returned for "
            f"{normalized_income}."
        )

    output_paths = {
        "swing": directory / "SWING.csv",
        "income": directory / "QDTE.csv",
        "dividends": directory / "QDTE_DIVIDENDS.csv",
        "vix": directory / "VIX.csv",
        "manifest": directory / "DOWNLOAD_MANIFEST.json",
    }

    backup_path = (
        Path(backup_directory).expanduser().resolve()
        if backup_directory is not None
        else None
    )
    _backup_existing_files(
        (
            output_paths["swing"],
            output_paths["income"],
            output_paths["dividends"],
            output_paths["vix"],
            output_paths["manifest"],
        ),
        backup_path,
    )

    _write_market(output_paths["swing"], swing_rows)
    _write_market(output_paths["income"], income_rows)
    _write_dividends(
        output_paths["dividends"],
        dividend_rows,
    )
    _write_vix(output_paths["vix"], vix_rows)

    common_first = max(
        swing_rows[0].date,
        income_rows[0].date,
        vix_rows[0].date,
    )
    common_last = min(
        swing_rows[-1].date,
        income_rows[-1].date,
        vix_rows[-1].date,
    )

    if common_first > common_last:
        raise YahooDataError(
            "Downloaded histories do not overlap."
        )

    manifest = {
        "provider": "Yahoo Finance chart endpoint",
        "downloaded_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "requested_range": range_name,
        "effective_window": _daily_period_bounds(range_name)[2],
        "interval": "1d",
        "symbols": {
            "swing": normalized_swing,
            "income": normalized_income,
            "vix": normalized_vix,
        },
        "rows": {
            "swing": len(swing_rows),
            "income": len(income_rows),
            "vix": len(vix_rows),
            "dividend_events": len(dividend_rows),
        },
        "common_first_date": common_first.isoformat(),
        "common_last_date": common_last.isoformat(),
        "files": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for name, path in output_paths.items()
            if name != "manifest"
        },
        "notice": (
            "Third-party market data can be revised or unavailable. "
            "Preserve this manifest with every research result."
        ),
    }
    output_paths["manifest"].write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return DownloadSummary(
        provider=manifest["provider"],
        swing_symbol=normalized_swing,
        income_symbol=normalized_income,
        vix_symbol=normalized_vix,
        swing_rows=len(swing_rows),
        income_rows=len(income_rows),
        vix_rows=len(vix_rows),
        dividend_events=len(dividend_rows),
        common_first_date=common_first,
        common_last_date=common_last,
        input_directory=directory,
        manifest_path=output_paths["manifest"],
    )
