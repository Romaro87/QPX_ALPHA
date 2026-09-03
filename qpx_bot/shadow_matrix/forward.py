"""Forward-only adapter for feeding one Clean-V2 causal snapshot to Shadow Matrix.

The adapter deliberately has no provider or order client.  It receives the
already acquired cycle inputs and persists the existing engine checkpoint in
the governed runtime state.  The default handler records observation-only
evidence; strategy promotion is not performed here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from .checkpoint import restore_checkpoint, serialize_checkpoint
from .engine import ShadowMatrixEngine
from .models import MarketEvent, thaw_json
from .registry import load_registry

CHECKPOINT_KEY = "shadow_matrix_checkpoint"
SUMMARY_EVENT = "SHADOW_MATRIX_DECISION_CYCLE"
SCHEMA_VERSION = 1


def _finite(value: Any) -> Any:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def build_cycle_payload(
    *,
    symbols: tuple[str, ...],
    histories: Mapping[str, list[Mapping[str, Any]]],
    indices: Mapping[str, Mapping[datetime, int]],
    indicators: Mapping[str, Any],
    bar_time: datetime,
    observed_at: datetime,
    vix: float | None,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a compact immutable snapshot from data already fetched by QPX."""
    observations: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        index = indices.get(symbol, {}).get(bar_time)
        if index is None:
            observations[symbol] = {"available": False}
            continue
        row = histories[symbol][index]
        item: dict[str, Any] = {
            "available": True,
            "bar_start": str(row.get("start")),
            "open": _finite(row.get("open")), "high": _finite(row.get("high")),
            "low": _finite(row.get("low")), "close": _finite(row.get("close")),
            "volume": _finite(row.get("volume")),
        }
        indicator = indicators.get(symbol)
        for name in ("sma", "atr", "rsi", "average_volume"):
            values = getattr(indicator, name, None)
            if values is not None and index < len(values):
                item[name] = _finite(values[index])
        observations[symbol] = item
    return {
        "schema_version": SCHEMA_VERSION,
        "decision_bar": bar_time.isoformat(),
        "decision_observed_at": observed_at.isoformat(),
        "decision_bar_interval": {
            "start": bar_time.isoformat(),
            "end": (bar_time + timedelta(minutes=15)).isoformat(),
        },
        "universe_fingerprint": contract.get("universe_manifest_fingerprint"),
        "symbols": list(symbols),
        "observations": observations,
        "vix": _finite(vix),
        "provider_feed": contract.get("feed"),
        "bar_adjustment": contract.get("bar_adjustment"),
        "provider_input_semantics_version": contract.get("provider_input_semantics_version"),
        "semantic_contract_fingerprint": contract.get("contract_fingerprint"),
        "entry_semantics_fingerprint": contract.get("entry_semantics_fingerprint"),
    }


def _observation_handler(event: MarketEvent, state: Any) -> tuple[str, dict[str, Any]]:
    payload = thaw_json(event.payload)
    return "OBSERVED_NO_PROMOTION", {
        "decision_id": event.event_id,
        "shadow_id": state.configuration.shadow_id,
        "symbol_count": len(payload.get("symbols", [])),
        "strategy_decision": None,
        "automatic_promotion": False,
    }


def _seed_from_governed(engine: ShadowMatrixEngine, governed: Mapping[str, Any]) -> None:
    """Seed isolated shadow ledgers from the current governed economic snapshot."""
    cash = float(governed.get("cash", 0.0))
    qdte_shares = int(governed.get("qdte_shares", 0))
    qdte_cost = float(governed.get("qdte_cost", 0.0))
    positions = governed.get("positions") or {}
    if cash < 0 or qdte_shares < 0 or not isinstance(positions, Mapping):
        raise ValueError("Governed account snapshot is invalid for Shadow seeding.")
    for state in engine.states.values():
        state.swing_cash = cash
        state.qdte_state = {
            "market_value": qdte_cost,
            "shares": qdte_shares,
            "entitlements": {},
            "settlements": {},
        }
        # Position-specific forward adapters are intentionally not guessed here;
        # unsupported non-empty governed positions fail closed at activation.
        if positions:
            raise ValueError("Shadow seeding requires an explicitly supported flat governed account.")


def dispatch_cycle(
    state: dict[str, Any],
    store: Any,
    *,
    payload: Mapping[str, Any],
    observed_at: datetime,
) -> dict[str, Any]:
    """Dispatch one shared event and durably attach the canonical checkpoint."""
    raw = state.get(CHECKPOINT_KEY)
    if raw:
        engine = restore_checkpoint(json.dumps(raw, sort_keys=True, separators=(",", ":")), load_registry(), handler=_observation_handler)
    else:
        engine = ShadowMatrixEngine(load_registry(), handler=_observation_handler)
        _seed_from_governed(engine, state)
    sequence = engine.last_sequence + 1
    event_timestamp = observed_at
    if engine.last_timestamp is not None and event_timestamp <= engine.last_timestamp:
        # Catch-up can contain several completed bars observed in one provider
        # response.  Keep engine ordering deterministic; the payload retains
        # the real decision-observed timestamp for causal interpretation.
        event_timestamp = engine.last_timestamp + timedelta(microseconds=1)
    event = MarketEvent.create(
        sequence=sequence, timestamp=event_timestamp,
        event_type="CLEAN_V2_CAUSAL_TOP100_DECISION_CYCLE", payload=dict(payload),
    )
    records = engine.dispatch(event)
    checkpoint = json.loads(serialize_checkpoint(engine).decode("utf-8"))
    state[CHECKPOINT_KEY] = checkpoint
    summary = {
        "event_id": event.event_id,
        "event_sequence": sequence,
        "decision_bar": payload.get("decision_bar"),
        "semantic_contract_fingerprint": payload.get("semantic_contract_fingerprint"),
        "registry_fingerprint": engine.registry.fingerprint,
        "dispatch_count": len(records),
        "healthy_count": sum(r.status != "SHADOW_HANDLER_FAILED_QUARANTINED" for r in records),
        "quarantined_count": len(engine.quarantines),
        "automatic_promotion": False,
        "observed_at": observed_at.isoformat(),
    }
    state["shadow_matrix_event_pending"] = summary
    return summary


def flush_pending_event(state: dict[str, Any], store: Any) -> bool:
    summary = state.pop("shadow_matrix_event_pending", None)
    if summary is None:
        return False
    store.event(SUMMARY_EVENT, summary)
    store.save(state)
    return True
