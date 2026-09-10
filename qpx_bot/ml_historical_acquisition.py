"""Resumable whole-market Alpaca SIP 15-minute historical reservoir.

This is acquisition software only.  It does not train, qualify, trade, or read
any QPX forward/broker runtime.  Daily and hourly views are deterministic local
derivations from the canonical 15-minute partitions.
"""
from __future__ import annotations

import csv
import errno
import gzip
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import signal
import socket
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time as wall_time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo

from qpx_bot.alpaca_provider import credentials
from qpx_bot.historical_market_calendar import (
    FROZEN_CALENDAR_CONTENT_FINGERPRINT,
    FrozenHistoricalMarketCalendar,
    load_frozen_historical_calendar,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    is_market_session,
    latest_completed_session,
    next_market_session,
)
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = ROOT / "research_data" / "qpx_ml_historical_v1"
QUALIFIED_FROZEN_ROOT = ROOT / "research_data" / "qpx_frozen_alpaca_top100_v1"
ASSET_URL = "https://paper-api.alpaca.markets/v2/assets"
BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
CORPORATE_ACTION_URL = "https://data.alpaca.markets/v1/corporate-actions"
PROVIDER = "alpaca"
FEED = "sip"
ADJUSTMENT = "raw"
TIMEFRAME = "15Min"
SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 3
ACQUISITION_PROVENANCE_VERSION = "QPX_ML_HISTORICAL_15M_V3"
PROVIDER_INPUT_SEMANTIC_VERSION = "ALPACA_SIP_RAW_15M_HISTORICAL_V2"
LEGACY_ACQUISITION_PROVENANCE_VERSION = "QPX_ML_HISTORICAL_15M_V2"
LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION = "ALPACA_SIP_RAW_15M_HISTORICAL_V1"
REJECTION_EVIDENCE_SCHEMA_VERSION = 1
PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION = 1
OBSERVATIONAL_COVERAGE_SCHEMA_VERSION = 1
CORPORATE_ACTION_EVIDENCE_SCHEMA_VERSION = 2
CORPORATE_ACTION_IDENTITY_RESOLUTION_SCHEMA_VERSION = 1
CORPORATE_ACTION_SEMANTIC_VERSION = "ALPACA_CORPORATE_ACTIONS_HISTORICAL_V2"
BATCH_SIZE = 50
PAGE_LIMIT = 10_000
REQUESTS_PER_MINUTE = 120
LIVE_REQUESTS_PER_MINUTE = 6
LIVE_CAPACITY_RECHECK_SECONDS = 30
LIVE_DECISION_PROTECTION_SECONDS = 240
LIVE_DECISION_LAG_LIMIT_SECONDS = 180
LIVE_ATTRIBUTION_WINDOW_SECONDS = 90
MAX_PENDING_FINALIZATIONS = 32
COEXISTENCE_JOURNAL_MAX_BYTES = 1_000_000
LIVE_MIN_AVAILABLE_MEMORY_BYTES = 2_000_000_000
LIVE_MAX_IO_PRESSURE_AVG10 = 10.0
LIVE_MAX_LOAD_PER_CPU = 0.5
CLEAN_V2_UNIT = "qpx-pr50-iex-forward-research-paper-clean-v2.service"
CLEAN_V2_RUNTIME = ROOT / "runtime" / "qpx_pr50_iex_forward_research_paper_clean_v2"
MAX_ATTEMPTS = 5
COOPERATIVE_WAIT_QUANTUM_SECONDS = 1.0
PROVIDER_REQUEST_TIMEOUT_SECONDS = 30
OUTAGE_BACKOFF_SECONDS = (60, 120, 300, 600, 900)
MIN_FREE_BYTES = 200_000_000_000
MORNING_DEADLINE = wall_time(8, 45)
EASTERN = ZoneInfo("America/New_York")
CA_TYPES = (
    "forward_split", "reverse_split", "stock_dividend", "spin_off",
    "cash_merger", "stock_merger", "stock_and_cash_merger", "unit_split",
    "cash_dividend", "redemption", "name_change", "worthless_removal",
    "rights_distribution", "contract_adjustment", "partial_call", "reorganization",
)
BAR_COLUMNS = (
    "provider_asset_id", "observation_symbol", "market_timestamp",
    "session_date", "open", "high", "low", "close", "volume",
    "provider", "feed", "adjustment", "request_fingerprint",
)
BAR_OUTCOMES = (
    "ACCEPTED", "BAD_TIMESTAMP", "FUTURE_OR_OUT_OF_RANGE", "OFF_15M_GRID",
    "CALENDAR_REJECTED", "OUTSIDE_REGULAR_SESSION", "INVALID_OHLC",
    "NEGATIVE_VOLUME", "MALFORMED_ROW",
)
REJECTION_CATEGORIES = tuple(value for value in BAR_OUTCOMES if value != "ACCEPTED")


@dataclass(frozen=True, slots=True)
class BarClassification:
    outcome: str
    accepted_row: dict[str, Any] | None
    provider_timestamp: str | None
    raw_provider_row_sha256: str


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def canonical_provider_asset_id(value: Any) -> str:
    """Canonicalize UUID identities and preserve exact non-UUID provider IDs."""
    text = str(value)
    if not text or text != text.strip():
        raise ValueError("Provider asset identity is empty or has surrounding whitespace.")
    try:
        return str(uuid.UUID(text))
    except ValueError:
        return text


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_bytes(path: Path, encoded: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    atomic_bytes(path, json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")


def atomic_content_addressed_json(
    directory: Path, identity: str, payload: Mapping[str, Any], *, label: str,
) -> Path:
    path = directory / f"{identity}.json"
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Existing {label} evidence is corrupt.") from exc
        if existing != dict(payload):
            raise RuntimeError(f"Content-addressed {label} evidence conflicts.")
    else:
        atomic_json(path, payload)
    return path


def calculate_range(now: datetime | None = None) -> dict[str, str]:
    end, end_status = latest_completed_session(now)
    try:
        requested_start = end.replace(year=end.year - 10)
    except ValueError:
        requested_start = end.replace(year=end.year - 10, day=28)
    actual_start = next_market_session(requested_start, include_day=True)
    return {
        "requested_start": requested_start.isoformat(),
        "actual_first_requested_session": actual_start.isoformat(),
        "requested_end": end.isoformat(),
        "actual_last_completed_session": end.isoformat(),
        "end_status": end_status,
    }


def session_dates(start: date, end: date) -> list[date]:
    values: list[date] = []
    current = start
    while current <= end:
        if is_market_session(current):
            values.append(current)
        current += timedelta(days=1)
    return values


def initial_estimate(security_count: int, requested: Mapping[str, str], free_bytes: int) -> dict[str, Any]:
    sessions = len(session_dates(date.fromisoformat(requested["actual_first_requested_session"]), date.fromisoformat(requested["actual_last_completed_session"])))
    upper_rows = security_count * sessions * 26
    estimated_rows_low = int(upper_rows * 0.22)
    estimated_rows_high = int(upper_rows * 0.55)
    compressed_low = estimated_rows_low * 45
    compressed_high = estimated_rows_high * 75
    uncompressed_low = estimated_rows_low * 115
    uncompressed_high = estimated_rows_high * 180
    partitions = ((security_count + BATCH_SIZE - 1) // BATCH_SIZE) * len({d.year for d in session_dates(date.fromisoformat(requested["actual_first_requested_session"]), date.fromisoformat(requested["actual_last_completed_session"]))})
    request_low = max(partitions, estimated_rows_low // PAGE_LIMIT)
    request_high = max(partitions, estimated_rows_high // PAGE_LIMIT + partitions)
    return {
        "security_count": security_count,
        "trading_sessions": sessions,
        "bars_per_full_session": 26,
        "upper_bound_rows": upper_rows,
        "estimated_rows_range": [estimated_rows_low, estimated_rows_high],
        "estimated_compressed_bytes_range": [compressed_low, compressed_high],
        "estimated_uncompressed_bytes_range": [uncompressed_low, uncompressed_high],
        "free_bytes_before_start": free_bytes,
        "safety_reserve_bytes": MIN_FREE_BYTES,
        "expected_remaining_free_bytes_range": [free_bytes - compressed_high, free_bytes - compressed_low],
        "partition_count": partitions,
        "estimated_api_requests_range": [request_low, request_high],
        "governor_requests_per_minute": REQUESTS_PER_MINUTE,
        "estimated_provider_minutes_range": [round(request_low / REQUESTS_PER_MINUTE, 1), round(request_high / REQUESTS_PER_MINUTE, 1)],
    }


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, systemic: bool = False,
                 transient: bool = False, failure_class: str = "PROVIDER_ERROR"):
        super().__init__(message)
        self.status = status
        self.systemic = systemic
        self.transient = transient
        self.failure_class = failure_class


class CooperativeStop(RuntimeError):
    """Internal control flow for a requested, safely checkpointed shutdown."""


def classify_transport_error(exc: BaseException) -> tuple[bool, str]:
    """Classify positively identifiable transport failures; unknowns fail closed."""
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, socket.gaierror):
        return True, "DNS_RESOLUTION_FAILURE"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return True, "CONNECTION_TIMEOUT"
    if isinstance(reason, ConnectionResetError):
        return True, "CONNECTION_RESET"
    if isinstance(reason, ssl.SSLCertVerificationError):
        return False, "TLS_CERTIFICATE_FAILURE"
    if isinstance(reason, ssl.SSLError):
        return True, "TLS_CONNECTIVITY_FAILURE"
    transient_errnos = {getattr(errno, name) for name in (
        "EAGAIN", "ECONNABORTED", "ECONNREFUSED", "ECONNRESET", "EHOSTDOWN",
        "EHOSTUNREACH", "ENETDOWN", "ENETRESET", "ENETUNREACH", "ETIMEDOUT",
    ) if hasattr(errno, name)}
    if isinstance(reason, OSError) and reason.errno in transient_errnos:
        return True, "NETWORK_UNREACHABLE"
    return False, "UNCLASSIFIED_TRANSPORT_FAILURE"


class RateGovernor:
    def __init__(self, requests_per_minute: int = REQUESTS_PER_MINUTE, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.interval = 60.0 / requests_per_minute
        self.clock, self.sleep, self.next_at = clock, sleep, 0.0

    def wait(self) -> None:
        now = self.clock()
        if now < self.next_at:
            self.sleep(self.next_at - now)
            now = self.clock()
        self.next_at = max(now, self.next_at) + self.interval

    def set_requests_per_minute(self, requests_per_minute: int) -> None:
        if requests_per_minute < 1:
            raise ValueError("Request rate must be positive.")
        self.interval = 60.0 / requests_per_minute


def _proc_available_memory() -> int:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _proc_io_pressure() -> float:
    try:
        first = Path("/proc/pressure/io").read_text().splitlines()[0]
        return float(next(part.split("=", 1)[1] for part in first.split() if part.startswith("avg10=")))
    except (OSError, ValueError, IndexError, StopIteration):
        return float("inf")


def _clean_service_state() -> str:
    try:
        result = subprocess.run(
            ("systemctl", "--user", "show", CLEAN_V2_UNIT, "--property=ActiveState", "--value"),
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _latest_clean_cycle_evidence() -> dict[str, Any] | None:
    path = CLEAN_V2_RUNTIME / "iex_research_paper_audit.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-200:]
    except OSError:
        return None
    for line in reversed(lines):
        try:
            record = json.loads(line)
            if record.get("event_type") != "IEX_RESEARCH_DECISION_CYCLE_TELEMETRY":
                continue
            end = record["details"]["decision_bar_interval"]["end_market"]
            observed = datetime.fromisoformat(record["observed_at_utc"])
            return {"lag_seconds": (observed - datetime.fromisoformat(end)).total_seconds(),
                    "observed_at_utc": observed.isoformat()}
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return None


def _latest_clean_cycle_lag() -> float | None:
    evidence = _latest_clean_cycle_evidence()
    return float(evidence["lag_seconds"]) if evidence else None


def _clean_provider_state() -> str:
    path = CLEAN_V2_RUNTIME / "iex_research_paper_heartbeat.json"
    checksum = path.with_suffix(".sha256")
    try:
        payload = json.loads(read_checksummed_state(path, checksum, label="Clean-V2 heartbeat"))
        return str(payload.get("provider_state", "UNKNOWN"))
    except Exception:
        return "UNKNOWN"


def coexistence_capacity(moment: datetime) -> dict[str, Any]:
    """Read-only, fail-safe capacity decision; it never controls Clean-V2."""
    from qpx_bot.clean_v2_market_supervisor import schedule_decision
    decision = schedule_decision(moment)
    if not decision.desired_active:
        return {"mode": "OFF_MARKET", "live_qpx_active": False, "reason": None}
    service_state = _clean_service_state()
    common = {"live_qpx_active": service_state in {"active", "activating"}, "clean_v2_service_state": service_state}
    if service_state not in {"active", "activating"}:
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CLEAN_V2_NOT_ACTIVE_OR_UNKNOWN", **common}
    market = moment.astimezone(EASTERN)
    seconds_after_quarter = ((market.minute % 15) * 60) + market.second
    if seconds_after_quarter < LIVE_DECISION_PROTECTION_SECONDS:
        return {"mode": "PROTECTED_DECISION_WINDOW", "reason": "CLEAN_V2_DECISION_WINDOW", **common}
    provider_state = _clean_provider_state()
    if market.time().replace(tzinfo=None) >= wall_time(9, 45) and provider_state != "HEALTHY":
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CLEAN_V2_PROVIDER_NOT_HEALTHY", "clean_v2_provider_state": provider_state, **common}
    available = _proc_available_memory()
    load = os.getloadavg()[0]
    io_pressure = _proc_io_pressure()
    evidence = {"available_memory_bytes": available, "load_1m": load, "io_pressure_avg10": io_pressure}
    if available < LIVE_MIN_AVAILABLE_MEMORY_BYTES:
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "MEMORY_PRESSURE", **evidence, **common}
    if load > max(1.0, (os.cpu_count() or 1) * LIVE_MAX_LOAD_PER_CPU):
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CPU_LOAD_PRESSURE", **evidence, **common}
    if io_pressure > LIVE_MAX_IO_PRESSURE_AVG10:
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "DISK_IO_PRESSURE", **evidence, **common}
    cycle = _latest_clean_cycle_evidence()
    lag = float(cycle["lag_seconds"]) if cycle else None
    if lag is not None and lag > LIVE_DECISION_LAG_LIMIT_SECONDS:
        return {"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "CLEAN_V2_DECISION_LATENCY", "clean_v2_latest_decision_lag_seconds": lag, "clean_v2_degradation_observed_at_utc": cycle["observed_at_utc"], **evidence, **common}
    return {"mode": "LIVE_COEXISTENCE", "reason": None, "historical_request_ceiling_per_minute": LIVE_REQUESTS_PER_MINUTE, "clean_v2_latest_decision_lag_seconds": lag, "clean_v2_provider_state": provider_state, **evidence, **common}


@dataclass
class AlpacaHistoricalClient:
    governor: RateGovernor
    attempts: int = MAX_ATTEMPTS
    request_count: int = 0
    retry_count: int = 0
    last_success_at_utc: str | None = None
    successful_request_count: int = 0
    request_latency_seconds_total: float = 0.0
    rate_limit: int | None = None
    rate_limit_remaining: int | None = None
    rate_limit_reset: str | None = None
    wait: Callable[[float], None] = time.sleep

    def request(self, url: str, params: Mapping[str, str]) -> dict[str, Any] | list[Any]:
        key, secret = credentials()
        request = urllib.request.Request(
            url + "?" + urllib.parse.urlencode(params),
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret, "Accept": "application/json", "Accept-Encoding": "identity", "User-Agent": "QPX-ML-HISTORICAL-V1"},
        )
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            self.governor.wait()
            self.request_count += 1
            request_started = time.monotonic()
            try:
                with urllib.request.urlopen(request, timeout=PROVIDER_REQUEST_TIMEOUT_SECONDS) as response:
                    payload = json.loads(response.read())
                    headers = response.headers
                if not isinstance(payload, (dict, list)):
                    raise ProviderError("Provider returned a non-container response.", systemic=True)
                self.last_success_at_utc = datetime.now(timezone.utc).isoformat()
                self.successful_request_count += 1
                self.request_latency_seconds_total += max(0.0, time.monotonic() - request_started)
                try:
                    self.rate_limit = int(headers.get("X-RateLimit-Limit")) if headers.get("X-RateLimit-Limit") else None
                    self.rate_limit_remaining = int(headers.get("X-RateLimit-Remaining")) if headers.get("X-RateLimit-Remaining") else None
                except (TypeError, ValueError):
                    self.rate_limit = self.rate_limit_remaining = None
                self.rate_limit_reset = headers.get("X-RateLimit-Reset")
                return payload
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")[:500]
                transient = exc.code in {429, 500, 502, 503, 504}
                last = ProviderError(f"Alpaca HTTP {exc.code}: {body}", status=exc.code,
                                     systemic=exc.code in {401, 403}, transient=transient,
                                     failure_class=f"HTTP_{exc.code}")
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise last
                retry_after = exc.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(30.0, 2 ** attempt + random.random())
            except json.JSONDecodeError as exc:
                raise ProviderError(f"Malformed provider JSON: {exc}", systemic=True,
                                    failure_class="MALFORMED_PROVIDER_RESPONSE") from exc
            except (OSError, urllib.error.URLError) as exc:
                transient, failure_class = classify_transport_error(exc)
                if not transient:
                    raise ProviderError(str(exc), systemic=True, failure_class=failure_class) from exc
                last = ProviderError(str(exc), transient=True, failure_class=failure_class)
                delay = min(30.0, 2 ** attempt + random.random())
            if attempt < self.attempts:
                self.retry_count += 1
                self.wait(delay)
        if isinstance(last, ProviderError) and last.transient:
            raise ProviderError(f"Provider request exhausted bounded retries: {last}", transient=True,
                                status=last.status, failure_class=last.failure_class) from last
        raise ProviderError(f"Provider request exhausted bounded retries: {last}", systemic=True)

    def assets(self, status: str) -> list[dict[str, Any]]:
        payload = self.request(ASSET_URL, {"status": status, "asset_class": "us_equity"})
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise ProviderError("Malformed Alpaca assets response.", systemic=True)
        return payload


def build_security_master(active: Iterable[Mapping[str, Any]], inactive: Iterable[Mapping[str, Any]], acquired_at: datetime) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for source_status, items in (("active", active), ("inactive", inactive)):
        for raw in items:
            try:
                asset_id = canonical_provider_asset_id(raw.get("id", ""))
            except ValueError:
                continue
            symbol = str(raw.get("symbol", "")).strip().upper()
            if not asset_id or not symbol or str(raw.get("class")) != "us_equity":
                continue
            facts = {
                "provider_asset_id": asset_id, "canonical_current_symbol": symbol,
                "historical_symbols": [], "exchange": raw.get("exchange"),
                "asset_class": raw.get("class"), "provider_status": raw.get("status", source_status),
                "active": raw.get("status", source_status) == "active",
                "tradable": bool(raw.get("tradable")), "fractionable": bool(raw.get("fractionable")),
                "marginable": bool(raw.get("marginable")), "shortable": bool(raw.get("shortable")),
                "easy_to_borrow": bool(raw.get("easy_to_borrow")), "attributes": raw.get("attributes") or [],
                "authoritative_listing_date": None, "authoritative_delisting_date": None,
                "first_observed_bar": None, "last_observed_bar": None,
                "source": PROVIDER, "acquired_at_utc": acquired_at.astimezone(timezone.utc).isoformat(),
            }
            facts["provenance_fingerprint"] = fingerprint(facts)
            previous = by_id.get(asset_id)
            if previous is None or (not previous["active"] and facts["active"]):
                by_id[asset_id] = facts
    return sorted(by_id.values(), key=lambda item: (item["provider_asset_id"], item["canonical_current_symbol"]))


def batch_descriptor(
    *, year: int, start: date, end: date, symbols: Iterable[str], asset_ids: Iterable[str],
    provider_input_semantic_version: str = PROVIDER_INPUT_SEMANTIC_VERSION,
) -> dict[str, Any]:
    symbol_values = list(symbols)
    identity_values = list(asset_ids)
    if len(symbol_values) != len(identity_values) or not identity_values:
        raise ValueError("Batch symbols and provider identities must be non-empty and one-to-one.")
    members = sorted(
        (
            {"provider_asset_id": canonical_provider_asset_id(asset_id), "canonical_symbol": str(symbol).strip().upper()}
            for symbol, asset_id in zip(symbol_values, identity_values)
        ),
        key=lambda item: (item["provider_asset_id"], item["canonical_symbol"]),
    )
    identity = {
        "year": int(year), "requested_start": start.isoformat(),
        "requested_end": end.isoformat(), "feed": FEED, "adjustment": ADJUSTMENT,
        "timeframe": TIMEFRAME, "provider_input_semantic_version": provider_input_semantic_version,
        "members": members,
    }
    return {**identity, "batch_fingerprint": fingerprint(identity)}


def request_identity(request_core: Mapping[str, Any], batch_fingerprint: str, *,
                     provider_input_semantic_version: str = PROVIDER_INPUT_SEMANTIC_VERSION) -> str:
    return fingerprint({
        "provider_input_semantic_version": provider_input_semantic_version,
        "batch_fingerprint": batch_fingerprint,
        "request": dict(request_core),
    })


def legacy_v2_page_evidence(path: Path, *, page: int, row_count: int,
                            request_fingerprint: str, batch_fingerprint: str) -> dict[str, Any]:
    """Reproduce historical V2 page evidence without relabelling it as V3."""
    core = {
        "schema_version": 2, "page": page,
        "sha256": sha256_path(path), "row_count": row_count,
        "request_fingerprint": request_fingerprint, "batch_fingerprint": batch_fingerprint,
        "acquisition_provenance_version": LEGACY_ACQUISITION_PROVENANCE_VERSION,
    }
    return {**core, "evidence_fingerprint": fingerprint(core)}


def _canonical_source_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return {"qpx_nonfinite_number": repr(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical_source_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_source_value(item) for item in value]
    if value is None or type(value) in {bool, int, float, str}:
        return value
    return {"qpx_unsupported_source_type": type(value).__name__, "text": str(value)}


def raw_provider_row_fingerprint(raw: Any) -> str:
    return fingerprint(_canonical_source_value(raw))


def _numeric(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a provider numeric value.")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Provider numeric value is non-finite.")
    return result


def classify_bar(raw: Any, symbol: str, asset_id: str, request_fp: str, start: date,
                 end: date, now: datetime, calendar: FrozenHistoricalMarketCalendar) -> BarClassification:
    raw_sha = raw_provider_row_fingerprint(raw)
    if not isinstance(raw, Mapping):
        return BarClassification("MALFORMED_ROW", None, None, raw_sha)
    try:
        raw_timestamp = raw["t"]
        if not isinstance(raw_timestamp, str):
            raise ValueError("Timestamp must be text.")
        timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Timestamp must be timezone-aware.")
        timestamp = timestamp.astimezone(EASTERN)
    except (KeyError, TypeError, ValueError, OverflowError):
        return BarClassification("BAD_TIMESTAMP", None, None, raw_sha)
    provider_timestamp = timestamp.isoformat()
    try:
        values = [_numeric(raw[name]) for name in ("o", "h", "l", "c")]
        raw_volume = _numeric(raw["v"])
        if not raw_volume.is_integer():
            raise ValueError("Volume must be an integer.")
        volume = int(raw_volume)
    except (KeyError, TypeError, ValueError, OverflowError):
        return BarClassification("MALFORMED_ROW", None, provider_timestamp, raw_sha)
    if (
        not start <= timestamp.date() <= end
        or not calendar.covered_start <= timestamp.date() <= calendar.covered_end
        or timestamp + timedelta(minutes=15) > now.astimezone(EASTERN)
    ):
        return BarClassification("FUTURE_OR_OUT_OF_RANGE", None, provider_timestamp, raw_sha)
    if timestamp.minute % 15 or timestamp.second or timestamp.microsecond:
        return BarClassification("OFF_15M_GRID", None, provider_timestamp, raw_sha)
    session = calendar.session_on(timestamp.date())
    if session is None:
        return BarClassification("CALENDAR_REJECTED", None, provider_timestamp, raw_sha)
    if not session.regular_open <= timestamp < session.regular_close:
        return BarClassification("OUTSIDE_REGULAR_SESSION", None, provider_timestamp, raw_sha)
    o, h, l, c = values
    if min(values) <= 0 or h < max(o, l, c) or l > min(o, h, c):
        return BarClassification("INVALID_OHLC", None, provider_timestamp, raw_sha)
    if volume < 0:
        return BarClassification("NEGATIVE_VOLUME", None, provider_timestamp, raw_sha)
    accepted = {
        "provider_asset_id": asset_id, "observation_symbol": symbol,
        "market_timestamp": timestamp.isoformat(), "session_date": timestamp.date().isoformat(),
        "open": repr(o), "high": repr(h), "low": repr(l), "close": repr(c), "volume": str(volume),
        "provider": PROVIDER, "feed": FEED, "adjustment": ADJUSTMENT,
        "request_fingerprint": request_fp,
    }
    return BarClassification("ACCEPTED", accepted, provider_timestamp, raw_sha)


def validate_bar(raw: Mapping[str, Any], symbol: str, asset_id: str, request_fp: str,
                 start: date, end: date, now: datetime,
                 calendar: FrozenHistoricalMarketCalendar | None = None) -> dict[str, Any] | None:
    authority = calendar or load_frozen_historical_calendar()
    return classify_bar(raw, symbol, asset_id, request_fp, start, end, now, authority).accepted_row


def encode_gzip_jsonl(rows: Iterable[Mapping[str, Any]]) -> bytes:
    raw = b"".join(canonical_bytes(row) + b"\n" for row in rows)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as zipped:
        zipped.write(raw)
    return output.getvalue()


def read_gzip_jsonl(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def load_provider_population(root: Path) -> dict[str, Any]:
    master_path = root / "security_master" / "alpaca_us_equity_assets.json.gz"
    manifest_path = master_path.with_suffix(master_path.suffix + ".manifest.json")
    try:
        external = json.loads(manifest_path.read_text(encoding="utf-8"))
        if external.get("sha256") != sha256_path(master_path):
            raise RuntimeError("Security-master checksum does not match.")
        master = json.loads(gzip.decompress(master_path.read_bytes()))
    except (OSError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise RuntimeError("Security-master evidence is missing or corrupt.") from exc
    claimed_master_fp = master.get("manifest_fingerprint")
    master_core = {key: value for key, value in master.items() if key != "manifest_fingerprint"}
    if not isinstance(claimed_master_fp, str) or fingerprint(master_core) != claimed_master_fp:
        raise RuntimeError("Security-master provenance fingerprint does not match.")
    if external.get("provenance_fingerprint") != claimed_master_fp:
        raise RuntimeError("External security-master provenance does not match.")
    assets = master.get("assets")
    if not isinstance(assets, list) or not assets:
        raise RuntimeError("Security master has no provider population.")
    members: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    by_symbol: dict[str, list[str]] = {}
    for asset in assets:
        if not isinstance(asset, Mapping):
            raise RuntimeError("Security master contains a malformed asset.")
        asset_id = canonical_provider_asset_id(asset.get("provider_asset_id", ""))
        symbol = str(asset.get("canonical_current_symbol", "")).strip().upper()
        if not symbol or asset_id in seen_ids:
            raise RuntimeError("Security master contains missing or duplicate provider identity.")
        seen_ids.add(asset_id)
        members.append({"provider_asset_id": asset_id, "canonical_symbol": symbol})
        by_symbol.setdefault(symbol, []).append(asset_id)
    members.sort(key=lambda value: (value["provider_asset_id"], value["canonical_symbol"]))
    population_core = {
        "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
        "security_master_fingerprint": claimed_master_fp,
        "members": members,
    }
    population_fp = fingerprint(population_core)
    population_evidence = {
        **population_core, "provider_population_fingerprint": population_fp,
    }
    records: list[dict[str, Any]] = []
    for symbol, ids in sorted(by_symbol.items()):
        if len(ids) < 2:
            continue
        core = {
            "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
            "observation_symbol": symbol,
            "conflicting_provider_asset_ids": sorted(ids),
            "reason": "AMBIGUOUS_PROVIDER_IDENTITY",
            "security_master_fingerprint": claimed_master_fp,
            "provider_population_fingerprint": population_fp,
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
        }
        records.append({**core, "exclusion_fingerprint": fingerprint(core)})
    exclusion_core = {
        "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
        "security_master_fingerprint": claimed_master_fp,
        "provider_population_fingerprint": population_fp,
        "record_count": len(records),
        "affected_provider_id_count": sum(len(record["conflicting_provider_asset_ids"]) for record in records),
        "records": records,
    }
    return {
        "security_master_fingerprint": claimed_master_fp,
        "provider_population_fingerprint": population_fp,
        "provider_population_evidence": population_evidence,
        "members": tuple(members),
        "ambiguous_by_symbol": {
            record["observation_symbol"]: tuple(record["conflicting_provider_asset_ids"])
            for record in records
        },
        "ambiguous_records_by_symbol": {
            record["observation_symbol"]: record for record in records
        },
        "ambiguous_exclusion_set": {
            **exclusion_core,
            "exclusion_set_fingerprint": fingerprint(exclusion_core),
        },
    }


def partition_population_disposition(item: Mapping[str, Any], population: Mapping[str, Any],
                                     provider_rejections: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    if len(item["symbols"]) != len(item["asset_ids"]):
        raise RuntimeError("Planned symbols and provider identities are not one-to-one.")
    planned = sorted(
        ({"provider_asset_id": canonical_provider_asset_id(asset_id), "canonical_symbol": str(symbol).strip().upper()}
         for symbol, asset_id in zip(item["symbols"], item["asset_ids"])),
        key=lambda value: (value["provider_asset_id"], value["canonical_symbol"]),
    )
    if len(planned) != len(item["symbols"]) or len({value["provider_asset_id"] for value in planned}) != len(planned):
        raise RuntimeError("Planned provider population is not one-to-one by provider identity.")
    population_members = {
        (value["provider_asset_id"], value["canonical_symbol"])
        for value in population["members"]
    }
    if any((value["provider_asset_id"], value["canonical_symbol"]) not in population_members for value in planned):
        raise RuntimeError("Planned batch membership is not present in the validated security master.")
    ambiguous = population["ambiguous_by_symbol"]
    rejected_ids = {
        canonical_provider_asset_id(value.get("provider_asset_id", ""))
        for value in provider_rejections
        if value.get("reason") == "PROVIDER_REJECTED_SYMBOL"
    }
    requested: list[dict[str, str]] = []
    ambiguous_excluded: list[dict[str, str]] = []
    provider_excluded: list[dict[str, str]] = []
    for member in planned:
        if member["canonical_symbol"] in ambiguous:
            ambiguous_excluded.append(member)
        elif member["provider_asset_id"] in rejected_ids:
            provider_excluded.append(member)
        else:
            requested.append(member)
    requested_symbols = [value["canonical_symbol"] for value in requested]
    if len(set(requested_symbols)) != len(requested_symbols):
        raise RuntimeError("Requested symbols do not resolve one-to-one to provider identities.")
    dispositions = (requested, ambiguous_excluded, provider_excluded)
    disposition_ids = [value["provider_asset_id"] for group in dispositions for value in group]
    planned_ids = [value["provider_asset_id"] for value in planned]
    if len(disposition_ids) != len(set(disposition_ids)) or sorted(disposition_ids) != sorted(planned_ids):
        raise RuntimeError("Provider population disposition does not reconcile exactly.")
    applicable_ambiguous_records = [
        population["ambiguous_records_by_symbol"][symbol]
        for symbol in sorted({value["canonical_symbol"] for value in ambiguous_excluded})
    ]
    provider_rejected_records: list[dict[str, Any]] = []
    for member in provider_excluded:
        record_core = {
            "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
            "observation_symbol": member["canonical_symbol"],
            "provider_asset_id": member["provider_asset_id"],
            "reason": "PROVIDER_REJECTED_SYMBOL",
            "security_master_fingerprint": population["security_master_fingerprint"],
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
        }
        provider_rejected_records.append({
            **record_core, "exclusion_fingerprint": fingerprint(record_core),
        })
    exclusion_set_core = {
        "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
        "ambiguous_identity_exclusions": applicable_ambiguous_records,
        "provider_rejected_exclusions": provider_rejected_records,
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
    }
    exclusion_set_fingerprint = fingerprint(exclusion_set_core)
    core = {
        "schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
        "planned_provider_ids": planned_ids,
        "requested_unambiguous_provider_ids": [value["provider_asset_id"] for value in requested],
        "ambiguous_identity_excluded_provider_ids": [value["provider_asset_id"] for value in ambiguous_excluded],
        "other_governed_excluded_provider_ids": [value["provider_asset_id"] for value in provider_excluded],
        "requested_members": requested,
        "ambiguous_identity_excluded_members": ambiguous_excluded,
        "ambiguous_identity_exclusions": applicable_ambiguous_records,
        "provider_rejected_exclusions": provider_rejected_records,
        "exclusion_set_fingerprint": exclusion_set_fingerprint,
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "security_master_fingerprint": population["security_master_fingerprint"],
    }
    return {**core, "population_disposition_fingerprint": fingerprint(core)}


def rejection_record(*, raw: Any, outcome: BarClassification, partition: str, page: int,
                     ordinal: int, symbol: str | None, asset_id: str | None,
                     request_fingerprint: str, batch_fingerprint: str,
                     calendar_fingerprint: str) -> dict[str, Any]:
    if outcome.outcome == "ACCEPTED":
        raise ValueError("Accepted rows do not belong in rejection evidence.")
    core = {
        "schema_version": REJECTION_EVIDENCE_SCHEMA_VERSION,
        "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
        "partition": partition,
        "page": page,
        "source_row_ordinal": ordinal,
        "observation_symbol": symbol,
        "provider_asset_id": asset_id,
        "provider_timestamp": outcome.provider_timestamp,
        "rejection_category": outcome.outcome,
        "raw_provider_row_sha256": outcome.raw_provider_row_sha256,
        "request_fingerprint": request_fingerprint,
        "batch_fingerprint": batch_fingerprint,
        "frozen_calendar_fingerprint": calendar_fingerprint,
    }
    return {**core, "rejection_fingerprint": fingerprint(core)}


def page_evidence(accepted_path: Path, rejection_path: Path, *, page: int,
                  source_row_count: int, accepted_row_count: int, rejected_row_count: int,
                  rejection_counts_by_category: Mapping[str, int], request_fingerprint: str,
                  batch_fingerprint: str, calendar_fingerprint: str,
                  provider_population_fingerprint: str,
                  population_disposition_fingerprint: str,
                  exclusion_set_fingerprint: str) -> dict[str, Any]:
    if any(type(value) is not int for value in (source_row_count, accepted_row_count, rejected_row_count)):
        raise RuntimeError("Page row counts must be structural integers.")
    if min(source_row_count, accepted_row_count, rejected_row_count) < 0 or source_row_count != accepted_row_count + rejected_row_count:
        raise RuntimeError("Page source-row reconciliation failed.")
    if set(rejection_counts_by_category) - set(REJECTION_CATEGORIES):
        raise RuntimeError("Page evidence contains an unknown rejection category.")
    if any(type(value) is not int for value in rejection_counts_by_category.values()):
        raise RuntimeError("Page rejection counts must be structural integers.")
    normalized_counts = {category: int(rejection_counts_by_category.get(category, 0)) for category in REJECTION_CATEGORIES}
    if any(value < 0 for value in normalized_counts.values()) or sum(normalized_counts.values()) != rejected_row_count:
        raise RuntimeError("Page rejection-category reconciliation failed.")
    core = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "page": page,
        "source_row_count": source_row_count,
        "accepted_row_count": accepted_row_count,
        "rejected_row_count": rejected_row_count,
        "rejection_counts_by_category": normalized_counts,
        "accepted_fragment_sha256": sha256_path(accepted_path),
        "rejection_evidence_sha256": sha256_path(rejection_path),
        "request_fingerprint": request_fingerprint,
        "batch_fingerprint": batch_fingerprint,
        "frozen_calendar_fingerprint": calendar_fingerprint,
        "provider_population_fingerprint": provider_population_fingerprint,
        "population_disposition_fingerprint": population_disposition_fingerprint,
        "exclusion_set_fingerprint": exclusion_set_fingerprint,
        "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
        "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
    }
    return {**core, "page_evidence_fingerprint": fingerprint(core)}


def encode_gzip_csv(rows: Iterable[Mapping[str, Any]], columns: tuple[str, ...]) -> bytes:
    raw = io.StringIO(newline="")
    writer = csv.DictWriter(raw, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode="wb", mtime=0) as zipped:
        zipped.write(raw.getvalue().encode())
    return output.getvalue()


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def aggregate_bars(rows: Iterable[Mapping[str, str]], period: str) -> list[dict[str, str]]:
    if period not in {"hourly", "daily"}:
        raise ValueError("Aggregation period must be hourly or daily.")
    groups: dict[tuple[str, str], list[Mapping[str, str]]] = {}
    for row in rows:
        stamp = datetime.fromisoformat(row["market_timestamp"])
        bucket = row["session_date"] if period == "daily" else stamp.replace(minute=(stamp.minute // 60) * 60, second=0, microsecond=0).isoformat()
        groups.setdefault((row["provider_asset_id"], bucket), []).append(row)
    result: list[dict[str, str]] = []
    for (asset_id, bucket), values in sorted(groups.items()):
        values.sort(key=lambda item: item["market_timestamp"])
        result.append({"provider_asset_id": asset_id, "bucket": bucket, "open": values[0]["open"], "high": repr(max(float(v["high"]) for v in values)), "low": repr(min(float(v["low"]) for v in values)), "close": values[-1]["close"], "volume": str(sum(int(v["volume"]) for v in values)), "source_resolution": TIMEFRAME})
    return result


def normalize_corporate_action(raw: Mapping[str, Any], action_type: str, _acquired_at: datetime) -> dict[str, Any]:
    """Preserve provider facts without inventing unavailable causal dates."""
    if action_type not in CA_TYPES:
        raise ValueError("Corporate action type is unsupported.")
    action_id = str(raw.get("id", "")).strip()
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not action_id or not symbol:
        raise ValueError("Corporate action requires authoritative id and symbol.")
    date_values: dict[str, str | None] = {}
    for output_name, source_names in {
        "announcement_or_observation_date": ("announcement_date",),
        "ex_or_effective_date": ("ex_date", "effective_date"),
        "record_date": ("record_date",),
        "payable_date": ("payable_date",),
        "process_date": ("process_date",),
    }.items():
        value = next((raw.get(name) for name in source_names if raw.get(name) is not None), None)
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("Corporate action date must be canonical text.")
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValueError("Corporate action date is malformed.") from exc
            if parsed.isoformat() != value:
                raise ValueError("Corporate action date is not canonical.")
        date_values[output_name] = value
    result = {
        "provider_event_id": action_id, "action_type": action_type,
        "symbol": symbol, "provider": PROVIDER,
        **date_values,
        "old_symbol": raw.get("old_symbol"),
        "new_symbol": raw.get("new_symbol"), "rate": raw.get("rate"),
        "cash": raw.get("cash"),
        "raw_provider_fingerprint": fingerprint(raw),
    }
    result["provenance_fingerprint"] = fingerprint(result)
    return result


def observational_coverage_evidence(
    state: Mapping[str, Any], population: Mapping[str, Any], *,
    calendar_fingerprint: str = FROZEN_CALENDAR_CONTENT_FINGERPRINT,
) -> dict[str, Any]:
    """Build derived bar coverage without mutating provider identity authority."""
    known_ids = {member["provider_asset_id"] for member in population["members"]}
    observed = state.get("observed_ranges", {})
    if not isinstance(observed, Mapping) or any(asset_id not in known_ids for asset_id in observed):
        raise RuntimeError("Observed coverage contains an unknown provider identity.")
    records: list[dict[str, Any]] = []
    for asset_id in sorted(known_ids):
        value = observed.get(asset_id)
        if value is None:
            first = last = None
        elif (
            not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise RuntimeError("Observed coverage range is malformed.")
        else:
            first, last = value
            try:
                first_at, last_at = datetime.fromisoformat(first), datetime.fromisoformat(last)
            except ValueError as exc:
                raise RuntimeError("Observed coverage timestamp is malformed.") from exc
            if (
                first_at.tzinfo is None or last_at.tzinfo is None
                or first_at > last_at
            ):
                raise RuntimeError("Observed coverage range is invalid.")
        records.append({
            "provider_asset_id": asset_id,
            "first_observed_bar": first,
            "last_observed_bar": last,
        })
    core = {
        "schema_version": OBSERVATIONAL_COVERAGE_SCHEMA_VERSION,
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "frozen_calendar_fingerprint": calendar_fingerprint,
        "records": records,
    }
    return {**core, "observational_coverage_fingerprint": fingerprint(core)}


def corporate_action_identity_resolution(
    records: Iterable[Mapping[str, Any]], population: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve provider events only through deterministic provider symbol facts."""
    by_symbol: dict[str, list[str]] = {}
    for member in population["members"]:
        by_symbol.setdefault(member["canonical_symbol"], []).append(
            member["provider_asset_id"]
        )
    resolutions: list[dict[str, Any]] = []
    excluded_ids: set[str] = set()
    for record in sorted(records, key=lambda item: str(item["provider_event_id"])):
        symbols = sorted({
            str(record.get(key) or "").strip().upper()
            for key in ("symbol", "old_symbol", "new_symbol")
            if str(record.get(key) or "").strip()
        })
        candidates = sorted({
            asset_id for symbol in symbols for asset_id in by_symbol.get(symbol, ())
        })
        unambiguous = {
            values[0] for symbol in symbols
            if len(values := by_symbol.get(symbol, ())) == 1
        }
        if len(unambiguous) == 1 and all(
            len(by_symbol.get(symbol, ())) <= 1 for symbol in symbols
        ):
            provider_asset_id = next(iter(unambiguous))
            outcome = "RESOLVED_PROVIDER_IDENTITY"
        else:
            provider_asset_id = None
            outcome = "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
            excluded_ids.update(candidates)
        core = {
            "schema_version": CORPORATE_ACTION_IDENTITY_RESOLUTION_SCHEMA_VERSION,
            "provider_event_id": record["provider_event_id"],
            "outcome": outcome,
            "provider_asset_id": provider_asset_id,
            "evidence_symbols": symbols,
            "excluded_provider_asset_ids": candidates if provider_asset_id is None else [],
            "bounded_dates": sorted({
                str(record.get(key)) for key in (
                    "announcement_or_observation_date", "ex_or_effective_date",
                    "record_date", "payable_date", "process_date",
                ) if record.get(key)
            }),
            "security_master_fingerprint": population["security_master_fingerprint"],
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "corporate_action_provenance_fingerprint": record["provenance_fingerprint"],
        }
        resolutions.append({**core, "resolution_fingerprint": fingerprint(core)})
    core = {
        "schema_version": CORPORATE_ACTION_IDENTITY_RESOLUTION_SCHEMA_VERSION,
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "records": resolutions,
        "resolved_count": sum(
            item["outcome"] == "RESOLVED_PROVIDER_IDENTITY" for item in resolutions
        ),
        "unresolved_count": sum(
            item["outcome"] == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
            for item in resolutions
        ),
        "excluded_provider_asset_ids": sorted(excluded_ids),
    }
    return {**core, "identity_resolution_fingerprint": fingerprint(core)}


class Acquisition:
    def __init__(self, root: Path = DEFAULT_ROOT, client: AlpacaHistoricalClient | None = None,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic,
                 capacity_probe: Callable[[datetime], Mapping[str, Any]] = coexistence_capacity):
        self.root = root.resolve()
        self.client = client or AlpacaHistoricalClient(RateGovernor())
        self.now = now
        self.sleep = sleep
        self.monotonic = monotonic
        self.capacity_probe = capacity_probe
        self.stop_requested = False
        self.request_count_base = 0
        self.retry_count_base = 0
        self.historical_calendar = load_frozen_historical_calendar()
        if self.historical_calendar.content_fingerprint != FROZEN_CALENDAR_CONTENT_FINGERPRINT:
            raise RuntimeError("Frozen historical calendar fingerprint is not governed.")
        self._provider_population_cache: dict[str, Any] | None = None
        self.state_path = self.root / "acquisition_state" / "state.json"
        self.state_checksum = self.state_path.with_suffix(".sha256")
        governor = getattr(self.client, "governor", None)
        if governor is not None and hasattr(governor, "sleep"):
            governor.sleep = self._cooperative_wait
        if hasattr(self.client, "wait"):
            self.client.wait = self._cooperative_wait

    def _calendar_preflight(self, requested: Mapping[str, str]) -> None:
        start = date.fromisoformat(str(requested["actual_first_requested_session"]))
        end = date.fromisoformat(str(requested["actual_last_completed_session"]))
        if start < self.historical_calendar.covered_start or end > self.historical_calendar.covered_end or start > end:
            raise RuntimeError("Requested acquisition range exceeds frozen historical calendar authority.")

    def _provider_population(self) -> dict[str, Any]:
        if self._provider_population_cache is None:
            population = load_provider_population(self.root)
            population_evidence = population["provider_population_evidence"]
            population_path = (
                self.root / "manifests" / "provider_populations"
                / f"{population['provider_population_fingerprint']}.json"
            )
            if population_path.exists():
                try:
                    if json.loads(population_path.read_text(encoding="utf-8")) != population_evidence:
                        raise RuntimeError("Content-addressed provider-population evidence conflicts.")
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Provider-population evidence is corrupt.") from exc
            else:
                atomic_json(population_path, population_evidence)
            exclusion = population["ambiguous_exclusion_set"]
            evidence_path = (
                self.root / "manifests" / "provider_population_exclusions"
                / f"{exclusion['exclusion_set_fingerprint']}.json"
            )
            if evidence_path.exists():
                try:
                    if json.loads(evidence_path.read_text(encoding="utf-8")) != exclusion:
                        raise RuntimeError("Content-addressed ambiguous exclusion evidence conflicts.")
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Ambiguous exclusion evidence is corrupt.") from exc
            else:
                atomic_json(evidence_path, exclusion)
            self._provider_population_cache = population
        return self._provider_population_cache

    def _cooperative_wait(self, seconds: float) -> None:
        remaining = max(0.0, float(seconds))
        while remaining > 0:
            if self.stop_requested:
                raise CooperativeStop("Historical acquisition stop requested.")
            interval = min(COOPERATIVE_WAIT_QUANTUM_SECONDS, remaining)
            self.sleep(interval)
            remaining -= interval
        if self.stop_requested:
            raise CooperativeStop("Historical acquisition stop requested.")

    def load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists() and not self.state_checksum.exists():
            return None
        return json.loads(read_checksummed_state(self.state_path, self.state_checksum, label="ML historical acquisition state"))

    def save_state(self, state: Mapping[str, Any]) -> None:
        encoded = json.dumps(state, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
        write_checksummed_state(self.state_path, self.state_checksum, encoded)

    def sync_provider_counts(self, state: dict[str, Any]) -> None:
        state["api_request_count"] = self.request_count_base + self.client.request_count
        state["retry_count"] = self.retry_count_base + self.client.retry_count
        last_success = getattr(self.client, "last_success_at_utc", None)
        if last_success:
            state["last_successful_request_at_utc"] = last_success
        successful = int(getattr(self.client, "successful_request_count", 0))
        latency_total = float(getattr(self.client, "request_latency_seconds_total", 0.0))
        state["provider_average_request_latency_seconds"] = latency_total / successful if successful else None
        state["provider_rate_limit"] = getattr(self.client, "rate_limit", None)
        state["provider_rate_limit_remaining"] = getattr(self.client, "rate_limit_remaining", None)
        state["provider_rate_limit_reset"] = getattr(self.client, "rate_limit_reset", None)

    def _state_defaults(self, state: dict[str, Any]) -> None:
        state.setdefault("transient_outage_count", 0)
        state.setdefault("transient_outage_seconds", 0.0)
        state.setdefault("provider_retry_count", state.get("retry_count", 0))
        state.setdefault("bad_symbol_failure_count", len(state.get("unqueryable_symbols", [])))
        state.setdefault("hard_failure_count", 0)
        state.setdefault("active_acquisition_seconds", 0.0)
        state.setdefault("active_measurement_rows_baseline", state.get("rows_15m", 0))
        state.setdefault("active_measurement_bytes_baseline", state.get("bytes_stored", 0))
        state.setdefault("outage_backoff_level", 0)
        state.setdefault("operating_mode", "OFF_MARKET")
        state.setdefault("historical_request_ceiling_per_minute", REQUESTS_PER_MINUTE)
        state.setdefault("historical_concurrency", 1)
        state.setdefault("live_session_yield_date", None)
        state.setdefault("live_session_latch_reason", None)
        state.setdefault("pending_finalizations", [])
        state.setdefault("last_historical_activity_at_utc", None)
        state.setdefault("attributable_live_degradation_count", 0)
        state.setdefault("coexistence_journal_events", 0)
        state.setdefault("request_rate_measurement_started_at_utc", self.now().isoformat())
        state.setdefault("request_rate_measurement_baseline", state.get("api_request_count", 0))
        state["morning_deadline"] = "REPLACED_BY_GUARDED_LIVE_COEXISTENCE"
        if state.get("live_session_yield_date") and not state.get("live_session_latch_reason"):
            state["live_session_yield_date"] = None

    def _journal_transition(self, state: dict[str, Any], previous: str | None,
                            new: str, reason: str | None,
                            assessment: Mapping[str, Any], attribution: str | None = None) -> None:
        signature = [new, reason, attribution]
        if state.get("last_coexistence_journal_signature") == signature:
            return
        path = self.root / "acquisition_state" / "coexistence_journal.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size >= COEXISTENCE_JOURNAL_MAX_BYTES:
            rotated = path.with_suffix(path.suffix + ".1")
            path.replace(rotated)
        record = {
            "timestamp_utc": self.now().isoformat(), "previous_mode": previous,
            "new_mode": new, "reason": reason,
            "last_historical_request_at_utc": state.get("last_historical_activity_at_utc"),
            "historical_request_rate": state.get("historical_request_ceiling_per_minute"),
            "current_partition": state.get("current_partition"),
            "pending_finalization_count": len(state.get("pending_finalizations", [])),
            "clean_v2_state": assessment.get("clean_v2_service_state"),
            "latest_decision_lag_seconds": assessment.get("clean_v2_latest_decision_lag_seconds"),
            "provider_limit": state.get("provider_rate_limit"),
            "provider_remaining": state.get("provider_rate_limit_remaining"),
            "available_memory_bytes": assessment.get("available_memory_bytes"),
            "load_1m": assessment.get("load_1m"), "io_pressure_avg10": assessment.get("io_pressure_avg10"),
            "attribution": attribution, "session_latch": state.get("live_session_latch_reason"),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush(); os.fsync(handle.fileno())
        state["last_coexistence_journal_signature"] = signature
        state["coexistence_journal_events"] = int(state.get("coexistence_journal_events", 0)) + 1

    def _historical_activity_recent(self, state: Mapping[str, Any], assessment: Mapping[str, Any]) -> bool:
        value = state.get("last_historical_activity_at_utc")
        if not value:
            return False
        try:
            event = datetime.fromisoformat(str(assessment.get("clean_v2_degradation_observed_at_utc") or self.now().isoformat()))
            age = (event - datetime.fromisoformat(str(value))).total_seconds()
        except ValueError:
            return False
        return 0 <= age <= LIVE_ATTRIBUTION_WINDOW_SECONDS

    def _set_mode(self, state: dict[str, Any], mode: str, reason: str | None,
                  assessment: Mapping[str, Any], attribution: str | None = None) -> None:
        previous = state.get("operating_mode")
        state["operating_mode"] = mode
        state["live_capacity_reason"] = reason
        self._journal_transition(state, previous, mode, reason, assessment, attribution)

    def _set_request_rate(self, requests_per_minute: int) -> None:
        governor = getattr(self.client, "governor", None)
        if governor is not None and hasattr(governor, "set_requests_per_minute"):
            governor.set_requests_per_minute(requests_per_minute)

    def _capacity_assessment(self, *, provider_request: bool) -> dict[str, Any]:
        assessment = dict(self.capacity_probe(self.now()))
        if (
            provider_request
            and assessment.get("mode") == "LIVE_COEXISTENCE"
            and int(getattr(self.client, "request_count", 0)) > 0
        ):
            remaining = getattr(self.client, "rate_limit_remaining", None)
            limit = getattr(self.client, "rate_limit", None)
            if remaining is None or limit is None:
                assessment.update({
                    "mode": "WAITING_FOR_LIVE_CAPACITY",
                    "reason": "PROVIDER_RATE_BUDGET_UNKNOWN",
                })
            elif remaining <= max(50, int(limit) // 2):
                assessment.update({
                    "mode": "WAITING_FOR_LIVE_CAPACITY",
                    "reason": "PROVIDER_CAPACITY_RESERVED_FOR_CLEAN_V2",
                })
        return assessment

    def _capacity_gate(self, state: dict[str, Any], item: Mapping[str, Any], *, finalization: bool = False) -> None:
        while True:
            assessment = self._capacity_assessment(provider_request=not finalization)
            market_date = self.now().astimezone(EASTERN).date().isoformat()
            if assessment.get("reason") == "PROVIDER_CAPACITY_RESERVED_FOR_CLEAN_V2":
                state["live_session_yield_date"] = market_date
                state["live_session_latch_reason"] = "ATTRIBUTABLE_PROVIDER_CAPACITY_EXHAUSTION"
            degradation = assessment.get("reason") in {"CLEAN_V2_DECISION_LATENCY", "CLEAN_V2_PROVIDER_NOT_HEALTHY"}
            attribution = None
            if degradation:
                if self._historical_activity_recent(state, assessment):
                    attribution = "ATTRIBUTABLE_RECENT_HISTORICAL_ACTIVITY"
                    state["attributable_live_degradation_count"] = int(state.get("attributable_live_degradation_count", 0)) + 1
                    if state["attributable_live_degradation_count"] >= 2:
                        state["live_session_yield_date"] = market_date
                        state["live_session_latch_reason"] = "REPRODUCIBLE_ATTRIBUTABLE_LIVE_DEGRADATION"
                else:
                    attribution = "LIVE_DEGRADATION_NOT_ATTRIBUTABLE_TO_HISTORICAL"
                    assessment.update({"mode": "LIVE_COEXISTENCE", "reason": "LIVE_DEGRADATION_NOT_ATTRIBUTABLE_TO_HISTORICAL"})
            if state.get("live_session_yield_date") == market_date and state.get("live_session_latch_reason") and assessment.get("mode") != "OFF_MARKET":
                assessment.update({"mode": "WAITING_FOR_LIVE_CAPACITY", "reason": "LIVE_SESSION_SAFETY_LATCH"})
            mode = str(assessment.get("mode", "WAITING_FOR_LIVE_CAPACITY"))
            state["live_qpx_detected_active"] = bool(assessment.get("live_qpx_active"))
            state["clean_v2_service_state"] = assessment.get("clean_v2_service_state")
            self._set_mode(state, mode, assessment.get("reason"), assessment, attribution)
            state["current_partition"] = f"year={item.get('year')}/batch={int(item.get('batch', 0)):05d}"
            if mode == "OFF_MARKET":
                self._set_request_rate(REQUESTS_PER_MINUTE)
                state["historical_request_ceiling_per_minute"] = REQUESTS_PER_MINUTE
                state["live_session_yield_date"] = None
                state["live_session_latch_reason"] = None
                state["attributable_live_degradation_count"] = 0
                state["status"] = "RUNNING"; state["next_retry_at_utc"] = None
                self.save_state(state)
                return
            if mode == "LIVE_COEXISTENCE":
                self._set_request_rate(LIVE_REQUESTS_PER_MINUTE)
                state["historical_request_ceiling_per_minute"] = LIVE_REQUESTS_PER_MINUTE
                state["status"] = "RUNNING"; state["next_retry_at_utc"] = None
                self.save_state(state)
                return
            state["status"] = "WAITING_FOR_LIVE_CAPACITY"
            state["live_capacity_recheck_seconds"] = LIVE_CAPACITY_RECHECK_SECONDS
            state["next_retry_at_utc"] = (self.now() + timedelta(seconds=LIVE_CAPACITY_RECHECK_SECONDS)).isoformat()
            self.save_state(state)
            self._cooperative_wait(LIVE_CAPACITY_RECHECK_SECONDS)

    def _seconds_until_deadline(self) -> float:
        local = self.now().astimezone(EASTERN)
        boundary_date = local.date() + timedelta(days=1) if local.time().replace(tzinfo=None) >= wall_time(16, 30) else local.date()
        boundary = datetime.combine(boundary_date, MORNING_DEADLINE, tzinfo=EASTERN)
        return max(0.0, (boundary - local).total_seconds())

    def _wait_for_network(self, state: dict[str, Any], item: Mapping[str, Any], exc: ProviderError) -> bool:
        self._state_defaults(state)
        now = self.now()
        if not state.get("outage_started_at_utc"):
            state["outage_started_at_utc"] = now.isoformat()
            state["transient_outage_count"] += 1
            state["outage_backoff_level"] = 0
        level = min(int(state["outage_backoff_level"]), len(OUTAGE_BACKOFF_SECONDS) - 1)
        if self.stop_requested:
            state["status"] = "STOPPED_FOR_MARKET_WINDOW"
            state["stop_reason"] = "SIGNAL"
            self.save_state(state)
            return False
        delay = OUTAGE_BACKOFF_SECONDS[level]
        state.update({
            "status": "WAITING_FOR_NETWORK", "stop_reason": None,
            "transient_failure_type": exc.failure_class, "transient_failure_message": str(exc)[:1000],
            "network_retry_attempt_count": int(state.get("network_retry_attempt_count", 0)) + 1,
            "outage_backoff_level": min(level + 1, len(OUTAGE_BACKOFF_SECONDS) - 1),
            "next_retry_at_utc": (now + timedelta(seconds=delay)).isoformat(),
            "current_partition": f"year={item['year']}/batch={int(item['batch']):05d}",
        })
        self.sync_provider_counts(state)
        state["provider_retry_count"] = state["retry_count"]
        self.save_state(state)
        self._cooperative_wait(delay)
        state["transient_outage_seconds"] += delay
        if self.stop_requested:
            state["status"] = "STOPPED_FOR_MARKET_WINDOW"
            state["stop_reason"] = "SIGNAL"
            state["next_retry_at_utc"] = None
            self.save_state(state)
            return False
        state["status"] = "RUNNING"
        state["next_retry_at_utc"] = None
        self.save_state(state)
        return True

    def disk_gate(self) -> int:
        free = shutil.disk_usage(self.root.parent if self.root.parent.exists() else ROOT).free
        if free < MIN_FREE_BYTES:
            raise RuntimeError(f"Disk safety gate failed: {free} free bytes is below {MIN_FREE_BYTES}.")
        return free

    def initialize(self) -> dict[str, Any]:
        if self.root == QUALIFIED_FROZEN_ROOT.resolve() or QUALIFIED_FROZEN_ROOT.resolve() in self.root.parents:
            raise RuntimeError("ML reservoir may not overlap the qualified frozen dataset.")
        free = self.disk_gate()
        acquired = self.now()
        requested = calculate_range(acquired)
        self._calendar_preflight(requested)
        active = self.client.assets("active")
        inactive = self.client.assets("inactive")
        master = build_security_master(active, inactive, acquired)
        if not master or not any(not item["active"] for item in master):
            raise RuntimeError("Survivorship gate failed: inactive provider assets were not recovered.")
        master_payload = {"schema_version": SCHEMA_VERSION, "provider": PROVIDER, "assets": master}
        master_payload["manifest_fingerprint"] = fingerprint(master_payload)
        master_path = self.root / "security_master" / "alpaca_us_equity_assets.json.gz"
        atomic_bytes(master_path, gzip.compress(json.dumps(master_payload, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
        atomic_json(master_path.with_suffix(master_path.suffix + ".manifest.json"), {"sha256": sha256_path(master_path), "security_count": len(master), "active_count": sum(i["active"] for i in master), "inactive_count": sum(not i["active"] for i in master), "provenance_fingerprint": master_payload["manifest_fingerprint"]})
        self._provider_population_cache = None
        years = list(range(date.fromisoformat(requested["actual_first_requested_session"]).year, date.fromisoformat(requested["actual_last_completed_session"]).year + 1))
        batches = [master[index:index + BATCH_SIZE] for index in range(0, len(master), BATCH_SIZE)]
        partitions = []
        for year in years:
            start, end = self._partition_bounds(year, requested)
            for index, batch in enumerate(batches):
                symbols = [item["canonical_current_symbol"] for item in batch]
                asset_ids = [item["provider_asset_id"] for item in batch]
                descriptor = batch_descriptor(year=year, start=start, end=end, symbols=symbols, asset_ids=asset_ids)
                partitions.append({"year": year, "batch": index, "symbols": symbols, "asset_ids": asset_ids, "batch_fingerprint": descriptor["batch_fingerprint"]})
        state = {
            "schema_version": SCHEMA_VERSION, "status": "PARTIAL", "stage": "BARS_15M",
            "requested_range": requested, "provider": PROVIDER, "feed": FEED,
            "adjustment": ADJUSTMENT, "canonical_resolution": TIMEFRAME,
            "security_count": len(master), "active_count": sum(i["active"] for i in master),
            "inactive_count": sum(not i["active"] for i in master), "partitions_total": len(partitions),
            "partitions_complete": 0, "rows_15m": 0, "bytes_stored": sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file()),
            "api_request_count": self.client.request_count, "retry_count": self.client.retry_count,
            "failure_count": 0, "current_partition": None, "completed": [],
            "transient_outage_count": 0, "transient_outage_seconds": 0.0,
            "provider_retry_count": self.client.retry_count, "bad_symbol_failure_count": 0,
            "hard_failure_count": 0, "active_acquisition_seconds": 0.0,
            "active_measurement_rows_baseline": 0, "active_measurement_bytes_baseline": 0,
            "outage_backoff_level": 0, "outage_started_at_utc": None,
            "last_successful_request_at_utc": getattr(self.client, "last_success_at_utc", None),
            "observed_ranges": {},
            "unqueryable_symbols": [],
            "partitions": partitions, "checkpoint_at_utc": acquired.isoformat(),
            "started_at_utc": acquired.isoformat(), "morning_deadline": "08:45 America/New_York",
            "survivorship_status": "ACTIVE_AND_INACTIVE_PROVIDER_ASSETS_RECOVERED",
            "training_eligibility": "ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE",
            "corporate_action_status": "PENDING", "estimate": initial_estimate(len(master), requested, free),
            "limitations": ["Provider assets omit authoritative listing/delisting dates; first/last observed bars are observational only.", "Historical observation symbols are limited to provider-returned/request symbols plus authoritative name-change actions."],
        }
        atomic_json(self.root / "manifests" / "dataset_plan.json", {k: state[k] for k in ("schema_version", "requested_range", "provider", "feed", "adjustment", "canonical_resolution", "security_count", "active_count", "inactive_count", "partitions_total", "estimate", "limitations")})
        self.save_state(state)
        return state

    def _deadline_reached(self) -> bool:
        return False

    def _partition_bounds(self, year: int, requested: Mapping[str, str]) -> tuple[date, date]:
        return max(date(year, 1, 1), date.fromisoformat(requested["actual_first_requested_session"])), min(date(year, 12, 31), date.fromisoformat(requested["actual_last_completed_session"]))

    def _quarantine_partial(self, page_root: Path, reason: str, evidence: Mapping[str, Any]) -> None:
        if not page_root.exists():
            return
        quarantine_root = self.root / "acquisition_state" / "rebuild_evidence"
        quarantine_root.mkdir(parents=True, exist_ok=True)
        suffix = fingerprint({"reason": reason, "evidence": evidence, "observed_at": self.now().isoformat()})[:16]
        destination = quarantine_root / f"{page_root.parent.name}-{page_root.name}-{suffix}"
        page_root.rename(destination)
        atomic_json(destination / "rebuild_reason.json", {"reason": reason, "evidence": dict(evidence), "recorded_at_utc": self.now().isoformat(), "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION})

    def _partition_context(self, state: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
        self._calendar_preflight(state["requested_range"])
        year = int(item["year"])
        start, end = self._partition_bounds(year, state["requested_range"])
        population = self._provider_population()
        disposition = partition_population_disposition(
            item, population, state.get("unqueryable_symbols", ()),
        )
        descriptor = batch_descriptor(
            year=year, start=start, end=end,
            symbols=item["symbols"], asset_ids=item["asset_ids"],
        )
        request_core = {
            "symbols": ",".join(value["canonical_symbol"] for value in disposition["requested_members"]),
            "timeframe": TIMEFRAME,
            "start": start.isoformat() + "T00:00:00Z",
            "end": (end + timedelta(days=1)).isoformat() + "T00:00:00Z",
            "limit": str(PAGE_LIMIT), "feed": FEED,
            "adjustment": ADJUSTMENT, "sort": "asc",
        }
        return {
            "year": year, "batch": int(item["batch"]), "start": start, "end": end,
            "descriptor": descriptor, "request_core": request_core,
            "request_fingerprint": request_identity(request_core, descriptor["batch_fingerprint"]),
            "population": population, "disposition": disposition,
        }

    @staticmethod
    def _page_aggregate(page_root: Path, page_count: int) -> dict[str, Any]:
        counts = {category: 0 for category in REJECTION_CATEGORIES}
        source = accepted = rejected = 0
        evidence_fingerprints: list[str] = []
        for page in range(1, page_count + 1):
            fragment = page_root / f"page-{page:06d}.csv.gz"
            manifest = json.loads(fragment.with_suffix(fragment.suffix + ".manifest.json").read_text())
            source += int(manifest["source_row_count"])
            accepted += int(manifest["accepted_row_count"])
            rejected += int(manifest["rejected_row_count"])
            for category in REJECTION_CATEGORIES:
                counts[category] += int(manifest["rejection_counts_by_category"][category])
            evidence_fingerprints.append(manifest["page_evidence_fingerprint"])
        return {
            "source_row_count": source, "accepted_row_count": accepted,
            "rejected_row_count": rejected, "rejection_counts_by_category": counts,
            "page_evidence_fingerprints": evidence_fingerprints,
        }

    def _validated_resume(
        self, page_root: Path, *, expected_request_fingerprint: str,
        expected_batch_fingerprint: str, descriptor: Mapping[str, Any],
        provider_population_fingerprint: str,
        population_disposition_fingerprint: str,
        exclusion_set_fingerprint: str,
    ) -> tuple[int, str | None]:
        checkpoint = page_root / "checkpoint.json"
        fragments = sorted(page_root.glob("page-*.csv.gz")) if page_root.exists() else []
        if not checkpoint.exists():
            if fragments:
                self._quarantine_partial(page_root, "FRAGMENTS_WITHOUT_CHECKPOINT", descriptor)
            return 0, None
        try:
            saved = json.loads(checkpoint.read_text())
        except Exception as exc:
            self._quarantine_partial(page_root, "UNREADABLE_CHECKPOINT_REBUILD", {"error_type": type(exc).__name__, **descriptor})
            return 0, None
        if saved.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            self._quarantine_partial(page_root, "LEGACY_CHECKPOINT_SCHEMA_REBUILD", {"legacy_keys": sorted(saved), **descriptor})
            return 0, None
        claimed_checkpoint_fingerprint = saved.get("checkpoint_fingerprint")
        checkpoint_core = {key: value for key, value in saved.items() if key != "checkpoint_fingerprint"}
        if claimed_checkpoint_fingerprint != fingerprint(checkpoint_core):
            self._quarantine_partial(page_root, "CHECKPOINT_INTEGRITY_FAILURE", descriptor)
            return 0, None
        checks = {
            "request_fingerprint": expected_request_fingerprint,
            "batch_fingerprint": expected_batch_fingerprint,
            "year": descriptor["year"], "requested_start": descriptor["requested_start"],
            "requested_end": descriptor["requested_end"],
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
            "frozen_calendar_fingerprint": FROZEN_CALENDAR_CONTENT_FINGERPRINT,
            "provider_population_fingerprint": provider_population_fingerprint,
            "population_disposition_fingerprint": population_disposition_fingerprint,
            "exclusion_set_fingerprint": exclusion_set_fingerprint,
        }
        if any(saved.get(key) != value for key, value in checks.items()):
            self._quarantine_partial(page_root, "CHECKPOINT_IDENTITY_MISMATCH", {"expected": checks, "observed": {key: saved.get(key) for key in checks}})
            return 0, None
        page = int(saved.get("page", 0))
        expected_names = [f"page-{number:06d}.csv.gz" for number in range(1, page + 1)]
        if [path.name for path in fragments] != expected_names:
            self._quarantine_partial(page_root, "PAGE_SEQUENCE_MISMATCH", {"expected": expected_names, "observed": [path.name for path in fragments]})
            return 0, None
        expected_rejections = [f"page-{number:06d}.rejections.jsonl.gz" for number in range(1, page + 1)]
        observed_rejections = sorted(path.name for path in page_root.glob("page-*.rejections.jsonl.gz"))
        if observed_rejections != expected_rejections:
            self._quarantine_partial(page_root, "REJECTION_EVIDENCE_SEQUENCE_MISMATCH", {"expected": expected_rejections, "observed": observed_rejections})
            return 0, None
        for number, fragment in enumerate(fragments, start=1):
            manifest_path = fragment.with_suffix(fragment.suffix + ".manifest.json")
            rejection_path = page_root / f"page-{number:06d}.rejections.jsonl.gz"
            try:
                evidence = json.loads(manifest_path.read_text())
                rows = read_gzip_csv(fragment)
                rejections = read_gzip_jsonl(rejection_path)
                rejection_identities = [
                    (record.get("page"), record.get("source_row_ordinal"))
                    for record in rejections
                ]
                rejection_valid = all(
                    record.get("schema_version") == REJECTION_EVIDENCE_SCHEMA_VERSION
                    and record.get("acquisition_provenance_version") == ACQUISITION_PROVENANCE_VERSION
                    and record.get("page") == number
                    and record.get("request_fingerprint") == expected_request_fingerprint
                    and record.get("batch_fingerprint") == expected_batch_fingerprint
                    and record.get("frozen_calendar_fingerprint") == FROZEN_CALENDAR_CONTENT_FINGERPRINT
                    and record.get("rejection_category") in REJECTION_CATEGORIES
                    and record.get("rejection_fingerprint") == fingerprint({key: value for key, value in record.items() if key != "rejection_fingerprint"})
                    for record in rejections
                ) and len(rejection_identities) == len(set(rejection_identities))
                valid = (
                    rejection_valid
                    and all(type(evidence.get(key)) is int for key in ("source_row_count", "accepted_row_count", "rejected_row_count"))
                    and len(rejections) == int(evidence["rejected_row_count"])
                    and evidence == page_evidence(
                        fragment, rejection_path, page=number,
                        source_row_count=int(evidence["source_row_count"]),
                        accepted_row_count=len(rows), rejected_row_count=len(rejections),
                        rejection_counts_by_category=evidence["rejection_counts_by_category"],
                        request_fingerprint=expected_request_fingerprint,
                        batch_fingerprint=expected_batch_fingerprint,
                        calendar_fingerprint=FROZEN_CALENDAR_CONTENT_FINGERPRINT,
                        provider_population_fingerprint=provider_population_fingerprint,
                        population_disposition_fingerprint=population_disposition_fingerprint,
                        exclusion_set_fingerprint=exclusion_set_fingerprint,
                    )
                    and all(row.get("request_fingerprint") == expected_request_fingerprint for row in rows)
                )
            except Exception:
                valid = False
            if not valid:
                self._quarantine_partial(page_root, "PAGE_FRAGMENT_INTEGRITY_FAILURE", {"page": number, **descriptor})
                return 0, None
        try:
            aggregate = self._page_aggregate(page_root, page)
        except Exception:
            self._quarantine_partial(page_root, "PAGE_AGGREGATE_INTEGRITY_FAILURE", descriptor)
            return 0, None
        for key in ("source_row_count", "accepted_row_count", "rejected_row_count", "rejection_counts_by_category", "page_evidence_fingerprints"):
            if saved.get(key) != aggregate[key]:
                self._quarantine_partial(page_root, "CHECKPOINT_PAGE_AGGREGATE_MISMATCH", {"field": key, **descriptor})
                return 0, None
        return page, saved.get("next_page_token")

    def _validate_committed_v3_partition(
        self, context: Mapping[str, Any],
        destination: Path, manifest_path: Path,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        part_id = f"year={context['year']}/batch={context['batch']:05d}"
        rejection_path = (
            self.root / "rejection_evidence" / f"year={context['year']}"
            / f"batch={context['batch']:05d}.rejections.jsonl.gz"
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            accepted = read_gzip_csv(destination)
            rejections = read_gzip_jsonl(rejection_path)
        except (OSError, EOFError, UnicodeDecodeError, gzip.BadGzipFile, csv.Error, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Committed V3 final evidence is missing or corrupt for {part_id}.") from exc

        descriptor = context["descriptor"]
        population = context["population"]
        disposition = context["disposition"]
        expected_identity = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
            "partition": part_id,
            "year": context["year"],
            "batch": context["batch"],
            "requested_start": context["start"].isoformat(),
            "requested_end": context["end"].isoformat(),
            "batch_fingerprint": descriptor["batch_fingerprint"],
            "request_fingerprint": context["request_fingerprint"],
            "frozen_calendar_fingerprint": FROZEN_CALENDAR_CONTENT_FINGERPRINT,
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "security_master_fingerprint": population["security_master_fingerprint"],
            "population_disposition_fingerprint": disposition["population_disposition_fingerprint"],
            "exclusion_set_fingerprint": disposition["exclusion_set_fingerprint"],
            "ambiguous_exclusion_set_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError(f"Committed V3 final evidence identity mismatch for {part_id}.")
        if manifest.get("population_disposition") != disposition:
            raise RuntimeError(f"Committed V3 population disposition mismatch for {part_id}.")
        if manifest.get("actual_request_members") != disposition["requested_members"]:
            raise RuntimeError(f"Committed V3 request membership mismatch for {part_id}.")
        manifest_core = {
            key: value for key, value in manifest.items()
            if key not in {"manifest_fingerprint", "completed_at_utc"}
        }
        if manifest.get("manifest_fingerprint") != fingerprint(manifest_core):
            raise RuntimeError(f"Committed V3 manifest fingerprint mismatch for {part_id}.")
        accepted_sha = sha256_path(destination)
        if manifest.get("accepted_partition_sha256") != accepted_sha or manifest.get("sha256") != accepted_sha:
            raise RuntimeError(f"Committed V3 accepted-partition checksum mismatch for {part_id}.")
        rejection_sha = sha256_path(rejection_path)
        if manifest.get("rejection_evidence_sha256") != rejection_sha:
            raise RuntimeError(f"Committed V3 rejection-evidence checksum mismatch for {part_id}.")
        if manifest.get("rejection_evidence_fingerprint") != fingerprint(rejections):
            raise RuntimeError(f"Committed V3 rejection-evidence fingerprint mismatch for {part_id}.")

        count_fields = ("source_row_count", "accepted_row_count", "rejected_row_count", "row_count")
        if any(type(manifest.get(key)) is not int or manifest[key] < 0 for key in count_fields):
            raise RuntimeError(f"Committed V3 row counts are malformed for {part_id}.")
        if manifest["source_row_count"] != manifest["accepted_row_count"] + manifest["rejected_row_count"]:
            raise RuntimeError(f"Committed V3 source-row reconciliation failed for {part_id}.")
        if manifest["row_count"] != manifest["accepted_row_count"] or len(accepted) != manifest["accepted_row_count"]:
            raise RuntimeError(f"Committed V3 accepted-row reconciliation failed for {part_id}.")
        rejection_counts = manifest.get("rejection_counts_by_category")
        if not isinstance(rejection_counts, dict) or set(rejection_counts) != set(REJECTION_CATEGORIES):
            raise RuntimeError(f"Committed V3 rejection categories are malformed for {part_id}.")
        if any(type(value) is not int or value < 0 for value in rejection_counts.values()):
            raise RuntimeError(f"Committed V3 rejection counts are malformed for {part_id}.")
        if sum(rejection_counts.values()) != manifest["rejected_row_count"] or len(rejections) != manifest["rejected_row_count"]:
            raise RuntimeError(f"Committed V3 rejected-row reconciliation failed for {part_id}.")
        observed_rejection_counts = {category: 0 for category in REJECTION_CATEGORIES}
        rejection_keys: set[tuple[Any, Any]] = set()
        for record in rejections:
            core = {key: value for key, value in record.items() if key != "rejection_fingerprint"}
            category = record.get("rejection_category")
            rejection_key = (record.get("page"), record.get("source_row_ordinal"))
            if (
                record.get("schema_version") != REJECTION_EVIDENCE_SCHEMA_VERSION
                or record.get("acquisition_provenance_version") != ACQUISITION_PROVENANCE_VERSION
                or record.get("request_fingerprint") != context["request_fingerprint"]
                or record.get("batch_fingerprint") != descriptor["batch_fingerprint"]
                or record.get("frozen_calendar_fingerprint") != FROZEN_CALENDAR_CONTENT_FINGERPRINT
                or category not in REJECTION_CATEGORIES
                or record.get("rejection_fingerprint") != fingerprint(core)
                or rejection_key in rejection_keys
            ):
                raise RuntimeError(f"Committed V3 rejection record is invalid for {part_id}.")
            rejection_keys.add(rejection_key)
            observed_rejection_counts[category] += 1
        if observed_rejection_counts != rejection_counts:
            raise RuntimeError(f"Committed V3 rejection-category evidence mismatch for {part_id}.")

        expected_members = {
            member["provider_asset_id"]: member["canonical_symbol"]
            for member in disposition["requested_members"]
        }
        accepted_keys: set[tuple[str, str]] = set()
        for row in accepted:
            key = (row.get("provider_asset_id", ""), row.get("market_timestamp", ""))
            if (
                key in accepted_keys
                or row.get("request_fingerprint") != context["request_fingerprint"]
                or expected_members.get(row.get("provider_asset_id")) != row.get("observation_symbol")
            ):
                raise RuntimeError(f"Committed V3 accepted-row identity is invalid for {part_id}.")
            accepted_keys.add(key)
        return manifest, accepted

    def _clean_redundant_transient_pages(self, context: Mapping[str, Any]) -> None:
        page_root = (
            self.root / "acquisition_state" / "pages" / f"year={context['year']}"
            / f"batch={context['batch']:05d}"
        )
        if not page_root.exists():
            return
        for path in page_root.iterdir():
            if not path.is_file():
                raise RuntimeError("Unexpected non-file in redundant V3 transient evidence.")
        for path in page_root.iterdir():
            path.unlink()
        page_root.rmdir()

    def _recover_committed_v3_state(
        self, state: dict[str, Any], part_id: str, accepted: Iterable[Mapping[str, str]],
    ) -> None:
        if part_id in state["completed"]:
            return
        rows = list(accepted)
        state["completed"].append(part_id)
        state["rows_15m"] = int(state.get("rows_15m", 0)) + len(rows)
        state["partitions_complete"] = len(state["completed"])
        state["bytes_stored"] = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        observed_ranges = state.setdefault("observed_ranges", {})
        for row in rows:
            timestamp = row["market_timestamp"]
            observed = observed_ranges.setdefault(row["provider_asset_id"], [timestamp, timestamp])
            observed[0] = min(observed[0], timestamp)
            observed[1] = max(observed[1], timestamp)

    def _recover_existing_final_partition(
        self, state: dict[str, Any], item: Mapping[str, Any],
    ) -> bool:
        year, batch = int(item["year"]), int(item["batch"])
        part_id = f"year={year}/batch={batch:05d}"
        destination = self.root / "bars_15m" / f"year={year}" / f"batch={batch:05d}.csv.gz"
        manifest_path = destination.with_suffix(destination.suffix + ".manifest.json")
        if not destination.exists() and not manifest_path.exists():
            return False
        if not destination.exists() or not manifest_path.exists():
            raise RuntimeError(f"Incomplete committed partition evidence for {part_id}; refusing provider overwrite.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unreadable committed partition manifest for {part_id}.") from exc
        is_v3 = (
            manifest.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
            and manifest.get("acquisition_provenance_version") == ACQUISITION_PROVENANCE_VERSION
        )
        if not is_v3:
            if part_id in state["completed"] and manifest.get("schema_version") in {1, 2}:
                if manifest.get("sha256") != sha256_path(destination):
                    raise RuntimeError(f"Legacy finalized partition checksum mismatch for {part_id}.")
                return True
            raise RuntimeError(f"Legacy finalized partition is absent from completed state for {part_id}; refusing implicit adoption.")
        context = self._partition_context(state, item)
        manifest, accepted = self._validate_committed_v3_partition(
            context, destination, manifest_path,
        )
        self._clean_redundant_transient_pages(context)
        recovery_required = part_id not in state["completed"]
        self._recover_committed_v3_state(state, part_id, accepted)
        if recovery_required:
            state["last_partition_recovery"] = {
                "reason": "FINAL_EVIDENCE_COMMITTED_STATE_RECOVERY",
                "partition": part_id,
                "manifest_fingerprint": manifest["manifest_fingerprint"],
            }
        return True

    def _finalize_downloaded_partition(self, state: dict[str, Any], item: Mapping[str, Any]) -> None:
        if self._recover_existing_final_partition(state, item):
            return
        context = self._partition_context(state, item)
        year, batch = context["year"], context["batch"]
        start, end = context["start"], context["end"]
        descriptor = context["descriptor"]
        request_fp = context["request_fingerprint"]
        population = context["population"]
        disposition = context["disposition"]
        part_id = f"year={year}/batch={batch:05d}"
        page_root = self.root / "acquisition_state" / "pages" / f"year={year}" / f"batch={batch:05d}"
        requested_count = len(disposition["requested_members"])
        if requested_count:
            page, token = self._validated_resume(
                page_root, expected_request_fingerprint=request_fp,
                expected_batch_fingerprint=descriptor["batch_fingerprint"], descriptor=descriptor,
                provider_population_fingerprint=population["provider_population_fingerprint"],
                population_disposition_fingerprint=disposition["population_disposition_fingerprint"],
                exclusion_set_fingerprint=disposition["exclusion_set_fingerprint"],
            )
        else:
            page, token = 0, None
        if (requested_count and page < 1) or token is not None:
            raise RuntimeError(f"Pending partition is not download-complete: {part_id}.")
        combined: dict[tuple[str, str], dict[str, str]] = {}
        combined_rejections: list[dict[str, Any]] = []
        for page_path in sorted(page_root.glob("page-*.csv.gz")):
            for row in read_gzip_csv(page_path):
                key = (row["provider_asset_id"], row["market_timestamp"])
                if key in combined: raise RuntimeError(f"Duplicate provider identity/timestamp in {part_id}.")
                combined[key] = row
            page_number = int(page_path.name.removeprefix("page-").removesuffix(".csv.gz"))
            combined_rejections.extend(read_gzip_jsonl(page_root / f"page-{page_number:06d}.rejections.jsonl.gz"))
        ordered = [combined[key] for key in sorted(combined)]
        aggregate = self._page_aggregate(page_root, page) if page else {
            "source_row_count": 0, "accepted_row_count": 0, "rejected_row_count": 0,
            "rejection_counts_by_category": {category: 0 for category in REJECTION_CATEGORIES},
            "page_evidence_fingerprints": [],
        }
        if aggregate["accepted_row_count"] != len(ordered) or aggregate["rejected_row_count"] != len(combined_rejections):
            raise RuntimeError(f"Partition row reconciliation failed for {part_id}.")
        destination = self.root / "bars_15m" / f"year={year}" / f"batch={batch:05d}.csv.gz"
        manifest = destination.with_suffix(destination.suffix + ".manifest.json")
        rejection_destination = self.root / "rejection_evidence" / f"year={year}" / f"batch={batch:05d}.rejections.jsonl.gz"
        self.disk_gate()
        atomic_bytes(destination, encode_gzip_csv(ordered, BAR_COLUMNS))
        atomic_bytes(rejection_destination, encode_gzip_jsonl(combined_rejections))
        sessions = sorted({row["session_date"] for row in ordered})
        partition_manifest = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "rejection_evidence_schema_version": REJECTION_EVIDENCE_SCHEMA_VERSION,
            "provider_population_exclusion_schema_version": PROVIDER_POPULATION_EXCLUSION_SCHEMA_VERSION,
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
            "partition": part_id, "year": year, "batch": batch,
            "original_state_batch_fingerprint": item.get("batch_fingerprint"),
            "batch_fingerprint": descriptor["batch_fingerprint"],
            "ordered_provider_asset_ids": [member["provider_asset_id"] for member in descriptor["members"]],
            "ordered_symbol_mapping": descriptor["members"],
            "requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "provider": PROVIDER, "feed": FEED, "adjustment": ADJUSTMENT, "timeframe": TIMEFRAME,
            "request_fingerprint": request_fp,
            "actual_request_members": disposition["requested_members"],
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "security_master_fingerprint": population["security_master_fingerprint"],
            "ambiguous_exclusion_set_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
            "population_disposition": disposition,
            "population_disposition_fingerprint": disposition["population_disposition_fingerprint"],
            "exclusion_set_fingerprint": disposition["exclusion_set_fingerprint"],
            "frozen_calendar_fingerprint": FROZEN_CALENDAR_CONTENT_FINGERPRINT,
            "requested_security_count": requested_count,
            "security_count": len({row["provider_asset_id"] for row in ordered}),
            "row_count": len(ordered), **aggregate,
            "accepted_partition_sha256": sha256_path(destination),
            "sha256": sha256_path(destination),
            "rejection_evidence_sha256": sha256_path(rejection_destination),
            "rejection_evidence_fingerprint": fingerprint(combined_rejections),
            "actual_first_observation": min((row["market_timestamp"] for row in ordered), default=None),
            "actual_last_observation": max((row["market_timestamp"] for row in ordered), default=None),
            "first_observed_bar": min((row["market_timestamp"] for row in ordered), default=None),
            "last_observed_bar": max((row["market_timestamp"] for row in ordered), default=None),
            "first_session": sessions[0] if sessions else None,
            "last_session": sessions[-1] if sessions else None,
            "page_count": page, "synthetic_bars": False, "forward_fill": False,
            "timestamp_substitution": False, "completed_at_utc": self.now().isoformat(),
        }
        partition_manifest["manifest_fingerprint"] = fingerprint({
            key: value for key, value in partition_manifest.items()
            if key != "completed_at_utc"
        })
        atomic_json(manifest, partition_manifest)
        _validated_manifest, validated_rows = self._validate_committed_v3_partition(
            context, destination, manifest,
        )
        self._clean_redundant_transient_pages(context)
        self._recover_committed_v3_state(state, part_id, validated_rows)

    def _enqueue_pending_finalization(self, state: dict[str, Any], item: Mapping[str, Any],
                                      descriptor: Mapping[str, Any], request_fp: str, page: int) -> None:
        part_id = f"year={int(item['year'])}/batch={int(item['batch']):05d}"
        pending = state.setdefault("pending_finalizations", [])
        if not any(entry["partition"] == part_id for entry in pending):
            pending.append({"partition": part_id, "year": int(item["year"]), "batch": int(item["batch"]),
                            "batch_fingerprint": descriptor["batch_fingerprint"],
                            "request_fingerprint": request_fp, "page_count": page,
                            "download_completed_at_utc": self.now().isoformat()})
        state["status"] = "DOWNLOAD_COMPLETE_FINALIZATION_PENDING"
        self._set_mode(state, "DOWNLOAD_COMPLETE_FINALIZATION_PENDING", "FINALIZATION_CAPACITY_DEFERRED", {}, None)
        self.save_state(state)

    def _drain_pending_finalizations(self, state: dict[str, Any]) -> None:
        pending = state.setdefault("pending_finalizations", [])
        while pending:
            entry = pending[0]
            item = next((value for value in state["partitions"] if int(value["year"]) == int(entry["year"]) and int(value["batch"]) == int(entry["batch"])), None)
            if item is None:
                raise RuntimeError(f"Pending finalization has no partition definition: {entry['partition']}.")
            self._capacity_gate(state, item, finalization=True)
            self._finalize_downloaded_partition(state, item)
            pending.pop(0)
            self.save_state(state)

    def _pending_capacity_gate(self, state: dict[str, Any]) -> None:
        while len(state.setdefault("pending_finalizations", [])) >= MAX_PENDING_FINALIZATIONS:
            self._drain_pending_finalizations(state)

    def acquire_partition(self, state: dict[str, Any], item: Mapping[str, Any]) -> None:
        year, batch = int(item["year"]), int(item["batch"])
        part_id = f"year={year}/batch={batch:05d}"
        if self._recover_existing_final_partition(state, item):
            return
        context = self._partition_context(state, item)
        start, end = context["start"], context["end"]
        descriptor = context["descriptor"]
        population = context["population"]
        disposition = context["disposition"]
        request_core = context["request_core"]
        request_fp = context["request_fingerprint"]
        identity = {
            member["canonical_symbol"]: member["provider_asset_id"]
            for member in disposition["requested_members"]
        }
        symbols = list(identity)
        page_root = self.root / "acquisition_state" / "pages" / f"year={year}" / f"batch={batch:05d}"
        checkpoint = page_root / "checkpoint.json"
        page, token = self._validated_resume(
            page_root, expected_request_fingerprint=request_fp,
            expected_batch_fingerprint=descriptor["batch_fingerprint"], descriptor=descriptor,
            provider_population_fingerprint=population["provider_population_fingerprint"],
            population_disposition_fingerprint=disposition["population_disposition_fingerprint"],
            exclusion_set_fingerprint=disposition["exclusion_set_fingerprint"],
        )
        pagination_complete = not symbols or (page > 0 and token is None)
        while not pagination_complete:
            params = dict(request_core)
            if token: params["page_token"] = token
            try:
                self._capacity_gate(state, item)
                state["last_historical_activity_at_utc"] = self.now().isoformat()
                payload = self.client.request(BARS_URL, params)
            except ProviderError as exc:
                if exc.status == 429 and state.get("operating_mode") in {"LIVE_COEXISTENCE", "WAITING_FOR_LIVE_CAPACITY"}:
                    state["live_session_yield_date"] = self.now().astimezone(EASTERN).date().isoformat()
                    state["live_session_latch_reason"] = "PROVIDER_429_DURING_HISTORICAL_OVERLAP"
                    state["live_capacity_reason"] = "PROVIDER_429_LIVE_SESSION_LATCH"
                if token and exc.status in {400, 404, 410, 422}:
                    self._quarantine_partial(page_root, "OPAQUE_PAGE_TOKEN_REJECTED_REBUILD", {"status": exc.status, **descriptor})
                    page, token = 0, None
                    continue
                invalid = re.search(r"invalid symbol:\s*([^\"}\s]+)", str(exc), re.IGNORECASE)
                bad_symbol = invalid.group(1).upper() if invalid else None
                if exc.status != 400 or bad_symbol not in symbols or page:
                    raise
                state.setdefault("unqueryable_symbols", []).append({"symbol": bad_symbol, "provider_asset_id": identity[bad_symbol], "reason": "PROVIDER_REJECTED_SYMBOL", "observed_at_utc": self.now().isoformat()})
                state["bad_symbol_failure_count"] = int(state.get("bad_symbol_failure_count", 0)) + 1
                context = self._partition_context(state, item)
                disposition = context["disposition"]
                request_core = context["request_core"]
                request_fp = context["request_fingerprint"]
                identity = {
                    member["canonical_symbol"]: member["provider_asset_id"]
                    for member in disposition["requested_members"]
                }
                symbols = list(identity)
                self.sync_provider_counts(state); self.save_state(state)
                if symbols:
                    continue
                pagination_complete = True
                break
            if not isinstance(payload, dict) or "bars" not in payload or not isinstance(payload["bars"], dict):
                raise ProviderError("Malformed bars response.", systemic=True)
            accepted: list[dict[str, Any]] = []
            rejections: list[dict[str, Any]] = []
            counts = {category: 0 for category in REJECTION_CATEGORIES}
            source_row_count = 0
            bars = payload["bars"]
            unexpected = sorted(str(symbol) for symbol in bars if symbol not in identity)
            if unexpected:
                raise ProviderError(f"Unexpected provider response symbols: {unexpected}", systemic=True)
            page_number = page + 1
            page_now = self.now()
            for symbol in sorted(bars):
                rows = bars[symbol]
                if not isinstance(rows, list):
                    raise ProviderError(f"Malformed provider page rows for {symbol}.", systemic=True)
                for raw in rows:
                    ordinal = source_row_count
                    source_row_count += 1
                    outcome = classify_bar(
                        raw, symbol, identity[symbol], request_fp, start, end,
                        page_now, self.historical_calendar,
                    )
                    if outcome.outcome == "ACCEPTED":
                        assert outcome.accepted_row is not None
                        accepted.append(outcome.accepted_row)
                    else:
                        counts[outcome.outcome] += 1
                        rejections.append(rejection_record(
                            raw=raw, outcome=outcome, partition=part_id,
                            page=page_number, ordinal=ordinal, symbol=symbol,
                            asset_id=identity[symbol], request_fingerprint=request_fp,
                            batch_fingerprint=descriptor["batch_fingerprint"],
                            calendar_fingerprint=FROZEN_CALENDAR_CONTENT_FINGERPRINT,
                        ))
            page += 1
            accepted.sort(key=lambda row: (row["provider_asset_id"], row["market_timestamp"]))
            fragment = page_root / f"page-{page:06d}.csv.gz"
            rejection_path = page_root / f"page-{page:06d}.rejections.jsonl.gz"
            atomic_bytes(fragment, encode_gzip_csv(accepted, BAR_COLUMNS))
            atomic_bytes(rejection_path, encode_gzip_jsonl(rejections))
            atomic_json(fragment.with_suffix(fragment.suffix + ".manifest.json"), page_evidence(
                fragment, rejection_path, page=page,
                source_row_count=source_row_count, accepted_row_count=len(accepted),
                rejected_row_count=len(rejections), rejection_counts_by_category=counts,
                request_fingerprint=request_fp,
                batch_fingerprint=descriptor["batch_fingerprint"],
                calendar_fingerprint=FROZEN_CALENDAR_CONTENT_FINGERPRINT,
                provider_population_fingerprint=population["provider_population_fingerprint"],
                population_disposition_fingerprint=disposition["population_disposition_fingerprint"],
                exclusion_set_fingerprint=disposition["exclusion_set_fingerprint"],
            ))
            token = payload.get("next_page_token")
            last_boundary = ([accepted[-1]["provider_asset_id"], accepted[-1]["market_timestamp"]] if accepted else None)
            aggregate = self._page_aggregate(page_root, page)
            checkpoint_payload = {
                "schema_version": CHECKPOINT_SCHEMA_VERSION, "year": year, "batch": batch,
                "batch_fingerprint": descriptor["batch_fingerprint"],
                "requested_start": start.isoformat(), "requested_end": end.isoformat(),
                "page": page, "next_page_token": token,
                "last_completed_boundary": last_boundary,
                "request_fingerprint": request_fp,
                "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
                "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
                "frozen_calendar_fingerprint": FROZEN_CALENDAR_CONTENT_FINGERPRINT,
                "provider_population_fingerprint": population["provider_population_fingerprint"],
                "population_disposition_fingerprint": disposition["population_disposition_fingerprint"],
                "exclusion_set_fingerprint": disposition["exclusion_set_fingerprint"],
                **aggregate,
            }
            checkpoint_payload["checkpoint_fingerprint"] = fingerprint(checkpoint_payload)
            atomic_json(checkpoint, checkpoint_payload)
            self.sync_provider_counts(state)
            state["checkpoint_at_utc"] = self.now().isoformat(); self.save_state(state)
            state["last_historical_activity_at_utc"] = self.now().isoformat()
            if not token: pagination_complete = True
        if page:
            verified_page, verified_token = self._validated_resume(
                page_root, expected_request_fingerprint=request_fp,
                expected_batch_fingerprint=descriptor["batch_fingerprint"], descriptor=descriptor,
                provider_population_fingerprint=population["provider_population_fingerprint"],
                population_disposition_fingerprint=disposition["population_disposition_fingerprint"],
                exclusion_set_fingerprint=disposition["exclusion_set_fingerprint"],
            )
            if verified_page != page or verified_token is not None:
                raise RuntimeError(f"Final page-fragment validation failed for {part_id}.")
        self._capacity_gate(state, item, finalization=True)
        self._finalize_downloaded_partition(state, item)

    def acquire_corporate_actions(self, state: dict[str, Any]) -> None:
        """Acquire and bind complete provider and stable-identity action evidence."""
        requested = state["requested_range"]
        params = {
            "types": ",".join(CA_TYPES), "start": requested["requested_start"],
            "end": requested["requested_end"], "limit": "1000", "sort": "asc",
        }
        request_core = {
            "provider": PROVIDER,
            "corporate_action_semantic_version": CORPORATE_ACTION_SEMANTIC_VERSION,
            "params": params,
        }
        request_fp = fingerprint(request_core)
        token = None
        seen_tokens: set[str] = set()
        page = 0
        records: dict[str, dict[str, Any]] = {}
        pages: list[dict[str, Any]] = []
        while True:
            request = dict(params)
            if token: request["page_token"] = token
            self._capacity_gate(state, {"year": "corporate_actions", "batch": 0})
            payload = self.client.request(CORPORATE_ACTION_URL, request)
            if not isinstance(payload, dict) or not isinstance(payload.get("corporate_actions", {}), dict):
                raise ProviderError("Malformed corporate-actions response.", systemic=True)
            page_event_ids: list[str] = []
            for collection, values in payload["corporate_actions"].items():
                if not isinstance(values, list):
                    raise ProviderError("Malformed corporate-action collection.", systemic=True)
                action_type = collection.removesuffix("s")
                if action_type not in CA_TYPES:
                    if values:
                        raise ProviderError(
                            f"Unsupported corporate-action collection: {collection}",
                            systemic=True,
                        )
                    continue
                for raw in values:
                    if not isinstance(raw, Mapping):
                        raise ProviderError("Malformed corporate-action event.", systemic=True)
                    normalized = normalize_corporate_action(raw, action_type, self.now())
                    key = normalized["provider_event_id"]
                    if key in records:
                        raise RuntimeError(f"Duplicate corporate-action provider event id: {key}")
                    records[key] = normalized
                    page_event_ids.append(key)
            next_token = payload.get("next_page_token")
            if next_token is not None and (not isinstance(next_token, str) or not next_token):
                raise ProviderError("Malformed corporate-action page token.", systemic=True)
            if next_token is not None and next_token in seen_tokens:
                raise ProviderError("Repeated corporate-action page token.", systemic=True)
            page += 1
            page_core = {
                "page": page,
                "request_fingerprint": request_fp,
                "input_page_token": token,
                "terminal_page": next_token is None,
                "next_page_token_fingerprint": (
                    fingerprint({"page_token": next_token}) if next_token else None
                ),
                "provider_event_ids": sorted(page_event_ids),
                "provider_payload_fingerprint": fingerprint(payload),
            }
            pages.append({**page_core, "page_evidence_fingerprint": fingerprint(page_core)})
            if next_token is not None:
                seen_tokens.add(next_token)
            token = next_token
            self.sync_provider_counts(state)
            state["checkpoint_at_utc"] = self.now().isoformat(); self.save_state(state)
            if not token: break
        ordered = [records[key] for key in sorted(records)]
        action_fp = fingerprint(ordered)
        path = self.root / "corporate_actions" / "artifacts" / f"{action_fp}.jsonl.gz"
        atomic_bytes(path, encode_gzip_jsonl(ordered))
        population = self._provider_population()
        resolution = corporate_action_identity_resolution(ordered, population)
        resolution_fp = resolution["identity_resolution_fingerprint"]
        resolution_path = atomic_content_addressed_json(
            self.root / "corporate_actions" / "identity_resolution",
            resolution_fp,
            resolution,
            label="corporate-action identity-resolution",
        )
        manifest_core = {
            "schema_version": CORPORATE_ACTION_EVIDENCE_SCHEMA_VERSION,
            "corporate_action_semantic_version": CORPORATE_ACTION_SEMANTIC_VERSION,
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider": PROVIDER,
            "requested_start": requested["requested_start"],
            "requested_end": requested["requested_end"],
            "supported_types": list(CA_TYPES),
            "request_fingerprint": request_fp,
            "event_count": len(ordered),
            "artifact_sha256": sha256_path(path),
            "corporate_action_artifact_fingerprint": action_fp,
            "page_count": page,
            "page_evidence": pages,
            "terminal_page_token": None,
            "security_master_fingerprint": population["security_master_fingerprint"],
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "identity_resolution_fingerprint": resolution_fp,
            "identity_resolution_sha256": sha256_path(resolution_path),
        }
        manifest = {**manifest_core, "manifest_fingerprint": fingerprint(manifest_core)}
        manifest_path = atomic_content_addressed_json(
            self.root / "corporate_actions" / "manifests",
            manifest["manifest_fingerprint"],
            manifest,
            label="corporate-action manifest",
        )
        state["corporate_action_artifact_fingerprint"] = action_fp
        state["corporate_action_manifest_fingerprint"] = manifest["manifest_fingerprint"]
        state["corporate_action_identity_resolution_fingerprint"] = resolution_fp
        state["corporate_action_artifact_path"] = str(path.relative_to(self.root))
        state["corporate_action_manifest_path"] = str(manifest_path.relative_to(self.root))
        state["corporate_action_identity_resolution_path"] = str(
            resolution_path.relative_to(self.root)
        )
        state["corporate_action_status"] = "COMPLETE"

    def finalize(self, state: dict[str, Any]) -> None:
        population = self._provider_population()
        coverage = observational_coverage_evidence(state, population)
        coverage_path = atomic_content_addressed_json(
            self.root / "manifests" / "observational_coverage",
            coverage["observational_coverage_fingerprint"],
            coverage,
            label="observational-coverage",
        )
        state["observational_coverage_fingerprint"] = coverage[
            "observational_coverage_fingerprint"
        ]
        state["observational_coverage_path"] = str(coverage_path.relative_to(self.root))
        state["status"] = "COMPLETE"; state["stage"] = "COMPLETE"; state["current_partition"] = None
        state["training_eligibility"] = "ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE"; state["completed_at_utc"] = self.now().isoformat()

    def record_failure(self, state: dict[str, Any], item: Mapping[str, Any], exc: Exception) -> None:
        path = self.root / "failures" / "acquisition_failures.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"recorded_at_utc": self.now().isoformat(), "partition": {"year": item.get("year"), "batch": item.get("batch")}, "error_type": type(exc).__name__, "message": str(exc)[:1000]}
        with path.open("a", encoding="utf-8") as handle: handle.write(json.dumps(record, sort_keys=True) + "\n"); handle.flush(); os.fsync(handle.fileno())
        state["failure_count"] += 1
        self.sync_provider_counts(state)

    def _run(self, max_partitions: int | None = None) -> dict[str, Any]:
        state = self.load_state() or self.initialize()
        self._state_defaults(state)
        self._calendar_preflight(state["requested_range"])
        self._provider_population()
        self.request_count_base = int(state.get("api_request_count", 0)) - self.client.request_count
        self.retry_count_base = int(state.get("retry_count", 0)) - self.client.retry_count
        self._drain_pending_finalizations(state)
        completed_now = 0
        for item in state["partitions"]:
            part_id = f"year={item['year']}/batch={int(item['batch']):05d}"
            if part_id in state["completed"]: continue
            if any(entry.get("partition") == part_id for entry in state.get("pending_finalizations", [])): continue
            self._pending_capacity_gate(state)
            if self.stop_requested:
                state["status"] = "STOPPED_FOR_MARKET_WINDOW"; state["stop_reason"] = "SIGNAL" if self.stop_requested else "MORNING_RESOURCE_BOUNDARY"; break
            state["status"] = "RUNNING"; state["current_partition"] = part_id; self.save_state(state)
            while True:
                active_started = self.monotonic()
                try:
                    self.acquire_partition(state, item)
                    state["active_acquisition_seconds"] += max(0.0, self.monotonic() - active_started)
                    if state.get("outage_started_at_utc"):
                        state["last_outage_ended_at_utc"] = self.now().isoformat()
                    state["outage_started_at_utc"] = None; state["outage_backoff_level"] = 0
                    break
                except CooperativeStop:
                    raise
                except ProviderError as exc:
                    state["active_acquisition_seconds"] += max(0.0, self.monotonic() - active_started)
                    if exc.transient:
                        if not self._wait_for_network(state, item, exc):
                            break
                        continue
                    self.record_failure(state, item, exc); state["hard_failure_count"] += 1
                    state["status"] = "HARD_FAILED"; state["stop_reason"] = exc.failure_class
                    self.save_state(state); raise
                except Exception as exc:
                    state["active_acquisition_seconds"] += max(0.0, self.monotonic() - active_started)
                    self.record_failure(state, item, exc); state["hard_failure_count"] += 1
                    state["status"] = "HARD_FAILED"; state["stop_reason"] = "DATA_INTEGRITY_OR_INVARIANT_FAILURE"
                    self.save_state(state); raise
            if state["status"] == "STOPPED_FOR_MARKET_WINDOW":
                break
            completed_now += 1; state["checkpoint_at_utc"] = self.now().isoformat(); self.save_state(state)
            if max_partitions is not None and completed_now >= max_partitions: break
        else:
            self._drain_pending_finalizations(state)
            state["stage"] = "CORPORATE_ACTIONS"; state["status"] = "RUNNING"; state["current_partition"] = "corporate_actions"; self.save_state(state)
            self.acquire_corporate_actions(state); self.finalize(state)
        if max_partitions is not None and completed_now >= max_partitions:
            state["status"] = "PARTIAL"; state["stop_reason"] = "BOUNDED_RUN_COMPLETE"
        self.sync_provider_counts(state); state["checkpoint_at_utc"] = self.now().isoformat(); self.save_state(state)
        return state

    def run(self, max_partitions: int | None = None) -> dict[str, Any]:
        try:
            return self._run(max_partitions=max_partitions)
        except CooperativeStop:
            state = self.load_state()
            if state is None:
                raise
            self._state_defaults(state)
            state["status"] = "STOPPED_FOR_MARKET_WINDOW"
            state["stop_reason"] = "SIGNAL"
            state["next_retry_at_utc"] = None
            state["checkpoint_at_utc"] = self.now().isoformat()
            self.sync_provider_counts(state)
            self.save_state(state)
            return state


def status(root: Path = DEFAULT_ROOT) -> dict[str, Any]:
    state_path = root / "acquisition_state" / "state.json"; checksum = state_path.with_suffix(".sha256")
    if not state_path.exists(): return {"status": "STOPPED", "root": str(root), "state_exists": False, "free_disk_bytes": shutil.disk_usage(root.parent if root.parent.exists() else ROOT).free}
    state = json.loads(read_checksummed_state(state_path, checksum, label="ML historical acquisition state"))
    manifests = list((root / "bars_15m").rglob("*.manifest.json")) if (root / "bars_15m").exists() else []
    integrity = all(json.loads(p.read_text()).get("sha256") == sha256_path(Path(str(p)[:-len(".manifest.json")])) for p in manifests)
    partition_metadata = [json.loads(path.read_text()) for path in manifests]
    acquired_sessions = [value for item in partition_metadata for value in (item.get("first_session"), item.get("last_session")) if value]
    elapsed = max(0.001, (datetime.now(timezone.utc) - datetime.fromisoformat(state["started_at_utc"])).total_seconds())
    wall_rate = state.get("rows_15m", 0) / elapsed
    active_seconds = max(0.001, float(state.get("active_acquisition_seconds", elapsed)))
    active_rows = max(0, state.get("rows_15m", 0) - state.get("active_measurement_rows_baseline", 0))
    active_bytes = max(0, state.get("bytes_stored", 0) - state.get("active_measurement_bytes_baseline", 0))
    active_rate = active_rows / active_seconds
    remaining = state["partitions_total"] - state["partitions_complete"]
    payload = {k: state.get(k) for k in ("status", "operating_mode", "historical_request_ceiling_per_minute", "historical_concurrency", "live_qpx_detected_active", "clean_v2_service_state", "live_capacity_reason", "live_capacity_recheck_seconds", "live_session_yield_date", "live_session_latch_reason", "last_historical_activity_at_utc", "coexistence_journal_events", "provider_average_request_latency_seconds", "provider_rate_limit", "provider_rate_limit_remaining", "provider_rate_limit_reset", "requested_range", "provider", "feed", "adjustment", "security_count", "active_count", "inactive_count", "partitions_total", "partitions_complete", "rows_15m", "bytes_stored", "api_request_count", "retry_count", "failure_count", "transient_outage_count", "transient_outage_seconds", "provider_retry_count", "bad_symbol_failure_count", "hard_failure_count", "outage_started_at_utc", "last_successful_request_at_utc", "next_retry_at_utc", "transient_failure_type", "transient_failure_message", "network_retry_attempt_count", "outage_backoff_level", "current_partition", "checkpoint_at_utc", "survivorship_status", "training_eligibility", "corporate_action_status", "morning_deadline")}
    systemd_state = "UNKNOWN"
    try:
        import subprocess
        result = subprocess.run(("systemctl", "--user", "is-active", "qpx-ml-historical-acquisition.service"), capture_output=True, text=True, timeout=5, check=False)
        systemd_state = result.stdout.strip().upper() or "STOPPED"
    except Exception:
        pass
    outage_duration = None
    if state.get("outage_started_at_utc"):
        outage_duration = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(state["outage_started_at_utc"])).total_seconds())
    rate_started = datetime.fromisoformat(state.get("request_rate_measurement_started_at_utc", state["started_at_utc"]))
    rate_seconds = max(1.0, (datetime.now(timezone.utc) - rate_started).total_seconds())
    measured_rpm = max(0, state.get("api_request_count", 0) - state.get("request_rate_measurement_baseline", 0)) * 60.0 / rate_seconds
    payload.update({"partitions_pending": remaining, "actual_acquired_range": {"first_session": min(acquired_sessions) if acquired_sessions else None, "last_session": max(acquired_sessions) if acquired_sessions else None}, "free_disk_bytes": shutil.disk_usage(root).free, "historical_measured_requests_per_minute": round(measured_rpm, 2), "active_rows_per_second": round(active_rate, 2), "active_megabytes_per_second": round((active_bytes / 1_000_000) / active_seconds, 3), "wall_clock_rows_per_second": round(wall_rate, 2), "wall_clock_megabytes_per_second": round((state.get("bytes_stored", 0) / 1_000_000) / elapsed, 3), "outage_duration_seconds": outage_duration, "estimated_remaining_seconds": round(remaining / (state["partitions_complete"] / elapsed), 0) if state["partitions_complete"] else None, "latest_manifest_integrity": integrity, "stored_partition_manifests": len(manifests), "systemd_state": systemd_state, "root": str(root)})
    payload["pending_finalization_count"] = len(state.get("pending_finalizations", []))
    payload["attribution_window_seconds"] = LIVE_ATTRIBUTION_WINDOW_SECONDS
    return payload


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=DEFAULT_ROOT); parser.add_argument("--max-partitions", type=int); args = parser.parse_args(argv)
    acquisition = Acquisition(args.root)
    def stop(_signum: int, _frame: Any) -> None: acquisition.stop_requested = True
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    if acquisition._deadline_reached():
        print(json.dumps({"status": "STOPPED_FOR_MARKET_WINDOW"}, sort_keys=True), flush=True)
        return 0
    try:
        result = acquisition.run(args.max_partitions)
    except ProviderError as exc:
        import traceback
        traceback.print_exc()
        return 1 if exc.transient else 78
    except Exception:
        import traceback
        traceback.print_exc()
        return 78
    print(json.dumps({"status": result["status"], "partitions_complete": result["partitions_complete"], "rows_15m": result["rows_15m"]}, sort_keys=True), flush=True); return 0
