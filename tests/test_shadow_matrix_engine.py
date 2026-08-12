from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

from qpx_bot.shadow_matrix import MarketEvent, ShadowMatrixEngine, load_registry


NOW = datetime(2026, 8, 12, 14, 30, tzinfo=timezone.utc)


def event(sequence: int, *, minutes: int | None = None) -> MarketEvent:
    return MarketEvent.create(
        sequence=sequence,
        timestamp=NOW + timedelta(minutes=sequence if minutes is None else minutes),
        event_type="MARKET_OPEN_SCALAR_SNAPSHOT",
        payload={"symbol": "AMD", "open": 172.5, "available": True},
    )


class ShadowMatrixEngineTests(unittest.TestCase):
    def test_one_immutable_event_object_fans_out_in_registry_order(self) -> None:
        seen = []

        def handler(shared_event, state):
            seen.append((id(shared_event), state.configuration.shadow_id))
            return "OBSERVED", {"event_id": shared_event.event_id}

        engine = ShadowMatrixEngine(load_registry(), handler=handler)
        shared = event(1)
        records = engine.dispatch(shared)
        self.assertEqual([item.shadow_id for item in records], list(engine.registry.by_id))
        self.assertEqual({identity for identity, _ in seen}, {id(shared)})
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            shared.sequence = 2
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            shared.payload.items = ()

    def test_empty_object_and_array_have_distinct_immutable_identity(self) -> None:
        empty_object = MarketEvent.create(
            sequence=1, timestamp=NOW, event_type="OBJECT", payload={}
        )
        empty_array = MarketEvent.create(
            sequence=1, timestamp=NOW, event_type="OBJECT", payload=[]
        )
        self.assertNotEqual(empty_object.payload, empty_array.payload)
        self.assertNotEqual(empty_object.event_id, empty_array.event_id)

    def test_duplicate_non_contiguous_and_non_monotonic_time_are_rejected(self) -> None:
        engine = ShadowMatrixEngine(load_registry())
        first = event(1)
        engine.dispatch(first)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            engine.dispatch(first)
        with self.assertRaisesRegex(ValueError, "expected 2"):
            engine.dispatch(event(3))
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            engine.dispatch(event(2, minutes=1))

    def test_decision_records_contain_deterministic_audit_fields(self) -> None:
        engine = ShadowMatrixEngine(load_registry())
        records = engine.dispatch(event(1))
        self.assertEqual(len(records), 17)
        for record in records:
            self.assertEqual(len(record.record_id), 64)
            self.assertEqual(len(record.before_state_hash), 64)
            self.assertEqual(len(record.after_state_hash), 64)
            self.assertNotEqual(record.before_state_hash, record.after_state_hash)
            self.assertEqual(record.event_sequence, 1)
            self.assertEqual(
                record.status, "EVENT_ACKNOWLEDGED_NO_STRATEGY_DECISION"
            )

    def test_identical_legal_replay_produces_identical_records_and_states(self) -> None:
        first = ShadowMatrixEngine(load_registry())
        second = ShadowMatrixEngine(load_registry())
        sequence = (event(1), event(2), event(3))
        first_records = tuple(item for shared in sequence for item in first.dispatch(shared))
        second_records = tuple(item for shared in sequence for item in second.dispatch(shared))
        self.assertEqual(first_records, second_records)
        self.assertEqual(
            {key: state.state_hash for key, state in first.states.items()},
            {key: state.state_hash for key, state in second.states.items()},
        )

    def test_dispatch_quarantines_one_failure_and_advances_healthy_shadows(self) -> None:
        def handler(shared_event, state):
            state.swing_cash += 1.0
            if state.configuration.shadow_id == "dynamic_60":
                raise RuntimeError("injected failure")
            return "OBSERVED", None

        engine = ShadowMatrixEngine(load_registry(), handler=handler)
        before = {key: state.state_hash for key, state in engine.states.items()}
        records = engine.dispatch(event(1))
        self.assertEqual(before["dynamic_60"], engine.states["dynamic_60"].state_hash)
        self.assertIn("dynamic_60", engine.quarantines)
        self.assertEqual(engine.states["fixed_60"].event_sequence, 1)
        self.assertEqual(records[6].status, "SHADOW_HANDLER_FAILED_QUARANTINED")
        self.assertEqual(engine.last_sequence, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
