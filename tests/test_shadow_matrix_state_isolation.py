from __future__ import annotations

import unittest
from dataclasses import replace

from qpx_bot.shadow_matrix import (
    PositionEntrySnapshot,
    ShadowMatrixEngine,
    ShadowPosition,
    load_registry,
)


class ShadowMatrixStateIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ShadowMatrixEngine(load_registry())

    def test_every_shadow_owns_distinct_mutable_state_objects(self) -> None:
        states = list(self.engine.states.values())
        for attribute in (
            "qdte_state", "positions", "pending_orders", "accelerator_state",
            "performance_metrics", "checkpoint_state",
        ):
            identities = {id(getattr(state, attribute)) for state in states}
            self.assertEqual(len(identities), 45, attribute)

    def test_mutating_fixed25_cannot_change_any_other_shadow(self) -> None:
        before = {
            key: state.state_hash
            for key, state in self.engine.states.items()
            if key != "fixed_25"
        }
        target = self.engine.states["fixed_25"]
        target.swing_cash += 100.0
        target.qdte_state["entitlements"]["test"] = 12.5
        target.pending_orders["AMD"] = {"shares": 1}
        target.accelerator_state["dynamic_sizing"]["decision_count"] = 99
        target.performance_metrics.record_rejection("RISK")
        target.checkpoint_state["cursor"] = "only-fixed-25"
        self.assertEqual(
            before,
            {
                key: state.state_hash
                for key, state in self.engine.states.items()
                if key != "fixed_25"
            },
        )

    def test_open_position_retains_entry_configuration_snapshot(self) -> None:
        state = self.engine.states["dynamic_40"]
        entry_configuration = state.configuration
        snapshot = PositionEntrySnapshot(
            shadow_configuration=entry_configuration,
            entry_event_id="a" * 64,
            entry_event_sequence=7,
            accelerator_decision_id="b" * 64,
        )
        position = ShadowPosition(
            symbol="AMD", shares=2, entry_price=170.0, entry_snapshot=snapshot
        )
        state.positions["AMD"] = position
        hypothetical_future = replace(
            entry_configuration, governance_identity="FUTURE_CONFIGURATION_REVISION"
        )
        self.assertNotEqual(
            hypothetical_future.fingerprint, entry_configuration.fingerprint
        )
        self.assertIs(
            state.positions["AMD"].entry_snapshot.shadow_configuration,
            entry_configuration,
        )
        self.assertEqual(
            state.positions["AMD"].entry_snapshot.shadow_configuration.fingerprint,
            entry_configuration.fingerprint,
        )

    def test_each_shadow_has_independent_accounting_and_event_state(self) -> None:
        for state in self.engine.states.values():
            self.assertEqual(state.swing_cash, 5.34)
            self.assertEqual(state.qdte_state["market_value"], 1438.0)
            self.assertEqual(state.tax_reserve, 0.0)
            self.assertEqual(state.positions, {})
            self.assertEqual(state.pending_orders, {})
            self.assertEqual(state.event_sequence, 0)
            self.assertFalse(state.checkpoint_state["resume_authorized"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
