from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import unittest

import qpx_bot.accelerators.dividend_opportunity as foundation
from qpx_bot.accelerators.dividend_opportunity import (
    DividendOpportunityEvidence,
    PostExRecoveryConfig,
    PostExRecoveryContext,
    PostExRecoveryObservation,
    PostExRecoveryV1,
    OpportunityState,
    OpportunityType,
    load_post_ex_recovery_config,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "qpx_bot/accelerators/configs/post_ex_recovery_v1_research.json"
UTC = timezone.utc
EX = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
EVAL = datetime(2026, 1, 10, 15, 0, tzinfo=UTC)
HEX_A = "a" * 64
HEX_B = "b" * 64


class PostExRecoveryV1Tests(unittest.TestCase):
    def config(self):
        return load_post_ex_recovery_config(CONFIG)

    def base(self, **changes):
        available = EX - timedelta(days=3)
        evidence = DividendOpportunityEvidence(
            evidence_identity="dividend-event-evidence-v1",
            source_identity="validated-corporate-action-source",
            source_fingerprint=HEX_A,
            provenance_identity="post-ex-recovery-research-provenance-v1",
            observed_at=available,
        )
        values = dict(
            opportunity_type=OpportunityType.POST_EX_DIVIDEND_RECOVERY,
            symbol="TEST",
            corporate_action_event_id=HEX_B,
            event_effective_time=EX,
            information_available_time=available,
            evaluation_timestamp=EVAL,
            causal_input_fingerprint=HEX_A,
            evidence=evidence,
        )
        values.update(changes)
        return foundation.DividendOpportunityContext(**values)

    def observation(self, hours=1, price=105.0, **changes):
        values = dict(
            observed_at=EX + timedelta(hours=hours),
            information_available_at=EX + timedelta(hours=hours),
            price=price,
            causal_input_fingerprint=HEX_B,
        )
        values.update(changes)
        return PostExRecoveryObservation(**values)

    def context(self, **changes):
        values = dict(
            base_context=self.base(),
            ex_dividend_reference_price=100.0,
            observations=(self.observation(),),
        )
        values.update(changes)
        return PostExRecoveryContext(**values)

    def test_identical_inputs_are_deterministic(self):
        engine = PostExRecoveryV1(self.config())
        self.assertEqual(engine.evaluate(self.context()), engine.evaluate(self.context()))

    def test_future_bar_access_fails_closed(self):
        future = EVAL + timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "Future recovery observation"):
            self.context(observations=(self.observation(observed_at=future, information_available_at=future),))

    def test_future_dividend_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Future dividend information"):
            self.base(information_available_time=EVAL + timedelta(seconds=1))

    def test_no_opportunity_before_required_event_information_exists(self):
        with self.assertRaisesRegex(ValueError, "before the ex-dividend event"):
            PostExRecoveryContext(
                base_context=self.base(evaluation_timestamp=EX - timedelta(seconds=1)),
                ex_dividend_reference_price=100.0,
                observations=(),
            )

    def test_recovery_threshold_behavior(self):
        engine = PostExRecoveryV1(self.config())
        reached = engine.evaluate(self.context(observations=(self.observation(price=105.0),)))
        missed = engine.evaluate(self.context(observations=(self.observation(price=104.99),)))
        self.assertEqual(reached.opportunity_state, OpportunityState.OPPORTUNITY_IDENTIFIED)
        self.assertEqual(missed.opportunity_state, OpportunityState.NO_OPPORTUNITY)
        self.assertEqual(reached.recovery_progress, 0.05)

    def test_lookback_window_boundary(self):
        config = replace(self.config(), lookback_window_seconds=1800.0)
        old = self.observation(hours=1, price=105.0)
        decision = PostExRecoveryV1(config).evaluate(
            self.context(observations=(old,))
        )
        self.assertEqual(decision.opportunity_state, OpportunityState.NO_OPPORTUNITY)
        self.assertIn("LOOKBACK_WINDOW_EMPTY", decision.reason_codes)

    def test_evaluation_window_boundary(self):
        config = replace(self.config(), evaluation_window_seconds=3600.0)
        exact_base = self.base(evaluation_timestamp=EX + timedelta(hours=1))
        exact = PostExRecoveryContext(exact_base, 100.0, (self.observation(),))
        self.assertEqual(PostExRecoveryV1(config).evaluate(exact).opportunity_state, OpportunityState.OPPORTUNITY_IDENTIFIED)
        expired_base = self.base(evaluation_timestamp=EX + timedelta(hours=1, seconds=1))
        expired = PostExRecoveryContext(expired_base, 100.0, (self.observation(),))
        decision = PostExRecoveryV1(config).evaluate(expired)
        self.assertEqual(decision.opportunity_state, OpportunityState.NO_OPPORTUNITY)
        self.assertIn("EVALUATION_WINDOW_EXPIRED", decision.reason_codes)

    def test_incomplete_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Invalid ex-dividend reference"):
            PostExRecoveryContext(self.base(), 0.0, (self.observation(),))
        with self.assertRaisesRegex(ValueError, "Recovery observations must be strictly chronological"):
            PostExRecoveryContext(self.base(), 100.0, (self.observation(), self.observation()))

    def test_explicit_no_opportunity_result(self):
        decision = PostExRecoveryV1(self.config()).evaluate(
            self.context(observations=(self.observation(price=101.0),))
        )
        self.assertEqual(decision.opportunity_state, OpportunityState.NO_OPPORTUNITY)
        self.assertIn("NO QUALIFIED / NO ACTIONABLE OPPORTUNITY", decision.reason_codes)
        self.assertEqual(decision.proposed_action, "NO_ACTION")

    def test_configuration_fingerprint_changes_with_research_policy(self):
        one = self.config()
        two = replace(one, recovery_threshold=0.10)
        self.assertNotEqual(one.fingerprint, two.fingerprint)

    def test_causal_observation_fingerprint_changes_with_observation(self):
        one = self.context().observation_fingerprint
        two = self.context(observations=(self.observation(price=106.0),)).observation_fingerprint
        self.assertNotEqual(one, two)

    def test_future_observation_availability_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Future recovery information"):
            self.context(observations=(self.observation(information_available_at=EVAL + timedelta(seconds=1)),))

    def test_no_capital_execution_or_governance_authority(self):
        decision = PostExRecoveryV1(self.config()).evaluate(self.context())
        self.assertIsNone(decision.proposed_capital)
        self.assertFalse(decision.capital_authority)
        self.assertFalse(decision.execution_authority)
        self.assertFalse(decision.qualification_authority)
        self.assertFalse(decision.promotion_authority)

    def test_no_candidate_qdte_or_selector_imports(self):
        source = inspect.getsource(foundation)
        for forbidden in ("candidate_v1", "QPX_RUN_FROZEN_TOP100", "causal_dividends", "income_role", "income_qualification", "Portfolio", "buy_fill"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
