"""Deterministic checkpoint serialization and fail-closed restore."""

from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING, Any

from qpx_bot.shadow_matrix.models import canonical_hash
from qpx_bot.shadow_matrix.registry import ShadowRegistry
from qpx_bot.shadow_matrix.state import ShadowState

if TYPE_CHECKING:
    from qpx_bot.shadow_matrix.engine import ShadowHandler, ShadowMatrixEngine


CHECKPOINT_SCHEMA_VERSION = 1


class ShadowCheckpointError(RuntimeError):
    pass


def serialize_checkpoint(engine: "ShadowMatrixEngine") -> bytes:
    states = {}
    for shadow_id in engine.dispatch_order:
        state = engine.states[shadow_id]
        state_payload = state.to_checkpoint_dict()
        states[shadow_id] = {
            "state": state_payload,
            "state_hash": state.state_hash,
        }
    payload = {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "matrix_version": engine.registry.matrix_version,
        "registry_fingerprint": engine.registry.fingerprint,
        "configuration_fingerprints": {
            item.shadow_id: item.fingerprint
            for item in engine.registry.configurations
        },
        "dispatch_order": list(engine.dispatch_order),
        "last_accepted_event_sequence": engine.last_sequence,
        "last_accepted_event_timestamp": (
            engine.last_timestamp.isoformat() if engine.last_timestamp else None
        ),
        "event_history": engine.event_history,
        "seen_event_ids": sorted(engine.seen_event_ids),
        "states": states,
        "quarantines": {
            key: value.as_dict() for key, value in sorted(engine.quarantines.items())
        },
        "decision_log": [item.as_dict() for item in engine.decision_log],
        "divergence_log": [item.as_dict() for item in engine.divergence_log],
    }
    envelope = {"payload": payload, "checksum": canonical_hash(payload)}
    return json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def restore_checkpoint(
    data: bytes | str,
    registry: ShadowRegistry,
    *,
    handler: "ShadowHandler | None" = None,
) -> "ShadowMatrixEngine":
    from qpx_bot.shadow_matrix.engine import ShadowMatrixEngine
    from qpx_bot.shadow_matrix.models import (
        DecisionRecord,
        DivergenceRecord,
        QuarantineRecord,
    )

    try:
        envelope = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
        raise ShadowCheckpointError("Checkpoint is not valid deterministic JSON.") from error
    if set(envelope) != {"payload", "checksum"}:
        raise ShadowCheckpointError("Checkpoint envelope is malformed.")
    payload = envelope["payload"]
    if envelope["checksum"] != canonical_hash(payload):
        raise ShadowCheckpointError("Checkpoint checksum mismatch.")
    if payload.get("checkpoint_schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise ShadowCheckpointError("Unsupported checkpoint schema version.")
    if payload.get("matrix_version") != registry.matrix_version:
        raise ShadowCheckpointError("Checkpoint matrix version is incompatible.")
    if payload.get("registry_fingerprint") != registry.fingerprint:
        raise ShadowCheckpointError("Checkpoint registry fingerprint differs.")
    dispatch_order = tuple(payload.get("dispatch_order", ()))
    if dispatch_order != registry.dispatch_order:
        raise ShadowCheckpointError("Checkpoint dispatch order differs.")
    expected_fingerprints = {
        item.shadow_id: item.fingerprint for item in registry.configurations
    }
    if payload.get("configuration_fingerprints") != expected_fingerprints:
        raise ShadowCheckpointError("Checkpoint configuration fingerprint differs.")
    if set(payload.get("states", {})) != set(dispatch_order):
        raise ShadowCheckpointError("Checkpoint has missing or extra Shadow state.")

    engine = ShadowMatrixEngine(registry, **({} if handler is None else {"handler": handler}))
    restored_states = {}
    for shadow_id in dispatch_order:
        wrapper = payload["states"][shadow_id]
        state = ShadowState.from_checkpoint_dict(
            wrapper["state"], registry.by_id[shadow_id]
        )
        if state.state_hash != wrapper["state_hash"]:
            raise ShadowCheckpointError(f"{shadow_id}: restored state hash differs.")
        restored_states[shadow_id] = state

    history = payload.get("event_history", [])
    last_sequence = payload.get("last_accepted_event_sequence")
    if last_sequence != len(history):
        raise ShadowCheckpointError("Checkpoint event history is not contiguous.")
    if [item.get("sequence") for item in history] != list(range(1, last_sequence + 1)):
        raise ShadowCheckpointError("Checkpoint event sequence history is invalid.")
    history_ids = [item.get("event_id") for item in history]
    if sorted(history_ids) != payload.get("seen_event_ids") or len(set(history_ids)) != len(history_ids):
        raise ShadowCheckpointError("Checkpoint seen-event continuity differs.")
    timestamp_text = payload.get("last_accepted_event_timestamp")
    expected_timestamp = history[-1]["timestamp"] if history else None
    if timestamp_text != expected_timestamp:
        raise ShadowCheckpointError("Checkpoint last event timestamp differs.")

    engine.states = restored_states
    engine.last_sequence = last_sequence
    engine.last_timestamp = datetime.fromisoformat(timestamp_text) if timestamp_text else None
    engine.event_history = history
    engine.seen_event_ids = set(history_ids)
    engine.quarantines = {
        key: QuarantineRecord.from_dict(value)
        for key, value in payload.get("quarantines", {}).items()
    }
    engine.decision_log = [DecisionRecord.from_dict(item) for item in payload.get("decision_log", [])]
    engine.divergence_log = [
        DivergenceRecord.from_dict(item) for item in payload.get("divergence_log", [])
    ]
    if serialize_checkpoint(engine) != (
        data.encode("utf-8") if isinstance(data, str) else data
    ):
        raise ShadowCheckpointError("Checkpoint cannot be reconstructed byte-for-byte.")
    return engine
