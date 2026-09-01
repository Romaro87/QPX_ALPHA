"""IEX-only causal forward research adapter for the PR_FRACTION_50 paper model.

This process has no broker/order client and does not claim SIP parity,
qualification, promotion, or production authority.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
import signal
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

import qpx_bot.fixed25_forward_paper as sip
from qpx_bot.alpaca_provider import (
    MAX_REQUEST_ATTEMPTS,
    MAX_RETRY_DELAY_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
)
from qpx_bot.accelerators.profit_recycling import (
    ProfitRecyclingRuntime,
    load_profit_recycling_config,
)
from qpx_bot.market_calendar import is_market_session
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


FEED = "iex"
VARIANT = "PR_FRACTION_50_IEX_FORWARD_RESEARCH_PAPER_ONLY"
DEFAULT_RUNTIME = sip.ROOT / "runtime/qpx_pr50_iex_forward_research_paper"
HEARTBEAT_SCHEMA_VERSION = 1
CORPORATE_ACTION_POLL_SECONDS = 900
STATUS_PRINT_SECONDS = 600
MAX_PROVIDER_PAGES = 100
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


@contextmanager
def _shutdown_signal_scope(stop_requested: threading.Event) -> Iterator[None]:
    """Turn systemd termination into an orderly daemon-loop exit."""
    previous: dict[int, Any] = {}

    def request_stop(_signum, _frame) -> None:
        stop_requested.set()

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, request_stop)
    try:
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


@dataclass
class ProviderFailure(Exception):
    failure_class: str
    provider: str
    operation: str
    endpoint: str
    recoverable: bool
    exception_type: str
    message: str
    request_parameters: Mapping[str, Any]
    http_status: int | None = None
    response_body: str | None = None
    retry_after_seconds: float | None = None

    def __str__(self) -> str:
        return (
            f"{self.failure_class}: provider={self.provider}; "
            f"operation={self.operation}; endpoint={self.endpoint}; "
            f"exception={self.exception_type}: {self.message}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "failure_class": self.failure_class,
            "provider": self.provider,
            "operation": self.operation,
            "endpoint": self.endpoint,
            "recoverable": self.recoverable,
            "exception_type": self.exception_type,
            "message": self.message,
            "request_parameters": dict(self.request_parameters),
            "http_status": self.http_status,
            "response_body": self.response_body,
            "retry_after_seconds": self.retry_after_seconds,
        }


_last_successful_provider_contact_utc: str | None = None


def _record_provider_contact() -> None:
    global _last_successful_provider_contact_utc
    _last_successful_provider_contact_utc = datetime.now(timezone.utc).isoformat()


def _request_context(parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in parameters.items()
        if key.lower() not in {"api_key", "apikey", "key", "secret", "secret_key"}
    }


def _provider_failure(
    error: BaseException,
    *,
    provider: str,
    operation: str,
    endpoint: str,
    parameters: Mapping[str, Any],
) -> ProviderFailure:
    request_parameters = _request_context(parameters)
    if isinstance(error, urllib.error.HTTPError):
        try:
            body = error.read().decode("utf-8", errors="replace")[:1000]
        except OSError:
            body = ""
        retry_header = error.headers.get("Retry-After") if error.headers else None
        try:
            retry_after = float(retry_header) if retry_header else None
        except ValueError:
            retry_after = None
        if error.code in (401, 403):
            failure_class = "AUTHENTICATION_PERMISSION_FAILURE"
            recoverable = False
        elif error.code == 429:
            failure_class = (
                "ALPACA_RATE_LIMIT" if provider == "alpaca" else "PROVIDER_RATE_LIMIT"
            )
            recoverable = True
        elif 500 <= error.code <= 599:
            failure_class = (
                "ALPACA_PROVIDER_5XX" if provider == "alpaca" else "PROVIDER_5XX"
            )
            recoverable = True
        else:
            failure_class = "ALPACA_HTTP_4XX"
            recoverable = error.code in (408, 425)
        return ProviderFailure(
            failure_class=failure_class,
            provider=provider,
            operation=operation,
            endpoint=endpoint,
            recoverable=recoverable,
            exception_type=type(error).__name__,
            message=f"HTTP {error.code} {error.reason}",
            request_parameters=request_parameters,
            http_status=error.code,
            response_body=body,
            retry_after_seconds=retry_after,
        )

    reason: BaseException | object = error
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
    if isinstance(reason, (TimeoutError, socket.timeout)):
        failure_class = "REQUEST_TIMEOUT"
    elif isinstance(reason, socket.gaierror):
        failure_class = "DNS_CONNECTIVITY_FAILURE"
    elif isinstance(reason, OSError) and reason.errno in {
        errno.ENETDOWN,
        errno.ENETUNREACH,
        errno.EHOSTDOWN,
        errno.EHOSTUNREACH,
    }:
        failure_class = "LOCAL_NETWORK_UNAVAILABLE"
    elif isinstance(error, (urllib.error.URLError, ConnectionError, OSError)):
        failure_class = "CONNECTIVITY_FAILURE"
    elif isinstance(error, (json.JSONDecodeError, UnicodeDecodeError)):
        failure_class = "MALFORMED_PROVIDER_RESPONSE"
    else:
        failure_class = "PROVIDER_FAILURE"
    return ProviderFailure(
        failure_class=failure_class,
        provider=provider,
        operation=operation,
        endpoint=endpoint,
        recoverable=True,
        exception_type=type(error).__name__,
        message=str(error),
        request_parameters=request_parameters,
    )


def _request_retry_delay(failure: ProviderFailure, attempt: int) -> float:
    if failure.failure_class in {"ALPACA_RATE_LIMIT", "PROVIDER_RATE_LIMIT"} and (
        failure.retry_after_seconds
    ):
        return min(MAX_RETRY_DELAY_SECONDS, max(1.0, failure.retry_after_seconds))
    return min(MAX_RETRY_DELAY_SECONDS, float(2 ** attempt))


def _request_json(
    *,
    provider: str,
    operation: str,
    endpoint: str,
    parameters: Mapping[str, Any],
    user_agent: str,
) -> Mapping[str, Any]:
    try:
        key, secret = sip.credentials()
    except RuntimeError as exc:
        raise ProviderFailure(
            failure_class="AUTHENTICATION_PERMISSION_FAILURE",
            provider=provider,
            operation=operation,
            endpoint=endpoint,
            recoverable=False,
            exception_type=type(exc).__name__,
            message=str(exc),
            request_parameters=_request_context(parameters),
        ) from exc
    url = endpoint + "?" + urllib.parse.urlencode(parameters)
    for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            headers={
                "APCA-API-KEY-ID": key,
                "APCA-API-SECRET-KEY": secret,
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "User-Agent": user_agent,
            },
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=REQUEST_TIMEOUT_SECONDS,
            ) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, Mapping):
                raise ProviderFailure(
                    failure_class="MALFORMED_PROVIDER_RESPONSE",
                    provider=provider,
                    operation=operation,
                    endpoint=endpoint,
                    recoverable=True,
                    exception_type=type(payload).__name__,
                    message="Provider JSON root is not an object.",
                    request_parameters=_request_context(parameters),
                )
            _record_provider_contact()
            return payload
        except ProviderFailure as exc:
            failure = exc
        except (
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
            ConnectionError,
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            failure = _provider_failure(
                exc,
                provider=provider,
                operation=operation,
                endpoint=endpoint,
                parameters=parameters,
            )
        if not failure.recoverable or attempt == MAX_REQUEST_ATTEMPTS:
            raise failure
        time.sleep(_request_retry_delay(failure, attempt))
    raise AssertionError("Provider retry loop terminated unexpectedly.")


def load_contract() -> dict[str, Any]:
    contract = dict(sip.load_contract())
    contract.update({
        "feed": FEED,
        "runner_variant": VARIANT,
        "research_only": True,
        "sip_parity_claimed": False,
        "qualified": False,
        "promoted": False,
    })
    return contract


def request_bars(
    symbols: tuple[str, ...], timeframe: str, start: datetime, end: datetime
) -> dict[str, list[dict[str, Any]]]:
    params = {
        "symbols": ",".join(symbols), "timeframe": timeframe,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feed": FEED, "adjustment": "raw", "limit": "10000", "sort": "asc",
    }
    collected: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    seen_tokens: set[str] = set()
    page_count = 0
    while True:
        page_count += 1
        if page_count > MAX_PROVIDER_PAGES:
            raise ProviderFailure(
                failure_class="MALFORMED_PROVIDER_RESPONSE",
                provider="alpaca",
                operation="market_bars",
                endpoint=sip.DATA_URL,
                recoverable=True,
                exception_type="PaginationLimitExceeded",
                message="Alpaca pagination exceeded the bounded page limit.",
                request_parameters=_request_context(params),
            )
        payload = _request_json(
            provider="alpaca",
            operation="market_bars",
            endpoint=sip.DATA_URL,
            parameters=params,
            user_agent="QPX-PR50-IEX-FORWARD-RESEARCH-PAPER/1",
        )
        bars = payload.get("bars", {})
        if not isinstance(bars, Mapping):
            raise ProviderFailure(
                failure_class="MALFORMED_PROVIDER_RESPONSE",
                provider="alpaca",
                operation="market_bars",
                endpoint=sip.DATA_URL,
                recoverable=True,
                exception_type=type(bars).__name__,
                message="The bars field is not an object.",
                request_parameters=_request_context(params),
            )
        for symbol, rows in bars.items():
            if symbol not in collected:
                continue
            if not isinstance(rows, list):
                raise ProviderFailure(
                    failure_class="MALFORMED_PROVIDER_RESPONSE",
                    provider="alpaca",
                    operation="market_bars",
                    endpoint=sip.DATA_URL,
                    recoverable=True,
                    exception_type=type(rows).__name__,
                    message=f"The bars value for {symbol} is not a list.",
                    request_parameters=_request_context(params),
                )
            collected[symbol].extend(rows)
        token = payload.get("next_page_token")
        if not token:
            return collected
        normalized_token = str(token)
        if normalized_token in seen_tokens:
            raise ProviderFailure(
                failure_class="MALFORMED_PROVIDER_RESPONSE",
                provider="alpaca",
                operation="market_bars",
                endpoint=sip.DATA_URL,
                recoverable=True,
                exception_type="RepeatedPageToken",
                message="Alpaca repeated a pagination token.",
                request_parameters=_request_context(params),
            )
        seen_tokens.add(normalized_token)
        params["page_token"] = normalized_token


def request_qdte_corporate_actions(start: date, end: date) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "symbols": "QDTE",
        "types": "cash_dividend",
        "region": "us",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "limit": "1000",
        "data_quality": "complete",
        "sort": "asc",
    }
    records: list[dict[str, Any]] = []
    seen_tokens: set[str] = set()
    page_count = 0
    while True:
        page_count += 1
        if page_count > MAX_PROVIDER_PAGES:
            raise ProviderFailure(
                failure_class="MALFORMED_PROVIDER_RESPONSE",
                provider="alpaca",
                operation="qdte_corporate_actions",
                endpoint=sip.CORPORATE_ACTION_URL,
                recoverable=True,
                exception_type="PaginationLimitExceeded",
                message="Alpaca pagination exceeded the bounded page limit.",
                request_parameters=_request_context(params),
            )
        payload = _request_json(
            provider="alpaca",
            operation="qdte_corporate_actions",
            endpoint=sip.CORPORATE_ACTION_URL,
            parameters=params,
            user_agent="QPX-PR50-IEX-FORWARD-RESEARCH-PAPER/1",
        )
        sip._find_action_records(payload, records)
        token = payload.get("next_page_token")
        if not token:
            return records
        normalized_token = str(token)
        if normalized_token in seen_tokens:
            raise ProviderFailure(
                failure_class="MALFORMED_PROVIDER_RESPONSE",
                provider="alpaca",
                operation="qdte_corporate_actions",
                endpoint=sip.CORPORATE_ACTION_URL,
                recoverable=True,
                exception_type="RepeatedPageToken",
                message="Alpaca repeated a pagination token.",
                request_parameters=_request_context(params),
            )
        seen_tokens.add(normalized_token)
        params["page_token"] = normalized_token


class IEXResearchStore(sip.Store):
    def __init__(self, directory: Path):
        super().__init__(directory)
        self.state = self.directory / "iex_research_paper_state.json"
        self.checksum = self.directory / "iex_research_paper_state.sha256"
        self.journal = self.directory / "iex_research_paper_audit.jsonl"
        self.lock = self.directory / "iex_research_paper.lock"
        self.heartbeat = self.directory / "iex_research_paper_heartbeat.json"
        self.heartbeat_checksum = (
            self.directory / "iex_research_paper_heartbeat.sha256"
        )

    def event(self, event_type: str, details: Mapping[str, Any]) -> bool:
        labeled = {
            ("iex_1m_bar" if key == "sip_1m_bar" else key): value
            for key, value in details.items()
        }
        labeled.update({"runner_variant": VARIANT, "market_data_feed": FEED})
        return super().event(event_type, labeled)

    def read_heartbeat(self) -> dict[str, Any] | None:
        if not self.heartbeat.exists():
            if self.heartbeat_checksum.exists():
                raise RuntimeError(
                    "IEX research heartbeat is missing while its checksum exists."
                )
            return None
        encoded = read_checksummed_state(
            self.heartbeat,
            self.heartbeat_checksum,
            label="IEX research heartbeat",
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise RuntimeError("IEX research heartbeat root must be an object.")
        return payload

    def write_heartbeat(self, payload: Mapping[str, Any]) -> None:
        encoded = json.dumps(
            dict(payload),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        write_checksummed_state(self.heartbeat, self.heartbeat_checksum, encoded)

    def reconcile(self) -> dict[str, Any] | None:
        state = super().reconcile()
        self.read_heartbeat()
        return state


def select_causal_execution_bar(
    rows: list[dict[str, Any]], observed_at: datetime
) -> dict[str, Any]:
    result = dict(sip.select_causal_execution_bar(rows, observed_at))
    result["feed"] = FEED
    result["research_only"] = True
    return result


def first_eligible_execution_minute(decision_observed_at: datetime) -> datetime:
    observed = decision_observed_at.astimezone(timezone.utc)
    return observed.replace(second=0, microsecond=0) + timedelta(minutes=1)


def execution_clock_action(signal: Mapping[str, Any], observed_at: datetime) -> str:
    eligible = datetime.fromisoformat(str(signal["first_eligible_execution_minute_utc"]))
    end = eligible + timedelta(minutes=1)
    observed = observed_at.astimezone(timezone.utc)
    if observed < eligible:
        return "WAIT"
    if observed < end:
        return "WINDOW_ACTIVE"
    return "EXPIRE_MISSED_WINDOW"


def market_session_state(observed_at: datetime) -> str:
    market = observed_at.astimezone(sip.NY)
    if not is_market_session(market.date()):
        return "NON_SESSION"
    wall = market.time().replace(tzinfo=None)
    if wall < clock_time(9, 30):
        return "PRE_MARKET"
    if wall < clock_time(9, 45):
        return "OPEN_NO_COMPLETED_DECISION_BAR"
    if wall < clock_time(16, 0):
        return "REGULAR_SESSION"
    if wall < clock_time(16, 15):
        return "POST_CLOSE_DECISION_FINALIZATION"
    return "AFTER_HOURS"


def expected_completed_decision_start(observed_at: datetime) -> datetime | None:
    market = observed_at.astimezone(sip.NY)
    phase = market_session_state(observed_at)
    if phase == "POST_CLOSE_DECISION_FINALIZATION":
        return market.replace(hour=15, minute=45, second=0, microsecond=0)
    if phase != "REGULAR_SESSION":
        return None
    elapsed = (market.hour * 60 + market.minute) - (9 * 60 + 30)
    completed = elapsed // 15
    if completed < 1:
        return None
    start_minutes = (9 * 60 + 30) + ((completed - 1) * 15)
    return market.replace(
        hour=start_minutes // 60,
        minute=start_minutes % 60,
        second=0,
        microsecond=0,
    )


def decision_processing_due(state: Mapping[str, Any], observed_at: datetime) -> bool:
    expected = expected_completed_decision_start(observed_at)
    if expected is None:
        return False
    last_raw = state.get("last_decision_bar")
    return last_raw is None or datetime.fromisoformat(str(last_raw)) < expected


def corporate_action_poll_due(state: Mapping[str, Any], observed_at: datetime) -> bool:
    last = state.get("last_corporate_action_observation_at_utc")
    if not last:
        return True
    return (
        observed_at.astimezone(timezone.utc) - datetime.fromisoformat(str(last))
    ).total_seconds() >= CORPORATE_ACTION_POLL_SECONDS


def _provider_backoff(
    failure: ProviderFailure,
    consecutive_failures: int,
    poll_seconds: int,
) -> int:
    if not failure.recoverable:
        return 900
    if failure.failure_class in {"ALPACA_RATE_LIMIT", "PROVIDER_RATE_LIMIT"}:
        requested = failure.retry_after_seconds or poll_seconds
        return int(min(900, max(poll_seconds, requested)))
    exponent = min(4, max(0, consecutive_failures - 1))
    return min(300, max(poll_seconds, poll_seconds * (2 ** exponent)))


def _sparse_data_failure(
    *,
    operation: str,
    message: str,
    parameters: Mapping[str, Any],
) -> ProviderFailure:
    return ProviderFailure(
        failure_class="EMPTY_SPARSE_MARKET_DATA",
        provider="alpaca",
        operation=operation,
        endpoint=sip.DATA_URL,
        recoverable=True,
        exception_type="SparseIEXData",
        message=message,
        request_parameters={"feed": FEED, **dict(parameters)},
    )


def _heartbeat_payload(
    *,
    daemon_started_at_utc: str,
    state: Mapping[str, Any] | None,
    provider_state: str,
    session_state: str,
    retry_count: int,
    backoff_seconds: int,
    last_successful_provider_contact_at_utc: str | None,
    failure: ProviderFailure | None = None,
    degraded_since_at_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "runner_variant": VARIANT,
        "market_data_feed": FEED,
        "research_only": True,
        "live_broker_enabled": False,
        "daemon_pid": os.getpid(),
        "daemon_started_at_utc": daemon_started_at_utc,
        "daemon_alive_at_utc": datetime.now(timezone.utc).isoformat(),
        "last_successful_provider_contact_at_utc": (
            last_successful_provider_contact_at_utc
        ),
        "last_completed_decision_time": (
            state.get("last_decision_bar") if state else None
        ),
        "last_completed_decision_observed_at_utc": (
            state.get("last_completed_decision_observed_at_utc") if state else None
        ),
        "last_completed_execution_observation": (
            state.get("last_completed_execution_observation_utc") if state else None
        ),
        "provider_state": provider_state,
        "market_session_state": session_state,
        "retry_count": retry_count,
        "backoff_seconds": backoff_seconds,
        "degraded_since_at_utc": degraded_since_at_utc,
        "state_revision": state.get("revision") if state else None,
        "failure": failure.as_dict() if failure else None,
    }


def _sleep_with_heartbeat(
    store: IEXResearchStore,
    payload: dict[str, Any],
    seconds: int,
    *,
    sleep: Any = None,
    stop_requested: threading.Event | None = None,
) -> None:
    sleeper = sleep or time.sleep
    remaining = max(0, seconds)
    while remaining:
        if stop_requested is not None and stop_requested.is_set():
            return
        interval = min(30, remaining)
        sleeper(interval)
        if stop_requested is not None and stop_requested.is_set():
            return
        remaining -= interval
        refreshed = dict(payload)
        refreshed["daemon_alive_at_utc"] = datetime.now(timezone.utc).isoformat()
        refreshed["backoff_seconds"] = remaining
        store.write_heartbeat(refreshed)


def _entry_execution_id(state: Mapping[str, Any], symbol: str, signal: Mapping[str, Any]) -> str:
    return sip.fingerprint({
        "kind": "causal_forward_entry", "symbol": symbol,
        "eligible_minute": signal["first_eligible_execution_minute_utc"],
        "signal": signal["signal_id"], "contract": state["contract_fingerprint"],
    })


def _expire_pending(
    state: dict[str, Any], store: IEXResearchStore, symbol: str,
    signal: Mapping[str, Any], observed_at: datetime, reason: str,
) -> None:
    execution_id = _entry_execution_id(state, symbol, signal)
    store.event("IEX_RESEARCH_ENTRY_EXECUTION_MISSED", {
        "symbol": symbol, "signal_id": signal["signal_id"],
        "execution_id": execution_id, "reason": reason,
        "decision_observed_at_utc": signal["decision_observed_at_utc"],
        "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
        "missed_recorded_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
    })
    state["completed_execution_ids"].append(execution_id)
    state["pending"].pop(symbol, None)
    state["last_completed_execution_observation_utc"] = (
        observed_at.astimezone(timezone.utc).isoformat()
    )


def process_pending_execution_clock(
    state: dict[str, Any], store: IEXResearchStore, observed_at: datetime
) -> bool:
    """Handle committed one-minute opportunities before slower decision work.

    Returns true while a pending signal is waiting for or inside its execution
    minute, so the cycle avoids slow catch-up work until the opportunity closes.
    """
    for symbol, signal in sorted(list(state["pending"].items())):
        action = execution_clock_action(signal, observed_at)
        if action == "WAIT":
            return True
        if action == "WINDOW_ACTIVE" and not signal.get("execution_window_observed_at_utc"):
            signal["execution_window_observed_at_utc"] = (
                observed_at.astimezone(timezone.utc).isoformat()
            )
            store.event("IEX_RESEARCH_EXECUTION_WINDOW_OBSERVED", {
                "symbol": symbol, "signal_id": signal["signal_id"],
                "decision_observed_at_utc": signal["decision_observed_at_utc"],
                "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
                "execution_window_observed_at_utc": signal["execution_window_observed_at_utc"],
            })
            store.save(state)
        if action == "EXPIRE_MISSED_WINDOW":
            _expire_pending(state, store, symbol, signal, observed_at,
                            "PROCESS_NOT_OBSERVED_DURING_ELIGIBLE_MINUTE")
            store.save(state)
            continue

        eligible = datetime.fromisoformat(signal["first_eligible_execution_minute_utc"])
        minute_rows = request_bars((symbol,), "1Min", eligible, eligible + timedelta(minutes=2))[symbol]
        execution_observed_at = datetime.now(timezone.utc)
        if execution_observed_at >= eligible + timedelta(minutes=1):
            _expire_pending(
                state,
                store,
                symbol,
                signal,
                execution_observed_at,
                "EXECUTION_BAR_NOT_OBSERVED_WITHIN_ELIGIBLE_MINUTE",
            )
            store.save(state)
            continue
        exact = [row for row in minute_rows
                 if sip._parse(str(row["t"])).astimezone(timezone.utc) == eligible]
        if not exact:
            store.save(state)
            return True
        one = exact[0]
        positions = {name: sip._position(raw) for name, raw in state["positions"].items()}
        mark_symbols = tuple(dict.fromkeys(("QDTE", *positions)))
        raw_marks = request_bars(mark_symbols, "15Min", eligible - timedelta(days=60), eligible)
        marks: dict[str, float] = {}
        for name in mark_symbols:
            completed = sip._completed_15m(raw_marks.get(name, []), eligible)
            if completed:
                marks[name] = float(completed[-1]["close"])
        if any(name not in marks for name in mark_symbols):
            _expire_pending(state, store, symbol, signal, observed_at,
                            "MISSING_CAUSAL_ACCOUNT_VALUATION_MARK")
            store.save(state)
            continue
        execution_id = _entry_execution_id(state, symbol, signal)
        open_price = float(one["o"])
        gap = abs(open_price - float(signal["prior_close"])) / float(signal["atr"])
        if gap > 2.0 or len(positions) >= 6:
            _expire_pending(state, store, symbol, signal, observed_at,
                            "GAP" if gap > 2.0 else "CAPACITY")
            store.save(state)
            continue
        swing_value = sum(pos.shares * marks[name] for name, pos in positions.items())
        equity = (state["cash"] + state.get("tax_reserve_cash", 0.0) + swing_value
                  + state["qdte_shares"] * marks["QDTE"])
        active_risk = sum(pos.shares * max(0.0, pos.entry_price - pos.stop_price)
                          for pos in positions.values())
        profit_runtime = sip._profit_runtime(state)
        next_sequence = max(state["profit_recycling"]["current_event_sequence"],
                            state["profit_recycling"]["event_sequence"] + 1)
        state["profit_recycling"]["current_event_sequence"] = next_sequence
        deployable = profit_runtime.ledger.available_swing_cash(state["cash"], next_sequence)
        config = sip.qualified.candidate_config()
        sizing = sip.calculate_position_size(
            account_equity=equity, available_cash=deployable, entry_price=open_price,
            atr=float(signal["atr"]), active_risk=active_risk, config=config,
            trade_results_r=(),
        )
        share_cap = math.floor((equity * sip.NOTIONAL_CAP) / sizing.entry_fill) if sizing.entry_fill else 0
        shares = min(sizing.shares, share_cap)
        if not sizing.is_tradeable or shares < 1:
            _expire_pending(state, store, symbol, signal, observed_at,
                            sizing.blocked_reason or "NOTIONAL_CAP")
            store.save(state)
            continue
        cost = shares * sizing.entry_fill
        used = min(cost, profit_runtime.ledger.recycled_profit_balance)
        if used:
            profit_runtime.ledger.consume(used, next_sequence, state["cash"])
        state["cash"] -= cost
        positions[symbol] = sip.Position(
            symbol=symbol, shares=shares, entry_date=eligible.astimezone(sip.NY).date(),
            entry_price=sizing.entry_fill, entry_atr=float(signal["atr"]),
            stop_price=sizing.stop_price, target_price=sizing.target_price,
            highest_price=sizing.entry_fill,
        )
        state["positions"] = {name: sip._position_dict(value) for name, value in positions.items()}
        sip._persist_profit_runtime(state, profit_runtime)
        state["completed_execution_ids"].append(execution_id)
        state["pending"].pop(symbol, None)
        state["last_completed_execution_observation_utc"] = (
            execution_observed_at.isoformat()
        )
        store.event("SIMULATED_ENTRY_FILLED", {
            "symbol": symbol, "execution_id": execution_id, "shares": shares,
            "fill_price": sizing.entry_fill, "iex_1m_bar": str(one["t"]),
            "decision_bar_interval": signal["decision_bar_interval"],
            "decision_observed_at_utc": signal["decision_observed_at_utc"],
            "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
            "execution_window_observed_at_utc": signal["execution_window_observed_at_utc"],
            "execution_observed_at_utc": execution_observed_at.isoformat(),
            "recycled_profit_consumed": used,
        })
        store.save(state)
    return False


def initialize(
    store: IEXResearchStore, contract: Mapping[str, Any], observed_at: datetime
) -> dict[str, Any]:
    rows = request_bars(("QDTE",), "1Min", observed_at - timedelta(days=7), observed_at)["QDTE"]
    execution = select_causal_execution_bar(rows, observed_at)
    fill = execution["source_price"] * (1.0 + sip.SLIPPAGE)
    shares = math.floor(sip.STARTING_CAPITAL / fill)
    if shares < 1:
        raise RuntimeError("Starting capital cannot purchase one simulated QDTE share.")
    cost = shares * fill
    cash = sip.STARTING_CAPITAL - cost
    identity = {
        "capital": sip.STARTING_CAPITAL, "symbol": "QDTE", "shares": shares,
        "cash_remainder": cash, "fill_price": fill, **execution,
        "runner_variant": VARIANT, "contract_fingerprint": sip.fingerprint(contract),
    }
    persisted_contract = json.loads(sip.canonical(contract))
    profit_config = load_profit_recycling_config(sip.PROFIT_CONFIG)
    profit_runtime = ProfitRecyclingRuntime(profit_config, sip.STARTING_CAPITAL)
    state = {
        "schema_version": sip.SCHEMA, "mode": VARIANT,
        "research_only": True, "sip_parity_claimed": False,
        "qualified": False, "promoted": False,
        "live_broker_enabled": False, "simulated_fills_only": True,
        "contract": persisted_contract, "contract_fingerprint": sip.fingerprint(contract),
        "initialization": identity, "initialization_fingerprint": sip.fingerprint(identity),
        "contributed_capital": sip.STARTING_CAPITAL, "cash": cash,
        "qdte_shares": shares, "qdte_cost": cost, "positions": {}, "pending": {},
        "tax_reserve_cash": 0.0, "realized_pnl": 0.0,
        "completed_execution_ids": [sip.fingerprint(identity)], "last_decision_bar": None,
        "last_completed_decision_observed_at_utc": None,
        "last_completed_execution_observation_utc": None,
        "last_rebalance_week": None,
        "profit_recycling": {
            "policy_identity": "PR_FRACTION_50",
            "configuration_fingerprint": profit_config.fingerprint,
            "event_sequence": 0, "current_event_sequence": 0,
            "decision_ids": [], "ledger": profit_runtime.ledger.as_dict(),
        },
        "qdte_corporate_actions": {}, "invalid_qdte_corporate_actions": [],
        "qdte_open_share_snapshots": {},
        "last_corporate_action_observation_at_utc": None, "revision": 1,
    }
    store.event("IEX_RESEARCH_ACCOUNT_INITIALIZED_SIMULATED_QDTE", identity)
    store.save(state)
    return state


@contextmanager
def _iex_request_scope() -> Iterator[None]:
    original_bars = sip.request_bars
    original_actions = sip.request_qdte_corporate_actions
    original_vix = sip._vix_previous_close

    def bounded_vix(day: date) -> float:
        failure: ProviderFailure | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            try:
                result = original_vix(day)
                _record_provider_contact()
                return result
            except RuntimeError:
                raise
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                ConnectionError,
                OSError,
                UnicodeDecodeError,
            ) as exc:
                failure = _provider_failure(
                    exc,
                    provider="cboe",
                    operation="vix_previous_close",
                    endpoint=CBOE_VIX_URL,
                    parameters={"decision_date": day.isoformat()},
                )
            if not failure.recoverable or attempt == MAX_REQUEST_ATTEMPTS:
                raise failure
            time.sleep(_request_retry_delay(failure, attempt))
        raise AssertionError("VIX retry loop terminated unexpectedly.")

    sip.request_bars = request_bars
    sip.request_qdte_corporate_actions = request_qdte_corporate_actions
    sip._vix_previous_close = bounded_vix
    try:
        yield
    finally:
        sip.request_bars = original_bars
        sip.request_qdte_corporate_actions = original_actions
        sip._vix_previous_close = original_vix


def _cycle(store: IEXResearchStore, observed_at: datetime) -> dict[str, Any]:
    contract = load_contract()
    state = store.reconcile()
    if state is None:
        try:
            state = initialize(store, contract, observed_at)
        except RuntimeError as exc:
            if str(exc) == "No causally completed regular-session QDTE 1-minute bar is available.":
                raise _sparse_data_failure(
                    operation="paper_account_initialization",
                    message=str(exc),
                    parameters={"symbol": "QDTE", "timeframe": "1Min"},
                ) from exc
            raise
    elif state.get("contract_fingerprint") != sip.fingerprint(contract):
        raise RuntimeError("Persisted IEX research strategy identity differs from its contract.")
    if state.get("schema_version") != sip.SCHEMA or state.get("mode") != VARIANT:
        raise RuntimeError("Persisted state is not the IEX forward-research schema.")
    if process_pending_execution_clock(state, store, observed_at):
        state["last_observed_at_utc"] = observed_at.astimezone(timezone.utc).isoformat()
        state["revision"] += 1
        store.save(state)
        store.event("IEX_RESEARCH_PAPER_HEARTBEAT", {
            "revision": state["revision"], "live_broker_enabled": False,
            "execution_clock": "WAITING_FOR_CAUSAL_MINUTE",
        })
        return state
    with _iex_request_scope():
        if corporate_action_poll_due(state, observed_at):
            sip.observe_qdte_corporate_actions(state, store, observed_at)
        if not decision_processing_due(state, observed_at):
            return state
        expected = expected_completed_decision_start(observed_at)
        previous_completed = state.get("last_decision_bar")
        try:
            sip.process_latest_decision(state, store, observed_at)
        except RuntimeError as exc:
            if str(exc).startswith("No completed Alpaca SIP 15-minute decision bars"):
                raise _sparse_data_failure(
                    operation="completed_15m_decision_data",
                    message=str(exc),
                    parameters={"timeframe": "15Min"},
                ) from exc
            if str(exc).startswith("No SIP 1-minute"):
                raise _sparse_data_failure(
                    operation="one_minute_execution_evidence",
                    message=str(exc),
                    parameters={"timeframe": "1Min"},
                ) from exc
            raise
        completed = state.get("last_decision_bar")
        if completed != previous_completed:
            state["last_completed_decision_observed_at_utc"] = (
                datetime.now(timezone.utc).isoformat()
            )
            store.save(state)
        if expected is not None and (
            completed is None or datetime.fromisoformat(str(completed)) < expected
        ):
            raise _sparse_data_failure(
                operation="completed_15m_decision_data",
                message=(
                    "No IEX bar established the expected completed decision boundary."
                ),
                parameters={
                    "timeframe": "15Min",
                    "expected_completed_bar_start": expected.isoformat(),
                    "last_completed_bar_start": completed,
                },
            )
    state["last_observed_at_utc"] = observed_at.astimezone(timezone.utc).isoformat()
    state["revision"] += 1
    store.save(state)
    store.event("IEX_RESEARCH_PAPER_HEARTBEAT", {
        "revision": state["revision"], "live_broker_enabled": False,
    })
    return state


def cycle(runtime: Path, observed_at: datetime | None = None) -> dict[str, Any]:
    store = IEXResearchStore(runtime)
    with store.locked():
        return _cycle(store, observed_at or datetime.now(timezone.utc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if args.poll_seconds < 15:
        raise ValueError("Poll interval must be at least 15 seconds.")
    if not args.daemon:
        state = cycle(args.runtime_dir)
        print(json.dumps({
            "status": VARIANT, "feed": FEED, "revision": state["revision"],
            "live_broker_enabled": False, "sip_parity_claimed": False,
        }, sort_keys=True), flush=True)
        return 0
    store = IEXResearchStore(args.runtime_dir)
    stop_requested = threading.Event()
    with _shutdown_signal_scope(stop_requested), store.locked():
        daemon_started = datetime.now(timezone.utc).isoformat()
        prior_heartbeat = store.read_heartbeat() or {}
        last_provider_contact = prior_heartbeat.get(
            "last_successful_provider_contact_at_utc"
        )
        prior_failure = prior_heartbeat.get("failure") or {}
        prior_provider_state = str(prior_heartbeat.get("provider_state", ""))
        recovering_degraded_state = prior_provider_state in {
            "DEGRADED_RECOVERABLE",
            "BLOCKED_PROVIDER_REQUEST",
        }
        consecutive_failures = (
            int(prior_heartbeat.get("retry_count", 0))
            if recovering_degraded_state
            else 0
        )
        previous_failure_class: str | None = (
            str(prior_failure.get("failure_class"))
            if recovering_degraded_state and prior_failure.get("failure_class")
            else None
        )
        degraded_since: str | None = (
            str(prior_heartbeat.get("degraded_since_at_utc"))
            if recovering_degraded_state
            and prior_heartbeat.get("degraded_since_at_utc")
            else None
        )
        last_status_print = datetime.min.replace(tzinfo=timezone.utc)
        while not stop_requested.is_set():
            observed_at = datetime.now(timezone.utc)
            state: dict[str, Any] | None = None
            try:
                state = _cycle(store, observed_at)
            except ProviderFailure as failure:
                new_degradation = previous_failure_class != failure.failure_class
                if new_degradation:
                    degraded_since = observed_at.isoformat()
                consecutive_failures = (
                    consecutive_failures + 1
                    if previous_failure_class == failure.failure_class
                    else 1
                )
                previous_failure_class = failure.failure_class
                reconciled = store.reconcile()
                last_provider_contact = (
                    _last_successful_provider_contact_utc or last_provider_contact
                )
                backoff = _provider_backoff(
                    failure,
                    consecutive_failures,
                    args.poll_seconds,
                )
                provider_state = (
                    "DEGRADED_RECOVERABLE"
                    if failure.recoverable
                    else "BLOCKED_PROVIDER_REQUEST"
                )
                heartbeat = _heartbeat_payload(
                    daemon_started_at_utc=daemon_started,
                    state=reconciled,
                    provider_state=provider_state,
                    session_state=market_session_state(observed_at),
                    retry_count=consecutive_failures,
                    backoff_seconds=backoff,
                    last_successful_provider_contact_at_utc=last_provider_contact,
                    failure=failure,
                    degraded_since_at_utc=degraded_since,
                )
                store.write_heartbeat(heartbeat)
                if new_degradation:
                    transition_id = sip.fingerprint({
                        "kind": "provider_degraded",
                        "degraded_since_at_utc": degraded_since,
                        "failure_class": failure.failure_class,
                        "operation": failure.operation,
                    })
                    store.event("IEX_RESEARCH_PROVIDER_DEGRADED", {
                        "event_id": transition_id,
                        "revision": reconciled.get("revision") if reconciled else None,
                        "retry_count": consecutive_failures,
                        "backoff_seconds": backoff,
                        **failure.as_dict(),
                    })
                if new_degradation or consecutive_failures % 10 == 0:
                    print(json.dumps({
                        "status": provider_state,
                        "feed": FEED,
                        "revision": reconciled.get("revision") if reconciled else None,
                        "retry_count": consecutive_failures,
                        "backoff_seconds": backoff,
                        "failure": failure.as_dict(),
                        "live_broker_enabled": False,
                        "sip_parity_claimed": False,
                    }, sort_keys=True), flush=True)
                _sleep_with_heartbeat(
                    store,
                    heartbeat,
                    backoff,
                    stop_requested=stop_requested,
                )
                continue
            except Exception as exc:
                try:
                    state = store.reconcile()
                except Exception:
                    state = None
                heartbeat = _heartbeat_payload(
                    daemon_started_at_utc=daemon_started,
                    state=state,
                    provider_state="FAIL_CLOSED_INTEGRITY_OR_CONFIGURATION",
                    session_state=market_session_state(observed_at),
                    retry_count=0,
                    backoff_seconds=0,
                    last_successful_provider_contact_at_utc=(
                        _last_successful_provider_contact_utc or last_provider_contact
                    ),
                    degraded_since_at_utc=degraded_since,
                )
                heartbeat["fatal_exception"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
                store.write_heartbeat(heartbeat)
                raise
            last_provider_contact = (
                _last_successful_provider_contact_utc or last_provider_contact
            )
            if consecutive_failures:
                store.event("IEX_RESEARCH_PROVIDER_RECOVERED", {
                    "event_id": sip.fingerprint({
                        "kind": "provider_recovered",
                        "degraded_since_at_utc": degraded_since,
                    }),
                    "previous_consecutive_failures": consecutive_failures,
                    "previous_failure_class": previous_failure_class,
                    "degraded_since_at_utc": degraded_since,
                    "reconciled_revision": state["revision"],
                })
                consecutive_failures = 0
                previous_failure_class = None
                degraded_since = None
            session_state = market_session_state(observed_at)
            provider_state = (
                "HEALTHY"
                if session_state in {
                    "REGULAR_SESSION",
                    "POST_CLOSE_DECISION_FINALIZATION",
                }
                else session_state
            )
            heartbeat = _heartbeat_payload(
                daemon_started_at_utc=daemon_started,
                state=state,
                provider_state=provider_state,
                session_state=session_state,
                retry_count=0,
                backoff_seconds=args.poll_seconds,
                last_successful_provider_contact_at_utc=last_provider_contact,
                degraded_since_at_utc=None,
            )
            store.write_heartbeat(heartbeat)
            now = datetime.now(timezone.utc)
            if (
                now - last_status_print
            ).total_seconds() >= STATUS_PRINT_SECONDS:
                print(json.dumps({
                    "status": provider_state,
                    "feed": FEED,
                    "revision": state["revision"],
                    "market_session_state": session_state,
                    "live_broker_enabled": False,
                    "sip_parity_claimed": False,
                }, sort_keys=True), flush=True)
                last_status_print = now
            _sleep_with_heartbeat(
                store,
                heartbeat,
                args.poll_seconds,
                stop_requested=stop_requested,
            )


if __name__ == "__main__":
    raise SystemExit(main())
