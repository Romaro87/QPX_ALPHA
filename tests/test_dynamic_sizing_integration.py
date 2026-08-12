from __future__ import annotations

import json
import unittest

import QPX_RUN_ACCELERATOR_DYNAMIC_SIZING as runner
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as strict
from qpx_bot.accelerators.dynamic_sizing import DynamicSizingV1, load_dynamic_sizing_config
from qpx_bot.causal_replay import CausalDataPortal
from qpx_bot.portfolio import Portfolio
from qpx_bot.qualification_provenance import verify_immutable_provenance


class DynamicSizingIntegrationTests(unittest.TestCase):
    def test_candidate_and_fixed25_protected_scopes_pass(self) -> None:
        runner.formal.verify_fixed_definition()
        result = verify_immutable_provenance()
        self.assertEqual(result["status"], "PASS")

    def test_enabled_scope_isolated_and_fully_restored(self) -> None:
        originals = {
            "current_open": CausalDataPortal.current_open,
            "marks": strict.current_position_marks,
            "cap": strict.apply_notional_cap,
            "open_position": Portfolio.open_position,
            "candidate_config": strict.candidate_config,
            "strategy": strict.evaluate_candidate_v1_causal,
            "selection": strict.choose_without_ranking,
        }
        accelerator = DynamicSizingV1(
            load_dynamic_sizing_config(runner.CONFIG_PATH, enabled=True)
        )
        with runner.enabled_accelerator_scope(accelerator, strict.candidate_config()) as state:
            self.assertIsNot(CausalDataPortal.current_open, originals["current_open"])
            self.assertIsNot(strict.apply_notional_cap, originals["cap"])
            self.assertIs(strict.candidate_config, originals["candidate_config"])
            self.assertIs(strict.evaluate_candidate_v1_causal, originals["strategy"])
            self.assertIs(strict.choose_without_ranking, originals["selection"])
            self.assertEqual(state.decisions, [])
            self.assertEqual(state.open_position_snapshots, {})
        self.assertIs(CausalDataPortal.current_open, originals["current_open"])
        self.assertIs(strict.current_position_marks, originals["marks"])
        self.assertIs(strict.apply_notional_cap, originals["cap"])
        self.assertIs(Portfolio.open_position, originals["open_position"])
        self.assertIs(strict.candidate_config, originals["candidate_config"])
        self.assertIs(strict.evaluate_candidate_v1_causal, originals["strategy"])
        self.assertIs(strict.choose_without_ranking, originals["selection"])

    def test_sequential_scopes_do_not_share_state(self) -> None:
        accelerator = DynamicSizingV1(
            load_dynamic_sizing_config(runner.CONFIG_PATH, enabled=True)
        )
        with runner.enabled_accelerator_scope(accelerator, strict.candidate_config()) as first:
            first.open_position_snapshots["AMD"] = object()
        with runner.enabled_accelerator_scope(accelerator, strict.candidate_config()) as second:
            self.assertEqual(second.open_position_snapshots, {})
            self.assertEqual(second.decisions, [])

    def test_frozen_top100_order_and_102_symbol_universe_are_unchanged(self) -> None:
        selection = json.loads(strict.baseline.SELECTION_PATH.read_text(encoding="utf-8"))
        top100 = tuple(str(symbol).strip().upper() for symbol in selection["top100"])
        self.assertEqual(len(top100), 100)
        self.assertEqual(len(set(top100)), 100)
        self.assertIn("AMD", top100)
        self.assertIn("TSLA", top100)
        universe = (*top100, "QDTE", "XLE")
        self.assertEqual(len(universe), 102)
        self.assertEqual(universe[:100], top100)

    def test_research_runner_uses_fixed25_account_state_and_cap(self) -> None:
        self.assertEqual(runner.account.STARTING_QDTE_VALUE, 1438.00)
        self.assertEqual(runner.account.STARTING_SWING_CASH, 5.34)
        self.assertEqual(runner.account.STARTING_TOTAL_EQUITY, 1443.34)
        self.assertEqual(runner.account.CONFIGURATIONS["cap_25pct"], 0.25)
        config = load_dynamic_sizing_config(runner.CONFIG_PATH, enabled=True)
        self.assertEqual(config.maximum_position_notional_fraction, 0.25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
