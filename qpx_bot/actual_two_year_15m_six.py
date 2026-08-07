"""All-real two-year 15-minute QPX six-position portfolio backtest."""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
import getpass
import hashlib
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from qpx_bot.allocation import rebalance_income_allocation
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import IndicatorSet, calculate_indicators
from qpx_bot.intraday_six_paper import (
    IntradayBar,
    choose_without_ranking,
    load_policy,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    is_market_session,
    latest_completed_session,
)
from qpx_bot.performance import ReturnMetrics, metrics_from_returns
from qpx_bot.portfolio import ClosedTrade, Portfolio, contribution_allocation
from qpx_bot.risk import buy_fill, calculate_position_size
from qpx_bot.strategy import evaluate_entry, evaluate_exit
from qpx_bot.time_rules import elapsed_complete_years


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_DATA_ROOT = (
    PROJECT_ROOT
    / "research_data"
    / "qpx_actual_two_year_15m_six"
)
DEFAULT_REPORT_ROOT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_actual_two_year_15m_six"
)
DEFAULT_VIX_CACHE = (
    DEFAULT_DATA_ROOT
    / "shared"
    / "CBOE_VIX_DAILY.csv"
)
DEFAULT_AGGREGATE_CACHE = (
    DEFAULT_DATA_ROOT
    / "shared"
    / "aggregate_15m"
)
FIXED_WINDOW_START = date(2024, 8, 6)
FIXED_WINDOW_END = date(2026, 7, 28)
FIXED_INITIALIZATION_BARS = 200
FIXED_MINIMUM_COMMON_BARS = 11_500
FIXED_MINIMUM_COMMON_SESSIONS = 450
DEFAULT_FIXED_REPORT_ROOT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_fixed_2024_08_06_to_2026_07_28"
)
DEFAULT_SWING_ONLY_REPORT_ROOT = (
    PROJECT_ROOT
    / "reports"
    / "qpx_swing_only_control_2024_08_06_to_2026_07_28"
)
PROVIDER_HOSTS = (
    "https://api.massive.com",
    "https://api.polygon.io",
)
SWING_SYMBOLS = (
    "DIA",
    "IWM",
    "QQQ",
    "SPY",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
)
INCOME_SYMBOL = "QDTE"
VIX_PROVIDER_SYMBOL = "CBOE_VIX_PREVIOUS_SESSION_CLOSE"
CBOE_VIX_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/"
    "daily_prices/VIX_History.csv"
)
VIX_OBSERVATION_POLICY = (
    "PREVIOUS_COMPLETED_SESSION_DAILY_CLOSE"
)
INTERVAL_MINUTES = 15
CHUNK_DAYS = 90
WARMUP_DAYS = 75
MINIMUM_TEST_BARS = 12_000
MINIMUM_TEST_SESSIONS = 480
MAXIMUM_START_DELAY_DAYS = 10
MAXIMUM_END_STALE_DAYS = 4
ANNUAL_15M_BARS = 252 * 26


@dataclass(frozen=True, slots=True)
class DividendEvent:
    event_id: str
    ex_date: date
    cash_amount: float


@dataclass(frozen=True, slots=True)
class PendingSignal:
    symbol: str
    signal_time: datetime
    signal_atr: float
    prior_close: float
    tie_key: str


@dataclass(frozen=True, slots=True)
class TradeRecord:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    shares: int
    entry_price: float
    exit_price: float
    pnl: float
    tax_reserved: float
    reason: str
    result_r: float


@dataclass(frozen=True, slots=True)
class EquityPoint:
    time: datetime
    total_equity: float
    total_contributions: float
    income_value: float
    swing_equity: float
    swing_cash: float
    swing_market_value: float
    tax_reserve: float
    income_weight: float
    target_income_weight: float
    open_positions: int
    pending_entries: int
    active_risk: float


@dataclass(frozen=True, slots=True)
class AllocationRecord:
    time: datetime
    event_type: str
    external_contribution: float
    target_income_weight: float
    action: str
    before_income_weight: float
    after_income_weight: float
    qdte_market_value_traded: float
    realized_pnl: float
    tax_reserved: float


@dataclass(frozen=True, slots=True)
class SignalRecord:
    time: datetime
    symbol: str
    action: str
    detail: str
    tie_key: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    generated_at_utc: str
    provider: str
    actual_data: bool
    requested_start: date
    actual_start: date
    actual_end: date
    warmup_start: date
    fixed_window: bool
    local_only: bool
    swing_only: bool
    initialization_bars: int
    first_entry_eligible_time: str
    interval: str
    common_test_bars: int
    test_sessions: int
    expected_market_sessions: int
    session_coverage: float
    swing_symbols: tuple[str, ...]
    income_symbol: str
    vix_symbol: str
    vix_observation_policy: str
    rankings_enabled: bool
    maximum_concurrent_positions: int
    maximum_observed_positions: int
    starting_income_cash: float
    starting_swing_cash: float
    starting_total_capital: float
    monthly_contribution: float
    contribution_count: int
    total_contributions: float
    ending_equity: float
    net_profit: float
    return_on_contributions: float
    flow_adjusted_total_return: float
    flow_adjusted_cagr: float
    annualized_volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    maximum_drawdown: float
    swing_exposure: float
    ending_income_value: float
    ending_income_weight: float
    ending_swing_equity: float
    ending_swing_cash: float
    ending_tax_reserve: float
    qdte_distributions_received: float
    qdte_distribution_events: int
    all_symbol_evaluations: int
    qualifying_signal_bars: int
    qualifying_by_symbol: Mapping[str, int]
    staged_signals: int
    filled_entries: int
    capacity_deferred: int
    gap_rejections: int
    risk_rejections: int
    closed_trades: int
    trades_by_symbol: Mapping[str, int]
    win_rate: float
    profit_factor: float | None
    failed_check_counts: Mapping[str, int]
    allocation_anniversary_rule: str
    forced_entries: bool
    placeholder_data: bool
    synthetic_data: bool
    live_broker_enabled: bool


@dataclass(frozen=True, slots=True)
class RunArtifacts:
    report: Path
    result: Path
    equity: Path
    trades: Path
    signals: Path
    allocations: Path
    diagnostics: Path
    provenance: Path
    manifest: Path


class ProviderError(RuntimeError):
    """Raised when all-real provider data cannot be retrieved or validated."""


def subtract_years(day: date, years: int) -> date:
    if years < 1:
        raise ValueError("Years must be positive.")

    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(
            year=day.year - years,
            month=2,
            day=28,
        )


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            block = file.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def _sanitize_message(
    raw: str,
    api_key: str,
) -> str:
    return raw.replace(api_key, "[REDACTED]")


def _provider_json(
    *,
    api_key: str,
    path: str,
    query: Mapping[str, str],
    attempts: int = 8,
) -> tuple[Mapping[str, Any], str]:
    last_error: Exception | None = None

    for host in PROVIDER_HOSTS:
        params = dict(query)
        params["apiKey"] = api_key
        url = (
            host.rstrip("/")
            + path
            + "?"
            + urllib.parse.urlencode(params)
        )

        for attempt in range(attempts):
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Linux; Android 14) "
                        "AppleWebKit/537.36 QPXBot/1.27.0"
                    ),
                    "Accept": "application/json",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )

            try:
                with urllib.request.urlopen(
                    request,
                    timeout=45.0,
                ) as response:
                    payload = json.loads(
                        response.read().decode("utf-8")
                    )

                if not isinstance(payload, Mapping):
                    raise ProviderError(
                        "Provider response is not a JSON object."
                    )

                status = str(
                    payload.get("status", "")
                ).upper()

                if status in {
                    "ERROR",
                    "NOT_AUTHORIZED",
                    "NOT_AUTHENTICATED",
                }:
                    message = str(
                        payload.get(
                            "error",
                            payload.get(
                                "message",
                                "Provider rejected the request.",
                            ),
                        )
                    )
                    raise ProviderError(
                        _sanitize_message(
                            message,
                            api_key,
                        )
                    )

                return payload, host
            except urllib.error.HTTPError as exc:
                try:
                    body = exc.read().decode(
                        "utf-8",
                        errors="replace",
                    )
                except OSError:
                    body = ""

                if exc.code == 429:
                    retry_after = exc.headers.get(
                        "Retry-After"
                    )
                    delay = (
                        float(retry_after)
                        if retry_after
                        else min(65.0, 5.0 * (attempt + 1))
                    )
                    print(
                        "Provider rate limit reached; "
                        f"waiting {delay:.0f} seconds..."
                    )
                    time.sleep(delay)
                    last_error = exc
                    continue

                message = (
                    f"HTTP {exc.code}: "
                    + _sanitize_message(
                        body[:500],
                        api_key,
                    )
                )
                last_error = ProviderError(message)
                break
            except (
                OSError,
                urllib.error.URLError,
                json.JSONDecodeError,
                ProviderError,
            ) as exc:
                last_error = exc

                if isinstance(exc, ProviderError):
                    break

                time.sleep(min(10.0, 1.5 * (attempt + 1)))

    raise ProviderError(
        "Unable to obtain entitled provider data: "
        f"{last_error}"
    )


def chunk_ranges(
    start: date,
    end: date,
    *,
    chunk_days: int = CHUNK_DAYS,
) -> tuple[tuple[date, date], ...]:
    if end < start:
        raise ValueError("End date cannot precede start date.")

    if chunk_days < 1:
        raise ValueError("Chunk size must be positive.")

    ranges: list[tuple[date, date]] = []
    current = start

    while current <= end:
        chunk_end = min(
            end,
            current + timedelta(days=chunk_days - 1),
        )
        ranges.append((current, chunk_end))
        current = chunk_end + timedelta(days=1)

    return tuple(ranges)


def _regular_bar(
    raw: Mapping[str, Any],
) -> IntradayBar | None:
    try:
        start = datetime.fromtimestamp(
            int(raw["t"]) / 1000.0,
            tz=timezone.utc,
        ).astimezone(NEW_YORK)
        values = (
            float(raw["o"]),
            float(raw["h"]),
            float(raw["l"]),
            float(raw["c"]),
        )
        volume = int(raw.get("v", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None

    if not all(
        math.isfinite(value) and value > 0
        for value in values
    ):
        return None

    wall = start.time().replace(tzinfo=None)

    if not (
        clock_time(9, 30)
        <= wall
        < clock_time(16, 0)
    ):
        return None

    if start.minute % INTERVAL_MINUTES != 0:
        return None

    return IntradayBar(
        start=start,
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
        volume=max(0, volume),
    )




def _chunk_id(
    chunk_start: date,
    chunk_end: date,
) -> str:
    return (
        f"{chunk_start.isoformat()}_"
        f"{chunk_end.isoformat()}"
    )


def _chunk_has_end_coverage(
    *,
    bars: Sequence[IntradayBar],
    chunk_start: date,
    chunk_end: date,
) -> bool:
    chunk_dates = [
        bar.start.date()
        for bar in bars
        if (
            chunk_start
            <= bar.start.date()
            <= chunk_end
        )
    ]

    if not chunk_dates:
        return False

    first_day = min(chunk_dates)
    last_day = max(chunk_dates)

    if (
        first_day
        > chunk_start
        + timedelta(days=MAXIMUM_START_DELAY_DAYS)
    ):
        return False

    return (
        chunk_end - last_day
    ).days <= MAXIMUM_END_STALE_DAYS


def _validated_completed_chunks(
    *,
    manifest_payload: Mapping[str, Any],
    bars: Sequence[IntradayBar],
    start: date,
    end: date,
) -> tuple[set[str], set[str]]:
    declared = {
        str(value)
        for value in manifest_payload.get(
            "completed_chunks",
            [],
        )
    }
    valid: set[str] = set()
    invalid: set[str] = set()

    for chunk_start, chunk_end in chunk_ranges(
        start,
        end,
    ):
        identifier = _chunk_id(
            chunk_start,
            chunk_end,
        )

        if identifier not in declared:
            continue

        if _chunk_has_end_coverage(
            bars=bars,
            chunk_start=chunk_start,
            chunk_end=chunk_end,
        ):
            valid.add(identifier)
        else:
            invalid.add(identifier)

    invalid.update(
        declared - valid - invalid
    )
    return valid, invalid


def fetch_aggregate_history(
    *,
    api_key: str,
    provider_symbol: str,
    start: date,
    end: date,
    require_volume: bool,
    checkpoint_path: str | Path | None = None,
    seed_bars: Sequence[IntradayBar] = (),
) -> tuple[list[IntradayBar], str]:
    collected: dict[str, IntradayBar] = {
        bar.start.isoformat(): bar
        for bar in seed_bars
    }
    provider_host = ""
    checkpoint = (
        Path(checkpoint_path)
        .expanduser()
        .resolve()
        if checkpoint_path is not None
        else None
    )
    checkpoint_manifest = (
        checkpoint.with_suffix(
            checkpoint.suffix + ".manifest.json"
        )
        if checkpoint is not None
        else None
    )
    completed_chunks: set[str] = set()

    if (
        checkpoint_manifest is not None
        and checkpoint_manifest.exists()
    ):
        try:
            payload = json.loads(
                checkpoint_manifest.read_text(
                    encoding="utf-8"
                )
            )
            (
                completed_chunks,
                invalidated_chunks,
            ) = _validated_completed_chunks(
                manifest_payload=payload,
                bars=tuple(
                    collected.values()
                ),
                start=start,
                end=end,
            )

            if invalidated_chunks:
                print(
                    f"{provider_symbol}: invalidated "
                    f"{len(invalidated_chunks)} stale or "
                    "incomplete checkpoint chunk(s)"
                )
        except (
            OSError,
            ValueError,
            TypeError,
        ):
            completed_chunks = set()

    for chunk_start, chunk_end in chunk_ranges(
        start,
        end,
    ):
        chunk_id = _chunk_id(
            chunk_start,
            chunk_end,
        )

        if chunk_id in completed_chunks:
            print(
                f"{provider_symbol}: reusing completed "
                f"checkpoint chunk {chunk_start} "
                f"to {chunk_end}"
            )
            continue
        encoded = urllib.parse.quote(
            provider_symbol,
            safe=":",
        )
        path = (
            f"/v2/aggs/ticker/{encoded}/range/"
            f"{INTERVAL_MINUTES}/minute/"
            f"{chunk_start.isoformat()}/"
            f"{chunk_end.isoformat()}"
        )
        payload, provider_host = _provider_json(
            api_key=api_key,
            path=path,
            query={
                "adjusted": "true",
                "sort": "asc",
                "limit": "50000",
            },
        )
        results = payload.get("results", [])

        if not isinstance(results, list):
            raise ProviderError(
                f"Aggregate results are malformed for {provider_symbol}."
            )

        for raw in results:
            if not isinstance(raw, Mapping):
                continue

            bar = _regular_bar(raw)

            if bar is None:
                continue

            if require_volume and bar.volume <= 0:
                continue

            collected[bar.start.isoformat()] = bar

        print(
            f"{provider_symbol}: "
            f"{chunk_start} to {chunk_end} "
            f"({len(results)} raw aggregates)"
        )

        if (
            checkpoint is not None
            and checkpoint_manifest is not None
        ):
            checkpoint.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            checkpoint_bars = sorted(
                collected.values(),
                key=lambda bar: bar.start,
            )
            chunk_complete = (
                _chunk_has_end_coverage(
                    bars=checkpoint_bars,
                    chunk_start=chunk_start,
                    chunk_end=chunk_end,
                )
            )

            if chunk_complete:
                completed_chunks.add(
                    chunk_id
                )
            else:
                completed_chunks.discard(
                    chunk_id
                )

            _write_bars(
                checkpoint,
                checkpoint_bars,
            )
            _atomic_json(
                checkpoint_manifest,
                {
                    "schema_version": 2,
                    "provider_symbol": provider_symbol,
                    "interval_minutes": (
                        INTERVAL_MINUTES
                    ),
                    "requested_start": (
                        start.isoformat()
                    ),
                    "requested_end": (
                        end.isoformat()
                    ),
                    "completed_chunks": sorted(
                        completed_chunks
                    ),
                    "last_attempted_chunk": (
                        chunk_id
                    ),
                    "last_attempted_chunk_complete": (
                        chunk_complete
                    ),
                    "bar_count": len(
                        checkpoint_bars
                    ),
                    "latest_bar": (
                        checkpoint_bars[-1]
                        .start
                        .isoformat()
                        if checkpoint_bars
                        else None
                    ),
                    "placeholder_data": False,
                    "synthetic_data": False,
                },
            )

            if chunk_complete:
                print(
                    f"{provider_symbol}: checkpoint saved "
                    f"after {chunk_end}"
                )
            else:
                print(
                    f"{provider_symbol}: chunk remains "
                    f"incomplete after {chunk_end}; "
                    "it will be requested again on the "
                    "next run"
                )

        time.sleep(0.05)

    bars = sorted(
        collected.values(),
        key=lambda bar: bar.start,
    )

    if not bars:
        raise ProviderError(
            f"No valid regular-session 15-minute bars "
            f"were returned for {provider_symbol}."
        )

    return bars, provider_host



def _read_cached_bars(
    path: Path,
) -> list[IntradayBar]:
    bars: list[IntradayBar] = []

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                start = datetime.fromisoformat(
                    str(row["TimestampMarket"])
                ).astimezone(NEW_YORK)
                values = (
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                )
                volume = int(
                    float(row.get("Volume", 0) or 0)
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            wall = start.time().replace(
                tzinfo=None
            )

            if not all(
                math.isfinite(value)
                and value > 0
                for value in values
            ):
                continue

            if not (
                clock_time(9, 30)
                <= wall
                < clock_time(16, 0)
            ):
                continue

            if (
                start.minute
                % INTERVAL_MINUTES
                != 0
            ):
                continue

            bars.append(
                IntradayBar(
                    start=start,
                    open=values[0],
                    high=values[1],
                    low=values[2],
                    close=values[3],
                    volume=max(
                        0,
                        volume,
                    ),
                )
            )

    deduplicated = {
        bar.start.isoformat(): bar
        for bar in bars
    }
    return sorted(
        deduplicated.values(),
        key=lambda bar: bar.start,
    )


def _find_valid_cached_history(
    *,
    data_root: Path,
    logical_symbol: str,
    start: date,
    end: date,
    exclude_directory: Path,
) -> tuple[list[IntradayBar], Path] | None:
    filename = (
        logical_symbol
        .replace("^", "")
        .replace(":", "_")
        + "_15M.csv"
    )
    candidates = [
        path
        for path in data_root.rglob(
            filename
        )
        if (
            path.is_file()
            and path.parent.resolve()
            != exclude_directory.resolve()
        )
    ]
    candidates.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for path in candidates:
        try:
            bars = _read_cached_bars(path)
        except OSError:
            continue

        if len(bars) < MINIMUM_TEST_BARS:
            continue

        if (
            bars[0].start.date()
            > start + timedelta(days=10)
        ):
            continue

        if (
            end - bars[-1].start.date()
        ).days > MAXIMUM_END_STALE_DAYS:
            continue

        return bars, path

    return None




def _aggregate_cache_path(
    logical_symbol: str,
) -> Path:
    filename = (
        logical_symbol
        .replace("^", "")
        .replace(":", "_")
        + "_15M.csv"
    )
    return (
        DEFAULT_AGGREGATE_CACHE
        / filename
    )


def _aggregate_manifest_path(
    cache_path: Path,
) -> Path:
    return cache_path.with_suffix(
        cache_path.suffix + ".manifest.json"
    )


def _mark_all_chunks_complete(
    *,
    cache_path: Path,
    provider_symbol: str,
    start: date,
    end: date,
    bars: Sequence[IntradayBar],
) -> None:
    _atomic_json(
        _aggregate_manifest_path(
            cache_path
        ),
        {
            "schema_version": 1,
            "provider_symbol": provider_symbol,
            "interval_minutes": (
                INTERVAL_MINUTES
            ),
            "requested_start": (
                start.isoformat()
            ),
            "requested_end": (
                end.isoformat()
            ),
            "completed_chunks": [
                (
                    f"{chunk_start.isoformat()}_"
                    f"{chunk_end.isoformat()}"
                )
                for chunk_start, chunk_end
                in chunk_ranges(start, end)
            ],
            "bar_count": len(bars),
            "imported_complete_history": True,
            "placeholder_data": False,
            "synthetic_data": False,
        },
    )


def _seed_aggregate_checkpoint(
    *,
    data_root: Path,
    logical_symbol: str,
    provider_symbol: str,
    start: date,
    end: date,
    exclude_directory: Path,
) -> tuple[list[IntradayBar], Path] | None:
    stable = _aggregate_cache_path(
        logical_symbol
    )
    valid = _find_valid_cached_history(
        data_root=data_root,
        logical_symbol=logical_symbol,
        start=start,
        end=end,
        exclude_directory=(
            exclude_directory
        ),
    )

    if valid is not None:
        bars, source_path = valid

        if (
            source_path.resolve()
            != stable.resolve()
        ):
            stable.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.copy2(
                source_path,
                stable,
            )
            print(
                "Imported completed aggregate "
                f"history into stable cache: "
                f"{logical_symbol} ({source_path})"
            )

        _mark_all_chunks_complete(
            cache_path=stable,
            provider_symbol=provider_symbol,
            start=start,
            end=end,
            bars=bars,
        )
        return bars, stable

    if stable.exists():
        try:
            bars = _read_cached_bars(
                stable
            )
        except OSError:
            bars = []

        if bars:
            print(
                "Found resumable aggregate checkpoint: "
                f"{logical_symbol} "
                f"({len(bars)} bars)"
            )
            return bars, stable

    return None


def _download_text(
    url: str,
    *,
    attempts: int = 5,
) -> str:
    last_error: Exception | None = None

    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 14) "
                    "AppleWebKit/537.36 QPXBot/1.27.0"
                ),
                "Accept": "text/csv,text/plain,*/*",
                "Accept-Encoding": "identity",
                "Connection": "close",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=45.0,
            ) as response:
                return response.read().decode(
                    "utf-8-sig"
                )
        except (
            OSError,
            urllib.error.URLError,
            UnicodeDecodeError,
        ) as exc:
            last_error = exc
            time.sleep(
                min(
                    12.0,
                    2.0 * (attempt + 1),
                )
            )

    raise ProviderError(
        "Unable to download official Cboe "
        f"VIX history: {last_error}"
    )


def _parse_cboe_date(
    raw: str,
) -> date:
    value = raw.strip()

    for date_format in (
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            return datetime.strptime(
                value,
                date_format,
            ).date()
        except ValueError:
            continue

    raise ValueError(
        f"Unsupported Cboe date: {raw!r}"
    )


def fetch_cboe_vix_daily(
    *,
    start: date,
    end: date,
) -> tuple[dict[date, float], str]:
    raw = _download_text(
        CBOE_VIX_HISTORY_URL
    )
    reader = csv.DictReader(
        raw.splitlines()
    )

    if not reader.fieldnames:
        raise ProviderError(
            "Official Cboe VIX CSV has no header."
        )

    headers = {
        name.strip().upper(): name
        for name in reader.fieldnames
    }

    if (
        "DATE" not in headers
        or "CLOSE" not in headers
    ):
        raise ProviderError(
            "Official Cboe VIX CSV is missing "
            "DATE or CLOSE."
        )

    closes: dict[date, float] = {}
    earliest = start - timedelta(days=20)

    for row in reader:
        try:
            day = _parse_cboe_date(
                str(
                    row[headers["DATE"]]
                )
            )
            close = float(
                row[headers["CLOSE"]]
            )
        except (
            KeyError,
            TypeError,
            ValueError,
        ):
            continue

        if (
            earliest <= day <= end
            and math.isfinite(close)
            and close >= 0
        ):
            closes[day] = close

    if len(closes) < 480:
        raise ProviderError(
            "Official Cboe VIX history did not "
            "cover the required two-year period."
        )

    return (
        closes,
        CBOE_VIX_HISTORY_URL,
    )




def _write_vix_daily_cache(
    path: Path,
    closes: Mapping[date, float],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "Close",
                "Source",
                "ObservationPolicy",
            )
        )

        for day in sorted(closes):
            writer.writerow(
                (
                    day.isoformat(),
                    f"{float(closes[day]):.10f}",
                    CBOE_VIX_HISTORY_URL,
                    VIX_OBSERVATION_POLICY,
                )
            )

    temporary.replace(path)


def _read_vix_daily_cache(
    path: Path,
) -> dict[date, float]:
    closes: dict[date, float] = {}

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                day = date.fromisoformat(
                    str(row["Date"])
                )
                close = float(row["Close"])
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if (
                math.isfinite(close)
                and close >= 0
            ):
                closes[day] = close

    return closes


def _validate_vix_daily_coverage(
    *,
    closes: Mapping[date, float],
    start: date,
    end: date,
) -> dict[date, float]:
    earliest = start - timedelta(days=20)
    filtered = {
        day: float(value)
        for day, value in closes.items()
        if (
            earliest <= day <= end
            and math.isfinite(float(value))
            and float(value) >= 0
        )
    }

    if len(filtered) < 480:
        raise ProviderError(
            "Official Cboe VIX cache does not cover "
            "the required two-year period."
        )

    ordered = sorted(filtered)

    if ordered[0] > start:
        raise ProviderError(
            "Official Cboe VIX cache does not include "
            "a pre-test observation."
        )

    if (
        end - ordered[-1]
    ).days > MAXIMUM_END_STALE_DAYS:
        raise ProviderError(
            "Official Cboe VIX cache is stale."
        )

    return filtered


def prepare_cboe_vix_cache(
    *,
    start: date,
    end: date,
    cache_path: str | Path = DEFAULT_VIX_CACHE,
    refresh: bool = False,
) -> tuple[dict[date, float], str, Path]:
    path = (
        Path(cache_path)
        .expanduser()
        .resolve()
    )

    if path.exists() and not refresh:
        try:
            cached = _read_vix_daily_cache(
                path
            )
            validated = (
                _validate_vix_daily_coverage(
                    closes=cached,
                    start=start,
                    end=end,
                )
            )
            print(
                "Reusing validated official Cboe "
                f"VIX cache: {path}"
            )
            return (
                validated,
                "LOCAL_VALIDATED_CBOE_CACHE",
                path,
            )
        except (
            OSError,
            ProviderError,
        ):
            print(
                "Existing Cboe VIX cache is invalid "
                "or stale; refreshing it."
            )

    closes, source = fetch_cboe_vix_daily(
        start=start,
        end=end,
    )
    validated = _validate_vix_daily_coverage(
        closes=closes,
        start=start,
        end=end,
    )
    _write_vix_daily_cache(
        path,
        validated,
    )
    print(
        "Official Cboe VIX cache ready: "
        f"{path}"
    )
    return validated, source, path


def expand_previous_session_vix(
    *,
    reference_bars: Sequence[IntradayBar],
    closes: Mapping[date, float],
    minimum_bars: int = MINIMUM_TEST_BARS,
) -> list[IntradayBar]:
    if minimum_bars < 0:
        raise ValueError(
            "Minimum VIX coverage cannot be negative."
        )

    close_dates = sorted(closes)

    if not close_dates:
        raise ProviderError(
            "No official Cboe VIX closes "
            "are available."
        )

    expanded: list[IntradayBar] = []

    for bar in reference_bars:
        index = bisect_left(
            close_dates,
            bar.start.date(),
        ) - 1

        if index < 0:
            continue

        observation_date = close_dates[index]
        value = float(
            closes[observation_date]
        )

        if (
            not math.isfinite(value)
            or value < 0
        ):
            continue

        expanded.append(
            IntradayBar(
                start=bar.start,
                open=value,
                high=value,
                low=value,
                close=value,
                volume=0,
            )
        )

    if len(expanded) < minimum_bars:
        raise ProviderError(
            "The official previous-session VIX "
            "series does not cover enough "
            "15-minute ETF timestamps."
        )

    return expanded


def fetch_qdte_dividends(
    *,
    api_key: str,
    start: date,
    end: date,
) -> tuple[list[DividendEvent], str]:
    payload, host = _provider_json(
        api_key=api_key,
        path="/stocks/v1/dividends",
        query={
            "ticker": INCOME_SYMBOL,
            "ex_dividend_date.gte": start.isoformat(),
            "ex_dividend_date.lte": end.isoformat(),
            "limit": "5000",
            "sort": "ex_dividend_date.asc",
        },
    )
    raw_results = payload.get("results", [])

    if not isinstance(raw_results, list):
        raise ProviderError(
            "QDTE dividend response is malformed."
        )

    events: list[DividendEvent] = []

    for raw in raw_results:
        if not isinstance(raw, Mapping):
            continue

        try:
            event_date = date.fromisoformat(
                str(raw["ex_dividend_date"])
            )
            amount = float(
                raw.get(
                    "split_adjusted_cash_amount",
                    raw.get("cash_amount", 0.0),
                )
            )
            event_id = str(
                raw.get(
                    "id",
                    (
                        f"{event_date.isoformat()}|"
                        f"{amount:.10f}"
                    ),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

        if amount <= 0:
            continue

        events.append(
            DividendEvent(
                event_id=event_id,
                ex_date=event_date,
                cash_amount=amount,
            )
        )

    events.sort(
        key=lambda item: (
            item.ex_date,
            item.event_id,
        )
    )

    if not events:
        raise ProviderError(
            "No actual QDTE dividend events were returned "
            "for the two-year test period."
        )

    return events, host



def _read_cached_dividends(
    path: Path,
) -> list[DividendEvent]:
    events: list[DividendEvent] = []

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                event_id = str(
                    row.get(
                        "EventId",
                        "",
                    )
                ).strip()
                ex_date = date.fromisoformat(
                    str(
                        row["ExDividendDate"]
                    )
                )
                cash_amount = float(
                    row["CashAmount"]
                )
            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if (
                not event_id
                or not math.isfinite(cash_amount)
                or cash_amount <= 0
            ):
                continue

            events.append(
                DividendEvent(
                    event_id=event_id,
                    ex_date=ex_date,
                    cash_amount=cash_amount,
                )
            )

    deduplicated = {
        event.event_id: event
        for event in events
    }
    return sorted(
        deduplicated.values(),
        key=lambda event: (
            event.ex_date,
            event.event_id,
        ),
    )


def _find_valid_cached_dividends(
    *,
    data_root: Path,
    start: date,
    end: date,
) -> tuple[list[DividendEvent], Path]:
    candidates = [
        path
        for path in data_root.rglob(
            "QDTE_DIVIDENDS.csv"
        )
        if path.is_file()
    ]
    candidates.sort(
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    for path in candidates:
        try:
            events = _read_cached_dividends(
                path
            )
        except OSError:
            continue

        filtered = [
            event
            for event in events
            if start <= event.ex_date <= end
        ]

        if len(filtered) < 80:
            continue

        if (
            filtered[0].ex_date
            > start + timedelta(days=21)
        ):
            continue

        if (
            end - filtered[-1].ex_date
        ).days > 21:
            continue

        return filtered, path

    raise ProviderError(
        "No validated local QDTE dividend cache "
        "covers the fixed historical window."
    )


def _write_bars(
    path: Path,
    bars: Sequence[IntradayBar],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
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

        for bar in bars:
            writer.writerow(
                (
                    bar.start.isoformat(),
                    f"{bar.open:.10f}",
                    f"{bar.high:.10f}",
                    f"{bar.low:.10f}",
                    f"{bar.close:.10f}",
                    bar.volume,
                )
            )


def _write_dividends(
    path: Path,
    events: Sequence[DividendEvent],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "EventId",
                "ExDividendDate",
                "CashAmount",
            )
        )

        for event in events:
            writer.writerow(
                (
                    event.event_id,
                    event.ex_date.isoformat(),
                    f"{event.cash_amount:.10f}",
                )
            )


def _common_times(
    histories: Mapping[str, Sequence[IntradayBar]],
) -> list[datetime]:
    common: set[datetime] | None = None

    for bars in histories.values():
        values = {
            bar.start
            for bar in bars
        }
        common = (
            values
            if common is None
            else common.intersection(values)
        )

    return sorted(common or set())


def _to_candles(
    bars: Sequence[IntradayBar],
) -> list[Candle]:
    return [
        Candle(
            date=bar.start.date(),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]


def _position_prices(
    *,
    portfolio: Portfolio,
    maps: Mapping[str, Mapping[datetime, IntradayBar]],
    bar_time: datetime,
    field: str,
) -> dict[str, float]:
    return {
        symbol: float(
            getattr(
                maps[symbol][bar_time],
                field,
            )
        )
        for symbol in portfolio.positions
    }


def _apply_rebalance(
    *,
    portfolio: Portfolio,
    income_shares: float,
    income_cost: float,
    qdte_price: float,
    position_prices: Mapping[str, float],
    target_income_weight: float,
    config: BotConfig,
) -> tuple[float, float, Any]:
    result = rebalance_income_allocation(
        income_shares=income_shares,
        income_cost=income_cost,
        swing_cash=portfolio.cash,
        swing_market_value=portfolio.market_value(
            position_prices
        ),
        income_price=qdte_price,
        target_income_weight=target_income_weight,
        slippage_rate=config.slippage_rate,
        tax_reserve_rate=config.annual_tax_reserve_rate,
        tolerance=config.allocation_rebalance_tolerance,
        minimum_trade=config.minimum_rebalance_trade,
    )
    portfolio.cash = result.swing_cash_after
    portfolio.tax_reserve_cash += result.tax_reserved
    portfolio.realized_pnl += result.realized_pnl

    return (
        result.shares_after,
        result.income_cost_after,
        result,
    )


def _profit_factor(
    trades: Sequence[TradeRecord],
) -> float | None:
    profit = sum(
        trade.pnl
        for trade in trades
        if trade.pnl > 0
    )
    loss = -sum(
        trade.pnl
        for trade in trades
        if trade.pnl < 0
    )

    if loss == 0:
        return None if profit > 0 else 0.0

    return profit / loss


def _daily_metrics(
    points: Sequence[EquityPoint],
    *,
    starting_capital: float,
) -> ReturnMetrics:
    end_of_day: dict[date, EquityPoint] = {}

    for point in points:
        end_of_day[point.time.date()] = point

    ordered = [
        end_of_day[day]
        for day in sorted(end_of_day)
    ]
    returns: list[float] = []
    previous_equity = starting_capital
    previous_contributions = starting_capital

    for point in ordered:
        contribution = (
            point.total_contributions
            - previous_contributions
        )
        daily_return = (
            (
                point.total_equity
                - contribution
            )
            / previous_equity
            - 1.0
            if previous_equity > 0
            else 0.0
        )
        returns.append(daily_return)
        previous_equity = point.total_equity
        previous_contributions = (
            point.total_contributions
        )

    exposure = (
        sum(
            point.open_positions > 0
            for point in points
        )
        / len(points)
        if points
        else 0.0
    )
    return metrics_from_returns(
        returns,
        exposure=exposure,
    )


def _write_equity(
    path: Path,
    points: Sequence[EquityPoint],
) -> None:
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "TimestampMarket",
                "TotalEquity",
                "TotalContributions",
                "IncomeValue",
                "SwingEquity",
                "SwingCash",
                "SwingMarketValue",
                "TaxReserve",
                "IncomeWeight",
                "TargetIncomeWeight",
                "OpenPositions",
                "PendingEntries",
                "ActiveRisk",
            )
        )

        for point in points:
            writer.writerow(
                (
                    point.time.isoformat(),
                    f"{point.total_equity:.8f}",
                    f"{point.total_contributions:.8f}",
                    f"{point.income_value:.8f}",
                    f"{point.swing_equity:.8f}",
                    f"{point.swing_cash:.8f}",
                    f"{point.swing_market_value:.8f}",
                    f"{point.tax_reserve:.8f}",
                    f"{point.income_weight:.10f}",
                    f"{point.target_income_weight:.10f}",
                    point.open_positions,
                    point.pending_entries,
                    f"{point.active_risk:.8f}",
                )
            )


def _write_trades(
    path: Path,
    trades: Sequence[TradeRecord],
) -> None:
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Symbol",
                "EntryTimestampMarket",
                "ExitTimestampMarket",
                "Shares",
                "EntryPrice",
                "ExitPrice",
                "PnL",
                "TaxReserved",
                "ExitReason",
                "ResultR",
            )
        )

        for trade in trades:
            writer.writerow(
                (
                    trade.symbol,
                    trade.entry_time.isoformat(),
                    trade.exit_time.isoformat(),
                    trade.shares,
                    f"{trade.entry_price:.8f}",
                    f"{trade.exit_price:.8f}",
                    f"{trade.pnl:.8f}",
                    f"{trade.tax_reserved:.8f}",
                    trade.reason,
                    f"{trade.result_r:.8f}",
                )
            )


def _write_signals(
    path: Path,
    records: Sequence[SignalRecord],
) -> None:
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "TimestampMarket",
                "Symbol",
                "Action",
                "Detail",
                "TieKey",
            )
        )

        for record in records:
            writer.writerow(
                (
                    record.time.isoformat(),
                    record.symbol,
                    record.action,
                    record.detail,
                    record.tie_key,
                )
            )


def _write_allocations(
    path: Path,
    records: Sequence[AllocationRecord],
) -> None:
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "TimestampMarket",
                "EventType",
                "ExternalContribution",
                "TargetIncomeWeight",
                "Action",
                "BeforeIncomeWeight",
                "AfterIncomeWeight",
                "QDTEMarketValueTraded",
                "RealizedPnL",
                "TaxReserved",
            )
        )

        for record in records:
            writer.writerow(
                (
                    record.time.isoformat(),
                    record.event_type,
                    f"{record.external_contribution:.8f}",
                    f"{record.target_income_weight:.10f}",
                    record.action,
                    f"{record.before_income_weight:.10f}",
                    f"{record.after_income_weight:.10f}",
                    f"{record.qdte_market_value_traded:.8f}",
                    f"{record.realized_pnl:.8f}",
                    f"{record.tax_reserved:.8f}",
                )
            )


def _format_report(
    result: BacktestResult,
) -> str:
    profit_factor = (
        "∞"
        if result.profit_factor is None
        else f"{result.profit_factor:.3f}"
    )
    qualifying = [
        (
            f"  {symbol}: "
            f"{result.qualifying_by_symbol.get(symbol, 0)}"
        )
        for symbol in result.swing_symbols
    ]
    trades = [
        (
            f"  {symbol}: "
            f"{result.trades_by_symbol.get(symbol, 0)}"
        )
        for symbol in result.swing_symbols
    ]
    failures = [
        f"  {name}: {count}"
        for name, count in sorted(
            result.failed_check_counts.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    ]

    return "\n".join(
        (
            "=" * 78,
            (
                (
                    "QPX BOT v1.27.0 — FIXED SWING-ONLY CONTROL "
                    "15-MINUTE SIX-POSITION BACKTEST"
                )
                if result.swing_only
                else (
                    (
                        "QPX BOT v1.27.0 — FIXED NEAR-TWO-YEAR "
                        "15-MINUTE SIX-POSITION BACKTEST"
                    )
                    if result.fixed_window
                    else (
                        "QPX BOT v1.27.0 — ACTUAL TWO-YEAR "
                        "15-MINUTE SIX-POSITION BACKTEST"
                    )
                )
            ),
            "=" * 78,
            f"Actual provider            : {result.provider}",
            (
                "Actual period              : "
                f"{result.actual_start} to {result.actual_end}"
            ),
            f"Warmup begins              : {result.warmup_start}",
            (
                "Window mode                : "
                + (
                    "FIXED_LOCAL_NEAR_TWO_YEAR"
                    if result.fixed_window
                    else "ROLLING_TWO_YEAR"
                )
            ),
            f"Local-only data            : {result.local_only}",
            (
                "Portfolio mode             : "
                + (
                    "SWING_ONLY_CONTROL"
                    if result.swing_only
                    else "HYBRID_QDTE_PLUS_SWING"
                )
            ),
            (
                "Indicator initialization   : "
                f"{result.initialization_bars} common bars"
            ),
            (
                "First swing entry eligible : "
                f"{result.first_entry_eligible_time}"
            ),
            f"Interval                   : {result.interval}",
            f"Common 15-minute bars      : {result.common_test_bars}",
            f"Market sessions            : {result.test_sessions}",
            (
                "Expected market sessions   : "
                f"{result.expected_market_sessions}"
            ),
            (
                "Session coverage           : "
                f"{result.session_coverage:.2%}"
            ),
            (
                "Swing universe             : "
                + ", ".join(result.swing_symbols)
            ),
            (
                "Income sleeve              : "
                + (
                    "DISABLED (QDTE retained only for timestamp control)"
                    if result.swing_only
                    else result.income_symbol
                )
            ),
            f"Volatility series          : {result.vix_symbol}",
            (
                "VIX observation timing      : "
                f"{result.vix_observation_policy}"
            ),
            f"Rankings enabled           : {result.rankings_enabled}",
            (
                "Concurrent swing slots     : "
                f"{result.maximum_concurrent_positions}"
            ),
            (
                "Maximum positions observed : "
                f"{result.maximum_observed_positions}"
            ),
            (
                "Initial QDTE seed          : "
                f"${result.starting_income_cash:,.2f}"
            ),
            (
                "Initial swing liquidity    : "
                f"${result.starting_swing_cash:,.2f}"
            ),
            (
                "Initial total capital      : "
                f"${result.starting_total_capital:,.2f}"
            ),
            (
                "Monthly contribution       : "
                f"${result.monthly_contribution:,.2f}"
            ),
            (
                "Monthly contributions made : "
                f"{result.contribution_count}"
            ),
            (
                "Total contributed capital  : "
                f"${result.total_contributions:,.2f}"
            ),
            (
                "Ending account equity      : "
                f"${result.ending_equity:,.2f}"
            ),
            (
                "Net profit                 : "
                f"${result.net_profit:,.2f}"
            ),
            (
                "Return on contributions    : "
                f"{result.return_on_contributions:.2%}"
            ),
            (
                "Flow-adjusted total return : "
                f"{result.flow_adjusted_total_return:.2%}"
            ),
            (
                "Flow-adjusted CAGR         : "
                f"{result.flow_adjusted_cagr:.2%}"
            ),
            (
                "Maximum drawdown           : "
                f"{result.maximum_drawdown:.2%}"
            ),
            (
                "Annualized volatility      : "
                f"{result.annualized_volatility:.2%}"
            ),
            (
                "Sharpe / Sortino           : "
                f"{result.sharpe_ratio:.3f} / "
                f"{result.sortino_ratio:.3f}"
            ),
            (
                "Swing exposure             : "
                f"{result.swing_exposure:.2%}"
            ),
            (
                "Ending QDTE value          : "
                f"${result.ending_income_value:,.2f}"
            ),
            (
                "Ending QDTE weight         : "
                f"{result.ending_income_weight:.2%}"
            ),
            (
                "Ending swing equity        : "
                f"${result.ending_swing_equity:,.2f}"
            ),
            (
                "Ending swing cash          : "
                f"${result.ending_swing_cash:,.2f}"
            ),
            (
                "Tax reserve cash           : "
                f"${result.ending_tax_reserve:,.2f}"
            ),
            (
                "Actual QDTE distributions  : "
                f"${result.qdte_distributions_received:,.2f} "
                f"({result.qdte_distribution_events} events)"
            ),
            (
                "All-symbol evaluations     : "
                f"{result.all_symbol_evaluations}"
            ),
            (
                "Qualifying signal bars     : "
                f"{result.qualifying_signal_bars}"
            ),
            (
                "Staged / filled entries    : "
                f"{result.staged_signals} / "
                f"{result.filled_entries}"
            ),
            (
                "Capacity deferred          : "
                f"{result.capacity_deferred}"
            ),
            (
                "Gap / risk rejections      : "
                f"{result.gap_rejections} / "
                f"{result.risk_rejections}"
            ),
            (
                "Closed swing trades        : "
                f"{result.closed_trades}"
            ),
            (
                "Win rate / profit factor   : "
                f"{result.win_rate:.2%} / "
                f"{profit_factor}"
            ),
            "Qualifying bars by symbol:",
            *qualifying,
            "Closed trades by symbol:",
            *trades,
            (
                "Failed checks across all symbols "
                "(counts overlap):"
            ),
            *failures,
            (
                "Allocation anniversary rule : "
                f"{result.allocation_anniversary_rule}"
            ),
            "Forced entries              : DISABLED",
            "Placeholder data            : DISABLED",
            "Synthetic data              : DISABLED",
            "Live brokerage              : DISABLED",
            "=" * 78,
            (
                "The run aborts rather than substituting daily, "
                "synthetic, interpolated, or placeholder market data."
            ),
            (
                "Historical research does not guarantee "
                "future performance."
            ),
        )
    )


def run_backtest(
    *,
    api_key: str = "",
    data_root: str | Path = DEFAULT_DATA_ROOT,
    report_root: str | Path = DEFAULT_REPORT_ROOT,
    fixed_start: date | None = None,
    fixed_end: date | None = None,
    local_only: bool = False,
    initialization_bars: int = 0,
    swing_only: bool = False,
) -> tuple[BacktestResult, RunArtifacts]:
    fixed_window = (
        fixed_start is not None
        or fixed_end is not None
    )

    if (
        (fixed_start is None)
        != (fixed_end is None)
    ):
        raise ValueError(
            "Fixed start and end must be supplied together."
        )

    if (
        fixed_start is not None
        and fixed_end is not None
        and fixed_end < fixed_start
    ):
        raise ValueError(
            "Fixed end cannot precede fixed start."
        )

    if initialization_bars < 0:
        raise ValueError(
            "Initialization bars cannot be negative."
        )

    if local_only and not fixed_window:
        raise ValueError(
            "Local-only mode requires a fixed historical window."
        )

    if swing_only and not (fixed_window and local_only):
        raise ValueError(
            "Swing-only control requires fixed local-only mode."
        )

    if not local_only and not api_key.strip():
        raise ProviderError(
            "A Massive/Polygon API key is required."
        )

    config = BotConfig()
    config.validate()
    policy = load_policy()

    if policy.interval != "15m":
        raise RuntimeError(
            "The active paper policy is not 15-minute."
        )

    if policy.maximum_concurrent_positions != 6:
        raise RuntimeError(
            "The active paper policy does not use six positions."
        )

    if policy.candidates != SWING_SYMBOLS:
        raise RuntimeError(
            "The active paper universe is not the required eight ETFs."
        )

    if policy.rankings_enabled:
        raise RuntimeError(
            "Rankings must remain disabled."
        )

    if fixed_window:
        assert fixed_start is not None
        assert fixed_end is not None
        end_session = fixed_end
        end_status = "FIXED_HISTORICAL_WINDOW"
        requested_start = fixed_start
        warmup_start = requested_start
    else:
        end_session, end_status = (
            latest_completed_session(
                datetime.now(tz=NEW_YORK)
            )
        )
        requested_start = subtract_years(
            end_session,
            2,
        )
        warmup_start = (
            requested_start
            - timedelta(days=WARMUP_DAYS)
        )

    expected_market_sessions = sum(
        1
        for offset in range(
            (end_session - requested_start).days + 1
        )
        if is_market_session(
            requested_start + timedelta(days=offset)
        )
    )

    if local_only:
        vix_cache_path = (
            Path(DEFAULT_VIX_CACHE)
            .expanduser()
            .resolve()
        )

        if not vix_cache_path.exists():
            raise ProviderError(
                "The validated local Cboe VIX cache "
                "is missing."
            )

        vix_closes = (
            _validate_vix_daily_coverage(
                closes=_read_vix_daily_cache(
                    vix_cache_path
                ),
                start=requested_start,
                end=end_session,
            )
        )
        vix_source = (
            "LOCAL_VALIDATED_CBOE_CACHE"
        )
        print(
            "Fixed-window local mode: reusing "
            f"official Cboe VIX cache {vix_cache_path}"
        )
    else:
        print(
            "VIX preflight: validating official Cboe "
            "history before any Massive/Polygon requests..."
        )
        (
            vix_closes,
            vix_source,
            vix_cache_path,
        ) = prepare_cboe_vix_cache(
            start=warmup_start,
            end=end_session,
        )

    run_id = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )
    data_directory = (
        Path(data_root).expanduser().resolve()
        / run_id
    )
    report_directory = (
        Path(report_root).expanduser().resolve()
        / run_id
    )
    data_directory.mkdir(parents=True, exist_ok=True)
    report_directory.mkdir(parents=True, exist_ok=True)

    provider_symbols = {
        **{
            symbol: symbol
            for symbol in SWING_SYMBOLS
        },
        INCOME_SYMBOL: INCOME_SYMBOL,
    }
    histories: dict[str, list[IntradayBar]] = {}
    provider_hosts: set[str] = set()
    input_paths: dict[str, Path] = {}
    vix_daily_path = (
        data_directory
        / "CBOE_VIX_DAILY.csv"
    )
    shutil.copy2(
        vix_cache_path,
        vix_daily_path,
    )
    input_paths[
        "CBOE_VIX_DAILY"
    ] = vix_daily_path
    provider_hosts.add(vix_source)

    data_root_path = (
        Path(data_root)
        .expanduser()
        .resolve()
    )

    if local_only:
        for logical_symbol in provider_symbols:
            cache_path = _aggregate_cache_path(
                logical_symbol
            )

            if not cache_path.exists():
                raise ProviderError(
                    "Missing local aggregate cache for "
                    f"{logical_symbol}: {cache_path}"
                )

            bars = [
                bar
                for bar in _read_cached_bars(
                    cache_path
                )
                if (
                    requested_start
                    <= bar.start.date()
                    <= end_session
                )
            ]

            if not bars:
                raise ProviderError(
                    "No local fixed-window bars for "
                    f"{logical_symbol}."
                )

            path = (
                data_directory
                / (
                    logical_symbol
                    .replace("^", "")
                    .replace(":", "_")
                    + "_15M.csv"
                )
            )
            _write_bars(path, bars)
            histories[logical_symbol] = bars
            input_paths[logical_symbol] = path
            provider_hosts.add(
                "LOCAL_VALIDATED_MASSIVE_POLYGON_CACHE"
            )
            print(
                "Fixed-window local cache: "
                f"{logical_symbol} "
                f"({bars[0].start.date()} to "
                f"{bars[-1].start.date()}, "
                f"{len(bars)} bars)"
            )
    else:
        for logical_symbol, provider_symbol in provider_symbols.items():
            path = (
                data_directory
                / (
                    logical_symbol
                    .replace("^", "")
                    .replace(":", "_")
                    + "_15M.csv"
                )
            )
            stable_cache = _aggregate_cache_path(
                logical_symbol
            )
            seeded = _seed_aggregate_checkpoint(
                data_root=data_root_path,
                logical_symbol=logical_symbol,
                provider_symbol=provider_symbol,
                start=warmup_start,
                end=end_session,
                exclude_directory=data_directory,
            )
            seed_bars: Sequence[IntradayBar] = ()

            if seeded is not None:
                seed_bars, seeded_path = seeded
                valid_seed = _find_valid_cached_history(
                    data_root=data_root_path,
                    logical_symbol=logical_symbol,
                    start=warmup_start,
                    end=end_session,
                    exclude_directory=data_directory,
                )

                if valid_seed is not None:
                    bars, _ = valid_seed
                    print(
                        "Reusing validated complete aggregate "
                        f"cache: {logical_symbol} "
                        f"({seeded_path})"
                    )
                    provider_hosts.add(
                        "LOCAL_VALIDATED_MASSIVE_POLYGON_CACHE"
                    )
                    _write_bars(
                        stable_cache,
                        bars,
                    )
                    _mark_all_chunks_complete(
                        cache_path=stable_cache,
                        provider_symbol=provider_symbol,
                        start=warmup_start,
                        end=end_session,
                        bars=bars,
                    )
                else:
                    print(
                        "Resuming missing aggregate chunks: "
                        f"{logical_symbol}"
                    )
                    bars, host = fetch_aggregate_history(
                        api_key=api_key,
                        provider_symbol=provider_symbol,
                        start=warmup_start,
                        end=end_session,
                        require_volume=True,
                        checkpoint_path=stable_cache,
                        seed_bars=seed_bars,
                    )
                    provider_hosts.add(host)
            else:
                print(
                    "Downloading actual 15-minute history "
                    f"with chunk checkpoints: "
                    f"{logical_symbol} ({provider_symbol})"
                )
                bars, host = fetch_aggregate_history(
                    api_key=api_key,
                    provider_symbol=provider_symbol,
                    start=warmup_start,
                    end=end_session,
                    require_volume=True,
                    checkpoint_path=stable_cache,
                )
                provider_hosts.add(host)

            _write_bars(path, bars)
            histories[logical_symbol] = bars
            input_paths[logical_symbol] = path

    print(
        "Expanding the validated previous-session "
        "Cboe VIX cache onto common 15-minute timestamps..."
    )
    vix_bars = expand_previous_session_vix(
        reference_bars=histories["SPY"],
        closes=vix_closes,
        minimum_bars=(
            FIXED_MINIMUM_COMMON_BARS
            if fixed_window
            else MINIMUM_TEST_BARS
        ),
    )
    histories["^VIX"] = vix_bars
    vix_path = (
        data_directory
        / "VIX_PREVIOUS_SESSION_DAILY_CLOSE_15M.csv"
    )
    _write_bars(
        vix_path,
        vix_bars,
    )
    input_paths["^VIX"] = vix_path

    dividend_path = (
        data_directory
        / "QDTE_DIVIDENDS.csv"
    )

    if swing_only:
        dividends = []
        dividend_host = "SWING_ONLY_NO_DIVIDEND_INPUT"
        print(
            "Swing-only control: QDTE dividends are disabled; "
            "QDTE bars remain only in the common-timestamp intersection."
        )
    elif local_only:
        (
            dividends,
            cached_dividend_path,
        ) = _find_valid_cached_dividends(
            data_root=data_root_path,
            start=requested_start,
            end=end_session,
        )
        dividend_host = (
            "LOCAL_VALIDATED_MASSIVE_POLYGON_DIVIDEND_CACHE"
        )
        print(
            "Fixed-window local QDTE dividends: "
            f"{cached_dividend_path} "
            f"({len(dividends)} events)"
        )
    else:
        dividends, dividend_host = (
            fetch_qdte_dividends(
                api_key=api_key,
                start=requested_start,
                end=end_session,
            )
        )

    provider_hosts.add(dividend_host)

    if not swing_only:
        _write_dividends(
            dividend_path,
            dividends,
        )
        input_paths["QDTE_DIVIDENDS"] = dividend_path

    common = _common_times(histories)
    test_times = [
        value
        for value in common
        if requested_start
        <= value.date()
        <= end_session
    ]

    if not test_times:
        raise ProviderError(
            "No common real 15-minute bars exist "
            "inside the requested two-year period."
        )

    actual_start = test_times[0].date()
    actual_end = test_times[-1].date()
    sessions = {
        value.date()
        for value in test_times
    }

    if fixed_window:
        if actual_start != requested_start:
            raise ProviderError(
                "The fixed-window common data does not "
                f"begin on {requested_start}; "
                f"it begins on {actual_start}."
            )
    elif (
        actual_start - requested_start
    ).days > MAXIMUM_START_DELAY_DAYS:
        raise ProviderError(
            "The real-data test starts too late to represent "
            "a full two-year period."
        )

    if (
        end_session - actual_end
    ).days > MAXIMUM_END_STALE_DAYS:
        latest_by_symbol = {
            symbol: (
                bars[-1].start.isoformat()
                if bars
                else "NO_BARS"
            )
            for symbol, bars
            in histories.items()
        }
        swing_common = _common_times(
            {
                symbol: histories[symbol]
                for symbol in (
                    *SWING_SYMBOLS,
                    "^VIX",
                )
            }
        )
        swing_common_end = (
            swing_common[-1].isoformat()
            if swing_common
            else "NO_COMMON_SWING_BAR"
        )
        details = "; ".join(
            (
                f"{symbol}="
                f"{latest_by_symbol[symbol]}"
            )
            for symbol in sorted(
                latest_by_symbol
            )
        )
        raise ProviderError(
            "The real-data test ends with stale market "
            f"data: expected through {end_session}, "
            f"latest all-symbol common bar is "
            f"{test_times[-1].isoformat()}, latest "
            f"swing/VIX common bar is "
            f"{swing_common_end}. Per-symbol latest "
            f"bars: {details}"
        )

    required_common_bars = (
        FIXED_MINIMUM_COMMON_BARS
        if fixed_window
        else MINIMUM_TEST_BARS
    )

    if len(test_times) < required_common_bars:
        raise ProviderError(
            "Insufficient common real 15-minute coverage: "
            f"{len(test_times)} bars; "
            f"{required_common_bars} required."
        )

    required_common_sessions = (
        FIXED_MINIMUM_COMMON_SESSIONS
        if fixed_window
        else MINIMUM_TEST_SESSIONS
    )

    if len(sessions) < required_common_sessions:
        raise ProviderError(
            "Insufficient common real session coverage: "
            f"{len(sessions)} sessions; "
            f"{required_common_sessions} required."
        )

    session_coverage = (
        len(sessions) / expected_market_sessions
        if expected_market_sessions > 0
        else 0.0
    )

    first_test_time = test_times[0]

    if initialization_bars:
        if (
            initialization_bars
            < config.sma_trend_period
        ):
            raise ProviderError(
                "The fixed-window initialization must "
                f"contain at least {config.sma_trend_period} "
                "common bars."
            )

        if (
            len(test_times)
            <= initialization_bars
        ):
            raise ProviderError(
                "The fixed window does not contain enough "
                "bars after initialization."
            )

        entry_eligible_time = test_times[
            initialization_bars
        ]
    else:
        entry_eligible_time = first_test_time

        for symbol in histories:
            warmup_count = sum(
                bar.start < first_test_time
                for bar in histories[symbol]
            )

            if warmup_count < config.sma_trend_period:
                raise ProviderError(
                    f"{symbol} has only {warmup_count} "
                    "warmup bars; "
                    f"{config.sma_trend_period} required."
                )

    manifest_path = (
        data_directory
        / "DOWNLOAD_MANIFEST.json"
    )
    manifest = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "actual_data": True,
        "provider_hosts": sorted(provider_hosts),
        "provider_end_status": end_status,
        "interval": "15m",
        "requested_start": requested_start.isoformat(),
        "actual_start": actual_start.isoformat(),
        "actual_end": actual_end.isoformat(),
        "warmup_start": warmup_start.isoformat(),
        "fixed_window": fixed_window,
        "local_only": local_only,
        "swing_only": swing_only,
        "income_sleeve_active": (not swing_only),
        "qdte_used_for_common_timestamp_control": swing_only,
        "initialization_bars": initialization_bars,
        "first_entry_eligible_time": (
            entry_eligible_time.isoformat()
        ),
        "window_label": (
            "FIXED_NEAR_TWO_YEAR"
            if fixed_window
            else "ROLLING_TWO_YEAR"
        ),
        "regular_session_only": True,
        "extended_hours": False,
        "rankings_enabled": False,
        "maximum_positions": 6,
        "stock_symbols": list(
            (*SWING_SYMBOLS, INCOME_SYMBOL)
        ),
        "index_symbol": VIX_PROVIDER_SYMBOL,
        "vix_source_url": CBOE_VIX_HISTORY_URL,
        "vix_observation_policy": VIX_OBSERVATION_POLICY,
        "intraday_vix_data": False,
        "vix_values_are_actual": True,
        "vix_placeholder": False,
        "bars": {
            symbol: len(bars)
            for symbol, bars in histories.items()
        },
        "common_test_bars": len(test_times),
        "test_sessions": len(sessions),
        "expected_market_sessions": (
            expected_market_sessions
        ),
        "session_coverage": session_coverage,
        "required_common_sessions": (
            required_common_sessions
        ),
        "dividend_events": len(dividends),
        "files": {
            name: {
                "path": str(path),
                "sha256": _sha256(path),
            }
            for name, path in input_paths.items()
        },
        "placeholder_data": False,
        "synthetic_data": False,
        "interpolated_bars": False,
        "tradeable_asset_daily_bar_substitution": False,
        "vix_daily_close_expanded_to_intraday_timestamps": True,
        "forced_entries": False,
        "live_broker_enabled": False,
    }
    _atomic_json(
        manifest_path,
        manifest,
    )

    maps = {
        symbol: {
            bar.start: bar
            for bar in bars
        }
        for symbol, bars in histories.items()
    }
    candles = {
        symbol: _to_candles(
            histories[symbol]
        )
        for symbol in SWING_SYMBOLS
    }
    indicators: dict[str, IndicatorSet] = {
        symbol: calculate_indicators(
            candles[symbol],
            config,
        )
        for symbol in SWING_SYMBOLS
    }
    indices = {
        symbol: {
            bar.start: index
            for index, bar in enumerate(
                histories[symbol]
            )
        }
        for symbol in SWING_SYMBOLS
    }
    dividend_by_date: dict[date, list[DividendEvent]] = {}

    for event in dividends:
        dividend_by_date.setdefault(
            event.ex_date,
            [],
        ).append(event)

    first_qdte = maps[INCOME_SYMBOL][
        first_test_time
    ]
    total_contributions = (
        config.total_starting_capital
    )
    contribution_count = 0
    distributions_received = 0.0
    distribution_count = 0
    processed_dividends: set[str] = set()
    pending: dict[str, PendingSignal] = {}
    entry_times: dict[str, datetime] = {}
    trade_records: list[TradeRecord] = []
    equity_points: list[EquityPoint] = []
    allocation_records: list[AllocationRecord] = []
    signal_records: list[SignalRecord] = []
    qualifying_by_symbol = Counter()
    failed_checks = Counter()
    all_evaluations = 0
    staged_signals = 0
    filled_entries = 0
    capacity_deferred = 0
    gap_rejections = 0
    risk_rejections = 0
    maximum_observed_positions = 0
    current_month = (
        first_test_time.year,
        first_test_time.month,
    )
    previous_allocation_years = 0

    if swing_only:
        income_shares = 0.0
        income_cost = 0.0
        portfolio = Portfolio(
            config.total_starting_capital
        )
        initial_target = 0.0
        allocation_records.append(
            AllocationRecord(
                time=first_test_time,
                event_type="SWING_ONLY_INITIAL_CAPITAL",
                external_contribution=(
                    config.total_starting_capital
                ),
                target_income_weight=0.0,
                action="ALL_CAPITAL_TO_SWING_CASH",
                before_income_weight=0.0,
                after_income_weight=0.0,
                qdte_market_value_traded=0.0,
                realized_pnl=0.0,
                tax_reserved=0.0,
            )
        )
    else:
        initial_fill = buy_fill(
            first_qdte.open,
            config.slippage_rate,
        )
        income_shares = (
            config.starting_cash
            / initial_fill
        )
        income_cost = config.starting_cash
        portfolio = Portfolio(
            config.starting_swing_cash
        )
        initial_target, _ = contribution_allocation(
            0,
            config,
        )
        (
            income_shares,
            income_cost,
            initial_rebalance,
        ) = _apply_rebalance(
            portfolio=portfolio,
            income_shares=income_shares,
            income_cost=income_cost,
            qdte_price=first_qdte.open,
            position_prices={},
            target_income_weight=initial_target,
            config=config,
        )
        allocation_records.append(
            AllocationRecord(
                time=first_test_time,
                event_type="INITIAL_REBALANCE",
                external_contribution=(
                    config.total_starting_capital
                ),
                target_income_weight=initial_target,
                action=initial_rebalance.action,
                before_income_weight=(
                    initial_rebalance.before_income_weight
                ),
                after_income_weight=(
                    initial_rebalance.after_income_weight
                ),
                qdte_market_value_traded=(
                    initial_rebalance.market_value_traded
                ),
                realized_pnl=(
                    initial_rebalance.realized_pnl
                ),
                tax_reserved=(
                    initial_rebalance.tax_reserved
                ),
            )
        )


    for bar_time in test_times:
        qdte_bar = maps[INCOME_SYMBOL][bar_time]

        if not swing_only:
            for event in dividend_by_date.get(
                bar_time.date(),
                [],
            ):
                if event.event_id in processed_dividends:
                    continue

                cash = (
                    income_shares
                    * event.cash_amount
                )
                portfolio.cash += cash
                distributions_received += cash
                distribution_count += 1
                processed_dividends.add(
                    event.event_id
                )

        month_key = (
            bar_time.year,
            bar_time.month,
        )
        allocation_years = elapsed_complete_years(
            actual_start,
            bar_time.date(),
        )
        month_changed = (
            month_key != current_month
        )
        phase_changed = (
            False
            if swing_only
            else (
                allocation_years
                != previous_allocation_years
            )
        )
        external_contribution = 0.0

        if month_changed:
            portfolio.deposit(
                config.monthly_contribution
            )
            total_contributions += (
                config.monthly_contribution
            )
            contribution_count += 1
            external_contribution = (
                config.monthly_contribution
            )
            current_month = month_key

        if (
            not swing_only
            and (month_changed or phase_changed)
        ):
            target, _ = contribution_allocation(
                allocation_years,
                config,
            )
            open_prices = _position_prices(
                portfolio=portfolio,
                maps=maps,
                bar_time=bar_time,
                field="open",
            )
            (
                income_shares,
                income_cost,
                rebalance,
            ) = _apply_rebalance(
                portfolio=portfolio,
                income_shares=income_shares,
                income_cost=income_cost,
                qdte_price=qdte_bar.open,
                position_prices=open_prices,
                target_income_weight=target,
                config=config,
            )
            allocation_records.append(
                AllocationRecord(
                    time=bar_time,
                    event_type=(
                        "MONTHLY_CONTRIBUTION_REBALANCE"
                        if month_changed
                        else "ALLOCATION_PHASE_REBALANCE"
                    ),
                    external_contribution=(
                        external_contribution
                    ),
                    target_income_weight=target,
                    action=rebalance.action,
                    before_income_weight=(
                        rebalance.before_income_weight
                    ),
                    after_income_weight=(
                        rebalance.after_income_weight
                    ),
                    qdte_market_value_traded=(
                        rebalance.market_value_traded
                    ),
                    realized_pnl=(
                        rebalance.realized_pnl
                    ),
                    tax_reserved=(
                        rebalance.tax_reserved
                    ),
                )
            )

        previous_allocation_years = (
            allocation_years
        )

        pending_items = sorted(
            pending.values(),
            key=lambda item: (
                item.tie_key,
                item.symbol,
            ),
        )
        pending = {}

        for signal in pending_items:
            if bar_time <= signal.signal_time:
                pending[signal.symbol] = signal
                continue

            if (
                len(portfolio.positions)
                >= policy.maximum_concurrent_positions
            ):
                capacity_deferred += 1
                signal_records.append(
                    SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action="CANCELLED_CAPACITY_AT_OPEN",
                        detail="Six slots already occupied.",
                        tie_key=signal.tie_key,
                    )
                )
                continue

            bar = maps[signal.symbol][bar_time]
            gap_atr = (
                abs(
                    bar.open
                    - signal.prior_close
                )
                / signal.signal_atr
            )

            if (
                gap_atr
                > policy.maximum_gap_atr_multiple
            ):
                gap_rejections += 1
                signal_records.append(
                    SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action="REJECTED_OPENING_GAP",
                        detail=f"{gap_atr:.8f} ATR",
                        tie_key=signal.tie_key,
                    )
                )
                continue

            open_prices = _position_prices(
                portfolio=portfolio,
                maps=maps,
                bar_time=bar_time,
                field="open",
            )
            account_equity = (
                portfolio.equity(
                    open_prices
                )
                if swing_only
                else (
                    portfolio.equity(
                        open_prices
                    )
                    + income_shares
                    * qdte_bar.open
                )
            )
            sizing = calculate_position_size(
                account_equity=account_equity,
                available_cash=portfolio.cash,
                entry_price=bar.open,
                atr=signal.signal_atr,
                active_risk=portfolio.active_risk(),
                config=config,
                trade_results_r=[
                    trade.result_r
                    for trade in trade_records
                ],
            )

            if not sizing.is_tradeable:
                risk_rejections += 1
                signal_records.append(
                    SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action="REJECTED_POSITION_SIZING",
                        detail=(
                            sizing.blocked_reason
                            or "Not tradeable."
                        ),
                        tie_key=signal.tie_key,
                    )
                )
                continue

            portfolio.open_position(
                symbol=signal.symbol,
                sizing=sizing,
                entry_date=bar_time.date(),
                entry_atr=signal.signal_atr,
            )
            entry_times[signal.symbol] = (
                bar_time
            )
            filled_entries += 1
            signal_records.append(
                SignalRecord(
                    time=bar_time,
                    symbol=signal.symbol,
                    action="FILLED",
                    detail=(
                        f"{sizing.shares} shares at "
                        f"{sizing.entry_fill:.8f}"
                    ),
                    tie_key=signal.tie_key,
                )
            )

        maximum_observed_positions = max(
            maximum_observed_positions,
            len(portfolio.positions),
        )

        for position in list(
            portfolio.positions.values()
        ):
            symbol = position.symbol
            index = indices[symbol][bar_time]
            atr = indicators[symbol].atr[index]

            if atr is None or atr <= 0:
                continue

            bar = maps[symbol][bar_time]
            evaluation = evaluate_exit(
                position=position,
                candle=Candle(
                    date=bar_time.date(),
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                ),
                current_atr=atr,
                config=config,
            )

            if evaluation.should_exit:
                assert evaluation.exit_price is not None
                closed = portfolio.close_position(
                    symbol=symbol,
                    exit_price=evaluation.exit_price,
                    exit_date=bar_time.date(),
                    reason=(
                        evaluation.reason
                        or "EXIT"
                    ),
                    config=config,
                )
                entry_time = entry_times.pop(
                    symbol
                )
                trade_records.append(
                    TradeRecord(
                        symbol=closed.symbol,
                        entry_time=entry_time,
                        exit_time=bar_time,
                        shares=closed.shares,
                        entry_price=closed.entry_price,
                        exit_price=closed.exit_price,
                        pnl=closed.pnl,
                        tax_reserved=closed.tax_reserved,
                        reason=closed.reason,
                        result_r=closed.result_r,
                    )
                )
            else:
                position.stop_price = (
                    evaluation.next_stop_price
                )
                position.highest_price = (
                    evaluation.highest_price
                )

        if bar_time >= entry_eligible_time:
            qualifying: list[str] = []
            open_symbols = set(
                portfolio.positions
            )
            pending_symbols = set(
                pending
            )

            for symbol in SWING_SYMBOLS:
                index = indices[symbol][bar_time]
                evaluation = evaluate_entry(
                    candles=candles[symbol],
                    indicators=indicators[symbol],
                    index=index,
                    vix=maps["^VIX"][bar_time].close,
                    config=config,
                )
                all_evaluations += 1

                for name in evaluation.failed_checks:
                    failed_checks[name] += 1

                if evaluation.should_enter:
                    qualifying_by_symbol[symbol] += 1

                    if (
                        symbol not in open_symbols
                        and symbol not in pending_symbols
                        and bar_time != test_times[-1]
                    ):
                        qualifying.append(symbol)

            available_slots = max(
                0,
                policy.maximum_concurrent_positions
                - len(portfolio.positions)
                - len(pending),
            )
            accepted, deferred = choose_without_ranking(
                signal_bar=bar_time,
                qualifying=qualifying,
                available_slots=available_slots,
            )
            capacity_deferred += len(deferred)

            for symbol in deferred:
                tie_key = hashlib.sha256(
                    (
                        bar_time.isoformat()
                        + "|"
                        + symbol
                    ).encode("utf-8")
                ).hexdigest()
                signal_records.append(
                    SignalRecord(
                        time=bar_time,
                        symbol=symbol,
                        action="DEFERRED_CAPACITY",
                        detail="More signals than available slots.",
                        tie_key=tie_key,
                    )
                )

            for symbol in accepted:
                index = indices[symbol][bar_time]
                atr = indicators[symbol].atr[index]

                if atr is None or atr <= 0:
                    continue

                bar = maps[symbol][bar_time]
                tie_key = hashlib.sha256(
                    (
                        bar_time.isoformat()
                        + "|"
                        + symbol
                    ).encode("utf-8")
                ).hexdigest()
                pending[symbol] = PendingSignal(
                    symbol=symbol,
                    signal_time=bar_time,
                    signal_atr=atr,
                    prior_close=bar.close,
                    tie_key=tie_key,
                )
                staged_signals += 1
                signal_records.append(
                    SignalRecord(
                        time=bar_time,
                        symbol=symbol,
                        action="STAGED",
                        detail="Next common 15-minute bar open.",
                        tie_key=tie_key,
                    )
                )

        elif bar_time == first_test_time:
            signal_records.append(
                SignalRecord(
                    time=bar_time,
                    symbol="PORTFOLIO",
                    action="INITIALIZATION_ONLY",
                    detail=(
                        f"{initialization_bars} common bars "
                        "reserved for indicator initialization; "
                        "swing entries disabled."
                    ),
                    tie_key="",
                )
            )

        close_prices = _position_prices(
            portfolio=portfolio,
            maps=maps,
            bar_time=bar_time,
            field="close",
        )
        swing_market_value = (
            portfolio.market_value(
                close_prices
            )
        )
        swing_equity = portfolio.equity(
            close_prices
        )
        income_value = (
            0.0
            if swing_only
            else (
                income_shares
                * qdte_bar.close
            )
        )
        total_equity = (
            swing_equity
            + income_value
        )
        if swing_only:
            target = 0.0
        else:
            target, _ = contribution_allocation(
                allocation_years,
                config,
            )
        investable = (
            income_value
            + portfolio.cash
            + swing_market_value
        )
        income_weight = (
            income_value / investable
            if investable > 0
            else 0.0
        )
        equity_points.append(
            EquityPoint(
                time=bar_time,
                total_equity=total_equity,
                total_contributions=(
                    total_contributions
                ),
                income_value=income_value,
                swing_equity=swing_equity,
                swing_cash=portfolio.cash,
                swing_market_value=(
                    swing_market_value
                ),
                tax_reserve=(
                    portfolio.tax_reserve_cash
                ),
                income_weight=income_weight,
                target_income_weight=target,
                open_positions=len(
                    portfolio.positions
                ),
                pending_entries=len(
                    pending
                ),
                active_risk=(
                    portfolio.active_risk()
                ),
            )
        )

    pending = {}
    final_time = test_times[-1]

    for position in list(
        portfolio.positions.values()
    ):
        symbol = position.symbol
        final_bar = maps[symbol][final_time]
        closed = portfolio.close_position(
            symbol=symbol,
            exit_price=final_bar.close,
            exit_date=final_time.date(),
            reason="END_OF_TEST",
            config=config,
        )
        entry_time = entry_times.pop(
            symbol
        )
        trade_records.append(
            TradeRecord(
                symbol=closed.symbol,
                entry_time=entry_time,
                exit_time=final_time,
                shares=closed.shares,
                entry_price=closed.entry_price,
                exit_price=closed.exit_price,
                pnl=closed.pnl,
                tax_reserved=closed.tax_reserved,
                reason=closed.reason,
                result_r=closed.result_r,
            )
        )

    final_qdte = maps[INCOME_SYMBOL][
        final_time
    ]
    final_income_value = (
        0.0
        if swing_only
        else (
            income_shares
            * final_qdte.close
        )
    )
    final_swing_equity = (
        portfolio.equity({})
    )
    ending_equity = (
        final_income_value
        + final_swing_equity
    )
    final_years = elapsed_complete_years(
        actual_start,
        actual_end,
    )
    if swing_only:
        final_target = 0.0
    else:
        final_target, _ = contribution_allocation(
            final_years,
            config,
        )
    final_investable = (
        final_income_value
        + portfolio.cash
    )
    final_income_weight = (
        final_income_value
        / final_investable
        if final_investable > 0
        else 0.0
    )
    equity_points[-1] = EquityPoint(
        time=final_time,
        total_equity=ending_equity,
        total_contributions=(
            total_contributions
        ),
        income_value=final_income_value,
        swing_equity=final_swing_equity,
        swing_cash=portfolio.cash,
        swing_market_value=0.0,
        tax_reserve=(
            portfolio.tax_reserve_cash
        ),
        income_weight=(
            final_income_weight
        ),
        target_income_weight=(
            final_target
        ),
        open_positions=0,
        pending_entries=0,
        active_risk=0.0,
    )

    metrics = _daily_metrics(
        equity_points,
        starting_capital=(
            config.total_starting_capital
        ),
    )
    trade_counts = Counter(
        trade.symbol
        for trade in trade_records
    )
    winners = sum(
        trade.pnl > 0
        for trade in trade_records
    )
    net_profit = (
        ending_equity
        - total_contributions
    )
    result = BacktestResult(
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        provider=(
            (
                (
                    "Validated local Massive/Polygon actual "
                    "15-minute ETF/QDTE timestamp-control caches "
                    "+ official Cboe VIX daily closes"
                )
                if swing_only
                else (
                    "Validated local Massive/Polygon actual "
                    "15-minute ETF/QDTE caches + official "
                    "Cboe VIX daily closes"
                )
            )
            if local_only
            else (
                "Massive/Polygon actual 15-minute ETF bars "
                "+ official Cboe VIX daily closes"
            )
        ),
        actual_data=True,
        requested_start=requested_start,
        actual_start=actual_start,
        actual_end=actual_end,
        warmup_start=warmup_start,
        fixed_window=fixed_window,
        local_only=local_only,
        swing_only=swing_only,
        initialization_bars=initialization_bars,
        first_entry_eligible_time=(
            entry_eligible_time.isoformat()
        ),
        interval="15m",
        common_test_bars=len(test_times),
        test_sessions=len(sessions),
        expected_market_sessions=(
            expected_market_sessions
        ),
        session_coverage=session_coverage,
        swing_symbols=SWING_SYMBOLS,
        income_symbol=INCOME_SYMBOL,
        vix_symbol=VIX_PROVIDER_SYMBOL,
        vix_observation_policy=(
            VIX_OBSERVATION_POLICY
        ),
        rankings_enabled=False,
        maximum_concurrent_positions=6,
        maximum_observed_positions=(
            maximum_observed_positions
        ),
        starting_income_cash=(
            0.0
            if swing_only
            else config.starting_cash
        ),
        starting_swing_cash=(
            config.total_starting_capital
            if swing_only
            else config.starting_swing_cash
        ),
        starting_total_capital=(
            config.total_starting_capital
        ),
        monthly_contribution=(
            config.monthly_contribution
        ),
        contribution_count=(
            contribution_count
        ),
        total_contributions=(
            total_contributions
        ),
        ending_equity=ending_equity,
        net_profit=net_profit,
        return_on_contributions=(
            net_profit
            / total_contributions
            if total_contributions > 0
            else 0.0
        ),
        flow_adjusted_total_return=(
            metrics.total_return
        ),
        flow_adjusted_cagr=metrics.cagr,
        annualized_volatility=(
            metrics.annualized_volatility
        ),
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        maximum_drawdown=(
            metrics.maximum_drawdown
        ),
        swing_exposure=metrics.exposure,
        ending_income_value=(
            final_income_value
        ),
        ending_income_weight=(
            final_income_weight
        ),
        ending_swing_equity=(
            final_swing_equity
        ),
        ending_swing_cash=(
            portfolio.cash
        ),
        ending_tax_reserve=(
            portfolio.tax_reserve_cash
        ),
        qdte_distributions_received=(
            distributions_received
        ),
        qdte_distribution_events=(
            distribution_count
        ),
        all_symbol_evaluations=(
            all_evaluations
        ),
        qualifying_signal_bars=sum(
            qualifying_by_symbol.values()
        ),
        qualifying_by_symbol={
            symbol: qualifying_by_symbol.get(
                symbol,
                0,
            )
            for symbol in SWING_SYMBOLS
        },
        staged_signals=(
            staged_signals
        ),
        filled_entries=(
            filled_entries
        ),
        capacity_deferred=(
            capacity_deferred
        ),
        gap_rejections=(
            gap_rejections
        ),
        risk_rejections=(
            risk_rejections
        ),
        closed_trades=len(
            trade_records
        ),
        trades_by_symbol={
            symbol: trade_counts.get(
                symbol,
                0,
            )
            for symbol in SWING_SYMBOLS
        },
        win_rate=(
            winners
            / len(trade_records)
            if trade_records
            else 0.0
        ),
        profit_factor=_profit_factor(
            trade_records
        ),
        failed_check_counts=dict(
            failed_checks
        ),
        allocation_anniversary_rule=(
            "NOT_APPLICABLE_SWING_ONLY"
            if swing_only
            else "EXACT_DATE"
        ),
        forced_entries=False,
        placeholder_data=False,
        synthetic_data=False,
        live_broker_enabled=False,
    )

    artifact_prefix = (
        "swing_only_control"
        if swing_only
        else "actual_two_year_15m"
    )
    report_path = (
        report_directory
        / f"{artifact_prefix}_report.txt"
    )
    result_path = (
        report_directory
        / f"{artifact_prefix}_result.json"
    )
    equity_path = (
        report_directory
        / f"{artifact_prefix}_equity.csv"
    )
    trades_path = (
        report_directory
        / f"{artifact_prefix}_trades.csv"
    )
    signals_path = (
        report_directory
        / f"{artifact_prefix}_signals.csv"
    )
    allocations_path = (
        report_directory
        / f"{artifact_prefix}_allocations.csv"
    )
    diagnostics_path = (
        report_directory
        / f"{artifact_prefix}_diagnostics.json"
    )
    provenance_path = (
        report_directory
        / f"{artifact_prefix}_provenance.json"
    )

    report_path.write_text(
        _format_report(result)
        + "\n",
        encoding="utf-8",
    )
    result_payload = asdict(result)

    for field in (
        "requested_start",
        "actual_start",
        "actual_end",
        "warmup_start",
    ):
        result_payload[field] = (
            getattr(result, field).isoformat()
        )

    _atomic_json(
        result_path,
        result_payload,
    )
    _write_equity(
        equity_path,
        equity_points,
    )
    _write_trades(
        trades_path,
        trade_records,
    )
    _write_signals(
        signals_path,
        signal_records,
    )
    _write_allocations(
        allocations_path,
        allocation_records,
    )
    _atomic_json(
        diagnostics_path,
        {
            "schema_version": 1,
            "all_symbol_evaluations": (
                all_evaluations
            ),
            "qualifying_by_symbol": {
                symbol: qualifying_by_symbol.get(
                    symbol,
                    0,
                )
                for symbol in SWING_SYMBOLS
            },
            "failed_check_counts": dict(
                failed_checks
            ),
            "counts_overlap": True,
            "fixed_window": fixed_window,
            "local_only": local_only,
            "swing_only": swing_only,
            "initialization_bars": (
                initialization_bars
            ),
            "first_entry_eligible_time": (
                entry_eligible_time.isoformat()
            ),
        },
    )
    _atomic_json(
        provenance_path,
        {
            "schema_version": 1,
            "generated_at_utc": (
                result.generated_at_utc
            ),
            "provider": result.provider,
            "provider_hosts": sorted(
                provider_hosts
            ),
            "provider_stock_endpoint": (
                "/v2/aggs/ticker/{ticker}/range/"
                "15/minute/{from}/{to}"
            ),
            "provider_index_symbol": (
                VIX_PROVIDER_SYMBOL
            ),
            "provider_vix_source_url": (
                CBOE_VIX_HISTORY_URL
            ),
            "vix_observation_policy": (
                VIX_OBSERVATION_POLICY
            ),
            "intraday_vix_data": False,
            "vix_values_are_actual": True,
            "vix_placeholder": False,
            "provider_dividend_endpoint": (
                "/stocks/v1/dividends"
            ),
            "actual_data": True,
            "interval": "15m",
            "regular_session_only": True,
            "extended_hours": False,
            "common_timestamp_intersection": True,
            "expected_market_sessions": (
                expected_market_sessions
            ),
            "observed_common_sessions": (
                len(sessions)
            ),
            "session_coverage": session_coverage,
            "required_common_sessions": (
                required_common_sessions
            ),
            "warmup_bars_required": (
                config.sma_trend_period
            ),
            "fixed_window": fixed_window,
            "local_only": local_only,
            "swing_only": swing_only,
            "income_sleeve_active": (
                not swing_only
            ),
            "qdte_used_for_common_timestamp_control": (
                swing_only
            ),
            "initialization_bars": (
                initialization_bars
            ),
            "first_entry_eligible_time": (
                entry_eligible_time.isoformat()
            ),
            "entry_engine": (
                "qpx_bot.strategy.evaluate_entry"
            ),
            "exit_engine": (
                "qpx_bot.strategy.evaluate_exit"
            ),
            "position_sizing_engine": (
                "qpx_bot.risk.calculate_position_size"
            ),
            "allocation_engine": (
                "DISABLED_SWING_ONLY"
                if swing_only
                else (
                    "qpx_bot.allocation."
                    "rebalance_income_allocation"
                )
            ),
            "simultaneous_signal_tiebreak": (
                policy.simultaneous_signal_tiebreak
            ),
            "configuration": asdict(config),
            "active_policy": asdict(policy),
            "download_manifest": {
                "path": str(manifest_path),
                "sha256": _sha256(
                    manifest_path
                ),
            },
            "placeholder_data": False,
            "synthetic_data": False,
            "interpolated_bars": False,
            "tradeable_asset_daily_bar_substitution": False,
        "vix_daily_close_expanded_to_intraday_timestamps": True,
            "forced_entries": False,
            "live_broker_enabled": False,
        },
    )
    artifacts = RunArtifacts(
        report=report_path,
        result=result_path,
        equity=equity_path,
        trades=trades_path,
        signals=signals_path,
        allocations=allocations_path,
        diagnostics=diagnostics_path,
        provenance=provenance_path,
        manifest=manifest_path,
    )
    return result, artifacts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run an all-real two-year 15-minute QPX "
            "six-position backtest."
        )
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
    )
    parser.add_argument(
        "--report-root",
        default=str(DEFAULT_REPORT_ROOT),
    )
    return parser


def _api_key(
    explicit: str | None,
) -> str:
    key = (
        explicit
        or os.environ.get("MASSIVE_API_KEY")
        or os.environ.get("POLYGON_API_KEY")
        or ""
    ).strip()

    if key:
        return key

    if os.isatty(0):
        return getpass.getpass(
            "Paste Massive/Polygon API key "
            "(input is hidden): "
        ).strip()

    raise ProviderError(
        "Set MASSIVE_API_KEY or POLYGON_API_KEY. "
        "The key is never written to the repository."
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    key = _api_key(args.api_key)
    result, artifacts = run_backtest(
        api_key=key,
        data_root=args.data_root,
        report_root=args.report_root,
    )
    print(
        _format_report(result)
    )
    print("-" * 78)
    print("Artifacts:")

    for name, path in asdict(
        artifacts
    ).items():
        print(f"  {name:<12}: {path}")

    print()
    print(
        "QPX ACTUAL TWO-YEAR 15-MINUTE "
        "SIX-POSITION CBOE-VIX BACKTEST V4: COMPLETE"
    )
    return 0




def fixed_window_main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed local QPX near-two-year "
            "15-minute six-position backtest."
        )
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
    )
    parser.add_argument(
        "--report-root",
        default=str(DEFAULT_FIXED_REPORT_ROOT),
    )
    args = parser.parse_args(argv)
    result, artifacts = run_backtest(
        api_key="",
        data_root=args.data_root,
        report_root=args.report_root,
        fixed_start=FIXED_WINDOW_START,
        fixed_end=FIXED_WINDOW_END,
        local_only=True,
        initialization_bars=(
            FIXED_INITIALIZATION_BARS
        ),
    )
    print(_format_report(result))
    print("-" * 78)
    print("Artifacts:")

    for name, path in asdict(
        artifacts
    ).items():
        print(f"  {name:<12}: {path}")

    print()
    print(
        "QPX FIXED 2024-08-06 TO 2026-07-28 "
        "LOCAL 15-MINUTE BACKTEST: COMPLETE"
    )
    return 0


def swing_only_control_main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the fixed local QPX swing-only control "
            "for 2024-08-06 through 2026-07-28."
        )
    )
    parser.add_argument(
        "--data-root",
        default=str(DEFAULT_DATA_ROOT),
    )
    parser.add_argument(
        "--report-root",
        default=str(DEFAULT_SWING_ONLY_REPORT_ROOT),
    )
    args = parser.parse_args(argv)
    result, artifacts = run_backtest(
        api_key="",
        data_root=args.data_root,
        report_root=args.report_root,
        fixed_start=FIXED_WINDOW_START,
        fixed_end=FIXED_WINDOW_END,
        local_only=True,
        initialization_bars=FIXED_INITIALIZATION_BARS,
        swing_only=True,
    )
    print(_format_report(result))
    print("-" * 78)
    print("Artifacts:")

    for name, path in asdict(
        artifacts
    ).items():
        print(f"  {name:<12}: {path}")

    print()
    print(
        "QPX SWING-ONLY CONTROL 2024-08-06 TO 2026-07-28 "
        "LOCAL 15-MINUTE BACKTEST: COMPLETE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
