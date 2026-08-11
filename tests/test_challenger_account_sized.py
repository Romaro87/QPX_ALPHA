from __future__ import annotations

import unittest

import QPX_RUN_CHALLENGER_ACCOUNT_SIZED as account
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.risk import PositionSize


class AccountSizedChallengerTests(unittest.TestCase):
    def test_only_requested_starting_amounts_and_caps_are_declared(self) -> None:
        self.assertEqual(account.STARTING_QDTE_VALUE, 1438.00)
        self.assertEqual(account.STARTING_SWING_CASH, 5.34)
        self.assertEqual(account.STARTING_TOTAL_EQUITY, 1443.34)
        self.assertEqual(
            account.CONFIGURATIONS,
            {
                "baseline": 0.90,
                "cap_60pct": 0.60,
                "cap_40pct": 0.40,
                "cap_25pct": 0.25,
            },
        )

    def test_scope_changes_starting_state_and_restores_runner(self) -> None:
        original_config = strict.candidate_config
        original_run = strict.run_strict
        with account.account_sized_scope("cap_40pct"):
            config = strict.candidate_config()
            self.assertEqual(config.starting_cash, 1438.00)
            self.assertEqual(config.starting_swing_cash, 5.34)
            self.assertEqual(config.total_starting_capital, 1443.34)
            self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, 0.40)
            self.assertIn(1443.34, strict.run_strict.__code__.co_consts)
        self.assertIs(strict.candidate_config, original_config)
        self.assertIs(strict.run_strict, original_run)

    def test_challenger_cap_is_absolute_but_baseline_is_unchanged(self) -> None:
        sizing = PositionSize(
            shares=1,
            entry_fill=500.0,
            stop_price=450.0,
            target_price=600.0,
            risk_per_share=50.0,
            planned_risk=50.0,
            risk_fraction=0.03,
        )
        with account.account_sized_scope("cap_25pct"):
            adjusted, _, _ = strict.apply_notional_cap(
                sizing=sizing,
                account_equity=1443.34,
            )
            self.assertFalse(adjusted.is_tradeable)
        with account.account_sized_scope("baseline"):
            adjusted, _, floor = strict.apply_notional_cap(
                sizing=sizing,
                account_equity=1443.34,
            )
            self.assertTrue(adjusted.is_tradeable)
            self.assertFalse(floor)


if __name__ == "__main__":
    unittest.main(verbosity=2)
