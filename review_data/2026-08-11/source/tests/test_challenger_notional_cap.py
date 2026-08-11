from __future__ import annotations

import unittest

import QPX_RUN_CHALLENGER_NOTIONAL_CAP as challenger
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict


class NotionalCapChallengerTests(unittest.TestCase):
    def test_only_predeclared_caps_are_accepted(self) -> None:
        self.assertEqual(challenger.ALLOWED_CAPS, (0.25, 0.40, 0.60))
        for cap in challenger.ALLOWED_CAPS:
            self.assertIn(f"cap_{int(cap * 100):02d}pct", str(challenger.report_root(cap)))
        with self.assertRaises(ValueError):
            challenger.report_root(0.50)

    def test_scope_changes_only_cap_and_output_paths_then_restores(self) -> None:
        names = (
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
        with challenger.challenger_scope(0.40) as destination:
            self.assertEqual(strict.MAXIMUM_NOTIONAL_FRACTION, 0.40)
            self.assertEqual(strict.REPORT_ROOT, destination)
            self.assertEqual(strict.SUMMARY_PATH, destination / "summary.json")
            self.assertNotEqual(destination, before["REPORT_ROOT"])
        self.assertEqual(before, {name: getattr(strict, name) for name in names})

    def test_qualified_baseline_files_match_immutable_commit(self) -> None:
        challenger.verify_immutable_baseline()


if __name__ == "__main__":
    unittest.main(verbosity=2)
