from __future__ import annotations

import unittest
from datetime import date

import QPX_RUN_DYNAMIC_SIZING_ROBUSTNESS as runner
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


class DynamicSizingRobustnessTests(unittest.TestCase):
    def test_periods_are_the_existing_predeclared_objects(self) -> None:
        self.assertIs(runner.PERIODS, runner.robustness.PERIODS)
        self.assertEqual(
            runner.PERIODS,
            {
                "p1_2024": (date(2024, 3, 7), date(2024, 12, 31)),
                "p2_2025": (date(2025, 1, 2), date(2025, 12, 31)),
                "p3_2026": (date(2026, 1, 2), date(2026, 8, 7)),
                "e2_through_2025": (date(2024, 3, 7), date(2025, 12, 31)),
            },
        )

    def test_only_fixed25_and_unchanged_dynamic_v1_are_available(self) -> None:
        self.assertEqual(runner.ARMS, ("fixed_25pct", "dynamic_sizing_v1"))
        self.assertEqual(runner.CONFIGURATION, "cap_25pct")
        config = runner.load_dynamic_sizing_config(runner.dynamic.CONFIG_PATH, enabled=True)
        self.assertEqual(config.fingerprint, "dab4dda61ffeeb93a85a46caac2d8c46125145a89230e9e6490751723178b328")

    def test_nested_scopes_restore_dates_outputs_and_accelerator_hooks(self) -> None:
        original = {
            "start": strict.START,
            "summary": strict.SUMMARY_PATH,
            "cap": strict.apply_notional_cap,
        }
        config = runner.load_dynamic_sizing_config(runner.dynamic.CONFIG_PATH, enabled=True)
        accelerator = runner.DynamicSizingV1(config)
        destination = runner.report_root("p2_2025", "dynamic_sizing_v1")
        with runner.robustness.account_robustness_scope("p2_2025", runner.CONFIGURATION):
            with runner.output_paths(destination):
                with runner.dynamic.enabled_accelerator_scope(
                    accelerator, strict.candidate_config()
                ):
                    self.assertEqual(strict.START, date(2025, 1, 2))
                    self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, 0.25)
                    self.assertEqual(strict.SUMMARY_PATH, destination / "summary.json")
                    self.assertIsNot(strict.apply_notional_cap, original["cap"])
        self.assertEqual(strict.START, original["start"])
        self.assertEqual(strict.SUMMARY_PATH, original["summary"])
        self.assertIs(strict.apply_notional_cap, original["cap"])

    def test_comparison_uses_higher_return_and_lower_drawdown(self) -> None:
        def arm(ret, eod, intraday):
            return {"metrics": {
                "ending_equity": 100.0 + ret,
                "total_return": ret,
                "eod_maximum_drawdown": eod,
                "intraday_maximum_drawdown": intraday,
            }}
        comparison = runner.compare(arm(1.0, 0.2, 0.3), arm(2.0, 0.1, 0.25))
        self.assertEqual(comparison["return_winner"], "dynamic_sizing_v1")
        self.assertEqual(comparison["eod_drawdown_winner"], "dynamic_sizing_v1")
        self.assertEqual(comparison["intraday_drawdown_winner"], "dynamic_sizing_v1")


    def test_completed_summary_has_all_periods_and_identical_guards(self) -> None:
        import json

        payload = json.loads(runner.SUMMARY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["period_order"], list(runner.PERIODS))
        self.assertEqual(
            payload["configuration_fingerprint"],
            "dab4dda61ffeeb93a85a46caac2d8c46125145a89230e9e6490751723178b328",
        )
        for period in runner.PERIODS:
            result = payload["results"][period]
            for arm in runner.ARMS:
                self.assertEqual(
                    result[arm]["dataset_fingerprint"],
                    runner.dynamic.DATASET_FINGERPRINT,
                )
                self.assertEqual(
                    result[arm]["causal_gates"], runner.dynamic.formal.REQUIRED_GATES
                )
            self.assertEqual(
                result["dynamic_sizing_v1"]["configuration_fingerprint"],
                payload["configuration_fingerprint"],
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
