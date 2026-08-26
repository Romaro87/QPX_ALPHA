from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import qpx_bot.income_role as income_role
from qpx_bot.income_role import (
    INCOME_ROLE_V1,
    IncomeDecisionOutcome,
    IncomeImplementationIdentity,
    IncomeRoleSelector,
    IncomeSelectionContext,
    IncomeSelectorConfig,
    NonCausalInputError,
    QualificationReference,
    QualificationRegistrySnapshot,
    QualificationStatus,
    candidate_v1_legacy_decision,
    fingerprint,
)


class IncomeRoleFoundationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.decision_time = datetime(2026, 8, 17, 14, 30, tzinfo=timezone.utc)
        self.cutoff = self.decision_time - timedelta(minutes=15)
        self.implementation = IncomeImplementationIdentity(
            implementation_id="qualified_income_example",
            implementation_version="1.0.0",
            instrument_symbol="TEST",
        )

    def qualification(
        self,
        *,
        status: QualificationStatus = QualificationStatus.QUALIFIED,
        eligible_from: datetime | None = None,
        eligible_through: datetime | None = None,
    ) -> QualificationReference:
        return QualificationReference(
            implementation_fingerprint=self.implementation.identity_fingerprint,
            qualification_id="qualification-test",
            qualification_version="1.0.0",
            qualification_reference="test:qualification:1",
            evidence_fingerprint=fingerprint({"evidence": "frozen-test"}),
            status=status,
            eligible_from=eligible_from,
            eligible_through=eligible_through,
        )

    def registry(
        self,
        qualifications: tuple[QualificationReference, ...] | None = None,
        *,
        snapshot_timestamp: datetime | None = None,
    ) -> QualificationRegistrySnapshot:
        return QualificationRegistrySnapshot(
            registry_id="test-registry",
            registry_version="1.0.0",
            snapshot_timestamp=snapshot_timestamp or self.cutoff,
            qualifications=(
                (self.qualification(),)
                if qualifications is None
                else qualifications
            ),
        )

    def config(
        self,
        *,
        selector_version: str = "1.0.0",
        candidates: tuple[str, ...] | None = None,
    ) -> IncomeSelectorConfig:
        return IncomeSelectorConfig(
            selector_id="test-income-selector",
            selector_version=selector_version,
            candidate_implementation_fingerprints=(
                (self.implementation.identity_fingerprint,)
                if candidates is None
                else candidates
            ),
        )

    def context(
        self,
        registry: QualificationRegistrySnapshot,
        *,
        available: tuple[str, ...] | None = None,
    ) -> IncomeSelectionContext:
        return IncomeSelectionContext(
            decision_timestamp=self.decision_time,
            information_cutoff=self.cutoff,
            qualification_registry_fingerprint=registry.identity_fingerprint,
            available_implementation_fingerprints=(
                (self.implementation.identity_fingerprint,)
                if available is None
                else available
            ),
        )

    def selector(
        self,
        registry: QualificationRegistrySnapshot,
        *,
        config: IncomeSelectorConfig | None = None,
        implementations: tuple[IncomeImplementationIdentity, ...] | None = None,
    ) -> IncomeRoleSelector:
        return IncomeRoleSelector(
            config=config or self.config(),
            implementations=(
                (self.implementation,)
                if implementations is None
                else implementations
            ),
            qualification_registry=registry,
        )

    def test_a_identical_inputs_produce_identical_identities_and_decisions(self) -> None:
        first_registry = self.registry()
        second_registry = self.registry()
        first = self.selector(first_registry).select(self.context(first_registry))
        second = self.selector(second_registry).select(self.context(second_registry))
        self.assertEqual(first, second)
        self.assertEqual(first.decision_id, second.decision_id)
        self.assertEqual(
            first.selector_configuration_fingerprint,
            second.selector_configuration_fingerprint,
        )
        self.assertEqual(first.context_fingerprint, second.context_fingerprint)

    def test_b_candidate_v1_legacy_adapter_represents_qdte_deterministically(self) -> None:
        first = candidate_v1_legacy_decision(
            decision_timestamp=self.decision_time,
            information_cutoff=self.cutoff,
        )
        second = candidate_v1_legacy_decision(
            decision_timestamp=self.decision_time,
            information_cutoff=self.cutoff,
        )
        self.assertEqual(first, second)
        self.assertIs(first.outcome, IncomeDecisionOutcome.IMPLEMENTATION)
        self.assertEqual(first.role, INCOME_ROLE_V1)
        self.assertEqual(first.selected_implementation.instrument_symbol, "QDTE")
        self.assertEqual(first.selector_id, "candidate_v1_legacy_fixed_income")

    def test_c_cash_is_a_first_class_outcome_not_an_implementation(self) -> None:
        registry = self.registry(())
        decision = self.selector(registry).select(self.context(registry))
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)
        self.assertIsNone(decision.selected_implementation)
        self.assertIsNone(decision.qualification_reference)
        self.assertIsNone(decision.qualification_fingerprint)
        self.assertIn("NO_QUALIFIED_IMPLEMENTATION_DEPLOYED", decision.reason_codes)

    def test_d_unqualified_implementation_cannot_be_selected(self) -> None:
        registry = self.registry(
            (self.qualification(status=QualificationStatus.UNQUALIFIED),)
        )
        decision = self.selector(registry).select(self.context(registry))
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)
        self.assertTrue(any(reason.startswith("NOT_QUALIFIED:") for reason in decision.reason_codes))

    def test_e_missing_qualification_fails_closed(self) -> None:
        registry = self.registry(())
        decision = self.selector(registry).select(self.context(registry))
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)
        self.assertTrue(any(reason.startswith("MISSING_QUALIFICATION:") for reason in decision.reason_codes))

    def test_f_unknown_implementation_fails_closed(self) -> None:
        unknown = fingerprint({"unknown": "implementation"})
        registry = self.registry(())
        config = self.config(candidates=(unknown,))
        decision = self.selector(
            registry,
            config=config,
            implementations=(),
        ).select(self.context(registry, available=(unknown,)))
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)
        self.assertTrue(any(reason.startswith("UNKNOWN_IMPLEMENTATION:") for reason in decision.reason_codes))

    def test_g_future_or_noncausal_input_is_rejected(self) -> None:
        registry = self.registry()
        with self.assertRaises(NonCausalInputError):
            IncomeSelectionContext(
                decision_timestamp=self.decision_time,
                information_cutoff=self.decision_time + timedelta(seconds=1),
                qualification_registry_fingerprint=registry.identity_fingerprint,
                available_implementation_fingerprints=(),
            )
        future_registry = self.registry(
            snapshot_timestamp=self.decision_time + timedelta(seconds=1)
        )
        with self.assertRaises(NonCausalInputError):
            self.selector(future_registry).select(self.context(future_registry))

    def test_h_decision_retains_selector_qualification_and_context_identity(self) -> None:
        registry = self.registry()
        decision = self.selector(registry).select(self.context(registry))
        lineage = decision.lineage_dict()
        self.assertEqual(
            lineage["selected_implementation"]["instrument_symbol"],
            "TEST",
        )
        self.assertEqual(
            lineage["selector_configuration_fingerprint"],
            self.config().configuration_fingerprint,
        )
        self.assertEqual(
            lineage["qualification_registry_fingerprint"],
            registry.identity_fingerprint,
        )
        self.assertEqual(
            lineage["qualification_fingerprint"],
            decision.qualification_reference.identity_fingerprint,
        )
        self.assertEqual(lineage["decision_id"], decision.decision_id)
        self.assertEqual(lineage["context_fingerprint"], decision.context_fingerprint)
        self.assertEqual(
            decision.decision_fingerprint,
            fingerprint(decision.as_dict()),
        )

    def test_i_later_config_cannot_reinterpret_an_earlier_decision(self) -> None:
        registry = self.registry()
        earlier = self.selector(registry).select(self.context(registry))
        frozen_lineage = earlier.lineage_dict()
        later_config = self.config(selector_version="2.0.0")
        later = self.selector(registry, config=later_config).select(
            self.context(registry)
        )
        self.assertNotEqual(
            earlier.selector_configuration_fingerprint,
            later.selector_configuration_fingerprint,
        )
        self.assertEqual(earlier.lineage_dict(), frozen_lineage)
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            earlier.selector_version = "2.0.0"

    def test_j_selector_instance_state_does_not_leak(self) -> None:
        qualified_registry = self.registry()
        empty_registry = self.registry(())
        qualified = self.selector(qualified_registry)
        empty = self.selector(empty_registry)
        self.assertIs(
            qualified.select(self.context(qualified_registry)).outcome,
            IncomeDecisionOutcome.IMPLEMENTATION,
        )
        self.assertIs(
            empty.select(self.context(empty_registry)).outcome,
            IncomeDecisionOutcome.CASH,
        )
        self.assertIs(
            qualified.select(self.context(qualified_registry)).outcome,
            IncomeDecisionOutcome.IMPLEMENTATION,
        )

    def test_k_invalid_configuration_fails_before_selection(self) -> None:
        identity = self.implementation.identity_fingerprint
        with self.assertRaises(ValueError):
            IncomeSelectorConfig(
                selector_id="invalid",
                selector_version="1",
                candidate_implementation_fingerprints=(identity, identity),
            )
        with self.assertRaises(ValueError):
            IncomeSelectorConfig(
                selector_id="invalid",
                selector_version="1",
                candidate_implementation_fingerprints=(identity,),
                allow_cash=False,
            )

    def test_stale_qualification_fails_closed(self) -> None:
        registry = self.registry(
            (
                self.qualification(
                    eligible_through=self.cutoff - timedelta(seconds=1)
                ),
            )
        )
        decision = self.selector(registry).select(self.context(registry))
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)
        self.assertTrue(any(reason.startswith("STALE_OR_NOT_YET_ELIGIBLE:") for reason in decision.reason_codes))

    def test_registry_order_does_not_change_its_fingerprint(self) -> None:
        second = IncomeImplementationIdentity(
            implementation_id="second",
            implementation_version="1",
            instrument_symbol="TWO",
        )
        second_qualification = QualificationReference(
            implementation_fingerprint=second.identity_fingerprint,
            qualification_id="second-q",
            qualification_version="1",
            qualification_reference="test:second",
            evidence_fingerprint=fingerprint({"second": True}),
            status=QualificationStatus.QUALIFIED,
        )
        first = self.registry((self.qualification(), second_qualification))
        second_registry = self.registry((second_qualification, self.qualification()))
        self.assertEqual(first.identity_fingerprint, second_registry.identity_fingerprint)

    def test_l_runtime_selection_imports_no_existing_candidate_or_economic_module(self) -> None:
        source = inspect.getsource(income_role)
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        self.assertFalse(any(name.startswith("qpx_bot") for name in imported))
        prohibited = {
            "candidate_v1_causal",
            "causal_dividends",
            "portfolio",
            "allocation",
            "hybrid",
            "strategy",
            "risk",
            "shadow_matrix",
            "regime_allocation",
        }
        self.assertFalse(imported.intersection(prohibited))


if __name__ == "__main__":
    unittest.main(verbosity=2)
