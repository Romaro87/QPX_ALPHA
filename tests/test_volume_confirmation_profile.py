from pathlib import Path
import unittest

from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs, evaluate_candidate_v1_causal
from qpx_bot.candidate_v1_config import load_candidate_v1_config


PROFILE = Path(__file__).parents[1] / "qpx_bot/paper_profiles/candidate_v1_volume_confirmation_25.json"


class VolumeConfirmationProfileTests(unittest.TestCase):
    def test_deployed_profile_reaches_account_and_sizing_configuration(self):
        snapshot = load_candidate_v1_config(PROFILE)
        self.assertEqual(snapshot.bot_config.total_starting_capital, 1443.34)
        self.assertEqual(snapshot.bot_config.starting_cash, 1438.0)
        self.assertEqual(snapshot.bot_config.starting_swing_cash, 5.34)
        self.assertEqual(snapshot.maximum_position_notional_fraction, 0.90)

    def test_deployed_profile_controls_causal_entry_evaluator(self):
        snapshot = load_candidate_v1_config(PROFILE)
        inputs = CandidateV1CausalInputs(
            index=1, current_close=110, current_volume=200_000,
            current_fast=11, previous_fast=10, current_slow=9,
            previous_slow=10, current_rsi=53, previous_rsi=53,
            current_rmi=40, previous_rmi=40, current_sma=100,
            slope_sma=99, baseline_volume=100_000, current_atr=1,
            prior_high=105, vix=22,
        )
        result = evaluate_candidate_v1_causal(
            inputs=inputs, config=snapshot.bot_config,
            momentum_persistence_level=snapshot.momentum_persistence_level,
            vix_exclusion_low=snapshot.vix_exclusion_low,
            vix_exclusion_high=snapshot.vix_exclusion_high,
        )
        self.assertIn("MOMENTUM_PERSISTENCE", result.triggers)
        self.assertIn("candidate_vix_20_25_exclusion", result.failed_checks)


if __name__ == "__main__":
    unittest.main()
