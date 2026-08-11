from __future__ import annotations

import unittest
from datetime import date

import QPX_RUN_CHALLENGER_ACCOUNT_ROBUSTNESS as robustness
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


class AccountSizedRobustnessTests(unittest.TestCase):
    def test_fixed_periods_cover_authentic_range(self) -> None:
        self.assertEqual(
            robustness.PERIODS["p1_2024"],
            (date(2024, 3, 7), date(2024, 12, 31)),
        )
        self.assertEqual(
            robustness.PERIODS["p3_2026"],
            (date(2026, 1, 2), date(2026, 8, 7)),
        )

    def test_only_requested_configurations_are_available(self) -> None:
        self.assertEqual(
            robustness.account.CONFIGURATIONS,
            {
                "baseline": 0.90,
                "cap_60pct": 0.60,
                "cap_40pct": 0.40,
                "cap_25pct": 0.25,
            },
        )

    def test_scope_applies_account_state_and_restores_runner(self) -> None:
        original_config = strict.candidate_config
        original_start = strict.START
        with robustness.account_robustness_scope("p2_2025", "cap_25pct"):
            config = strict.candidate_config()
            self.assertEqual(config.starting_cash, 1438.00)
            self.assertEqual(config.starting_swing_cash, 5.34)
            self.assertEqual(strict.START, date(2025, 1, 2))
            self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, 0.25)
        self.assertIs(strict.candidate_config, original_config)
        self.assertEqual(strict.START, original_start)


if __name__ == "__main__":
    unittest.main(verbosity=2)
