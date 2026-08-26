from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone

import qpx_bot.income_qualification as qualification_module
from qpx_bot.income_qualification import (
    CANDIDATE_V1_QUALIFICATION_DOCUMENT,
    GOVERNANCE_SCHEMA_VERSION,
    GovernedIncomeQualificationRegistryBuilder,
    GovernedQualificationRecord,
    GovernedQualificationState,
    QualificationAuthorityIdentity,
    QualificationAuthorityKind,
    QualificationEvidenceAvailability,
    QualificationGovernanceError,
    QualificationRevocationRecord,
    candidate_v1_qdte_compatibility_evidence,
    candidate_v1_qdte_compatibility_qualification,
    candidate_v1_qdte_implementation,
)
from qpx_bot.income_role import (
    CANDIDATE_V1_QUALIFICATION_COMMIT,
    IncomeDecisionOutcome,
    IncomeImplementationIdentity,
    IncomeRoleSelector,
    IncomeSelectionContext,
    IncomeSelectorConfig,
    fingerprint,
)


UTC = timezone.utc
T0 = datetime(2026, 8, 11, 12, tzinfo=UTC)


class GovernedIncomeQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.implementation = IncomeImplementationIdentity(
            "test_income", "1.0.0", "TEST"
        )
        self.authority = QualificationAuthorityIdentity(
            "income_qualification_board",
            "1.0.0",
            QualificationAuthorityKind.GOVERNANCE,
        )
        self.evidence_fingerprint = fingerprint({"frozen": "evidence-v1"})
        self.evidence_reference = "artifact:test-income:evidence-v1"

    def record(self, **changes: object) -> GovernedQualificationRecord:
        values = {
            "implementation": self.implementation,
            "implementation_fingerprint": self.implementation.identity_fingerprint,
            "qualification_id": "test-income-qualification",
            "qualification_version": "1.0.0",
            "qualification_evidence_reference": self.evidence_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "status": GovernedQualificationState.QUALIFIED,
            "qualified_at": T0,
            "effective_from": T0,
            "effective_through": None,
            "no_expiry": True,
            "recorded_at": T0,
            "governance_authority": self.authority,
        }
        values.update(changes)
        return GovernedQualificationRecord(**values)

    def evidence(self, **changes: object) -> QualificationEvidenceAvailability:
        values = {
            "evidence_reference": self.evidence_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "available_at": T0,
        }
        values.update(changes)
        return QualificationEvidenceAvailability(**values)

    def builder(
        self, *implementations: IncomeImplementationIdentity
    ) -> GovernedIncomeQualificationRegistryBuilder:
        return GovernedIncomeQualificationRegistryBuilder(
            registry_id="governed-income-test",
            registry_version="1.0.0",
            implementations=implementations or (self.implementation,),
            governance_authorities=(self.authority,),
        )

    def build(
        self,
        *,
        cutoff: datetime = T0,
        qualifications: tuple[GovernedQualificationRecord, ...] | None = None,
        revocations: tuple[QualificationRevocationRecord, ...] = (),
        evidence: tuple[QualificationEvidenceAvailability, ...] | None = None,
    ):
        return self.builder().build(
            information_cutoff=cutoff,
            qualifications=(self.record(),) if qualifications is None else qualifications,
            revocations=revocations,
            evidence=(self.evidence(),) if evidence is None else evidence,
        )

    def revocation(
        self, record: GovernedQualificationRecord, when: datetime
    ) -> QualificationRevocationRecord:
        return QualificationRevocationRecord(
            qualification_fingerprint=record.identity_fingerprint,
            implementation_fingerprint=record.implementation_fingerprint,
            revocation_id="test-income-revocation",
            revocation_version="1.0.0",
            revocation_reference="artifact:test-income:revocation-v1",
            evidence_fingerprint=fingerprint({"revocation": "evidence-v1"}),
            revoked_at=when,
            recorded_at=when,
            governance_authority=self.authority,
        )

    @staticmethod
    def revocation_evidence(
        revocation: QualificationRevocationRecord,
    ) -> QualificationEvidenceAvailability:
        return QualificationEvidenceAvailability(
            revocation.revocation_reference,
            revocation.evidence_fingerprint,
            revocation.recorded_at,
        )

    def test_a_deterministic_qualification_identity(self) -> None:
        first, second = self.record(), self.record()
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(first.identity_fingerprint, second.identity_fingerprint)
        with self.assertRaises(FrozenInstanceError):
            first.qualification_version = "mutated"  # type: ignore[misc]

    def test_b_snapshot_is_order_independent(self) -> None:
        other = IncomeImplementationIdentity("other", "1", "OTHER")
        other_evidence = QualificationEvidenceAvailability(
            "artifact:other:evidence", fingerprint({"other": "evidence"}), T0
        )
        other_record = GovernedQualificationRecord(
            implementation=other,
            implementation_fingerprint=other.identity_fingerprint,
            qualification_id="other-q",
            qualification_version="1",
            qualification_evidence_reference=other_evidence.evidence_reference,
            evidence_fingerprint=other_evidence.evidence_fingerprint,
            status=GovernedQualificationState.QUALIFIED,
            qualified_at=T0,
            effective_from=T0,
            effective_through=None,
            no_expiry=True,
            recorded_at=T0,
            governance_authority=self.authority,
        )
        builder = self.builder(self.implementation, other)
        first = builder.build(
            information_cutoff=T0,
            qualifications=(self.record(), other_record),
            evidence=(self.evidence(), other_evidence),
        )
        second = builder.build(
            information_cutoff=T0,
            qualifications=(other_record, self.record()),
            evidence=(other_evidence, self.evidence()),
        )
        self.assertEqual(first.identity_fingerprint, second.identity_fingerprint)

    def test_c_future_qualification_cannot_affect_past(self) -> None:
        future = self.record(
            qualified_at=T0 + timedelta(days=2),
            effective_from=T0 + timedelta(days=2),
            recorded_at=T0 + timedelta(days=2),
        )
        snapshot = self.build(qualifications=(future,))
        self.assertEqual(snapshot.qualifications, ())

    def test_d_future_revocation_cannot_alter_past(self) -> None:
        record = self.record()
        revocation = self.revocation(record, T0 + timedelta(days=2))
        before = self.build(qualifications=(record,))
        with_future = self.build(
            qualifications=(record,),
            revocations=(revocation,),
            evidence=(self.evidence(), self.revocation_evidence(revocation)),
        )
        self.assertEqual(before.identity_fingerprint, with_future.identity_fingerprint)

    def test_e_revoked_is_excluded_at_and_after_revocation(self) -> None:
        record = self.record()
        when = T0 + timedelta(days=1)
        revocation = self.revocation(record, when)
        evidence = (self.evidence(), self.revocation_evidence(revocation))
        for cutoff in (when, when + timedelta(days=1)):
            with self.subTest(cutoff=cutoff):
                snapshot = self.build(
                    cutoff=cutoff,
                    qualifications=(record,),
                    revocations=(revocation,),
                    evidence=evidence,
                )
                self.assertEqual(snapshot.qualifications, ())

    def test_f_expired_is_excluded_after_expiry(self) -> None:
        expiry = T0 + timedelta(days=1)
        record = self.record(effective_through=expiry, no_expiry=False)
        snapshot = self.build(
            cutoff=expiry + timedelta(microseconds=1), qualifications=(record,)
        )
        self.assertEqual(snapshot.qualifications, ())

    def test_g_valid_inside_effective_interval(self) -> None:
        record = self.record(
            effective_from=T0 + timedelta(hours=1),
            effective_through=T0 + timedelta(days=1),
            no_expiry=False,
        )
        snapshot = self.build(
            cutoff=T0 + timedelta(hours=2), qualifications=(record,)
        )
        self.assertEqual(len(snapshot.qualifications), 1)

    def test_h_duplicate_active_conflict_fails_closed(self) -> None:
        second = self.record(
            qualification_id="second-qualification", qualification_version="2"
        )
        with self.assertRaisesRegex(QualificationGovernanceError, "Conflicting active"):
            self.build(qualifications=(self.record(), second))

    def test_i_unknown_implementation_fails_closed(self) -> None:
        unknown = IncomeImplementationIdentity("unknown", "1", "UNKNOWN")
        record = self.record(
            implementation=unknown,
            implementation_fingerprint=unknown.identity_fingerprint,
        )
        with self.assertRaisesRegex(QualificationGovernanceError, "unknown"):
            self.build(qualifications=(record,))

    def test_j_bad_or_mismatched_evidence_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            self.record(evidence_fingerprint="bad")
        mismatch = self.evidence(
            evidence_fingerprint=fingerprint({"different": "evidence"})
        )
        with self.assertRaisesRegex(QualificationGovernanceError, "mismatch"):
            self.build(evidence=(mismatch,))
        with self.assertRaisesRegex(QualificationGovernanceError, "unavailable"):
            self.build(evidence=())

    def test_k_governance_authority_is_required(self) -> None:
        research = QualificationAuthorityIdentity(
            "research-component", "1", QualificationAuthorityKind.RESEARCH
        )
        with self.assertRaisesRegex(QualificationGovernanceError, "cannot grant"):
            self.record(governance_authority=research)

    def test_l_post_revocation_requires_new_lineage(self) -> None:
        first = self.record()
        revocation = self.revocation(first, T0 + timedelta(days=1))
        later = T0 + timedelta(days=2)
        second = self.record(
            qualification_id="renewed-qualification",
            qualification_version="2",
            qualified_at=later,
            effective_from=later,
            recorded_at=later,
        )
        evidence = (
            self.evidence(),
            self.revocation_evidence(revocation),
        )
        with self.assertRaisesRegex(QualificationGovernanceError, "new lineage"):
            self.builder().build(
                information_cutoff=later,
                qualifications=(first, second),
                revocations=(revocation,),
                evidence=evidence,
            )
        explicit = replace(
            second,
            predecessor_qualification_fingerprint=first.identity_fingerprint,
        )
        snapshot = self.builder().build(
            information_cutoff=later,
            qualifications=(first, explicit),
            revocations=(revocation,),
            evidence=evidence,
        )
        self.assertEqual(snapshot.qualifications[0].qualification_version, "2")

    def test_m_candidate_v1_maps_existing_provenance(self) -> None:
        record = candidate_v1_qdte_compatibility_qualification()
        self.assertEqual(record.implementation.instrument_symbol, "QDTE")
        self.assertIn(
            CANDIDATE_V1_QUALIFICATION_COMMIT,
            record.qualification_evidence_reference,
        )
        self.assertIn(
            CANDIDATE_V1_QUALIFICATION_DOCUMENT,
            record.qualification_evidence_reference,
        )
        self.assertEqual(record.qualification_id, "candidate_v1_strict_causal")

    def test_n_selector_accepts_governed_qdte_snapshot(self) -> None:
        implementation = candidate_v1_qdte_implementation()
        record = candidate_v1_qdte_compatibility_qualification()
        cutoff = datetime(2026, 8, 26, tzinfo=UTC)
        snapshot = GovernedIncomeQualificationRegistryBuilder(
            registry_id="candidate-v1-governed-compatibility",
            registry_version="1",
            governance_authorities=(record.governance_authority,),
            implementations=(implementation,),
        ).build(
            information_cutoff=cutoff,
            qualifications=(record,),
            evidence=(candidate_v1_qdte_compatibility_evidence(),),
        )
        selector = IncomeRoleSelector(
            config=IncomeSelectorConfig(
                selector_id="compatibility-selector",
                selector_version="1",
                candidate_implementation_fingerprints=(
                    implementation.identity_fingerprint,
                ),
            ),
            implementations=(implementation,),
            qualification_registry=snapshot,
        )
        decision = selector.select(
            IncomeSelectionContext(
                decision_timestamp=cutoff,
                information_cutoff=cutoff,
                qualification_registry_fingerprint=snapshot.identity_fingerprint,
                available_implementation_fingerprints=(
                    implementation.identity_fingerprint,
                ),
            )
        )
        self.assertIs(decision.outcome, IncomeDecisionOutcome.IMPLEMENTATION)
        self.assertEqual(decision.selected_implementation, implementation)

    def test_o_empty_snapshot_permits_cash(self) -> None:
        snapshot = self.build(qualifications=(), evidence=())
        selector = IncomeRoleSelector(
            config=IncomeSelectorConfig(
                selector_id="cash-selector",
                selector_version="1",
                candidate_implementation_fingerprints=(
                    self.implementation.identity_fingerprint,
                ),
            ),
            implementations=(self.implementation,),
            qualification_registry=snapshot,
        )
        decision = selector.select(
            IncomeSelectionContext(
                decision_timestamp=T0,
                information_cutoff=T0,
                qualification_registry_fingerprint=snapshot.identity_fingerprint,
                available_implementation_fingerprints=(
                    self.implementation.identity_fingerprint,
                ),
            )
        )
        self.assertIs(decision.outcome, IncomeDecisionOutcome.CASH)

    def test_p_research_shadow_ml_cannot_create_authority(self) -> None:
        for kind in (
            QualificationAuthorityKind.RESEARCH,
            QualificationAuthorityKind.SHADOW,
            QualificationAuthorityKind.ML,
        ):
            with self.subTest(kind=kind):
                authority = QualificationAuthorityIdentity("component", "1", kind)
                with self.assertRaises(QualificationGovernanceError):
                    self.record(governance_authority=authority)

    def test_q_fresh_instances_have_identical_fingerprints(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first.identity_fingerprint, second.identity_fingerprint)

    def test_additional_fail_closed_contracts(self) -> None:
        other = IncomeImplementationIdentity("other", "1", "OTHER")
        with self.assertRaisesRegex(QualificationGovernanceError, "mismatch"):
            self.record(
                implementation=other,
                implementation_fingerprint=self.implementation.identity_fingerprint,
            )
        with self.assertRaisesRegex(QualificationGovernanceError, "unavailable"):
            self.build(
                evidence=(
                    self.evidence(available_at=T0 + timedelta(microseconds=1)),
                )
            )
        for invalid_status in (
            GovernedQualificationState.REVOKED,
            GovernedQualificationState.EXPIRED,
        ):
            with self.subTest(invalid_status=invalid_status):
                with self.assertRaisesRegex(
                    QualificationGovernanceError, "begin as QUALIFIED"
                ):
                    self.record(status=invalid_status)
        untrusted = QualificationAuthorityIdentity(
            "untrusted-board", "1", QualificationAuthorityKind.GOVERNANCE
        )
        untrusted_record = self.record(governance_authority=untrusted)
        with self.assertRaisesRegex(QualificationGovernanceError, "Untrusted"):
            self.build(qualifications=(untrusted_record,))
        with self.assertRaisesRegex(QualificationGovernanceError, "Unsupported"):
            QualificationAuthorityIdentity(
                "authority",
                "1",
                QualificationAuthorityKind.GOVERNANCE,
                schema_version=GOVERNANCE_SCHEMA_VERSION + 1,
            )

    def test_runtime_imports_only_income_role_foundation(self) -> None:
        source = inspect.getsource(qualification_module)
        imported_qpx_modules = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("qpx_bot")
        }
        self.assertEqual(imported_qpx_modules, {"qpx_bot.income_role"})
        self.assertEqual(GOVERNANCE_SCHEMA_VERSION, 1)


if __name__ == "__main__":
    unittest.main()
