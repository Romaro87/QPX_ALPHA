"""Operator control for the external DUMMY broker-account observation input."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence
from zoneinfo import ZoneInfo

from qpx_bot.broker_account_provider import (
    DUMMY_PROVIDER_IDENTITY,
    DummyBrokerAccountProvider,
    build_broker_account_provider,
    load_provider_selection,
    snapshot_from_dummy_state,
    write_dummy_broker_account_state,
)
from qpx_bot.paper_state import runtime_lock


CLEAN_V2_UNIT = "qpx-pr50-iex-forward-research-paper-clean-v2.service"
INTERVENTION_TIME = datetime(
    2026, 9, 3, 11, 0, tzinfo=ZoneInfo("America/New_York")
)
INTERVENTION_WINDOW_START = INTERVENTION_TIME - timedelta(seconds=5)
INTERVENTION_WINDOW_END = INTERVENTION_TIME + timedelta(minutes=1)
EXPECTED_MARKET_DATA_PROVIDER = "ALPACA_IEX"
EXPECTED_BROKER_ACCOUNT_PROVIDER = DUMMY_PROVIDER_IDENTITY
EXPECTED_ORDER_EXECUTION_PROVIDER = "SIMULATED"


def _number(value: str, field: str, *, positive: bool = False) -> str:
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{field} is invalid.")
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or atomically change only the external DUMMY brokerage "
            "account input observed by QPX."
        )
    )
    parser.add_argument("--provider-config", type=Path, required=True)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--set-cash")
    parser.add_argument("--clear-positions", action="store_true")
    parser.add_argument("--set-position", metavar="SYMBOL")
    parser.add_argument("--remove-position", metavar="SYMBOL")
    parser.add_argument("--side", choices=("long", "short"))
    parser.add_argument("--quantity")
    parser.add_argument("--average-entry-price")
    parser.add_argument("--cost-basis")
    parser.add_argument("--market-value")
    parser.add_argument("--current-price")
    parser.add_argument("--asset-class")
    parser.add_argument("--set-account-identity")
    parser.add_argument("--set-account-status")
    parser.add_argument("--set-currency")
    parser.add_argument("--set-equity")
    parser.add_argument("--set-portfolio-value")
    parser.add_argument("--set-buying-power")
    parser.add_argument("--preflight-clean-v2-intervention", action="store_true")
    parser.add_argument("--clean-v2-runtime", type=Path)
    return parser


def _provider(config_path: Path) -> DummyBrokerAccountProvider:
    selection = load_provider_selection(config_path)
    if selection.broker_account_provider != DUMMY_PROVIDER_IDENTITY:
        raise ValueError("Operator control requires broker_account_provider=DUMMY.")
    provider = build_broker_account_provider(selection)
    if not isinstance(provider, DummyBrokerAccountProvider):
        raise TypeError("Configured DUMMY provider is not the canonical dummy adapter.")
    return provider


def _systemd_property(property_name: str) -> str:
    result = subprocess.run(
        (
            "systemctl", "--user", "show", CLEAN_V2_UNIT,
            f"--property={property_name}", "--value",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"systemctl failed for {property_name}")
    return result.stdout.strip()


def preflight_clean_v2_intervention(
    config_path: Path,
    clean_v2_runtime: Path,
    *,
    now: datetime | None = None,
    systemd_properties: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Read-only gate for the dated external DUMMY intervention."""
    observed = (now or datetime.now(INTERVENTION_TIME.tzinfo)).astimezone(
        INTERVENTION_TIME.tzinfo
    )
    checks: dict[str, dict[str, Any]] = {}
    selection = None
    provider = None
    snapshot = None
    state = None
    store = None

    def check(name: str, passed: bool, detail: str) -> None:
        checks[name] = {"status": "PASS" if passed else "FAIL", "detail": detail}

    properties = systemd_properties
    try:
        properties = properties or {
            "ActiveState": _systemd_property("ActiveState"),
            "Environment": _systemd_property("Environment"),
        }
        active = properties.get("ActiveState") == "active"
        check(
            "clean_v2_active",
            active,
            "Clean-V2 systemd ActiveState=active."
            if active
            else f"Clean-V2 systemd ActiveState={properties.get('ActiveState', '')!r}.",
        )
    except Exception as exc:
        check("clean_v2_active", False, f"Cannot verify Clean-V2 service state: {exc}")
        properties = properties or {}

    try:
        selection = load_provider_selection(config_path)
        roles_match = (
            selection.market_data_provider == EXPECTED_MARKET_DATA_PROVIDER
            and selection.broker_account_provider == EXPECTED_BROKER_ACCOUNT_PROVIDER
            and selection.order_execution_provider == EXPECTED_ORDER_EXECUTION_PROVIDER
        )
        check(
            "provider_roles",
            roles_match,
            (
                f"Loaded roles {selection.market_data_provider}/"
                f"{selection.broker_account_provider}/"
                f"{selection.order_execution_provider}."
            ),
        )
        expected_environment = str(config_path.expanduser().resolve())
        loaded_environment = str(properties.get("Environment", ""))
        environment_match = (
            f"QPX_BROKER_ACCOUNT_PROVIDER_CONFIG={expected_environment}" in loaded_environment
        )
        check(
            "loaded_provider_configuration",
            environment_match,
            "Clean-V2 loaded the configured provider-selection path."
            if environment_match
            else "Clean-V2 provider-selection environment does not match the requested config.",
        )
    except Exception as exc:
        check("provider_roles", False, f"Provider configuration failed: {exc}")
        check("loaded_provider_configuration", False, f"Provider configuration unavailable: {exc}")

    if selection is not None and selection.broker_account_provider == DUMMY_PROVIDER_IDENTITY:
        try:
            provider = build_broker_account_provider(selection)
            snapshot = provider.observe(observed.astimezone(timezone.utc))
            check("dummy_state_checksum", True, "DUMMY state and checksum validate.")
        except Exception as exc:
            check("dummy_state_checksum", False, f"DUMMY state/checksum validation failed: {exc}")
    else:
        check("dummy_state_checksum", False, "DUMMY provider was not configured.")

    try:
        from qpx_bot.pr50_iex_forward_research_paper import IEXResearchStore

        store = IEXResearchStore(clean_v2_runtime)
        state = store.reconcile()
        integrity = isinstance(state, dict)
        check(
            "clean_v2_state_audit_integrity",
            integrity,
            "Clean-V2 state checksum and audit chain validate."
            if integrity
            else "Clean-V2 state is unavailable.",
        )
    except Exception as exc:
        check("clean_v2_state_audit_integrity", False, f"Clean-V2 integrity validation failed: {exc}")

    broker = state.get("broker_reconciliation") if isinstance(state, dict) else None
    baseline_bound = bool(
        isinstance(broker, dict)
        and broker.get("initial_binding_id")
        and broker.get("last_applied_identity_fingerprint")
        and broker.get("broker_account_provider") == DUMMY_PROVIDER_IDENTITY
    )
    baseline_snapshot = broker.get("last_snapshot") if isinstance(broker, dict) else None
    baseline_observed_today = False
    if isinstance(baseline_snapshot, dict) and baseline_snapshot.get("observed_at_utc"):
        try:
            baseline_observed_today = (
                datetime.fromisoformat(
                    str(baseline_snapshot["observed_at_utc"]).replace("Z", "+00:00")
                ).astimezone(INTERVENTION_TIME.tzinfo).date()
                == INTERVENTION_TIME.date()
            )
        except (TypeError, ValueError):
            baseline_observed_today = False
    baseline_bound = baseline_bound and baseline_observed_today
    check(
        "dummy_baseline_bound",
        baseline_bound,
        "Today's DUMMY broker baseline is bound."
        if baseline_bound
        else "Today's DUMMY broker baseline is not bound.",
    )

    identity_match = False
    if baseline_bound and snapshot is not None:
        identity_match = (
            isinstance(baseline_snapshot, dict)
            and baseline_snapshot.get("provider_identity") == DUMMY_PROVIDER_IDENTITY
            and baseline_snapshot.get("account_identity_fingerprint")
            == snapshot.account_identity_fingerprint
            and broker.get("last_applied_identity_fingerprint") == snapshot.identity_fingerprint
        )
    check(
        "dummy_identity_matches_bound_baseline",
        identity_match,
        "Current DUMMY provider/account identity matches the bound baseline."
        if identity_match
        else "Current DUMMY provider/account identity differs from the bound baseline.",
    )

    healthy = False
    if isinstance(state, dict) and store is not None:
        try:
            heartbeat = store.read_heartbeat()
            healthy = (
                isinstance(heartbeat, dict)
                and heartbeat.get("provider_state") == "HEALTHY"
                and heartbeat.get("failure") in (None, {})
                and not (broker or {}).get("risk_block_reason")
            )
            detail = (
                "No unresolved provider/reconciliation failure is recorded."
                if healthy
                else "Heartbeat or broker reconciliation state is degraded/blocked."
            )
        except Exception as exc:
            detail = f"Cannot verify heartbeat/reconciliation state: {exc}"
    else:
        detail = "Clean-V2 state is unavailable."
    check("no_unresolved_reconciliation_failure", healthy, detail)

    simulation_only = (
        isinstance(state, dict)
        and state.get("simulated_fills_only") is True
        and state.get("live_broker_enabled") is False
    )
    check(
        "clean_v2_simulation_only",
        simulation_only,
        "Clean-V2 remains simulated-fills-only with live broker disabled."
        if simulation_only
        else "Clean-V2 simulation-only safety flags are not valid.",
    )

    within_window = INTERVENTION_WINDOW_START <= observed <= INTERVENTION_WINDOW_END
    check(
        "execution_time_window",
        within_window,
        f"Observed {observed.isoformat()} within the allowed intervention window."
        if within_window
        else (
            f"Observed {observed.isoformat()}, allowed window is "
            f"{INTERVENTION_WINDOW_START.isoformat()} through "
            f"{INTERVENTION_WINDOW_END.isoformat()}."
        ),
    )

    passed = all(item["status"] == "PASS" for item in checks.values())
    return {
        "status": "INTERVENTION_PREFLIGHT_PASS" if passed else "INTERVENTION_PREFLIGHT_FAIL",
        "intervention_time": INTERVENTION_TIME.isoformat(),
        "allowed_window_start": INTERVENTION_WINDOW_START.isoformat(),
        "allowed_window_end": INTERVENTION_WINDOW_END.isoformat(),
        "observed_at": observed.isoformat(),
        "clean_v2_unit": CLEAN_V2_UNIT,
        "clean_v2_runtime": str(clean_v2_runtime.expanduser().resolve()),
        "dummy_observation_fingerprint": (
            snapshot.observation_fingerprint if snapshot is not None else None
        ),
        "mutation_attempted": False,
        "checks": checks,
    }


def _initial_payload(args: argparse.Namespace) -> dict[str, Any]:
    required = {
        "--set-account-identity": args.set_account_identity,
        "--set-account-status": args.set_account_status,
        "--set-currency": args.set_currency,
        "--set-cash": args.set_cash,
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        raise ValueError("Initialization requires " + ", ".join(missing) + ".")
    return {
        "schema_version": 1,
        "provider_identity": DUMMY_PROVIDER_IDENTITY,
        "account_identity": str(args.set_account_identity),
        "account_status": str(args.set_account_status),
        "cash": _number(args.set_cash, "cash"),
        "equity": None,
        "portfolio_value": None,
        "buying_power": None,
        "currency": str(args.set_currency),
        "positions": [],
        "trading_blocked": False,
        "account_blocked": False,
        "restriction_flags": [],
        "revision": 0,
    }


def _position(args: argparse.Namespace) -> dict[str, Any]:
    required = {
        "--side": args.side,
        "--quantity": args.quantity,
        "--average-entry-price": args.average_entry_price,
    }
    missing = [name for name, value in required.items() if value in (None, "")]
    if missing:
        raise ValueError("--set-position requires " + ", ".join(missing) + ".")
    return {
        "symbol": str(args.set_position).strip().upper(),
        "side": args.side,
        "quantity": _number(args.quantity, "quantity", positive=True),
        "average_entry_price": _number(
            args.average_entry_price,
            "average entry price",
            positive=True,
        ),
        "cost_basis": (
            _number(args.cost_basis, "cost basis")
            if args.cost_basis is not None
            else None
        ),
        "market_value": (
            _number(args.market_value, "market value")
            if args.market_value is not None
            else None
        ),
        "current_price": (
            _number(args.current_price, "current price", positive=True)
            if args.current_price is not None
            else None
        ),
        "asset_class": str(args.asset_class).strip() if args.asset_class else None,
    }


def _mutate(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    updated = json.loads(json.dumps(payload))
    if args.set_account_identity is not None:
        if not str(args.set_account_identity).strip():
            raise ValueError("Account identity cannot be empty.")
        updated["account_identity"] = str(args.set_account_identity).strip()
    if args.set_account_status is not None:
        updated["account_status"] = str(args.set_account_status).strip()
    if args.set_currency is not None:
        updated["currency"] = str(args.set_currency).strip()
    scalar_numbers = {
        "cash": args.set_cash,
        "equity": args.set_equity,
        "portfolio_value": args.set_portfolio_value,
        "buying_power": args.set_buying_power,
    }
    for field, value in scalar_numbers.items():
        if value is not None:
            updated[field] = _number(value, field.replace("_", " "))
    if args.clear_positions:
        updated["positions"] = []
    if args.remove_position:
        removed = str(args.remove_position).strip().upper()
        updated["positions"] = [
            item for item in updated["positions"]
            if str(item.get("symbol", "")).strip().upper() != removed
        ]
    if args.set_position:
        position = _position(args)
        updated["positions"] = [
            item for item in updated["positions"]
            if str(item.get("symbol", "")).strip().upper() != position["symbol"]
        ]
        updated["positions"].append(position)
        updated["positions"].sort(key=lambda item: str(item["symbol"]))
    updated["revision"] = int(updated.get("revision", 0)) + 1
    updated["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
    snapshot_from_dummy_state(updated, datetime.now(timezone.utc))
    return updated


def _status(provider: DummyBrokerAccountProvider) -> dict[str, Any]:
    snapshot = provider.observe(datetime.now(timezone.utc))
    raw = provider.load_state()
    return {
        "status": "DUMMY_BROKER_ACCOUNT_VALID",
        "state_path": str(provider.state_path),
        "checksum_path": str(provider.checksum_path),
        "dummy_state_revision": int(raw.get("revision", 0)),
        "provider_identity": snapshot.provider_identity,
        "account_identity_fingerprint": snapshot.account_identity_fingerprint,
        "account_status": snapshot.account_status,
        "cash": str(snapshot.cash),
        "equity": str(snapshot.equity) if snapshot.equity is not None else None,
        "portfolio_value": (
            str(snapshot.portfolio_value)
            if snapshot.portfolio_value is not None
            else None
        ),
        "buying_power": (
            str(snapshot.buying_power) if snapshot.buying_power is not None else None
        ),
        "currency": snapshot.currency,
        "positions": [position.as_dict() for position in snapshot.positions],
        "trading_blocked": snapshot.trading_blocked,
        "account_blocked": snapshot.account_blocked,
        "restriction_flags": list(snapshot.restriction_flags),
        "observation_fingerprint": snapshot.observation_fingerprint,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.preflight_clean_v2_intervention:
        if args.clean_v2_runtime is None:
            raise ValueError("Preflight requires --clean-v2-runtime.")
        result = preflight_clean_v2_intervention(
            args.provider_config,
            args.clean_v2_runtime,
        )
        print(json.dumps(result, indent=2, sort_keys=True), flush=True)
        return 0 if result["status"] == "INTERVENTION_PREFLIGHT_PASS" else 1
    provider = _provider(args.provider_config)
    mutating = any((
        args.initialize,
        args.set_cash is not None,
        args.clear_positions,
        args.set_position is not None,
        args.remove_position is not None,
        args.set_account_identity is not None,
        args.set_account_status is not None,
        args.set_currency is not None,
        args.set_equity is not None,
        args.set_portfolio_value is not None,
        args.set_buying_power is not None,
    ))
    if not mutating and not args.status:
        raise ValueError("Specify --status, --initialize, or an account-state change.")
    control_lock = provider.state_path.with_suffix(provider.state_path.suffix + ".control.lock")
    mutation_completed_at_utc = None
    with runtime_lock(control_lock):
        before = (
            _status(provider)
            if mutating
            and (provider.state_path.exists() or provider.checksum_path.exists())
            else None
        )
        if mutating:
            if args.initialize:
                if provider.state_path.exists() or provider.checksum_path.exists():
                    raise FileExistsError(
                        "Dummy broker-account state already exists; refusing reinitialization."
                    )
                payload = _initial_payload(args)
            else:
                payload = provider.load_state()
            updated = _mutate(payload, args)
            write_dummy_broker_account_state(
                provider.state_path,
                updated,
                checksum_path=provider.checksum_path,
            )
            mutation_completed_at_utc = datetime.now(timezone.utc).isoformat()
        result = _status(provider)
    if before is not None:
        result = {
            **result,
            "mutation": {
                "operation": "EXTERNAL_DUMMY_BROKER_STATE_CHANGE",
                "executed_at_utc": mutation_completed_at_utc,
                "before": before,
                "after": result,
            },
        }
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0
