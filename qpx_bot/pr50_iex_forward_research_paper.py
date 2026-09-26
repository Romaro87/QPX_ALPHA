"""Profile-governed Alpaca SIP forward-paper adapter.

This process has no broker-order client.  An optional canonical read-only
broker-account observer is configuration-gated.  The runner does not claim
qualification, promotion, or production authority.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
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
from qpx_bot.broker_account_provider import (
    BrokerAccountProvider,
    BrokerAccountSnapshot,
    ProviderSelection,
    build_broker_account_provider,
    load_provider_selection,
)
from qpx_bot.market_calendar import is_market_session, market_session, previous_market_session
from qpx_bot.iex_paper_observability import performance
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


VARIANT = "VOLUME_CONFIRMATION_25_ALPACA_SIP_FORWARD_RESEARCH_PAPER_ONLY"
DEFAULT_RUNTIME = sip.ROOT / "runtime/qpx_volume_confirmation_alpaca_sip_forward_paper"
HEARTBEAT_SCHEMA_VERSION = 1
CORPORATE_ACTION_POLL_SECONDS = 900
STATUS_PRINT_SECONDS = 600
MAX_PROVIDER_PAGES = 100
CBOE_VIX_URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
BROKER_PROVIDER_CONFIG_ENV = "QPX_BROKER_ACCOUNT_PROVIDER_CONFIG"
BROKER_RECONCILIATION_MODE = "CANONICAL_BROKER_ACCOUNT_OBSERVATION"
BROKER_RECONCILIATION_POLICY = "BROKER_ANCHORED_SIMULATION_V1"
BROKER_RECONCILIATION_POLL_SECONDS = 300
EXTERNAL_BROKER_RECONCILIATION_EVENT = "EXTERNAL_BROKER_RECONCILIATION"
BROKER_PROVIDER_BASELINE_EVENT = "BROKER_ACCOUNT_PROVIDER_BASELINE_BOUND"
EXTERNAL_BROKER_RISK_BLOCK = "EXTERNAL_BROKER_POSITION_UNMANAGED_FAIL_CLOSED"
OLD_SEMANTIC_CONTRACT_FINGERPRINT = (
    "d594cd578070ab61393411e2cec97803d7c9e62f8061ac3c38f018b26f8fdf5b"
)
PRE_CONFIG_AUTHORITY_CONTRACT_FINGERPRINT = (
    "5fcab69089cbfd069727b754f1ca1be9338500234348fbbc56bf3e5633603c5d"
)
NEW_SEMANTIC_CONTRACT_FINGERPRINT = (
    "ead839eb2b081e5cb4271c52f52673412ce73b56dcd777780c668a10e7a31074"
)
SEMANTIC_VERSION_OLD = "PR50_IEX_PRE_PARITY_V1"
SEMANTIC_VERSION_PARITY = "PR50_IEX_HISTORICAL_CANDIDATE_V1_SPLIT_V2"
SEMANTIC_VERSION_NEW = "PR50_ALPACA_SIP_CANDIDATE_V1_CONFIG_AUTHORITY_V4"
ENTRY_SEMANTICS_VERSION = "CANDIDATE_V1_HISTORICAL_NINE_GATE_V1"
ENTRY_SEMANTICS_FINGERPRINT = sip.fingerprint({
    "implementation": "qpx_bot.strategy.evaluate_entry",
    "qualification_commit": "7213db1e17fedce9e923889b116775cca121f766",
    "gates": (
        "data_ready", "price_above_sma", "sma_slope_positive",
        "average_volume", "breakout_volume", "price_breakout",
        "vix_filter", "rsi_not_overbought", "momentum_trigger",
    ),
})
PROVIDER_INPUT_SEMANTICS_VERSION = "ALPACA_SIP_15M_COMPLETED_SPLIT_V1"
EXECUTION_PHASE_SEMANTICS_VERSION = "AUTHENTIC_OPEN_THEN_COMPLETED_CLOSE_V1"
BAR_ADJUSTMENT_MODE = "split"
SEMANTIC_TRANSITION_EVENT = "CONFIGURATION_VERSION_CHANGED"
MARKET_DATA_AUTHORITY_EVENT = "MARKET_DATA_AUTHORITY_CHANGED"
SUPPORTED_MARKET_DATA_PROVIDER = "alpaca"
REQUIRED_MARKET_DATA_FEED = "sip"
NO_MARKET_DATA_FALLBACK = None
DEFAULT_PAPER_PROFILE = (
    sip.ROOT / "qpx_bot/paper_profiles/volume_confirmation_25_v1.json"
)
PAPER_PROFILE_IDENTITY = "qpx_bot/paper_profiles/volume_confirmation_25_v1.json"


def _feed_identity(provider: str, feed: str) -> str:
    return sip.fingerprint({
        "provider": provider,
        "feed": feed,
        "bar_adjustment": BAR_ADJUSTMENT_MODE,
        "decision_timeframe": "15Min",
        "execution_timeframe": "1Min",
        "fallback": NO_MARKET_DATA_FALLBACK,
    })


def _configured_market_data_authority() -> dict[str, Any]:
    configured_path = os.environ.get("QPX_PAPER_PROFILE", "").strip()
    profile_path = Path(configured_path) if configured_path else DEFAULT_PAPER_PROFILE
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    contract = profile.get("contract")
    if not isinstance(contract, Mapping):
        raise RuntimeError("Paper profile contract is missing.")
    provider = str(contract.get("market_data_provider", "")).strip().lower()
    feed = str(contract.get("feed", "")).strip().lower()
    fallback = contract.get("market_data_fallback", "MISSING")
    if provider != SUPPORTED_MARKET_DATA_PROVIDER:
        raise RuntimeError("Live paper requires the profile-governed Alpaca market-data provider.")
    if feed != REQUIRED_MARKET_DATA_FEED:
        raise RuntimeError("Live paper requires profile-governed Alpaca SIP; IEX is prohibited.")
    if fallback is not NO_MARKET_DATA_FALLBACK:
        raise RuntimeError("Live-paper market-data fallback must be null; substitution is prohibited.")
    return {
        "configured_provider": provider,
        "configured_feed": feed,
        "fallback_feed": None,
        "feed_identity_fingerprint": _feed_identity(provider, feed),
    }


def configured_feed() -> str:
    return str(_configured_market_data_authority()["configured_feed"])


def _preserved_account_payload(state: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "initialization", "initialization_fingerprint", "contributed_capital",
        "cash", "qdte_shares", "qdte_cost", "positions", "pending",
        "tax_reserve_cash", "realized_pnl", "qdte_corporate_actions",
        "invalid_qdte_corporate_actions", "qdte_open_share_snapshots",
        "profit_recycling", "completed_execution_ids",
    )
    return {key: state.get(key) for key in keys}


def _migrate_market_data_contract_if_required(
    state: dict[str, Any], store: "IEXResearchStore",
    contract: Mapping[str, Any], observed_at: datetime,
) -> bool:
    expected = sip.fingerprint(contract)
    if state.get("contract_fingerprint") == expected:
        return False
    persisted = dict(state.get("contract") or {})
    if persisted.get("feed") != "iex" or contract.get("feed") != "sip":
        return False
    if state.get("pending"):
        raise RuntimeError(
            "Market-data authority migration requires no pending IEX-derived signal."
        )
    allowed = {
        "feed", "market_data_provider", "market_data_fallback",
        "feed_identity_fingerprint", "runner_variant", "paper_profile_path",
        "semantic_version", "provider_input_semantics_version",
        "sip_parity_claimed",
    }
    old_comparable = {
        key: (list(value) if key == "symbols" else value)
        for key, value in persisted.items() if key not in allowed
    }
    new_comparable = {
        key: (list(value) if key == "symbols" else value)
        for key, value in contract.items() if key not in allowed
    }
    if old_comparable != new_comparable:
        raise RuntimeError(
            "SIP authority migration would alter non-feed strategy/account contract fields."
        )
    before = _preserved_account_payload(state)
    before_fingerprint = sip.fingerprint(before)
    old_contract_fingerprint = str(state.get("contract_fingerprint"))
    old_mode = state.get("mode")
    authority = {
        **_configured_market_data_authority(),
        "effective_provider_feed": None,
        "sip_entitlement_result": "NOT_YET_VERIFIED",
        "migrated_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
    }
    state["contract"] = json.loads(sip.canonical(contract))
    state["contract_fingerprint"] = expected
    state["semantic_contract_version"] = SEMANTIC_VERSION_NEW
    state["mode"] = str(contract.get("runner_variant", VARIANT))
    state["sip_parity_claimed"] = True
    state["market_data_authority"] = authority
    state["revision"] = int(state["revision"]) + 1
    details = {
        "old_provider": persisted.get("market_data_provider", "alpaca"),
        "old_feed": persisted.get("feed"),
        "new_provider": authority["configured_provider"],
        "new_feed": authority["configured_feed"],
        "fallback_feed": None,
        "old_contract_fingerprint": old_contract_fingerprint,
        "new_contract_fingerprint": expected,
        "old_runner_variant": old_mode,
        "new_runner_variant": state["mode"],
        "account_preservation_fingerprint": before_fingerprint,
        "initialization_fingerprint": state.get("initialization_fingerprint"),
        "candidate_v1_config_fingerprint": state.get("candidate_v1_config_fingerprint"),
        "effective_at_utc": authority["migrated_at_utc"],
        "reason": "HISTORICAL_STRATEGY_MARKET_DATA_AUTHORITY_PARITY",
    }
    store.bind(state)
    store.event(MARKET_DATA_AUTHORITY_EVENT, details)
    store.save(state)
    if _preserved_account_payload(state) != before:
        raise RuntimeError("Account state changed during market-data authority migration.")
    return True


def _sync_effective_market_data_authority(state: dict[str, Any]) -> None:
    configured = _configured_market_data_authority()
    current = dict(state.get("market_data_authority") or {})
    state["market_data_authority"] = {
        **current,
        **configured,
        **dict(_last_effective_market_data_authority or {}),
    }


def _normalize_sip_contract_identity_if_required(
    state: dict[str, Any], store: "IEXResearchStore",
    contract: Mapping[str, Any], observed_at: datetime,
) -> bool:
    expected = sip.fingerprint(contract)
    if state.get("contract_fingerprint") == expected:
        return False
    persisted = dict(state.get("contract") or {})
    if persisted.get("feed") != "sip" or contract.get("feed") != "sip":
        return False
    old_comparable = {
        key: (list(value) if key == "symbols" else value)
        for key, value in persisted.items()
        if key != "paper_profile_path"
    }
    new_comparable = {
        key: (list(value) if key == "symbols" else value)
        for key, value in contract.items()
        if key != "paper_profile_path"
    }
    if old_comparable != new_comparable:
        return False
    before = _preserved_account_payload(state)
    old_fingerprint = str(state.get("contract_fingerprint"))
    state["contract"] = json.loads(sip.canonical(contract))
    state["contract_fingerprint"] = expected
    state["revision"] = int(state["revision"]) + 1
    store.bind(state)
    store.event("PAPER_PROFILE_IDENTITY_NORMALIZED", {
        "old_contract_fingerprint": old_fingerprint,
        "new_contract_fingerprint": expected,
        "old_paper_profile_path": persisted.get("paper_profile_path"),
        "new_paper_profile_identity": contract.get("paper_profile_path"),
        "effective_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "account_preservation_fingerprint": sip.fingerprint(before),
    })
    store.save(state)
    if _preserved_account_payload(state) != before:
        raise RuntimeError("Account state changed during profile identity normalization.")
    return True


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
_last_effective_market_data_authority: dict[str, Any] | None = None


def _record_provider_contact(
    *, provider: str | None = None, parameters: Mapping[str, Any] | None = None,
    endpoint: str | None = None,
) -> None:
    global _last_successful_provider_contact_utc, _last_effective_market_data_authority
    _last_successful_provider_contact_utc = datetime.now(timezone.utc).isoformat()
    if provider == "alpaca" and parameters and parameters.get("feed") is not None:
        configured = _configured_market_data_authority()
        effective = str(parameters["feed"]).strip().lower()
        if effective != configured["configured_feed"]:
            raise RuntimeError("Alpaca returned data for an unauthorized feed request.")
        _last_effective_market_data_authority = {
            **configured,
            "effective_provider_feed": effective,
            "sip_entitlement_result": "AVAILABLE",
            "last_successful_feed_response_at_utc": _last_successful_provider_contact_utc,
            "last_successful_feed_endpoint": endpoint,
        }


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
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    attempts: int = MAX_REQUEST_ATTEMPTS,
) -> Mapping[str, Any]:
    if provider == "alpaca" and parameters.get("feed") is not None:
        configured = _configured_market_data_authority()
        requested = str(parameters["feed"]).strip().lower()
        if requested != configured["configured_feed"]:
            raise ProviderFailure(
                failure_class="MARKET_DATA_AUTHORITY_MISMATCH",
                provider=provider,
                operation=operation,
                endpoint=endpoint,
                recoverable=False,
                exception_type="ConfiguredFeedMismatch",
                message=(
                    f"Requested feed {requested!r} differs from governed feed "
                    f"{configured['configured_feed']!r}; fallback is prohibited."
                ),
                request_parameters=_request_context(parameters),
            )
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
    for attempt in range(1, attempts + 1):
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
                timeout=timeout_seconds,
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
            _record_provider_contact(
                provider=provider, parameters=parameters, endpoint=endpoint
            )
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
        if not failure.recoverable or attempt == attempts:
            raise failure
        time.sleep(_request_retry_delay(failure, attempt))
    raise AssertionError("Provider retry loop terminated unexpectedly.")


def load_contract() -> dict[str, Any]:
    contract = dict(sip.load_contract())
    configured_path = os.environ.get("QPX_PAPER_PROFILE", "").strip()
    profile_path = Path(configured_path) if configured_path else DEFAULT_PAPER_PROFILE
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    contract.update(profile.get("contract", {}))
    contract["paper_profile_path"] = PAPER_PROFILE_IDENTITY
    authority = _configured_market_data_authority()
    contract.update({
        "market_data_provider": authority["configured_provider"],
        "feed": authority["configured_feed"],
        "market_data_fallback": authority["fallback_feed"],
        "feed_identity_fingerprint": authority["feed_identity_fingerprint"],
        "runner_variant": contract.get("runner_variant", VARIANT),
        "research_only": True,
        "sip_parity_claimed": True,
        "qualified": False,
        "promoted": False,
        "semantic_version": SEMANTIC_VERSION_NEW,
        "entry_semantics_version": ENTRY_SEMANTICS_VERSION,
        "entry_semantics_fingerprint": ENTRY_SEMANTICS_FINGERPRINT,
        "bar_adjustment": BAR_ADJUSTMENT_MODE,
        "provider_input_semantics_version": PROVIDER_INPUT_SEMANTICS_VERSION,
        "execution_phase_semantics_version": EXECUTION_PHASE_SEMANTICS_VERSION,
    })
    return contract


def request_bars(
    symbols: tuple[str, ...], timeframe: str, start: datetime, end: datetime
) -> dict[str, list[dict[str, Any]]]:
    feed = configured_feed()
    params = {
        "symbols": ",".join(symbols), "timeframe": timeframe,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        # The frozen qualified dataset is explicitly split-adjusted.  Keep
        # the forward input on the same Alpaca adjustment basis.
        "feed": feed, "adjustment": "split", "limit": "10000", "sort": "asc",
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
            user_agent="QPX-LIVE-PAPER-ALPACA-SIP/1",
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
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ProviderFailure(
                        failure_class="MALFORMED_PROVIDER_RESPONSE",
                        provider="alpaca",
                        operation="market_bars",
                        endpoint=sip.DATA_URL,
                        recoverable=True,
                        exception_type=type(row).__name__,
                        message=f"The bars row for {symbol} is not an object.",
                        request_parameters=_request_context(params),
                    )
                labeled = dict(row)
                labeled["qpx_market_data_provider"] = SUPPORTED_MARKET_DATA_PROVIDER
                labeled["qpx_market_data_feed"] = feed
                labeled["qpx_feed_identity_fingerprint"] = _feed_identity(
                    SUPPORTED_MARKET_DATA_PROVIDER, feed
                )
                collected[symbol].append(labeled)
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
            user_agent="QPX-LIVE-PAPER-ALPACA-SIP/1",
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


def broker_reconciliation_enabled() -> bool:
    return bool(os.environ.get(BROKER_PROVIDER_CONFIG_ENV, "").strip())


def configured_broker_account_provider(
) -> tuple[ProviderSelection, BrokerAccountProvider]:
    raw_path = os.environ.get(BROKER_PROVIDER_CONFIG_ENV, "").strip()
    if not raw_path:
        raise RuntimeError("Broker-account provider configuration is not enabled.")
    selection = load_provider_selection(raw_path)
    if selection.market_data_provider != "ALPACA_SIP":
        raise RuntimeError("Live paper requires the ALPACA_SIP market-data provider.")
    if selection.order_execution_provider != "SIMULATED":
        raise RuntimeError("Clean-V2 permits only the SIMULATED execution provider.")
    return selection, build_broker_account_provider(selection)


def _broker_configuration_fingerprint(selection: ProviderSelection) -> str:
    return sip.fingerprint({
        "policy": BROKER_RECONCILIATION_POLICY,
        "mode": BROKER_RECONCILIATION_MODE,
        "provider_selection_fingerprint": selection.fingerprint,
        "poll_seconds": BROKER_RECONCILIATION_POLL_SECONDS,
        "broker_orders_enabled": False,
        "simulated_strategy_fills_only": True,
    })


def _broker_state(
    state: dict[str, Any], selection: ProviderSelection
) -> dict[str, Any]:
    expected = _broker_configuration_fingerprint(selection)
    existing = state.get("broker_reconciliation")
    if existing is None:
        existing = {
            "schema_version": 1,
            "policy_identity": BROKER_RECONCILIATION_POLICY,
            "configuration_fingerprint": expected,
            "mode": BROKER_RECONCILIATION_MODE,
            "market_data_provider": selection.market_data_provider,
            "broker_account_provider": selection.broker_account_provider,
            "order_execution_provider": selection.order_execution_provider,
            "poll_seconds": BROKER_RECONCILIATION_POLL_SECONDS,
            "broker_orders_enabled": False,
            "simulated_strategy_fills_only": True,
            "last_observed_at_utc": None,
            "last_snapshot": None,
            "last_applied_identity_fingerprint": None,
            "last_reconciliation_id": None,
            "initial_binding_id": None,
            "reconciliation_count": 0,
            "external_account_cash_delta_total": 0.0,
            "external_positions": {},
            "risk_block_reason": None,
        }
        state["broker_reconciliation"] = existing
    if (
        existing.get("configuration_fingerprint") != expected
        or existing.get("mode") != BROKER_RECONCILIATION_MODE
        or existing.get("market_data_provider") != selection.market_data_provider
        or existing.get("broker_account_provider") != selection.broker_account_provider
        or existing.get("order_execution_provider") != "SIMULATED"
        or existing.get("broker_orders_enabled") is not False
    ):
        raise RuntimeError("Persisted broker-reconciliation identity is incompatible.")
    return existing


def broker_reconciliation_due(
    state: Mapping[str, Any], observed_at: datetime, *, force: bool = False
) -> bool:
    if force:
        return True
    broker = state.get("broker_reconciliation")
    if not isinstance(broker, Mapping) or not broker.get("last_observed_at_utc"):
        return True
    return (
        observed_at.astimezone(timezone.utc)
        - datetime.fromisoformat(str(broker["last_observed_at_utc"]))
    ).total_seconds() >= BROKER_RECONCILIATION_POLL_SECONDS


def _flush_pending_broker_reconciliation(
    state: dict[str, Any], store: "IEXResearchStore"
) -> bool:
    flushed = False
    for key, event_type in (
        ("broker_provider_baseline_event_pending", BROKER_PROVIDER_BASELINE_EVENT),
        ("broker_reconciliation_event_pending", EXTERNAL_BROKER_RECONCILIATION_EVENT),
    ):
        details = state.get(key)
        if details is None:
            continue
        store.event(event_type, details)
        state.pop(key, None)
        store.save(state)
        flushed = True
    return flushed


def _flush_pending_semantic_transition(
    state: dict[str, Any], store: "IEXResearchStore"
) -> bool:
    details = state.get("semantic_transition_event_pending")
    if details is None:
        return False
    store.event(SEMANTIC_TRANSITION_EVENT, details)
    state.pop("semantic_transition_event_pending", None)
    store.save(state)
    return True


def _next_decision_boundary(state: Mapping[str, Any], observed_at: datetime) -> str:
    last = state.get("last_decision_bar")
    if last:
        return (datetime.fromisoformat(str(last)) + timedelta(minutes=15)).isoformat()
    expected = expected_completed_decision_start(observed_at)
    return (expected or observed_at.astimezone(timezone.utc)).isoformat()


def _transition_semantic_contract_if_required(
    state: dict[str, Any],
    store: "IEXResearchStore",
    contract: Mapping[str, Any],
    observed_at: datetime,
) -> bool:
    current = str(state.get("contract_fingerprint", ""))
    expected = sip.fingerprint(contract)
    if current == expected:
        return False
    if current not in {
        OLD_SEMANTIC_CONTRACT_FINGERPRINT,
        PRE_CONFIG_AUTHORITY_CONTRACT_FINGERPRINT,
    }:
        raise RuntimeError("Persisted semantic contract is not an allowlisted predecessor.")
    if (
        str(contract.get("semantic_version")) != SEMANTIC_VERSION_NEW
        or contract.get("entry_semantics_version") != ENTRY_SEMANTICS_VERSION
        or contract.get("entry_semantics_fingerprint") != ENTRY_SEMANTICS_FINGERPRINT
        or contract.get("bar_adjustment") != BAR_ADJUSTMENT_MODE
        or contract.get("provider_input_semantics_version") != PROVIDER_INPUT_SEMANTICS_VERSION
    ):
        raise RuntimeError("Executable semantic contract is not the allowlisted NEW contract.")
    if store.reconcile() is None:
        raise RuntimeError("Semantic transition requires an existing validated runtime state.")
    if not state.get("initialization_fingerprint"):
        raise RuntimeError("Semantic transition requires a preserved initialization identity.")
    if state.get("positions") or state.get("pending"):
        raise RuntimeError("Semantic transition requires no open positions or pending actions.")
    if not broker_reconciliation_enabled():
        raise RuntimeError("Semantic transition requires the DUMMY broker observation to be enabled.")
    broker = state.get("broker_reconciliation") or {}
    if broker.get("broker_account_provider") != "DUMMY":
        raise RuntimeError("Semantic transition requires the configured DUMMY broker provider.")
    if broker.get("risk_block_reason"):
        raise RuntimeError("Semantic transition blocked by unresolved broker risk state.")
    snapshot = broker.get("last_snapshot") or {}
    if snapshot.get("provider_identity") != "DUMMY":
        raise RuntimeError("Semantic transition requires a bound DUMMY observation.")
    if not snapshot.get("account_identity_fingerprint"):
        raise RuntimeError("Semantic transition broker/account identity is not bound.")
    if snapshot.get("account_status") != "ACTIVE" or snapshot.get("account_blocked") or snapshot.get("trading_blocked"):
        raise RuntimeError("Semantic transition requires a valid active DUMMY account.")
    before = int(state["revision"])
    details = {
        "event_id": sip.fingerprint({
            "kind": "semantic_contract_transition",
            "old_contract_fingerprint": current,
            "new_contract_fingerprint": expected,
            "initialization_fingerprint": state.get("initialization_fingerprint"),
        }),
        "old_contract_fingerprint": current,
        "new_contract_fingerprint": expected,
        "old_semantic_version": (
            SEMANTIC_VERSION_OLD
            if current == OLD_SEMANTIC_CONTRACT_FINGERPRINT
            else SEMANTIC_VERSION_PARITY
        ),
        "new_semantic_version": SEMANTIC_VERSION_NEW,
        "effective_observation_timestamp_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "first_decision_boundary_governed_by_new_contract": _next_decision_boundary(state, observed_at),
        "reason": "CANDIDATE_V1_JSON_CONFIGURATION_AUTHORITY",
        "entry_semantics_version": ENTRY_SEMANTICS_VERSION,
        "entry_semantics_fingerprint": ENTRY_SEMANTICS_FINGERPRINT,
        "bar_adjustment_old": "raw",
        "bar_adjustment_new": BAR_ADJUSTMENT_MODE,
        "provider_input_semantics_version": PROVIDER_INPUT_SEMANTICS_VERSION,
        "revision_before": before,
        "revision_after": before + 1,
        "positions_zero": True,
        "pending_actions_zero": True,
        "initialization_fingerprint": state.get("initialization_fingerprint"),
    }
    state["contract"] = json.loads(sip.canonical(contract))
    state["contract_fingerprint"] = expected
    state["semantic_contract_version"] = SEMANTIC_VERSION_NEW
    state["semantic_transition_event_pending"] = details
    state["revision"] = before + 1
    store.save(state)
    _flush_pending_semantic_transition(state, store)
    return True


def _broker_risk_block_reason(
    snapshot: BrokerAccountSnapshot,
    *,
    managed_strategy_symbols: frozenset[str] = frozenset(),
) -> str | None:
    if snapshot.account_status != "ACTIVE":
        return "BROKER_ACCOUNT_NOT_ACTIVE_FAIL_CLOSED"
    if snapshot.account_blocked or snapshot.trading_blocked:
        return "BROKER_ACCOUNT_BLOCKED_FAIL_CLOSED"
    if snapshot.restriction_flags:
        return "BROKER_ACCOUNT_RESTRICTED_FAIL_CLOSED"
    external = [
        position for position in snapshot.positions
        if (
            position.symbol != "QDTE"
            and position.symbol not in managed_strategy_symbols
        )
        or position.side != "long"
    ]
    if external:
        return EXTERNAL_BROKER_RISK_BLOCK
    return None


def _initial_broker_compatibility_mismatches(
    state: Mapping[str, Any], snapshot: BrokerAccountSnapshot
) -> list[str]:
    mismatches: list[str] = []
    if snapshot.account_status != "ACTIVE":
        mismatches.append("ACCOUNT_NOT_ACTIVE")
    if snapshot.currency != "USD":
        mismatches.append("CURRENCY_MISMATCH")
    if snapshot.account_blocked or snapshot.trading_blocked or snapshot.restriction_flags:
        mismatches.append("ACCOUNT_RESTRICTED")
    expected_cash = float(state["cash"]) + float(state.get("tax_reserve_cash", 0.0))
    if abs(float(snapshot.cash) - expected_cash) > 1e-7:
        mismatches.append("CASH_MISMATCH")

    expected_positions: dict[str, tuple[float, float]] = {}
    qdte_shares = float(state.get("qdte_shares", 0.0))
    if qdte_shares > 0:
        expected_positions["QDTE"] = (
            qdte_shares,
            float(state.get("qdte_cost", 0.0)),
        )
    for symbol, position in state.get("positions", {}).items():
        shares = float(position["shares"])
        expected_positions[str(symbol).upper()] = (
            shares,
            shares * float(position["entry_price"]),
        )
    observed_positions = {position.symbol: position for position in snapshot.positions}
    if set(observed_positions) != set(expected_positions):
        mismatches.append("POSITION_SYMBOLS_MISMATCH")
    for symbol in sorted(set(observed_positions) & set(expected_positions)):
        observed = observed_positions[symbol]
        expected_quantity, expected_cost = expected_positions[symbol]
        if observed.side != "long" or abs(float(observed.quantity) - expected_quantity) > 1e-9:
            mismatches.append(f"POSITION_QUANTITY_MISMATCH:{symbol}")
        if observed.cost_basis is not None and (
            abs(float(observed.cost_basis) - expected_cost) > 1e-6
        ):
            mismatches.append(f"POSITION_COST_BASIS_MISMATCH:{symbol}")
    return mismatches


def _bind_initial_broker_snapshot(
    state: dict[str, Any],
    store: "IEXResearchStore",
    snapshot: BrokerAccountSnapshot,
    selection: ProviderSelection,
) -> bool:
    mismatches = _initial_broker_compatibility_mismatches(state, snapshot)
    if mismatches:
        raise ProviderFailure(
            failure_class="BROKER_INITIAL_STATE_INCOMPATIBLE",
            provider=snapshot.provider_identity.lower(),
            operation="broker_account_initial_binding",
            endpoint=f"broker-account-provider:{snapshot.provider_identity}",
            recoverable=False,
            exception_type="BrokerInitialCompatibilityError",
            message="Initial broker snapshot differs from authoritative QPX account state.",
            request_parameters={"mismatch_codes": mismatches},
        )
    broker = _broker_state(state, selection)
    revision_before = int(state["revision"])
    binding_id = sip.fingerprint({
        "kind": "broker_account_provider_baseline",
        "provider_selection_fingerprint": selection.fingerprint,
        "account_identity_fingerprint": snapshot.account_identity_fingerprint,
        "broker_identity_fingerprint": snapshot.identity_fingerprint,
        "contract_fingerprint": state["contract_fingerprint"],
    })
    broker["last_observed_at_utc"] = snapshot.observed_at_utc.isoformat()
    broker["last_snapshot"] = snapshot.as_dict()
    broker["last_applied_identity_fingerprint"] = snapshot.identity_fingerprint
    broker["initial_binding_id"] = binding_id
    broker["external_positions"] = {}
    broker["risk_block_reason"] = None
    state["revision"] = revision_before + 1
    state["broker_provider_baseline_event_pending"] = {
        "event_id": binding_id,
        "binding_id": binding_id,
        "result": "COMPATIBLE_NO_ACCOUNT_RECONCILIATION",
        "market_data_provider": selection.market_data_provider,
        "broker_account_provider": selection.broker_account_provider,
        "order_execution_provider": selection.order_execution_provider,
        "account_identity_fingerprint": snapshot.account_identity_fingerprint,
        "broker_identity_fingerprint": snapshot.identity_fingerprint,
        "broker_observed_at_utc": snapshot.observed_at_utc.isoformat(),
        "cash": float(snapshot.cash),
        "positions": [position.as_dict() for position in snapshot.positions],
        "revision_before": revision_before,
        "revision_after": state["revision"],
        "broker_orders_enabled": False,
    }
    store.save(state)
    _flush_pending_broker_reconciliation(state, store)
    return False


def _reconcile_confirmed_broker_snapshot(
    state: dict[str, Any],
    store: "IEXResearchStore",
    snapshot: BrokerAccountSnapshot,
    selection: ProviderSelection,
) -> bool:
    broker = _broker_state(state, selection)
    snapshot_dict = snapshot.as_dict()
    previous_snapshot = broker.get("last_snapshot")
    previous_identity = broker.get("last_applied_identity_fingerprint")
    identity = snapshot.identity_fingerprint
    account_identity = snapshot.account_identity_fingerprint
    if previous_snapshot is not None and (
        str(previous_snapshot.get("account_identity_fingerprint")) != account_identity
    ):
        raise RuntimeError("Broker account identity changed; refusing cross-account recovery.")
    if previous_identity is None:
        return _bind_initial_broker_snapshot(state, store, snapshot, selection)
    broker["last_observed_at_utc"] = snapshot.observed_at_utc.isoformat()
    broker["last_snapshot"] = snapshot_dict
    if identity == previous_identity:
        store.save(state)
        return False

    broker_cash = float(snapshot.cash)
    tax_reserve = float(state.get("tax_reserve_cash", 0.0))
    withheld = float(
        state.get("profit_recycling", {}).get("ledger", {}).get(
            "withheld_profit_balance", 0.0
        )
    )
    if broker_cash < -1e-9 or broker_cash + 1e-9 < tax_reserve + withheld:
        raise ProviderFailure(
            failure_class="BROKER_ACCOUNT_CASH_INCOMPATIBLE",
            provider=snapshot.provider_identity.lower(),
            operation="broker_account_reconciliation",
            endpoint=f"broker-account-provider:{snapshot.provider_identity}",
            recoverable=False,
            exception_type="BrokerAccountingConflict",
            message="Broker cash cannot preserve the existing tax/withheld separation.",
            request_parameters={},
        )

    revision_before = int(state["revision"])
    cash_before = float(state["cash"])
    qdte_shares_before = float(state.get("qdte_shares", 0.0))
    managed_positions_before = {
        symbol: dict(position) for symbol, position in state.get("positions", {}).items()
    }
    strategy_realized_before = float(state.get("realized_pnl", 0.0))
    contributed_before = float(state.get("contributed_capital", 0.0))
    profit_ledger_before = sip.fingerprint(state.get("profit_recycling", {}))
    invalidated_pending: list[dict[str, str]] = []
    for symbol, signal in sorted(state.get("pending", {}).items()):
        execution_id = _entry_execution_id(state, symbol, signal)
        if execution_id not in state["completed_execution_ids"]:
            state["completed_execution_ids"].append(execution_id)
        invalidated_pending.append({
            "symbol": symbol,
            "signal_id": str(signal["signal_id"]),
            "execution_id": execution_id,
            "reason": "EXTERNAL_BROKER_ACCOUNT_CHANGE_INVALIDATED_PENDING_ACTION",
        })
    state["pending"] = {}

    qdte_position = next(
        (
            position for position in snapshot.positions
            if position.symbol == "QDTE" and position.side == "long"
        ),
        None,
    )
    state["qdte_shares"] = float(qdte_position.quantity) if qdte_position else 0.0
    state["qdte_cost"] = (
        float(
            qdte_position.cost_basis
            if qdte_position.cost_basis is not None
            else qdte_position.quantity * qdte_position.average_entry_price
        )
        if qdte_position
        else 0.0
    )
    state["cash"] = max(0.0, broker_cash - tax_reserve)
    observed_by_symbol = {position.symbol: position for position in snapshot.positions}
    preserved_managed_positions: dict[str, dict[str, Any]] = {}
    for symbol, managed in managed_positions_before.items():
        observed = observed_by_symbol.get(str(symbol).upper())
        expected_quantity = float(managed["shares"])
        expected_cost = expected_quantity * float(managed["entry_price"])
        if (
            observed is not None
            and observed.side == "long"
            and abs(float(observed.quantity) - expected_quantity) <= 1e-9
            and (
                observed.cost_basis is None
                or abs(float(observed.cost_basis) - expected_cost) <= 1e-6
            )
        ):
            preserved_managed_positions[str(symbol).upper()] = managed
    state["positions"] = preserved_managed_positions
    external_positions = {
        position.symbol: position.as_dict()
        for position in snapshot.positions
        if (
            position is not qdte_position
            and position.symbol not in preserved_managed_positions
        )
    }
    broker["external_positions"] = external_positions
    broker["risk_block_reason"] = _broker_risk_block_reason(
        snapshot,
        managed_strategy_symbols=frozenset(preserved_managed_positions),
    )
    previous_broker_cash = (
        float(previous_snapshot["cash"]) if previous_snapshot is not None else None
    )
    broker_cash_delta = (
        broker_cash - previous_broker_cash if previous_broker_cash is not None else 0.0
    )
    broker["external_account_cash_delta_total"] = float(
        broker.get("external_account_cash_delta_total", 0.0)
    ) + broker_cash_delta
    broker["last_applied_identity_fingerprint"] = identity
    broker["reconciliation_count"] = int(broker.get("reconciliation_count", 0)) + 1
    state["revision"] = revision_before + 1
    reconciliation_id = sip.fingerprint({
        "kind": "external_broker_reconciliation",
        "account_identity_fingerprint": account_identity,
        "previous_identity_fingerprint": previous_identity,
        "identity_fingerprint": identity,
        "revision": state["revision"],
        "contract_fingerprint": state["contract_fingerprint"],
    })
    broker["last_reconciliation_id"] = reconciliation_id
    cash_classification = (
        "INITIAL_BROKER_AUTHORITY_ADOPTION"
        if previous_snapshot is None
        else (
            "NO_BROKER_CASH_CHANGE"
            if abs(broker_cash_delta) <= 1e-9
            else "EXTERNAL_ACCOUNT_CASH_CHANGE_UNCLASSIFIED_NOT_STRATEGY_PNL"
        )
    )
    event = {
        "event_id": reconciliation_id,
        "reconciliation_id": reconciliation_id,
        "source": f"{snapshot.provider_identity}_CANONICAL_BROKER_OBSERVATION_ONLY",
        "operator_origin": "EXTERNAL_OR_OPERATOR_ORIGINATED_ACCOUNT_CHANGE",
        "broker_orders_submitted": False,
        "account_identity_fingerprint": account_identity,
        "previous_broker_identity_fingerprint": previous_identity,
        "broker_identity_fingerprint": identity,
        "broker_observed_at_utc": snapshot.observed_at_utc.isoformat(),
        "market_data_provider": selection.market_data_provider,
        "broker_account_provider": selection.broker_account_provider,
        "order_execution_provider": selection.order_execution_provider,
        "broker_cash": broker_cash,
        "broker_equity": float(snapshot.equity) if snapshot.equity is not None else None,
        "broker_buying_power": (
            float(snapshot.buying_power) if snapshot.buying_power is not None else None
        ),
        "broker_cash_delta_from_previous_snapshot": broker_cash_delta,
        "cash_change_classification": cash_classification,
        "working_cash_before": cash_before,
        "working_cash_after": state["cash"],
        "strategy_tax_reserve_preserved": tax_reserve,
        "qdte_shares_before": qdte_shares_before,
        "qdte_shares_after": state["qdte_shares"],
        "managed_strategy_positions_before": managed_positions_before,
        "managed_strategy_positions_after": preserved_managed_positions,
        "authoritative_broker_positions_after": [
            position.as_dict() for position in snapshot.positions
        ],
        "external_broker_positions_after": external_positions,
        "invalidated_pending_actions": invalidated_pending,
        "strategy_realized_pnl_before": strategy_realized_before,
        "strategy_realized_pnl_after": float(state.get("realized_pnl", 0.0)),
        "contributed_capital_before": contributed_before,
        "contributed_capital_after": float(state.get("contributed_capital", 0.0)),
        "profit_recycling_state_before": profit_ledger_before,
        "profit_recycling_state_after": sip.fingerprint(state.get("profit_recycling", {})),
        "risk_block_reason": broker["risk_block_reason"],
        "revision_before": revision_before,
        "revision_after": state["revision"],
    }
    state["broker_reconciliation_event_pending"] = event
    store.save(state)
    _flush_pending_broker_reconciliation(state, store)
    return True


def observe_and_reconcile_broker_account(
    state: dict[str, Any],
    store: "IEXResearchStore",
    observed_at: datetime,
    *,
    force: bool = False,
    selection: ProviderSelection | None = None,
    provider: BrokerAccountProvider | None = None,
) -> bool:
    _flush_pending_broker_reconciliation(state, store)
    if selection is None or provider is None:
        if not broker_reconciliation_enabled():
            return False
        selection, provider = configured_broker_account_provider()
    if provider.provider_identity != selection.broker_account_provider:
        raise RuntimeError("Configured broker provider identity is inconsistent.")
    broker = _broker_state(state, selection)
    if not broker_reconciliation_due(state, observed_at, force=force):
        return False
    candidate = _observe_broker_provider(provider, observed_at)
    previous_identity = broker.get("last_applied_identity_fingerprint")
    if candidate.identity_fingerprint != previous_identity:
        confirmation = _observe_broker_provider(provider, datetime.now(timezone.utc))
        if confirmation.identity_fingerprint != candidate.identity_fingerprint:
            raise ProviderFailure(
                failure_class="BROKER_SNAPSHOT_UNSTABLE",
                provider=provider.provider_identity.lower(),
                operation="broker_account_reconciliation",
                endpoint=f"broker-account-provider:{provider.provider_identity}",
                recoverable=True,
                exception_type="BrokerSnapshotRace",
                message="Broker cash/position identity changed during confirmation.",
                request_parameters={},
            )
        candidate = confirmation
    return _reconcile_confirmed_broker_snapshot(
        state,
        store,
        candidate,
        selection,
    )


def _observe_broker_provider(
    provider: BrokerAccountProvider, observed_at: datetime
) -> BrokerAccountSnapshot:
    try:
        snapshot = provider.observe(observed_at)
    except ProviderFailure:
        raise
    except Exception as exc:
        raise ProviderFailure(
            failure_class="BROKER_ACCOUNT_PROVIDER_FAILURE",
            provider=provider.provider_identity.lower(),
            operation="broker_account_observation",
            endpoint=f"broker-account-provider:{provider.provider_identity}",
            recoverable=True,
            exception_type=type(exc).__name__,
            message=str(exc),
            request_parameters={},
        ) from exc
    if not isinstance(snapshot, BrokerAccountSnapshot):
        raise RuntimeError("Broker provider returned a non-canonical snapshot.")
    if snapshot.provider_identity != provider.provider_identity:
        raise RuntimeError("Broker snapshot provider identity is inconsistent.")
    _record_provider_contact()
    return snapshot


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
        self.bound_state: dict[str, Any] | None = None

    def bind(self, state: dict[str, Any]) -> None:
        self.bound_state = state

    def save(self, state: dict[str, Any]) -> None:
        # Commit account + outcome together before delivering idempotent audit.
        super().save(state)
        for item in state.get("audit_outbox", []):
            super().event(item["event_type"], item["details"])
        if state.get("audit_outbox"):
            state["audit_outbox"] = []
            super().save(state)

    def publish_metrics(self, state: dict[str, Any], observed_at: datetime) -> None:
        self.save(state)
        records = [json.loads(line) for line in self.journal.read_text().splitlines() if line.strip()]
        report = performance(state, records, observed_at, sip.NY)
        authority = dict(state.get("market_data_authority") or {})
        report["market_data_authority"] = authority
        report["current"].update({
            "configured_market_data_feed": authority.get("configured_feed"),
            "effective_provider_feed": authority.get("effective_provider_feed"),
            "feed_identity_fingerprint": authority.get("feed_identity_fingerprint"),
            "sip_entitlement_result": authority.get("sip_entitlement_result"),
        })
        if "profit_recycling" in state and "contributed_capital" in state:
            runtime = sip._profit_runtime(state)
            sequence = state["profit_recycling"]["current_event_sequence"]
            report["current"]["deployable_cash"] = runtime.ledger.available_swing_cash(state["cash"], sequence)
        else:
            report["current"]["deployable_cash"] = None
        report["current"].update({key: value for key, value in report["account_to_date"].items()
                                  if key not in {"dividends_recorded", "dividends_released"}})
        state["account_metrics"] = report["current"]
        state["performance"] = report
        self.save(state)
        write_checksummed_state(
            self.directory / "iex_research_paper_performance.json",
            self.directory / "iex_research_paper_performance.sha256",
            json.dumps(report, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n",
        )

    def event(self, event_type: str, details: Mapping[str, Any]) -> bool:
        labeled = dict(details)
        authority = _configured_market_data_authority()
        labeled.update({
            "runner_variant": VARIANT,
            "configured_market_data_feed": authority["configured_feed"],
            "market_data_feed": authority["configured_feed"],
            "feed_identity_fingerprint": authority["feed_identity_fingerprint"],
        })
        if self.bound_state is not None:
            item = {"event_type": event_type, "details": labeled}
            outbox = self.bound_state.setdefault("audit_outbox", [])
            if item not in outbox:
                outbox.append(item)
            return True
        return super().event(event_type, labeled)

    def read_heartbeat(self) -> dict[str, Any] | None:
        if not self.heartbeat.exists():
            if self.heartbeat_checksum.exists():
                raise RuntimeError(
                    "Live-paper heartbeat is missing while its checksum exists."
                )
            return None
        encoded = read_checksummed_state(
            self.heartbeat,
            self.heartbeat_checksum,
            label="live-paper heartbeat",
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise RuntimeError("Live-paper heartbeat root must be an object.")
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
        self.bound_state = None
        state = super().reconcile()
        self.read_heartbeat()
        if state is not None and state.get("audit_outbox"):
            self.save(state)
        return state


def implementation_fingerprint() -> str:
    paths = (Path(__file__), Path(sip.__file__), Path(__file__).with_name("iex_paper_observability.py"))
    return sip.fingerprint({p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})


def request_authentic_open(symbol: str, eligible: datetime, observed_at: datetime) -> dict[str, Any] | None:
    """First minute-open-eligible SIP trade, acquired during that same minute.

    Alpaca market-data FAQ: most restrictive condition wins; unknown conditions
    fail closed. Never use a completed bar obtained after the execution window.
    """
    end = eligible + timedelta(minutes=1)
    if not eligible <= observed_at < end:
        return None
    feed = configured_feed()
    parameters = {"start": eligible.isoformat(), "end": observed_at.isoformat(),
                  "feed": feed, "sort": "asc", "limit": 10000}
    allowed = {"A": set(" EFKLOTX56"), "B": set(" EFKLOTX56"), "C": set("@ABDFKLOTXY56")}
    for _ in range(3):
        payload = _request_json(provider="alpaca", operation="authentic_minute_open",
                                endpoint=f"https://data.alpaca.markets/v2/stocks/{urllib.parse.quote(symbol, safe='')}/trades",
                                parameters=parameters, user_agent="QPX-SIP-causal-open",
                                timeout_seconds=2, attempts=1)
        received = datetime.now(timezone.utc)
        if received >= end:
            return None
        trades = payload.get("trades") or []
        prior = eligible
        for trade in trades:
            timestamp = sip._parse(str(trade["t"])).astimezone(timezone.utc)
            if timestamp < prior or timestamp > observed_at:
                raise RuntimeError("SIP trade sequence violates causal request bounds.")
            prior = timestamp
            conditions = trade.get("c")
            tape = str(trade.get("z", ""))
            if not conditions or tape not in allowed or not set(conditions) <= allowed[tape]:
                continue
            price = float(trade["p"])
            if not math.isfinite(price) or price <= 0 or float(trade["s"]) <= 0:
                raise RuntimeError("Invalid SIP open trade price/size.")
            return {"t": eligible.isoformat(), "o": price, "trade": trade,
                    "observed_at_utc": received.isoformat(),
                    "market_data_provider": SUPPORTED_MARKET_DATA_PROVIDER,
                    "feed": feed,
                    "feed_identity_fingerprint": _feed_identity(SUPPORTED_MARKET_DATA_PROVIDER, feed),
                    "price_source": "ALPACA_SIP_FIRST_ELIGIBLE_TRADE", "causal_status": "OBSERVED_WITHIN_ELIGIBLE_MINUTE"}
        token = payload.get("next_page_token")
        if not token:
            return None
        parameters["page_token"] = token
    raise RuntimeError("SIP open trade pagination bound exceeded; no open assumed.")


def refresh_account_marks(state: dict[str, Any], observed_at: datetime) -> None:
    symbols = tuple(dict.fromkeys(("QDTE", *state["positions"])))
    raw = request_bars(symbols, "15Min", observed_at - timedelta(days=7), observed_at)
    marks = state.setdefault("account_marks", {})
    for symbol in symbols:
        rows = sip._completed_15m(raw.get(symbol, []), observed_at)
        if rows:
            row = rows[-1]
            marks[symbol] = {"price": row["close"], "market_data_timestamp": (row["start"] + timedelta(minutes=15)).astimezone(timezone.utc).isoformat(),
                             "observed_at_utc": observed_at.isoformat(), "source": "ALPACA_SIP_COMPLETED_15M_CLOSE",
                             "feed": configured_feed(),
                             "feed_identity_fingerprint": _feed_identity(SUPPORTED_MARKET_DATA_PROVIDER, configured_feed())}
    state["last_account_mark_refresh_at_utc"] = observed_at.isoformat()


def select_causal_execution_bar(
    rows: list[dict[str, Any]], observed_at: datetime
) -> dict[str, Any]:
    result = dict(sip.select_causal_execution_bar(rows, observed_at))
    result["feed"] = configured_feed()
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
    session = market_session(market.date())
    if market < session.regular_open:
        return "PRE_MARKET"
    if market < session.regular_open + timedelta(minutes=15):
        return "OPEN_NO_COMPLETED_DECISION_BAR"
    if market < session.regular_close:
        return "REGULAR_SESSION"
    if market < session.regular_close + timedelta(minutes=15):
        return "POST_CLOSE_DECISION_FINALIZATION"
    return "AFTER_HOURS"


def expected_completed_decision_start(observed_at: datetime) -> datetime | None:
    market = observed_at.astimezone(sip.NY)
    phase = market_session_state(observed_at)
    if phase == "POST_CLOSE_DECISION_FINALIZATION":
        return market_session(market.date()).regular_close - timedelta(minutes=15)
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
        exception_type="SparseSIPData",
        message=message,
        request_parameters={"feed": configured_feed(), **dict(parameters)},
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
    broker = state.get("broker_reconciliation", {}) if state else {}
    broker_snapshot = broker.get("last_snapshot") or {}
    configured_authority = _configured_market_data_authority()
    effective_authority = dict(_last_effective_market_data_authority or {})
    persisted_authority = dict(state.get("market_data_authority") or {}) if state else {}
    market_data_authority = {
        **configured_authority,
        **persisted_authority,
        **effective_authority,
    }
    if failure and failure.request_parameters.get("feed") == REQUIRED_MARKET_DATA_FEED:
        market_data_authority.update({
            "effective_provider_feed": None,
            "sip_entitlement_result": (
                "UNAVAILABLE_PERMISSION" if failure.failure_class == "AUTHENTICATION_PERMISSION_FAILURE"
                else "UNAVAILABLE_PROVIDER"
            ),
            "availability_failure": failure.as_dict(),
        })
    return {
        "schema_version": HEARTBEAT_SCHEMA_VERSION,
        "implementation_fingerprint": implementation_fingerprint(),
        "account_metrics": state.get("account_metrics") if state else None,
        "performance": state.get("performance") if state else None,
        "minute_observer": state.get("minute_observer") if state else None,
        "last_authentic_open_phase": state.get("last_authentic_open_phase") if state else None,
        "last_open_phase_error": state.get("last_open_phase_error") if state else None,
        "runner_variant": state.get("mode", VARIANT) if state else VARIANT,
        "market_data_provider": configured_authority["configured_provider"],
        "configured_market_data_feed": configured_authority["configured_feed"],
        "effective_provider_feed": market_data_authority.get("effective_provider_feed"),
        "feed_identity_fingerprint": configured_authority["feed_identity_fingerprint"],
        "sip_entitlement_result": market_data_authority.get("sip_entitlement_result", "NOT_YET_VERIFIED"),
        "market_data_authority": market_data_authority,
        "market_data_feed": configured_authority["configured_feed"],
        "research_only": True,
        "live_broker_enabled": False,
        "simulated_fills_only": True,
        "maximum_position_notional_fraction": (
            state.get("contract", {}).get("maximum_position_notional_fraction")
            if state else None
        ),
        "candidate_v1_config_fingerprint": (
            state.get("candidate_v1_config_fingerprint") if state else None
        ),
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
        "broker_reconciliation": {
            "enabled": broker_reconciliation_enabled(),
            "mode": broker.get("mode"),
            "market_data_provider": broker.get("market_data_provider"),
            "broker_account_provider": broker.get("broker_account_provider"),
            "order_execution_provider": broker.get("order_execution_provider"),
            "broker_orders_enabled": False,
            "last_observed_at_utc": broker.get("last_observed_at_utc"),
            "last_reconciliation_id": broker.get("last_reconciliation_id"),
            "reconciliation_count": broker.get("reconciliation_count", 0),
            "account_identity_fingerprint": broker_snapshot.get(
                "account_identity_fingerprint"
            ),
            "broker_cash": broker_snapshot.get("cash"),
            "broker_equity": broker_snapshot.get("equity"),
            "broker_buying_power": broker_snapshot.get("buying_power"),
            "broker_position_count": len(broker_snapshot.get("positions", [])),
            "risk_block_reason": broker.get("risk_block_reason"),
        },
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
    store.bind(state)
    store.event("LIVE_PAPER_ENTRY_EXECUTION_MISSED", {
        "symbol": symbol, "signal_id": signal["signal_id"],
        "execution_id": execution_id, "reason": reason,
        "decision_observed_at_utc": signal["decision_observed_at_utc"],
        "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
        "missed_recorded_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "signal_boundary": signal.get("decision_bar_interval"),
        "execution_window_observed_at_utc": signal.get("execution_window_observed_at_utc"),
        "last_open_observation_error": signal.get("last_open_observation_error"),
        "last_open_attempt_at_utc": signal.get("last_open_attempt_at_utc"),
        "authentic_open": signal.get("authentic_open"),
        "execution_observed_at_utc": (signal.get("authentic_open") or {}).get("observed_at_utc"),
        "price_source": (signal.get("authentic_open") or {}).get("price_source"),
        "causal_status": "NO_RETROSPECTIVE_FILL",
    })
    if execution_id not in state["completed_execution_ids"]:
        state["completed_execution_ids"].append(execution_id)
    state["pending"].pop(symbol, None)
    state["last_completed_execution_observation_utc"] = (
        observed_at.astimezone(timezone.utc).isoformat()
    )


def process_pending_execution_clock(
    state: dict[str, Any], store: IEXResearchStore, observed_at: datetime,
    *, allow_execution: bool = True,
) -> bool:
    """Handle committed one-minute opportunities before slower decision work.

    Returns true while a pending signal is waiting for or inside its execution
    minute, so the cycle avoids slow catch-up work until the opportunity closes.
    """
    fixed25_notional_fraction = float(state.get("contract", {}).get(
        "maximum_position_notional_fraction", sip.load_qualified_fixed25_notional_fraction()
    ))
    if not math.isfinite(fixed25_notional_fraction) or not 0 < fixed25_notional_fraction <= 1:
        raise RuntimeError("Invalid persisted maximum position notional fraction.")
    store.bind(state)
    broker_block = state.get("broker_reconciliation", {}).get("risk_block_reason")
    if broker_block:
        had_pending = bool(state["pending"])
        for symbol, signal in sorted(list(state["pending"].items())):
            _expire_pending(
                state,
                store,
                symbol,
                signal,
                observed_at,
                f"BROKER_RECONCILIATION_RISK_BLOCK:{broker_block}",
            )
        if had_pending:
            store.save(state)
        return False
    for symbol, signal in sorted(list(state["pending"].items())):
        action = execution_clock_action(signal, observed_at)
        if action == "WAIT":
            continue
        eligible = datetime.fromisoformat(signal["first_eligible_execution_minute_utc"])
        local = eligible.astimezone(sip.NY)
        if not is_market_session(local.date()) or not (
            market_session(local.date()).regular_open <= local < market_session(local.date()).regular_close
        ):
            _expire_pending(state, store, symbol, signal, observed_at, "ELIGIBLE_MINUTE_OUTSIDE_REGULAR_SESSION")
            store.save(state)
            continue
        if action == "WINDOW_ACTIVE" and not signal.get("execution_window_observed_at_utc"):
            signal["execution_window_observed_at_utc"] = (
                observed_at.astimezone(timezone.utc).isoformat()
            )
            store.event("LIVE_PAPER_EXECUTION_WINDOW_OBSERVED", {
                "symbol": symbol, "signal_id": signal["signal_id"],
                "decision_observed_at_utc": signal["decision_observed_at_utc"],
                "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
                "execution_window_observed_at_utc": signal["execution_window_observed_at_utc"],
            })
            store.save(state)
        if action == "EXPIRE_MISSED_WINDOW":
            _expire_pending(state, store, symbol, signal, observed_at,
                            ("AUTHENTIC_OPEN_UNAVAILABLE_DURING_ELIGIBLE_MINUTE" if signal.get("execution_window_observed_at_utc")
                             else "PROCESS_NOT_OBSERVED_DURING_ELIGIBLE_MINUTE"))
            store.save(state)
            continue

        signal["last_open_attempt_at_utc"] = observed_at.isoformat()
        try:
            one = signal.get("authentic_open") or request_authentic_open(symbol, eligible, datetime.now(timezone.utc))
        except (ProviderFailure, RuntimeError) as exc:
            signal["last_open_observation_error"] = exc.as_dict() if isinstance(exc, ProviderFailure) else str(exc)
            store.save(state)
            continue
        if one is None:
            signal["last_open_observation_error"] = "NO_OPEN_ELIGIBLE_SIP_TRADE_OBSERVED_WITHIN_DEADLINE"
            store.save(state)
            continue
        execution_observed_at = datetime.fromisoformat(one["observed_at_utc"])
        if not eligible <= execution_observed_at < eligible + timedelta(minutes=1):
            raise RuntimeError("Authentic open observation outside execution minute.")
        signal["authentic_open"] = one
        store.save(state)
        if not allow_execution:
            signal["last_open_observation_error"] = "WAITING_FOR_ACCOUNT_OPEN_PHASE"
            store.save(state)
            continue
        if datetime.now(timezone.utc) >= eligible + timedelta(minutes=1):
            _expire_pending(state, store, symbol, signal, datetime.now(timezone.utc), "EXECUTION_DEADLINE_PASSED_BEFORE_ACCOUNT_COMMIT")
            store.save(state)
            continue
        positions = {name: sip._position(raw) for name, raw in state["positions"].items()}
        mark_symbols = tuple(dict.fromkeys(("QDTE", *positions)))
        marks = {name: float(mark["price"]) for name, mark in state.get("account_marks", {}).items()
                 if datetime.fromisoformat(mark["market_data_timestamp"]) <= eligible}
        if any(name not in marks for name in mark_symbols):
            _expire_pending(state, store, symbol, signal, observed_at,
                            "MISSING_CAUSAL_ACCOUNT_VALUATION_MARK")
            store.save(state)
            continue
        execution_id = _entry_execution_id(state, symbol, signal)
        if execution_id in state["completed_execution_ids"]:
            state["pending"].pop(symbol, None)
            store.save(state)
            continue
        candidate_snapshot = sip.candidate_v1_config_from_snapshot(
            signal.get("candidate_v1_config_snapshot"),
            str(signal.get("candidate_v1_config_fingerprint", "")),
        )
        config = candidate_snapshot.bot_config
        open_price = float(one["o"])
        gap = abs(open_price - float(signal["prior_close"])) / float(signal["atr"])
        if (
            gap > candidate_snapshot.maximum_gap_atr_multiple
            or len(positions) >= config.maximum_swing_positions
        ):
            _expire_pending(state, store, symbol, signal, observed_at,
                            "GAP" if gap > candidate_snapshot.maximum_gap_atr_multiple else "CAPACITY")
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
        broker_snapshot = state.get("broker_reconciliation", {}).get("last_snapshot")
        if broker_snapshot is not None and broker_snapshot.get("buying_power") is not None:
            deployable = min(deployable, max(0.0, float(broker_snapshot["buying_power"])))
        sizing = sip.calculate_position_size(
            account_equity=equity, available_cash=deployable, entry_price=open_price,
            atr=float(signal["atr"]), active_risk=active_risk, config=config,
            trade_results_r=sip.disabled_kelly_trade_history(candidate_snapshot),
        )
        share_cap = math.floor(
            (equity * fixed25_notional_fraction)
            / sizing.entry_fill
        ) if sizing.entry_fill else 0
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
            entry_stop_atr_multiple=config.stop_atr_multiple,
            entry_target_atr_multiple=config.target_atr_multiple,
            entry_trailing_activation_atr=config.trailing_activation_atr,
            exit_slippage_rate=config.slippage_rate,
        )
        state["positions"] = {name: sip._position_dict(value) for name, value in positions.items()}
        entry_snapshot = {
            "entry_decision_id": signal.get("decision_id", signal["signal_id"]),
            "entry_signal_id": signal["signal_id"],
            "semantic_contract_fingerprint": state["contract_fingerprint"],
            "semantic_version": state.get("semantic_contract_version", state["contract"].get("semantic_version")),
            "candidate_v1_semantic_version": state["contract"].get("entry_semantics_version"),
            "candidate_v1_semantic_fingerprint": state["contract"].get("entry_semantics_fingerprint"),
            "profit_recycling_configuration_fingerprint": state["contract"].get("profit_recycling_configuration_fingerprint"),
            "bar_adjustment": state["contract"].get("bar_adjustment"),
            "provider_input_semantics_version": state["contract"].get("provider_input_semantics_version"),
            "candidate_v1_config_fingerprint": candidate_snapshot.fingerprint,
            "candidate_v1_config_snapshot": candidate_snapshot.as_dict(),
        }
        state["positions"][symbol]["entry_semantic_snapshot"] = entry_snapshot
        state.setdefault("account_marks", {})[symbol] = {
            "price": open_price, "market_data_timestamp": str(one["trade"]["t"]),
            "observed_at_utc": execution_observed_at.isoformat(), "source": one["price_source"],
        }
        sip._persist_profit_runtime(state, profit_runtime)
        state["completed_execution_ids"].append(execution_id)
        state["pending"].pop(symbol, None)
        state["last_completed_execution_observation_utc"] = (
            execution_observed_at.isoformat()
        )
        store.event("SIMULATED_ENTRY_FILLED", {
            "symbol": symbol, "execution_id": execution_id, "shares": shares,
            "fill_price": sizing.entry_fill, "sip_1m_trade_minute": str(one["t"]),
            "decision_bar_interval": signal["decision_bar_interval"],
            "decision_observed_at_utc": signal["decision_observed_at_utc"],
            "first_eligible_execution_minute_utc": signal["first_eligible_execution_minute_utc"],
            "execution_window_observed_at_utc": signal["execution_window_observed_at_utc"],
            "execution_observed_at_utc": execution_observed_at.isoformat(),
            "authentic_open": one, "causal_status": one["causal_status"],
            "signal_id": signal["signal_id"], "price_source": one["price_source"],
            "recycled_profit_consumed": used,
            "candidate_v1_config_fingerprint": candidate_snapshot.fingerprint,
        })
        store.save(state)
    return bool(state["pending"])


def process_open_phase_clock(
    state: dict[str, Any], store: IEXResearchStore, observed_at: datetime
) -> bool:
    """Process exact 15-minute opens before pending entries or close decisions."""
    previous_error = state.get("last_open_phase_error")
    if previous_error and datetime.fromisoformat(previous_error["minute"]) + timedelta(minutes=1) <= observed_at:
        store.bind(state)
        store.event("AUTHENTIC_OPEN_PHASE_MISSED", {
            "bar": previous_error["minute"], **previous_error,
            "recorded_at_utc": observed_at.isoformat(), "causal_status": "NO_RETROSPECTIVE_FILL",
        })
        state.pop("last_open_phase_error")
        store.save(state)
    market = observed_at.astimezone(sip.NY)
    if (
        not is_market_session(market.date())
        or market < market_session(market.date()).regular_open
        or market >= market_session(market.date()).regular_close
        or market.minute % 15
    ):
        return False
    bar_open = market.replace(second=0, microsecond=0)
    phase_id = sip.fingerprint({
        "kind": "SIP_AUTHENTIC_OPEN_PHASE", "bar_open": bar_open.isoformat(),
        "contract": state["contract_fingerprint"],
    })
    completed = state.setdefault("completed_open_phase_ids", [])
    if phase_id in completed:
        return False
    store.bind(state)

    positions = {name: sip._position(raw) for name, raw in state["positions"].items()}
    symbols = tuple(dict.fromkeys(("QDTE", *positions)))
    start_utc = bar_open.astimezone(timezone.utc)
    exact: dict[str, Mapping[str, Any]] = {}
    for symbol in symbols:
        try:
            one = request_authentic_open(symbol, start_utc, observed_at)
        except (ProviderFailure, RuntimeError) as exc:
            state["last_open_phase_error"] = {"minute": start_utc.isoformat(), "symbol": symbol, "reason": str(exc)}
            store.save(state)
            return True
        if one is None:
            state["last_open_phase_error"] = {"minute": start_utc.isoformat(), "symbol": symbol, "reason": "NO_OPEN_ELIGIBLE_SIP_TRADE"}
            store.save(state)
            return True
        exact[symbol] = one

    # Eligible gap exits use the authentic open and release proceeds before
    # settlement/allocation and before any pending entries.
    for symbol, position in list(positions.items()):
        entry = position.entry_semantic_snapshot
        if not isinstance(entry, Mapping):
            raise RuntimeError("Open position lacks its Candidate V1 entry configuration snapshot.")
        position_snapshot = sip.candidate_v1_config_from_snapshot(
            entry.get("candidate_v1_config_snapshot"),
            str(entry.get("candidate_v1_config_fingerprint", "")),
        )
        open_price = float(exact[symbol]["o"])
        candle = sip.Candle(
            date=bar_open.date(), open=open_price, high=open_price,
            low=open_price, close=open_price, volume=0,
        )
        evaluation = sip.evaluate_exit(
            position=position, candle=candle, current_atr=position.entry_atr,
            config=position_snapshot.bot_config,
        )
        if not evaluation.should_exit:
            continue
        fill = float(evaluation.exit_price)
        pnl, tax_reserved, tax_reserve_released = (
            sip._apply_simulated_swing_exit_accounting(
                state, position, fill,
                position_snapshot.bot_config.annual_tax_reserve_rate,
            )
        )
        execution_id = sip.fingerprint({
            "kind": "open_exit", "symbol": symbol, "bar": bar_open.isoformat(),
            "reason": evaluation.reason, "contract": state["contract_fingerprint"],
        })
        state["completed_execution_ids"].append(execution_id)
        positions.pop(symbol)
        store.event("SIMULATED_OPEN_EXIT_FILLED", {
            "symbol": symbol, "execution_id": execution_id, "shares": position.shares,
            "fill_price": fill, "reason": evaluation.reason,
            "realized_pnl": pnl, "authentic_open": exact[symbol],
            "sip_1m_trade_minute": str(exact[symbol]["t"]), "tax_reserved": tax_reserved,
            "tax_reserve_released": tax_reserve_released,
            "required_tax_reserve": state["tax_reserve_cash"],
        })
    state["positions"] = {name: sip._position_dict(value) for name, value in positions.items()}

    sip.apply_qdte_corporate_actions(state, store, bar_open)
    candidate_snapshot = sip.candidate_v1_config_from_snapshot(
        state.get("candidate_v1_config_snapshot"),
        str(state.get("candidate_v1_config_fingerprint", "")),
    )
    if (
        bar_open.weekday() == candidate_snapshot.rebalance_weekday
        and state.get("last_rebalance_week")
        != f"{bar_open.isocalendar().year}-W{bar_open.isocalendar().week:02d}"
    ):
        week = f"{bar_open.isocalendar().year}-W{bar_open.isocalendar().week:02d}"
        marks = {name: float(exact[name]["o"]) for name in positions}
        result = sip.rebalance_income_allocation(
            income_shares=state["qdte_shares"], income_cost=state["qdte_cost"],
            swing_cash=state["cash"],
            swing_market_value=sum(pos.shares * marks[name] for name, pos in positions.items()),
            income_price=float(exact["QDTE"]["o"]),
            target_income_weight=candidate_snapshot.bot_config.dividend_allocation_years_1_2,
            slippage_rate=candidate_snapshot.bot_config.slippage_rate,
            tax_reserve_rate=candidate_snapshot.bot_config.annual_tax_reserve_rate,
            tolerance=candidate_snapshot.bot_config.allocation_rebalance_tolerance,
            minimum_trade=candidate_snapshot.bot_config.minimum_rebalance_trade,
        )
        state["qdte_shares"] = result.shares_after
        state["qdte_cost"] = result.income_cost_after
        state["cash"] = result.swing_cash_after
        state["tax_reserve_cash"] += result.tax_reserved
        state["realized_pnl"] += result.realized_pnl
        state["last_rebalance_week"] = week
        store.event("SIMULATED_AUTHENTIC_OPEN_REBALANCE", {
            "week": week, "action": result.action,
            "shares_before": result.shares_before, "shares_after": result.shares_after,
            "target_income_weight": candidate_snapshot.bot_config.dividend_allocation_years_1_2,
            "sip_1m_trade_minute": str(exact["QDTE"]["t"]),
            "authentic_open": exact["QDTE"], "realized_pnl": result.realized_pnl,
        })
    completed.append(phase_id)
    state["last_authentic_open_phase"] = {"minute": start_utc.isoformat(), "observations": exact}
    state.pop("last_open_phase_error", None)
    store.event("AUTHENTIC_OPEN_PHASE_OBSERVED", {"execution_id": phase_id, "minute": start_utc.isoformat(), "observations": exact})
    store.save(state)
    return False


def initialize(
    store: IEXResearchStore, contract: Mapping[str, Any], observed_at: datetime
) -> dict[str, Any]:
    candidate_path = contract.get("candidate_v1_configuration_path")
    candidate_snapshot = sip.load_candidate_v1_config(Path(candidate_path)) if candidate_path else sip.load_candidate_v1_config()
    config = candidate_snapshot.bot_config
    starting_capital = float(contract.get("starting_equity", candidate_snapshot.forward_starting_capital))
    qdte_start = float(contract.get("qdte_starting_value", starting_capital))
    swing_start = float(contract.get("swing_starting_cash", starting_capital - qdte_start))
    if abs(qdte_start + swing_start - starting_capital) > 1e-6:
        raise RuntimeError("Paper profile starting sleeves do not equal starting equity.")
    rows = request_bars(("QDTE",), "1Min", observed_at - timedelta(days=7), observed_at)["QDTE"]
    execution = select_causal_execution_bar(rows, observed_at)
    fill = execution["source_price"] * (1.0 + config.slippage_rate)
    shares = math.floor(qdte_start / fill)
    if shares < 1:
        raise RuntimeError("Starting capital cannot purchase one simulated QDTE share.")
    cost = shares * fill
    cash = swing_start + qdte_start - cost
    identity = {
        "capital": starting_capital, "qdte_starting_value": qdte_start,
        "swing_starting_cash": swing_start, "symbol": config.dividend_symbol, "shares": shares,
        "cash_remainder": cash, "fill_price": fill, **execution,
        "candidate_v1_config_fingerprint": candidate_snapshot.fingerprint,
        "runner_variant": contract.get("runner_variant", VARIANT), "contract_fingerprint": sip.fingerprint(contract),
    }
    persisted_contract = json.loads(sip.canonical(contract))
    profit_path = (sip.ROOT / str(contract["profit_recycling_configuration_path"])) if contract.get("profit_recycling_configuration_path") else sip.PROFIT_CONFIG
    profit_config = load_profit_recycling_config(profit_path)
    profit_runtime = ProfitRecyclingRuntime(profit_config, starting_capital)
    state = {
        "schema_version": sip.SCHEMA, "mode": contract.get("runner_variant", VARIANT),
        "research_only": True, "sip_parity_claimed": True,
        "semantic_contract_version": contract.get("semantic_version"),
        "qualified": False, "promoted": False,
        "live_broker_enabled": False, "simulated_fills_only": True,
        "contract": persisted_contract, "contract_fingerprint": sip.fingerprint(contract),
        "initialization": identity, "initialization_fingerprint": sip.fingerprint(identity),
        "candidate_v1_config_snapshot": candidate_snapshot.as_dict(),
        "candidate_v1_config_fingerprint": candidate_snapshot.fingerprint,
        "candidate_v1_config_effective_boundary": None,
        "contributed_capital": starting_capital, "cash": cash,
        "qdte_shares": shares, "qdte_cost": cost, "positions": {}, "pending": {},
        "tax_reserve_cash": 0.0, "realized_pnl": 0.0,
        "completed_execution_ids": [sip.fingerprint(identity)], "last_decision_bar": None,
        "last_completed_decision_observed_at_utc": None,
        "last_completed_execution_observation_utc": None,
        "last_rebalance_week": None,
        "profit_recycling": {
            "policy_identity": profit_config.policy_identity,
            "configuration_fingerprint": profit_config.fingerprint,
            "event_sequence": 0, "current_event_sequence": 0,
            "decision_ids": [], "ledger": profit_runtime.ledger.as_dict(),
        },
        "qdte_corporate_actions": {}, "invalid_qdte_corporate_actions": [],
        "qdte_open_share_snapshots": {},
        "last_corporate_action_observation_at_utc": None, "revision": 1,
    }
    store.event("LIVE_PAPER_ACCOUNT_INITIALIZED_SIMULATED_QDTE", identity)
    store.save(state)
    return state


@contextmanager
def _market_data_request_scope() -> Iterator[None]:
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


def _cycle(
    store: IEXResearchStore,
    observed_at: datetime,
    *,
    force_broker_reconciliation: bool = False,
) -> dict[str, Any]:
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
    else:
        _migrate_market_data_contract_if_required(
            state, store, contract, observed_at
        )
        _normalize_sip_contract_identity_if_required(
            state, store, contract, observed_at
        )
    if state.get("contract_fingerprint") not in {
        OLD_SEMANTIC_CONTRACT_FINGERPRINT,
        PRE_CONFIG_AUTHORITY_CONTRACT_FINGERPRINT,
        sip.fingerprint(contract),
    }:
        old_contract_fingerprint = str(state.get("contract_fingerprint"))
        persisted = dict(state.get("contract") or {})
        reloadable = {"maximum_position_notional_fraction", "execution_phase_semantics_version"}
        comparable_old = {k: (list(v) if k == "symbols" else v) for k, v in persisted.items() if k not in reloadable}
        comparable_new = {k: (list(v) if k == "symbols" else v) for k, v in contract.items() if k not in reloadable}
        if comparable_old != comparable_new:
            raise RuntimeError("Persisted live-paper strategy identity differs from its contract.")
        if state.get("positions") or state.get("pending"):
            raise RuntimeError("Execution-phase transition requires no open positions or pending actions.")
        state["contract"] = json.loads(sip.canonical(contract))
        state["contract_fingerprint"] = sip.fingerprint(contract)
        store.event("PAPER_CONFIGURATION_RELOADED", {
            "old_contract_fingerprint": old_contract_fingerprint,
            "new_contract_fingerprint": sip.fingerprint(contract),
            "maximum_position_notional_fraction": contract.get("maximum_position_notional_fraction"),
            "execution_phase_semantics_version": contract.get("execution_phase_semantics_version"),
            "effective_boundary": _next_decision_boundary(state, observed_at),
        })
        store.save(state)
    if state.get("schema_version") != sip.SCHEMA or state.get("mode") != contract.get("runner_variant", VARIANT):
        raise RuntimeError("Persisted state is not the live-paper forward-research schema.")
    store.bind(state)
    _flush_pending_broker_reconciliation(state, store)
    _flush_pending_semantic_transition(state, store)
    if broker_reconciliation_enabled():
        observe_and_reconcile_broker_account(
            state,
            store,
            observed_at,
            force=(
                force_broker_reconciliation
                or bool(state.get("pending"))
                or decision_processing_due(state, observed_at)
            ),
        )
    _transition_semantic_contract_if_required(state, store, contract, observed_at)
    with _market_data_request_scope():
        waiting_for_open = process_open_phase_clock(state, store, observed_at)
    waiting_for_pending = process_pending_execution_clock(state, store, observed_at, allow_execution=not waiting_for_open)
    _sync_effective_market_data_authority(state)
    state["minute_observer"] = {"last_worker_poll_at_utc": observed_at.isoformat(),
                                "session_state": market_session_state(observed_at),
                                "execution_source": "ALPACA_SIP_FIRST_ELIGIBLE_TRADE"}
    if waiting_for_open or waiting_for_pending:
        state["last_observed_at_utc"] = observed_at.astimezone(timezone.utc).isoformat()
        state["revision"] += 1
        store.save(state)
        store.event("LIVE_PAPER_HEARTBEAT", {
            "revision": state["revision"], "live_broker_enabled": False,
            "execution_clock": (
                "WAITING_FOR_AUTHENTIC_OPEN_MINUTE" if waiting_for_open
                else "WAITING_FOR_CAUSAL_MINUTE"
            ),
        })
        store.publish_metrics(state, observed_at)
        return state
    with _market_data_request_scope():
        if corporate_action_poll_due(state, observed_at):
            sip.observe_qdte_corporate_actions(state, store, observed_at)
        if not decision_processing_due(state, observed_at):
            store.publish_metrics(state, observed_at)
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
        _sync_effective_market_data_authority(state)
        completed = state.get("last_decision_bar")
        if completed != previous_completed:
            state["last_completed_decision_observed_at_utc"] = (
                datetime.now(timezone.utc).isoformat()
            )
            store.save(state)
        if not state["pending"] and expected is not None and (
            completed is None or datetime.fromisoformat(str(completed)) < expected
        ):
            raise _sparse_data_failure(
                operation="completed_15m_decision_data",
                message=(
                    "No SIP bar established the expected completed decision boundary."
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
    store.event("LIVE_PAPER_HEARTBEAT", {
        "revision": state["revision"], "live_broker_enabled": False,
    })
    store.publish_metrics(state, datetime.now(timezone.utc))
    return state


def cycle(runtime: Path, observed_at: datetime | None = None) -> dict[str, Any]:
    store = IEXResearchStore(runtime)
    with store.locked():
        return _cycle(
            store,
            observed_at or datetime.now(timezone.utc),
            force_broker_reconciliation=broker_reconciliation_enabled(),
        )


def broker_reconciliation_status(runtime: Path) -> dict[str, Any]:
    state = IEXResearchStore(runtime).reconcile()
    if state is None:
        return {
            "status": "NO_CLEAN_V2_STATE",
            "runtime": str(runtime.resolve()),
            "broker_orders_enabled": False,
        }
    broker = state.get("broker_reconciliation") or {}
    snapshot = broker.get("last_snapshot") or {}
    return {
        "status": (
            "BROKER_RECONCILIATION_ACTIVE"
            if broker
            else "BROKER_RECONCILIATION_NOT_YET_ACTIVATED"
        ),
        "runner_variant": state.get("mode"),
        "state_revision": state.get("revision"),
        "live_broker_enabled": False,
        "broker_orders_enabled": False,
        "broker_reconciliation_mode": broker.get("mode"),
        "configuration_fingerprint": broker.get("configuration_fingerprint"),
        "market_data_provider": broker.get("market_data_provider"),
        "broker_account_provider": broker.get("broker_account_provider"),
        "order_execution_provider": broker.get("order_execution_provider"),
        "last_observed_at_utc": broker.get("last_observed_at_utc"),
        "last_reconciliation_id": broker.get("last_reconciliation_id"),
        "reconciliation_count": broker.get("reconciliation_count", 0),
        "account_identity_fingerprint": snapshot.get(
            "account_identity_fingerprint"
        ),
        "broker_cash": snapshot.get("cash"),
        "broker_equity": snapshot.get("equity"),
        "broker_buying_power": snapshot.get("buying_power"),
        "broker_positions": snapshot.get("positions", []),
        "external_account_cash_delta_total": broker.get(
            "external_account_cash_delta_total", 0.0
        ),
        "risk_block_reason": broker.get("risk_block_reason"),
        "managed_strategy_positions": state.get("positions", {}),
        "pending_actions": state.get("pending", {}),
        "strategy_realized_pnl": state.get("realized_pnl"),
        "contributed_capital": state.get("contributed_capital"),
    }


def _verify_sip_entitlement(observed_at: datetime) -> dict[str, Any]:
    authority = _configured_market_data_authority()
    market_day = previous_market_session(
        observed_at.astimezone(sip.NY).date(), include_day=True
    )
    session = market_session(market_day)
    bars = request_bars(
        ("QDTE",), "15Min", session.regular_open, session.regular_close
    ).get("QDTE", [])
    trade_parameters = {
        "start": session.regular_open.astimezone(timezone.utc).isoformat(),
        "end": session.regular_close.astimezone(timezone.utc).isoformat(),
        "feed": authority["configured_feed"],
        "sort": "asc",
        "limit": 100,
    }
    trade_payload = _request_json(
        provider="alpaca",
        operation="sip_entitlement_probe_trades",
        endpoint="https://data.alpaca.markets/v2/stocks/QDTE/trades",
        parameters=trade_parameters,
        user_agent="QPX-LIVE-PAPER-SIP-ENTITLEMENT-PROBE/1",
        attempts=1,
    )
    trades = trade_payload.get("trades")
    if not bars or not isinstance(trades, list) or not trades:
        raise ProviderFailure(
            failure_class="SIP_DATA_UNAVAILABLE",
            provider="alpaca",
            operation="sip_entitlement_probe",
            endpoint=sip.DATA_URL,
            recoverable=False,
            exception_type="EmptySIPProbeResult",
            message="SIP entitlement probe returned no completed QDTE bars or trades.",
            request_parameters={
                "feed": authority["configured_feed"],
                "session": market_day.isoformat(),
            },
        )
    return {
        **authority,
        "effective_provider_feed": authority["configured_feed"],
        "sip_entitlement_result": "AVAILABLE",
        "verified_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "verified_session": market_day.isoformat(),
        "completed_15m_bar_count": len(bars),
        "trade_sample_count": len(trades),
        "bar_feed_attestation": bars[0].get("qpx_market_data_feed"),
        "trade_request_feed": trade_parameters["feed"],
    }


def migrate_market_data_authority(runtime: Path) -> dict[str, Any]:
    observed = datetime.now(timezone.utc)
    store = IEXResearchStore(runtime)
    with store.locked():
        state = store.reconcile()
        if state is None:
            raise RuntimeError("Market-data authority migration requires the existing account state.")
        before = _preserved_account_payload(state)
        contract = load_contract()
        _migrate_market_data_contract_if_required(state, store, contract, observed)
        _normalize_sip_contract_identity_if_required(state, store, contract, observed)
        store.bind(state)
        try:
            verification = _verify_sip_entitlement(observed)
        except ProviderFailure as failure:
            state["market_data_authority"] = {
                **_configured_market_data_authority(),
                "effective_provider_feed": None,
                "sip_entitlement_result": (
                    "UNAVAILABLE_PERMISSION"
                    if failure.failure_class == "AUTHENTICATION_PERMISSION_FAILURE"
                    else "UNAVAILABLE_PROVIDER"
                ),
                "verified_at_utc": observed.isoformat(),
                "availability_failure": failure.as_dict(),
            }
            store.event("MARKET_DATA_AUTHORITY_VERIFICATION_FAILED", {
                "configured_feed": configured_feed(),
                "fallback_feed": None,
                "failure": failure.as_dict(),
            })
            store.save(state)
            heartbeat = _heartbeat_payload(
                daemon_started_at_utc=observed.isoformat(), state=state,
                provider_state="BLOCKED_SIP_AUTHORITY",
                session_state=market_session_state(observed), retry_count=1,
                backoff_seconds=0,
                last_successful_provider_contact_at_utc=_last_successful_provider_contact_utc,
                failure=failure,
            )
            heartbeat.update(
                runtime_operation="MARKET_DATA_AUTHORITY_MIGRATION_BLOCKED",
                session_worker_active=False, daemon_pid=None,
            )
            store.write_heartbeat(heartbeat)
            raise
        state["market_data_authority"] = verification
        store.event("MARKET_DATA_AUTHORITY_VERIFIED", verification)
        store.save(state)
        store.publish_metrics(state, observed)
        if _preserved_account_payload(state) != before:
            raise RuntimeError("Account state changed during SIP authority verification.")
        heartbeat = _heartbeat_payload(
            daemon_started_at_utc=observed.isoformat(), state=state,
            provider_state="SIP_AUTHORITY_VERIFIED",
            session_state=market_session_state(observed), retry_count=0,
            backoff_seconds=0,
            last_successful_provider_contact_at_utc=_last_successful_provider_contact_utc,
        )
        heartbeat.update(
            runtime_operation="MARKET_DATA_AUTHORITY_MIGRATION_COMPLETED",
            session_worker_active=False, daemon_pid=None,
        )
        store.write_heartbeat(heartbeat)
        return verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=5)
    parser.add_argument("--refresh-account-metrics", action="store_true",
                        help="Finite valuation-only migration; no decisions, fills or corporate-action mutation.")
    parser.add_argument("--broker-reconciliation-status", action="store_true")
    parser.add_argument("--migrate-market-data-authority", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.poll_seconds <= 15:
        raise ValueError("Execution observer poll interval must be between 1 and 15 seconds.")
    if args.refresh_account_metrics:
        store = IEXResearchStore(args.runtime_dir)
        with store.locked():
            state = store.reconcile()
            if state is None or state["contract_fingerprint"] != sip.fingerprint(load_contract()):
                raise RuntimeError("Metrics refresh requires the existing matching account; initialization forbidden.")
            store.bind(state)
            observed = datetime.now(timezone.utc)
            refresh_account_marks(state, observed)
            store.publish_metrics(state, observed)
            heartbeat = _heartbeat_payload(
                daemon_started_at_utc=observed.isoformat(), state=state,
                provider_state="HEALTHY", session_state=market_session_state(observed),
                retry_count=0, backoff_seconds=0, last_successful_provider_contact_at_utc=observed.isoformat())
            heartbeat.update(runtime_operation="VALUATION_ONLY_REFRESH_COMPLETED", session_worker_active=False,
                             refresh_pid=os.getpid(), daemon_pid=None)
            store.write_heartbeat(heartbeat)
            print(json.dumps(state["account_metrics"], sort_keys=True))
        return 0
    if args.broker_reconciliation_status:
        print(
            json.dumps(broker_reconciliation_status(args.runtime_dir), indent=2, sort_keys=True),
            flush=True,
        )
        return 0
    if args.migrate_market_data_authority:
        print(json.dumps(migrate_market_data_authority(args.runtime_dir), indent=2, sort_keys=True))
        return 0
    if not args.daemon:
        state = cycle(args.runtime_dir)
        print(json.dumps({
            "status": VARIANT, "feed": configured_feed(), "revision": state["revision"],
            "live_broker_enabled": False, "sip_parity_claimed": True,
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
        broker_reconciliation_required = broker_reconciliation_enabled()
        while not stop_requested.is_set():
            observed_at = datetime.now(timezone.utc)
            state: dict[str, Any] | None = None
            try:
                if broker_reconciliation_enabled():
                    state = _cycle(
                        store,
                        observed_at,
                        force_broker_reconciliation=(
                            broker_reconciliation_required or consecutive_failures > 0
                        ),
                    )
                else:
                    state = _cycle(store, observed_at)
                broker_reconciliation_required = False
            except ProviderFailure as failure:
                broker_reconciliation_required = True
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
                    store.event("LIVE_PAPER_PROVIDER_DEGRADED", {
                        "event_id": transition_id,
                        "revision": reconciled.get("revision") if reconciled else None,
                        "retry_count": consecutive_failures,
                        "backoff_seconds": backoff,
                        **failure.as_dict(),
                    })
                if new_degradation or consecutive_failures % 10 == 0:
                    print(json.dumps({
                        "status": provider_state,
                        "feed": configured_feed(),
                        "revision": reconciled.get("revision") if reconciled else None,
                        "retry_count": consecutive_failures,
                        "backoff_seconds": backoff,
                        "failure": failure.as_dict(),
                        "live_broker_enabled": False,
                        "sip_parity_claimed": True,
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
                store.event("LIVE_PAPER_PROVIDER_RECOVERED", {
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
                    "feed": configured_feed(),
                    "revision": state["revision"],
                    "market_session_state": session_state,
                    "live_broker_enabled": False,
                    "sip_parity_claimed": True,
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
