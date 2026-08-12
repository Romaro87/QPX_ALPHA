from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace

from qpx_bot.shadow_matrix import ShadowRole, load_registry
from qpx_bot.shadow_matrix.models import AcceleratorSnapshot, ShadowConfiguration
from qpx_bot.shadow_matrix.registry import EXPECTED_IDS, ShadowRegistry


class ShadowMatrixRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_registry()

    def test_registry_contains_exactly_seventeen_ordered_governance_identities(self) -> None:
        self.assertEqual(
            tuple(item.shadow_id for item in self.registry.configurations),
            EXPECTED_IDS,
        )
        self.assertEqual(len(self.registry.configurations), 17)
        self.assertNotEqual(
            self.registry.by_id["permanent_control"].governance_identity,
            self.registry.by_id["fixed_90"].governance_identity,
        )

    def test_permanent_control_is_separate_and_all_accelerators_are_off(self) -> None:
        control = self.registry.by_id["permanent_control"]
        self.assertIs(control.role, ShadowRole.CONTROL)
        self.assertTrue(all(not item.enabled for item in control.accelerators))
        enabled = replace(control.accelerators[0], enabled=True)
        with self.assertRaises(ValueError):
            replace(control, accelerators=(enabled,))

    def test_paired_definitions_differ_only_by_dynamic_sizing_identity(self) -> None:
        for cap in (25, 40, 60, 90):
            with self.subTest(cap=cap):
                fixed = self.registry.by_id[f"fixed_{cap}"]
                dynamic = self.registry.by_id[f"dynamic_{cap}"]
                self.assertEqual(fixed.hard_notional_cap, cap / 100)
                self.assertEqual(dynamic.hard_notional_cap, cap / 100)
                for field in (
                    "strategy_id", "strategy_reference_commit", "starting_state_profile",
                    "starting_qdte_value", "starting_swing_cash", "starting_total_equity",
                ):
                    self.assertEqual(getattr(fixed, field), getattr(dynamic, field))
                self.assertFalse(fixed.accelerators[0].enabled)
                self.assertTrue(dynamic.accelerators[0].enabled)
                self.assertEqual(
                    fixed.accelerators[0].name, dynamic.accelerators[0].name
                )

    def test_registry_and_configuration_snapshots_are_immutable(self) -> None:
        configuration = self.registry.by_id["dynamic_25"]
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            configuration.hard_notional_cap = 0.40
        with self.assertRaises(TypeError):
            self.registry.by_id["dynamic_25"] = configuration

    def test_configuration_fingerprints_are_deterministic_and_unique(self) -> None:
        first = load_registry()
        second = load_registry()
        self.assertEqual(
            [item.fingerprint for item in first.configurations],
            [item.fingerprint for item in second.configurations],
        )
        self.assertEqual(
            len({item.fingerprint for item in first.configurations}), 17
        )

    def test_dynamic_tiers_are_exact_and_automatic_promotion_is_forbidden(self) -> None:
        self.assertFalse(self.registry.automatic_promotion)
        expected = [
            {"upper_bound": 0.25, "multiplier": 1.0},
            {"upper_bound": 0.5, "multiplier": 0.85},
            {"upper_bound": 0.75, "multiplier": 0.7},
            {"upper_bound": None, "multiplier": 0.5},
        ]
        from qpx_bot.shadow_matrix.models import thaw_json
        for cap in (25, 40, 60, 90):
            parameters = thaw_json(
                self.registry.by_id[f"dynamic_{cap}"].accelerators[0].parameters
            )
            self.assertEqual(parameters["risk_tiers"], expected)
            self.assertEqual(
                parameters["maximum_position_notional_fraction"], cap / 100
            )
            self.assertTrue(parameters["reduction_only"])

    def test_required_provenance_is_embedded(self) -> None:
        self.assertEqual(
            dict(self.registry.provenance),
            {
                "candidate_v1_qualification_commit": "7213db1e17fedce9e923889b116775cca121f766",
                "dynamic_paired_cap_results_commit": "625cb218d9ec6b15278716dad648d9e25614bb04",
                "fixed_25_qualification_commit": "bba0f48273815ede42374015db7c5770bf446962",
                "research_parent_commit": "cf1d059a54efdbe455e2f9edf340662d15d57aa3",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
