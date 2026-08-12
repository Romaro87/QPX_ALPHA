from __future__ import annotations

import hashlib
import unittest

import QPX_RUN_DYNAMIC_SIZING_PAIRED_CAPS as paired
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


class DynamicSizingPairedCapsTests(unittest.TestCase):
    def test_matrix_is_exact_and_has_no_search_surface(self) -> None:
        self.assertEqual(paired.CAP_ORDER, ("25", "40", "60", "90"))
        self.assertEqual(
            paired.ARM_ORDER,
            (
                "fixed_25", "dynamic_25", "fixed_40", "dynamic_40",
                "fixed_60", "dynamic_60", "fixed_90", "dynamic_90",
            ),
        )
        self.assertEqual(
            paired.PERIODS,
            {paired.FULL_PERIOD: (strict.START, strict.END), **paired.robustness.PERIODS},
        )

    def test_only_hard_cap_and_configuration_identity_vary(self) -> None:
        configs = {cap: paired.experimental_config(cap) for cap in paired.CAP_ORDER}
        reference = configs["25"]
        expected_caps = {"25": 0.25, "40": 0.40, "60": 0.60, "90": 0.90}
        for cap, config in configs.items():
            self.assertEqual(config.maximum_position_notional_fraction, expected_caps[cap])
            self.assertEqual(config.enabled, reference.enabled)
            self.assertEqual(config.accelerator_version, reference.accelerator_version)
            self.assertEqual(config.risk_tiers, reference.risk_tiers)
        self.assertEqual(
            reference.fingerprint,
            "dab4dda61ffeeb93a85a46caac2d8c46125145a89230e9e6490751723178b328",
        )

    def test_original_25pct_configuration_is_preserved_byte_for_byte(self) -> None:
        observed = hashlib.sha256(paired.dynamic.CONFIG_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            observed,
            "6141c3fabff38c18d37d43a06de7aaf5ffce748c88007363ea651ecbd6bf13e7",
        )

    def test_matching_account_caps_are_explicit(self) -> None:
        definitions = paired.load_definitions()["caps"]
        self.assertEqual(
            {cap: item["account_configuration"] for cap, item in definitions.items()},
            {
                "25": "cap_25pct",
                "40": "cap_40pct",
                "60": "cap_60pct",
                "90": "baseline",
            },
        )

    def test_scopes_apply_matching_cap_and_restore_runner(self) -> None:
        original_cap = strict.MAXIMUM_NOTIONAL_FRACTION
        original_start = strict.START
        for cap in paired.CAP_ORDER:
            with self.subTest(cap=cap):
                with paired.run_scope("p2_2025", cap):
                    self.assertEqual(
                        strict.MAXIMUM_NOTIONAL_FRACTION,
                        paired.experimental_config(cap).maximum_position_notional_fraction,
                    )
                    self.assertEqual(strict.START.isoformat(), "2025-01-02")
                self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, original_cap)
                self.assertEqual(strict.START, original_start)

    def test_validator_accepts_declared_caps_and_rejects_above_90(self) -> None:
        for cap in paired.CAP_ORDER:
            paired.experimental_config(cap).validate()
        invalid = paired.replace(
            paired.experimental_config("90"),
            maximum_position_notional_fraction=0.900001,
        )
        with self.assertRaises(ValueError):
            invalid.validate()


    def test_completed_matrix_preserves_guards_and_original_dynamic25(self) -> None:
        import json

        payload = json.loads(paired.SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["period_order"], list(paired.PERIODS))
        self.assertEqual(payload["cap_order"], list(paired.CAP_ORDER))
        old = json.loads(
            paired.dynamic_robustness.SUMMARY_PATH.read_text(encoding="utf-8")
        )
        for period in paired.PERIODS:
            for cap in paired.CAP_ORDER:
                pair = payload["matrix"][period][cap]
                for kind in ("fixed", "dynamic"):
                    self.assertEqual(
                        pair[kind]["dataset_fingerprint"],
                        paired.dynamic.DATASET_FINGERPRINT,
                    )
                    self.assertEqual(
                        pair[kind]["causal_gates"], paired.dynamic.formal.REQUIRED_GATES
                    )
                self.assertEqual(
                    pair["fixed"]["hard_cap"], pair["dynamic"]["hard_cap"]
                )
            if period != paired.FULL_PERIOD:
                previous = old["results"][period]["dynamic_sizing_v1"]
                current = payload["matrix"][period]["25"]["dynamic"]
                for group in ("metrics", "dynamic_sizing"):
                    for key, value in previous[group].items():
                        self.assertEqual(current[group][key], value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
