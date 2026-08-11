from __future__ import annotations

import unittest
from datetime import date

import QPX_RUN_CHALLENGER_ROBUSTNESS as robustness
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.risk import PositionSize


class ChallengerRobustnessTests(unittest.TestCase):
    def test_only_baseline_and_predeclared_caps_exist(self) -> None:
        self.assertEqual(
            robustness.CONFIGURATIONS,
            {"baseline": 0.90, "cap_40pct": 0.40, "cap_25pct": 0.25},
        )

    def test_nonoverlapping_partitions_cover_authentic_range(self) -> None:
        p1 = robustness.PERIODS["p1_2024"]
        p2 = robustness.PERIODS["p2_2025"]
        p3 = robustness.PERIODS["p3_2026"]
        self.assertEqual(p1[0], date(2024, 3, 7))
        self.assertEqual(p3[1], date(2026, 8, 7))
        self.assertLess(p1[1], p2[0])
        self.assertLess(p2[1], p3[0])

    def test_expanding_window_is_predeclared(self) -> None:
        self.assertEqual(
            robustness.PERIODS["e2_through_2025"],
            (date(2024, 3, 7), date(2025, 12, 31)),
        )

    def test_scope_restores_strict_runner_state(self) -> None:
        names = (
            "START",
            "END",
            "MAXIMUM_NOTIONAL_FRACTION",
            "REPORT_ROOT",
            "SUMMARY_PATH",
            "TRADES_PATH",
            "EQUITY_PATH",
            "SIGNALS_PATH",
            "ALLOCATIONS_PATH",
            "DIAGNOSTICS_PATH",
        )
        before = {name: getattr(strict, name) for name in names}
        before_vix = strict.qpx._validate_vix_daily_coverage
        before_cap = strict.apply_notional_cap
        with robustness.robustness_scope("p2_2025", "cap_25pct"):
            self.assertEqual(strict.START, date(2025, 1, 2))
            self.assertEqual(strict.END, date(2025, 12, 31))
            self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, 0.25)
        self.assertEqual(before, {name: getattr(strict, name) for name in names})
        self.assertIs(before_vix, strict.qpx._validate_vix_daily_coverage)
        self.assertIs(before_cap, strict.apply_notional_cap)

    def test_challenger_rejects_one_share_above_absolute_cap(self) -> None:
        sizing = PositionSize(
            shares=1,
            entry_fill=500.0,
            stop_price=450.0,
            target_price=600.0,
            risk_per_share=50.0,
            planned_risk=50.0,
            risk_fraction=0.03,
        )
        with robustness.robustness_scope("p3_2026", "cap_25pct"):
            adjusted, _, _ = strict.apply_notional_cap(
                sizing=sizing,
                account_equity=1300.0,
            )
        self.assertFalse(adjusted.is_tradeable)
        self.assertEqual(adjusted.shares, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
