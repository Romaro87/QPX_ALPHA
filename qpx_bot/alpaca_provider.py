from __future__ import annotations

import csv
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


NEW_YORK = ZoneInfo("America/New_York")


def _thanksgiving_day(year: int) -> date:
    """
    Fourth Thursday of November.
    """
    day = date(year, 11, 1)

    while day.weekday() != 3:
        day += timedelta(days=1)

    return day + timedelta(days=21)


def _regular_session_close(day: date):
    """
    NYSE-equity regular-session close.

    Normal session:
        16:00 ET

    Standard early-close sessions:
        - day after Thanksgiving
        - Christmas Eve when it is an open weekday
        - July 3 when it is an open weekday

    Full market holidays are handled separately by the
    historical engine's market-session validation.
    """
    thanksgiving = _thanksgiving_day(
        day.year
    )

    if day == thanksgiving + timedelta(days=1):
        return (13, 0)

    if (
        day.month == 12
        and day.day == 24
        and day.weekday() < 5
    ):
        return (13, 0)

    if (
        day.month == 7
        and day.day == 3
        and day.weekday() < 5
    ):
        return (13, 0)

    return (16, 0)

ALPACA_URL = "https://data.alpaca.markets/v2/stocks/bars"

REQUEST_TIMEOUT_SECONDS = 30
MAX_REQUEST_ATTEMPTS = 4
MAX_RETRY_DELAY_SECONDS = 30

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CACHE_ROOT = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_alpaca_sip"
    / "shared"
    / "aggregate_15m"
)

KEY_FILE = (
    Path.home()
    / ".config"
    / "qpx"
    / "alpaca.json"
)


@dataclass(frozen=True, slots=True)
class Bar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def _symbol_name(symbol: str) -> str:
    return (
        symbol.strip().upper()
        .replace("^", "")
        .replace(":", "_")
        .replace("/", "_")
    )


def cache_path(symbol: str) -> Path:
    return CACHE_ROOT / f"{_symbol_name(symbol)}_15M.csv"


def manifest_path(symbol: str) -> Path:
    path = cache_path(symbol)
    return path.with_suffix(path.suffix + ".manifest.json")


def credentials() -> tuple[str, str]:
    if not KEY_FILE.exists():
        raise RuntimeError(
            "Alpaca credentials not found. "
            "Run QPX_SET_ALPACA_KEYS.py first."
        )

    payload = json.loads(
        KEY_FILE.read_text(encoding="utf-8")
    )

    key = str(payload.get("key_id", "")).strip()
    secret = str(payload.get("secret_key", "")).strip()

    if not key or not secret:
        raise RuntimeError("Alpaca credentials are incomplete.")

    return key, secret


def _parse_time(raw: str) -> datetime:
    text = str(raw)

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    return datetime.fromisoformat(
        text
    ).astimezone(NEW_YORK)


def _regular_bar(
    raw: dict[str, Any],
) -> Bar | None:
    try:
        timestamp = _parse_time(raw["t"])

        o = float(raw["o"])
        h = float(raw["h"])
        l = float(raw["l"])
        c = float(raw["c"])
        v = int(float(raw.get("v", 0) or 0))
    except (
        KeyError,
        TypeError,
        ValueError,
    ):
        return None

    wall = timestamp.time().replace(tzinfo=None)

    minutes = wall.hour * 60 + wall.minute

    close_hour, close_minute = (
        _regular_session_close(
            timestamp.date()
        )
    )

    close_minutes = (
        close_hour * 60
        + close_minute
    )

    is_early_close = (
        close_minutes < 960
    )

    if is_early_close:
        valid_session_time = (
            570
            <= minutes
            <= close_minutes
        )
    else:
        valid_session_time = (
            570
            <= minutes
            < close_minutes
        )

    if not valid_session_time:
        return None

    if timestamp.minute % 15:
        return None

    if not all(
        math.isfinite(x) and x > 0
        for x in (o, h, l, c)
    ):
        return None

    return Bar(
        start=timestamp,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=max(0, v),
    )


def read_cache(symbol: str) -> dict[str, Bar]:
    path = cache_path(symbol)

    if not path.exists():
        return {}

    bars: dict[str, Bar] = {}

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                start = datetime.fromisoformat(
                    row["TimestampMarket"]
                ).astimezone(NEW_YORK)

                bar = Bar(
                    start=start,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(float(row["Volume"])),
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            bars[start.isoformat()] = bar

    return bars


def write_cache(
    symbol: str,
    bars: dict[str, Bar],
) -> None:
    path = cache_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(".tmp")

    with tmp.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)

        writer.writerow(
            (
                "TimestampMarket",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            )
        )

        for bar in sorted(
            bars.values(),
            key=lambda x: x.start,
        ):
            writer.writerow(
                (
                    bar.start.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                )
            )

    tmp.replace(path)


def read_manifest(symbol: str) -> dict[str, Any]:
    path = manifest_path(symbol)

    if not path.exists():
        return {}

    try:
        payload = json.loads(
            path.read_text(encoding="utf-8")
        )

        if isinstance(payload, dict):
            return payload
    except (
        OSError,
        ValueError,
    ):
        pass

    return {}


def write_manifest(
    symbol: str,
    *,
    bars: dict[str, Bar],
    coverage_start: date,
    coverage_end: date,
) -> None:
    ordered = sorted(
        bars.values(),
        key=lambda x: x.start,
    )

    payload = {
        "schema_version": 1,
        "provider": "alpaca",
        "feed": "sip",
        "symbol": symbol,
        "interval": "15Min",
        "adjustment": "split",
        "coverage_start": coverage_start.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "bar_count": len(ordered),
        "first_bar": (
            ordered[0].start.isoformat()
            if ordered else None
        ),
        "last_bar": (
            ordered[-1].start.isoformat()
            if ordered else None
        ),
        "synthetic_data": False,
        "placeholder_data": False,
    }

    path = manifest_path(symbol)
    path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _request(
    params: dict[str, str],
) -> dict[str, Any]:
    key, secret = credentials()

    url = (
        ALPACA_URL
        + "?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": "QPX-ALPHA",
        },
    )

    for attempt in range(MAX_REQUEST_ATTEMPTS):
        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                payload = json.loads(
                    response.read().decode("utf-8")
                )

            if not isinstance(payload, dict):
                raise RuntimeError(
                    "Malformed Alpaca response."
                )

            return payload

        except urllib.error.HTTPError as exc:
            body = exc.read().decode(
                "utf-8",
                errors="replace",
            )

            if exc.code == 429:
                retry = exc.headers.get("Retry-After")

                try:
                    delay = float(retry) if retry else 5.0
                except ValueError:
                    delay = 5.0

                delay = min(
                    MAX_RETRY_DELAY_SECONDS,
                    max(0.0, delay),
                )

                print(
                    f"Rate limit reached; waiting {delay:.0f}s"
                )
                if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                    time.sleep(delay)
                continue

            raise RuntimeError(
                f"Alpaca HTTP {exc.code}: {body[:500]}"
            ) from exc

        except (
            OSError,
            urllib.error.URLError,
            json.JSONDecodeError,
        ) as exc:
            delay = min(15, 2 + attempt * 2)

            print(
                f"Temporary connection problem; "
                f"retrying in {delay}s"
            )

            if attempt + 1 < MAX_REQUEST_ATTEMPTS:
                time.sleep(delay)

    raise RuntimeError(
        "Alpaca history request failed after retries."
    )


def _fetch_group(
    *,
    symbols: list[str],
    start: date,
    end: date,
    stores: dict[str, dict[str, Bar]],
) -> int:
    params = {
        "symbols": ",".join(symbols),
        "timeframe": "15Min",
        "start": start.isoformat() + "T00:00:00Z",
        "end": (
            end + timedelta(days=1)
        ).isoformat() + "T00:00:00Z",
        "limit": "10000",
        "feed": "sip",
        "adjustment": "split",
        "sort": "asc",
    }

    requests = 0
    page = 0

    while True:
        page += 1
        requests += 1

        payload = _request(params)

        payload_bars = payload.get("bars", {})

        if not isinstance(payload_bars, dict):
            raise RuntimeError(
                "Alpaca returned malformed bars."
            )

        accepted = 0

        for symbol, rows in payload_bars.items():
            normalized = str(symbol).upper()

            if normalized not in stores:
                continue

            if not isinstance(rows, list):
                continue

            for raw in rows:
                if not isinstance(raw, dict):
                    continue

                bar = _regular_bar(raw)

                if bar is None:
                    continue

                if not (
                    start
                    <= bar.start.date()
                    <= end
                ):
                    continue

                stores[normalized][
                    bar.start.isoformat()
                ] = bar

                accepted += 1

        print(
            f"Page {page:02d}: "
            f"{accepted:,} regular-session bars"
        )

        token = payload.get("next_page_token")

        if not token:
            break

        params["page_token"] = str(token)

    return requests


def sync(
    *,
    symbols: list[str],
    start: date,
    end: date,
) -> dict[str, Path]:
    cleaned: list[str] = []

    for raw in symbols:
        symbol = str(raw).strip().upper()

        if symbol and symbol not in cleaned:
            cleaned.append(symbol)

    if not cleaned:
        raise ValueError("No symbols supplied.")

    stores = {
        symbol: read_cache(symbol)
        for symbol in cleaned
    }

    manifests = {
        symbol: read_manifest(symbol)
        for symbol in cleaned
    }

    groups: dict[
        tuple[date, date],
        list[str],
    ] = {}

    for symbol in cleaned:
        manifest = manifests[symbol]

        coverage_start = manifest.get("coverage_start")
        coverage_end = manifest.get("coverage_end")

        if not coverage_start or not coverage_end:
            groups.setdefault(
                (start, end),
                [],
            ).append(symbol)
            continue

        try:
            cached_start = date.fromisoformat(
                str(coverage_start)
            )
            cached_end = date.fromisoformat(
                str(coverage_end)
            )
        except ValueError:
            groups.setdefault(
                (start, end),
                [],
            ).append(symbol)
            continue

        if start < cached_start:
            missing_end = min(
                end,
                cached_start - timedelta(days=1),
            )

            if start <= missing_end:
                groups.setdefault(
                    (start, missing_end),
                    [],
                ).append(symbol)

        if end > cached_end:
            missing_start = max(
                start,
                cached_end + timedelta(days=1),
            )

            if missing_start <= end:
                groups.setdefault(
                    (missing_start, end),
                    [],
                ).append(symbol)

        if (
            cached_start <= start
            and cached_end >= end
        ):
            print(
                f"{symbol:8} CACHE HIT "
                f"{cached_start} -> {cached_end}"
            )

    requests = 0

    for (
        missing_start,
        missing_end,
    ), group_symbols in sorted(
        groups.items(),
        key=lambda x: x[0],
    ):
        print()
        print(
            "FETCHING "
            + ", ".join(group_symbols)
        )
        print(
            f"{missing_start} -> {missing_end}"
        )

        requests += _fetch_group(
            symbols=group_symbols,
            start=missing_start,
            end=missing_end,
            stores=stores,
        )

    outputs: dict[str, Path] = {}

    for symbol in cleaned:
        bars = stores[symbol]

        if not bars:
            raise RuntimeError(
                f"No usable bars available for {symbol}."
            )

        write_cache(symbol, bars)

        existing = manifests[symbol]

        existing_start = existing.get("coverage_start")
        existing_end = existing.get("coverage_end")

        ranges = [start, end]

        if existing_start:
            try:
                ranges.append(
                    date.fromisoformat(
                        str(existing_start)
                    )
                )
            except ValueError:
                pass

        if existing_end:
            try:
                ranges.append(
                    date.fromisoformat(
                        str(existing_end)
                    )
                )
            except ValueError:
                pass

        coverage_start = min(ranges)
        coverage_end = max(ranges)

        write_manifest(
            symbol,
            bars=bars,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
        )

        outputs[symbol] = cache_path(symbol)

        ordered = sorted(
            bars.values(),
            key=lambda x: x.start,
        )

        print(
            f"{symbol:8} "
            f"{len(ordered):,} cached bars | "
            f"{ordered[0].start.date()} -> "
            f"{ordered[-1].start.date()}"
        )

    print()
    print(
        f"TOTAL ALPACA REQUESTS: {requests}"
    )

    return outputs


# ============================================================
# QPX STRICT CACHE VALIDATION V1
# ============================================================

def _qpx_expected_session_timestamps(
    start: date,
    end: date,
) -> set[datetime]:
    """
    Build the exact regular-session 15-minute timestamp grid
    required by QPX.

    Normal NYSE session:
        09:30 through 15:45

    Early-close session:
        09:30 through 13:00

    QPX fails closed when required timestamps are absent.
    """
    from qpx_bot.actual_two_year_15m_six import (
        is_market_session,
    )

    expected: set[datetime] = set()

    day = start

    while day <= end:
        # January 9, 2025 was an actual NYSE closure
        # for the National Day of Mourning.
        open_session = (
            day != date(2025, 1, 9)
            and is_market_session(day)
        )

        if open_session:
            close_hour, close_minute = (
                _regular_session_close(day)
            )

            close_total = (
                close_hour * 60
                + close_minute
            )

            minute = 9 * 60 + 30

            while True:
                if close_total < 16 * 60:
                    if minute > close_total:
                        break
                else:
                    if minute >= close_total:
                        break

                hour = minute // 60
                minute_part = minute % 60

                expected.add(
                    datetime(
                        day.year,
                        day.month,
                        day.day,
                        hour,
                        minute_part,
                        tzinfo=NEW_YORK,
                    )
                )

                minute += 15

        day += timedelta(days=1)

    return expected


def validate_cache_file(
    *,
    path: Path,
    symbol: str,
    start: date,
    end: date,
) -> dict[str, object]:
    """
    Strict QPX validation of one cached 15-minute CSV.

    Rejects:
      - missing files
      - malformed rows
      - duplicate timestamps
      - timestamps outside the required session grid
      - any missing expected regular-session timestamp
      - invalid OHLC values
      - negative volume
    """
    symbol = symbol.strip().upper()

    if not path.exists():
        raise RuntimeError(
            f"{symbol}: Alpaca cache is missing: {path}"
        )

    actual: dict[
        datetime,
        tuple[float, float, float, float, int],
    ] = {}

    malformed = 0
    duplicates = 0

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        required = {
            "TimestampMarket",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        fields = set(
            reader.fieldnames or []
        )

        if not required.issubset(fields):
            raise RuntimeError(
                f"{symbol}: Alpaca cache has invalid columns."
            )

        for row in reader:
            try:
                timestamp = datetime.fromisoformat(
                    str(
                        row["TimestampMarket"]
                    )
                ).astimezone(NEW_YORK)

                if not (
                    start
                    <= timestamp.date()
                    <= end
                ):
                    continue

                open_price = float(
                    row["Open"]
                )

                high_price = float(
                    row["High"]
                )

                low_price = float(
                    row["Low"]
                )

                close_price = float(
                    row["Close"]
                )

                volume = int(
                    float(
                        row["Volume"]
                    )
                )

                if (
                    open_price <= 0
                    or high_price <= 0
                    or low_price <= 0
                    or close_price <= 0
                    or volume < 0
                    or high_price
                    < max(
                        open_price,
                        low_price,
                        close_price,
                    )
                    or low_price
                    > min(
                        open_price,
                        high_price,
                        close_price,
                    )
                ):
                    raise ValueError(
                        "invalid OHLCV"
                    )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                malformed += 1
                continue

            if timestamp in actual:
                duplicates += 1
                continue

            actual[timestamp] = (
                open_price,
                high_price,
                low_price,
                close_price,
                volume,
            )

    if malformed:
        raise RuntimeError(
            f"{symbol}: Alpaca cache contains "
            f"{malformed} malformed rows."
        )

    if duplicates:
        raise RuntimeError(
            f"{symbol}: Alpaca cache contains "
            f"{duplicates} duplicate timestamps."
        )

    expected = (
        _qpx_expected_session_timestamps(
            start,
            end,
        )
    )

    actual_times = set(actual)

    missing = sorted(
        expected - actual_times
    )

    unexpected = sorted(
        actual_times - expected
    )

    if missing:
        preview = ", ".join(
            value.isoformat()
            for value in missing[:5]
        )

        raise RuntimeError(
            f"{symbol}: Alpaca cache is incomplete. "
            f"Missing {len(missing)} required "
            f"15-minute bars. First missing: {preview}"
        )

    if unexpected:
        preview = ", ".join(
            value.isoformat()
            for value in unexpected[:5]
        )

        raise RuntimeError(
            f"{symbol}: Alpaca cache contains "
            f"{len(unexpected)} timestamps outside "
            f"the validated regular-session grid. "
            f"First unexpected: {preview}"
        )

    if len(actual_times) != len(expected):
        raise RuntimeError(
            f"{symbol}: Alpaca cache count mismatch."
        )

    sessions = {
        value.date()
        for value in actual_times
    }

    return {
        "symbol": symbol,
        "bars": len(actual_times),
        "sessions": len(sessions),
        "start": (
            min(actual_times).date()
            if actual_times
            else None
        ),
        "end": (
            max(actual_times).date()
            if actual_times
            else None
        ),
    }


def _qpx_cache_file(
    symbol: str,
) -> Path:
    safe = (
        symbol.strip().upper()
        .replace("^", "")
        .replace(":", "_")
        .replace("/", "_")
    )

    return (
        CACHE_ROOT
        / f"{safe}_15M.csv"
    )


def validate_cache(
    *,
    symbols,
    start: date,
    end: date,
) -> dict[str, dict[str, object]]:
    results = {}

    for symbol in symbols:
        normalized = str(
            symbol
        ).strip().upper()

        result = validate_cache_file(
            path=_qpx_cache_file(
                normalized
            ),
            symbol=normalized,
            start=start,
            end=end,
        )

        results[normalized] = result

        print(
            f"{normalized:<8} STRICT VALIDATION PASSED | "
            f"{result['bars']:,} bars | "
            f"{result['sessions']} sessions"
        )

    return results


# Preserve the existing downloader and wrap it with strict
# post-download validation. If a manifest incorrectly claims
# that an incomplete cache is valid, QPX removes that symbol's
# local cache and downloads it again. If the provider still
# cannot supply the complete dataset, the run aborts.
_qpx_original_sync = sync


def sync(
    *,
    symbols,
    start: date,
    end: date,
    **kwargs,
):
    result = _qpx_original_sync(
        symbols=symbols,
        start=start,
        end=end,
        **kwargs,
    )

    failed = []

    for raw_symbol in symbols:
        symbol = str(
            raw_symbol
        ).strip().upper()

        try:
            validate_cache_file(
                path=_qpx_cache_file(
                    symbol
                ),
                symbol=symbol,
                start=start,
                end=end,
            )

        except RuntimeError as exc:
            print(
                f"{symbol:<8} CACHE VALIDATION FAILED: "
                f"{exc}"
            )

            failed.append(symbol)

    if failed:
        print(
            "Invalid Alpaca cache detected. "
            "Refreshing affected symbols only."
        )

        for symbol in failed:
            cache = _qpx_cache_file(
                symbol
            )

            manifest = cache.with_suffix(
                cache.suffix
                + ".manifest.json"
            )

            cache.unlink(
                missing_ok=True
            )

            manifest.unlink(
                missing_ok=True
            )

        result = _qpx_original_sync(
            symbols=symbols,
            start=start,
            end=end,
            **kwargs,
        )

    validate_cache(
        symbols=symbols,
        start=start,
        end=end,
    )

    return result
