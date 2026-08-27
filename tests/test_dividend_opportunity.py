from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import unittest

import qpx_bot.accelerators.dividend_opportunity as foundation
from qpx_bot.accelerators.dividend_opportunity import (
    DividendOpportunityEngineV1,
    DividendOpportunityEvidence,
    OpportunityState,
    OpportunityType,
    load_dividend_opportunity_config,
)

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "qpx_bot/accelerators/configs/dividend_opportunity_v1_foundation.json"
NOW = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
HEX_A = "a" * 64
HEX_B = "b" * 64


class DividendOpportunityFoundationTests(unittest.TestCase):
    def config(self):
        return load_dividend_opportunity_config(CONFIG)

    def context(self, **changes):
        available = NOW - timedelta(hours=2)
        evidence = DividendOpportunityEvidence(
            evidence_identity="frozen-corporate-action-record-v1",
            source_identity="validated-corporate-action-source",
            source_fingerprint=HEX_A,
            provenance_identity="research-evidence-provenance-v1",
            observed_at=available,
        )
        values = {
            "opportunity_type": OpportunityType.DIVIDEND_CAPTURE,
            "symbol": "TEST",
            "corporate_action_event_id": HEX_B,
            "event_effective_time": NOW + timedelta(days=3),
            "information_available_time": available,
            "evaluation_timestamp": NOW,
            "causal_input_fingerprint": HEX_A,
            "evidence": evidence,
        }
        values.update(changes)
        return foundation.DividendOpportunityContext(**values)

    def test_identical_inputs_are_deterministic(self):
        engine = DividendOpportunityEngineV1(self.config())
        self.assertEqual(engine.evaluate(self.context()), engine.evaluate(self.context()))

    def test_future_information_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Future dividend information"):
            self.context(information_available_time=NOW + timedelta(seconds=1))

    def test_future_evidence_fails_closed(self):
        evidence = replace(self.context().evidence, observed_at=NOW + timedelta(seconds=1))
        with self.assertRaisesRegex(ValueError, "Future evidence"):
            self.context(evidence=evidence)

    def test_incomplete_metadata_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Incomplete symbol"):
            self.context(symbol="")
        with self.assertRaisesRegex(ValueError, "Invalid corporate_action_event_id"):
            self.context(corporate_action_event_id="short")

    def test_no_opportunity_is_explicit(self):
        decision = DividendOpportunityEngineV1(self.config()).evaluate(self.context())
        self.assertEqual(decision.opportunity_state, OpportunityState.NO_OPPORTUNITY)
        self.assertEqual(decision.proposed_action, "NO_ACTION")
        self.assertIn("NO QUALIFIED / NO ACTIONABLE OPPORTUNITY", decision.reason_codes)

    def test_models_and_config_are_immutable(self):
        values = (
            (self.config(), "enabled", True),
            (self.context().evidence, "source_identity", "changed"),
            (self.context(), "symbol", "CHANGED"),
            (DividendOpportunityEngineV1(self.config()).evaluate(self.context()),
             "symbol", "CHANGED"),
        )
        for value, name, replacement in values:
            with self.assertRaises(FrozenInstanceError):
                setattr(value, name, replacement)

    def test_configuration_fingerprint_is_stable(self):
        self.assertEqual(self.config().fingerprint, self.config().fingerprint)
        self.assertEqual(len(self.config().fingerprint), 64)

    def test_input_fingerprint_is_stable(self):
        self.assertEqual(self.context().input_fingerprint, self.context().input_fingerprint)

    def test_opportunity_types_are_separate(self):
        engine = DividendOpportunityEngineV1(self.config())
        decisions = [engine.evaluate(self.context(opportunity_type=item)) for item in OpportunityType]
        self.assertEqual(len({item.opportunity_id for item in decisions}), len(OpportunityType))
        self.assertEqual({item.opportunity_type for item in decisions}, set(OpportunityType))

    def test_announced_future_effective_event_is_causal(self):
        decision = DividendOpportunityEngineV1(self.config()).evaluate(self.context())
        self.assertGreater(decision.event_effective_time, decision.evaluation_timestamp)
        self.assertLessEqual(decision.information_available_time, decision.evaluation_timestamp)

    def test_foundation_has_no_capital_or_execution_authority(self):
        decision = DividendOpportunityEngineV1(self.config()).evaluate(self.context())
        self.assertIsNone(decision.proposed_capital)
        self.assertFalse(decision.capital_authority)
        self.assertFalse(decision.execution_authority)

    def test_foundation_has_no_qualification_or_promotion_authority(self):
        decision = DividendOpportunityEngineV1(self.config()).evaluate(self.context())
        self.assertFalse(decision.qualification_authority)
        self.assertFalse(decision.promotion_authority)

    def test_enabled_or_policy_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "disabled research"):
            replace(self.config(), enabled=True).validate()
        with self.assertRaisesRegex(ValueError, "cannot declare"):
            replace(self.config(), policy_identity="invented").validate()

    def test_authority_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no allocation"):
            replace(self.config(), capital_authority=True).validate()

    def test_module_has_no_protected_or_selector_imports(self):
        source = inspect.getsource(foundation)
        for forbidden in (
            "candidate_v1", "QPX_RUN_FROZEN_TOP100", "causal_dividends",
            "income_role", "income_qualification", "Portfolio", "buy_fill",
        ):
            self.assertNotIn(forbidden, source)

    def test_decision_contract_is_research_evidence_only(self):
        fields = foundation.DividendOpportunityDecision.__dataclass_fields__
        for forbidden in ("shares", "order", "fill", "allocation", "qualification_record"):
            self.assertNotIn(forbidden, fields)


if __name__ == "__main__":
    unittest.main()
