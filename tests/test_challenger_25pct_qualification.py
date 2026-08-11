from __future__ import annotations

import unittest

import QPX_RUN_CHALLENGER_25PCT_QUALIFICATION as qualification
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


class Fixed25PctQualificationTests(unittest.TestCase):
    def test_definition_is_fixed_and_has_no_cap_search_surface(self) -> None:
        self.assertEqual(qualification.MAXIMUM_POSITION_NOTIONAL_FRACTION, 0.25)
        self.assertEqual(qualification.STARTING_QDTE_VALUE, 1438.00)
        self.assertEqual(qualification.STARTING_SWING_CASH, 5.34)
        self.assertEqual(qualification.STARTING_TOTAL_EQUITY, 1443.34)
        self.assertEqual(qualification.RUN_IDS, ("run_1", "run_2"))
        qualification.verify_fixed_definition()

    def test_isolation_audit_passes_and_restores_candidate_runner(self) -> None:
        before = {
            "candidate_config": strict.candidate_config,
            "run_strict": strict.run_strict,
            "apply_notional_cap": strict.apply_notional_cap,
            "maximum_notional_fraction": strict.MAXIMUM_NOTIONAL_FRACTION,
        }
        audit = qualification.isolation_audit()
        self.assertEqual(audit["status"], "PASS")
        self.assertEqual(
            audit["only_intentional_behavioral_differences"],
            [
                "maximum_position_notional_fraction",
                "starting_qdte_value",
                "starting_swing_cash",
            ],
        )
        self.assertIs(strict.candidate_config, before["candidate_config"])
        self.assertIs(strict.run_strict, before["run_strict"])
        self.assertIs(strict.apply_notional_cap, before["apply_notional_cap"])
        self.assertEqual(
            strict.MAXIMUM_NOTIONAL_FRACTION,
            before["maximum_notional_fraction"],
        )

    def test_all_required_causal_gates_are_fail_closed(self) -> None:
        self.assertEqual(
            qualification.REQUIRED_GATES,
            {
                "LOOKAHEAD_PROTECTION": "PASS",
                "SIMULATION_CLOCK": "STRICT_RECORDED_UNION",
                "FUTURE_BAR_ACCESS": "BLOCKED",
                "CURRENT_OPEN_FULL_OHLCV": "BLOCKED",
                "SYNTHETIC_FUTURE_DATA": "NONE",
                "DECISION_DATA_CUTOFF": "VERIFIED_SWING_STRATEGY_BOUNDARY",
                "EXECUTION_TIMING": "VERIFIED_OPEN_CLOSE_PHASES",
                "MISSING_SYMBOL_BAR_HANDLING": "UNAVAILABLE_SYMBOL_ONLY",
                "INDICATOR_PREFIX_EQUIVALENCE": "PASS",
                "STRATEGY_SEMANTIC_EQUIVALENCE": "PASS",
                "CORPORATE_ACTION_CASH_TIMING": "PASS_LATER_OF_PAYABLE_OR_PROCESS_DATE",
                "DIVIDEND_ENTITLEMENT": "PASS_EX_DATE_OWNERSHIP_SNAPSHOT",
                "OVERALL_PORTFOLIO_QUALIFICATION": "FULL_CAUSAL_ACCOUNTING_PASS",
            },
        )

    def test_periods_are_the_predeclared_robustness_periods(self) -> None:
        self.assertEqual(
            tuple(qualification.robustness.PERIODS),
            ("p1_2024", "p2_2025", "p3_2026", "e2_through_2025"),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
