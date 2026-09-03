"""IEX-only causal forward research adapter for the PR_FRACTION_50 paper model.

This process has no broker-order client.  An optional canonical read-only
broker-account observer is configuration-gated.  The runner does not claim SIP
parity, qualification, promotion, or production authority.
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
from qpx_bot.broker_account_provider import (
    BrokerAccountProvider,
    BrokerAccountSnapshot,
    ProviderSelection,
    build_broker_account_provider,
    load_provider_selection,
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
NEW_SEMANTIC_CONTRACT_FINGERPRINT = (
    "5fcab69089cbfd069727b754f1ca1be9338500234348fbbc56bf3e5633603c5d"
)
SEMANTIC_VERSION_OLD = "PR50_IEX_PRE_PARITY_V1"
SEMANTIC_VERSION_NEW = "PR50_IEX_HISTORICAL_CANDIDATE_V1_SPLIT_V2"
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
PROVIDER_INPUT_SEMANTICS_VERSION = "ALPACA_IEX_15M_COMPLETED_SPLIT_V1"
BAR_ADJUSTMENT_MODE = "split"
SEMANTIC_TRANSITION_EVENT = "CONFIGURATION_VERSION_CHANGED"


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
        "semantic_version": SEMANTIC_VERSION_NEW,
        "entry_semantics_version": ENTRY_SEMANTICS_VERSION,
        "entry_semantics_fingerprint": ENTRY_SEMANTICS_FINGERPRINT,
        "bar_adjustment": BAR_ADJUSTMENT_MODE,
        "provider_input_semantics_version": PROVIDER_INPUT_SEMANTICS_VERSION,
    })
    return contract


def request_bars(
    symbols: tuple[str, ...], timeframe: str, start: datetime, end: datetime
) -> dict[str, list[dict[str, Any]]]:
    params = {
        "symbols": ",".join(symbols), "timeframe": timeframe,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        # The frozen qualified dataset is explicitly split-adjusted.  Keep
        # the forward input on the same Alpaca adjustment basis.
        "feed": FEED, "adjustment": "split", "limit": "10000", "sort": "asc",
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


def broker_reconciliation_enabled() -> bool:
    return bool(os.environ.get(BROKER_PROVIDER_CONFIG_ENV, "").strip())


def configured_broker_account_provider(
) -> tuple[ProviderSelection, BrokerAccountProvider]:
    raw_path = os.environ.get(BROKER_PROVIDER_CONFIG_ENV, "").strip()
    if not raw_path:
        raise RuntimeError("Broker-account provider configuration is not enabled.")
    selection = load_provider_selection(raw_path)
    if selection.market_data_provider != "ALPACA_IEX":
        raise RuntimeError("Clean-V2 requires the ALPACA_IEX market-data provider.")
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
    if current != OLD_SEMANTIC_CONTRACT_FINGERPRINT:
        raise RuntimeError("Persisted semantic contract is not the allowlisted OLD contract.")
    if (
        expected != NEW_SEMANTIC_CONTRACT_FINGERPRINT
        or str(contract.get("semantic_version")) != SEMANTIC_VERSION_NEW
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
        "old_semantic_version": SEMANTIC_VERSION_OLD,
        "new_semantic_version": SEMANTIC_VERSION_NEW,
        "effective_observation_timestamp_utc": observed_at.astimezone(timezone.utc).isoformat(),
        "first_decision_boundary_governed_by_new_contract": _next_decision_boundary(state, observed_at),
        "reason": "FORWARD_PARITY_CORRECTION",
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
    broker = state.get("broker_reconciliation", {}) if state else {}
    broker_snapshot = broker.get("last_snapshot") or {}
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
        broker_snapshot = state.get("broker_reconciliation", {}).get("last_snapshot")
        if broker_snapshot is not None and broker_snapshot.get("buying_power") is not None:
            deployable = min(deployable, max(0.0, float(broker_snapshot["buying_power"])))
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
        }
        state["positions"][symbol]["entry_semantic_snapshot"] = entry_snapshot
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
        "semantic_contract_version": contract.get("semantic_version"),
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
    elif state.get("contract_fingerprint") not in {
        OLD_SEMANTIC_CONTRACT_FINGERPRINT,
        sip.fingerprint(contract),
    }:
        raise RuntimeError("Persisted IEX research strategy identity differs from its contract.")
    if state.get("schema_version") != sip.SCHEMA or state.get("mode") != VARIANT:
        raise RuntimeError("Persisted state is not the IEX forward-research schema.")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--broker-reconciliation-status", action="store_true")
    args = parser.parse_args(argv)
    if args.poll_seconds < 15:
        raise ValueError("Poll interval must be at least 15 seconds.")
    if args.broker_reconciliation_status:
        print(
            json.dumps(broker_reconciliation_status(args.runtime_dir), indent=2, sort_keys=True),
            flush=True,
        )
        return 0
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
