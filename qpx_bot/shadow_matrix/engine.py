"""Deterministic transactional fan-out for isolated Shadow states."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import datetime
from typing import Any

from qpx_bot.shadow_matrix.models import (
    DecisionRecord,
    MarketEvent,
    canonical_hash,
    freeze_json,
    thaw_json,
)
from qpx_bot.shadow_matrix.registry import ShadowRegistry
from qpx_bot.shadow_matrix.state import ShadowState


ShadowHandler = Callable[[MarketEvent, ShadowState], tuple[str, Any]]


def acknowledge_event(event: MarketEvent, state: ShadowState) -> tuple[str, Any]:
    """Foundation handler: advance causal state without fabricating a trade."""
    return "EVENT_ACKNOWLEDGED_NO_STRATEGY_DECISION", {
        "event_type": event.event_type,
        "strategy_decision": None,
    }


class ShadowMatrixEngine:
    def __init__(
        self,
        registry: ShadowRegistry,
        *,
        handler: ShadowHandler = acknowledge_event,
    ) -> None:
        self.registry = registry
        self._handler = handler
        self.states = {
            item.shadow_id: ShadowState.initial(item)
            for item in registry.configurations
        }
        self.decision_log: list[DecisionRecord] = []
        self.last_sequence = 0
        self.last_timestamp: datetime | None = None
        self.seen_event_ids: set[str] = set()

    def dispatch(self, event: MarketEvent) -> tuple[DecisionRecord, ...]:
        self._validate_event(event)
        working = copy.deepcopy(self.states)
        records = []
        for configuration in self.registry.configurations:
            state = working[configuration.shadow_id]
            before = state.state_hash
            status, payload = self._handler(event, state)
            state.event_sequence = event.sequence
            state.last_event_id = event.event_id
            state.performance_metrics["event_count"] = float(event.sequence)
            state.checkpoint_state["last_event_timestamp"] = event.timestamp.isoformat()
            after = state.state_hash
            frozen_payload = freeze_json(payload)
            record_core = {
                "event_id": event.event_id,
                "event_sequence": event.sequence,
                "event_timestamp": event.timestamp.isoformat(),
                "shadow_id": configuration.shadow_id,
                "shadow_configuration_fingerprint": configuration.fingerprint,
                "before_state_hash": before,
                "after_state_hash": after,
                "accelerator_identities": [
                    item.as_dict() for item in configuration.accelerators
                ],
                "status": status,
                "result_payload": thaw_json(frozen_payload),
            }
            records.append(DecisionRecord(
                event_id=event.event_id,
                event_sequence=event.sequence,
                event_timestamp=event.timestamp,
                shadow_id=configuration.shadow_id,
                shadow_configuration_fingerprint=configuration.fingerprint,
                before_state_hash=before,
                after_state_hash=after,
                accelerator_identities=configuration.accelerators,
                status=status,
                result_payload=frozen_payload,
                record_id=canonical_hash(record_core),
            ))
        self.states = working
        self.decision_log.extend(records)
        self.last_sequence = event.sequence
        self.last_timestamp = event.timestamp
        self.seen_event_ids.add(event.event_id)
        return tuple(records)

    def _validate_event(self, event: MarketEvent) -> None:
        if event.event_id in self.seen_event_ids:
            raise ValueError(f"Duplicate market event: {event.event_id}")
        if event.sequence != self.last_sequence + 1:
            raise ValueError(
                f"Non-monotonic event sequence: expected {self.last_sequence + 1}, "
                f"received {event.sequence}."
            )
        if self.last_timestamp is not None and event.timestamp <= self.last_timestamp:
            raise ValueError("Market event timestamps must be strictly increasing.")
