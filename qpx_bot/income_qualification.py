"""Governed, causal qualification admission for the isolated income role."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from qpx_bot.income_role import (
    CANDIDATE_V1_QUALIFICATION_COMMIT,
    IncomeImplementationIdentity,
    QualificationReference,
    QualificationRegistrySnapshot,
    QualificationStatus,
    _aware,
    _fingerprint_value,
    _identifier,
    _timestamp,
    fingerprint,
)

GOVERNANCE_SCHEMA_VERSION = 1
CANDIDATE_V1_QUALIFICATION_DOCUMENT = (
    "docs/CANDIDATE_V1_STRICT_CAUSAL_QUALIFICATION_2026-08-11.md"
)


class QualificationAuthorityKind(StrEnum):
    GOVERNANCE = "GOVERNANCE"
    RESEARCH = "RESEARCH"
    SHADOW = "SHADOW"
    ML = "ML"


class GovernedQualificationState(StrEnum):
    QUALIFIED = "QUALIFIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class QualificationGovernanceError(ValueError):
    """A qualification journal cannot safely authorize a registry snapshot."""


@dataclass(frozen=True, slots=True)
class QualificationAuthorityIdentity:
    authority_id: str
    authority_version: str
    authority_kind: QualificationAuthorityKind
    schema_version: int = GOVERNANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            raise QualificationGovernanceError("Unsupported authority schema version.")
        _identifier(self.authority_id, "Authority ID")
        _identifier(self.authority_version, "Authority version")
        if not isinstance(self.authority_kind, QualificationAuthorityKind):
            raise QualificationGovernanceError("Invalid qualification authority kind.")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authority_id": self.authority_id,
            "authority_version": self.authority_version,
            "authority_kind": self.authority_kind.value,
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class QualificationEvidenceAvailability:
    evidence_reference: str
    evidence_fingerprint: str
    available_at: datetime
    schema_version: int = GOVERNANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            raise QualificationGovernanceError("Unsupported evidence schema version.")
        _identifier(self.evidence_reference, "Evidence reference")
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _fingerprint_value(self.evidence_fingerprint, "Evidence fingerprint"),
        )
        _aware(self.available_at, "Evidence available_at")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "evidence_reference": self.evidence_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "available_at": _timestamp(self.available_at),
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class GovernedQualificationRecord:
    implementation: IncomeImplementationIdentity
    implementation_fingerprint: str
    qualification_id: str
    qualification_version: str
    qualification_evidence_reference: str
    evidence_fingerprint: str
    status: GovernedQualificationState
    qualified_at: datetime
    effective_from: datetime
    effective_through: datetime | None
    no_expiry: bool
    recorded_at: datetime
    governance_authority: QualificationAuthorityIdentity
    predecessor_qualification_fingerprint: str | None = None
    schema_version: int = GOVERNANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            raise QualificationGovernanceError("Unsupported qualification schema.")
        if not isinstance(self.implementation, IncomeImplementationIdentity):
            raise QualificationGovernanceError("Implementation identity is required.")
        implementation_fingerprint = _fingerprint_value(
            self.implementation_fingerprint, "Implementation fingerprint"
        )
        object.__setattr__(
            self, "implementation_fingerprint", implementation_fingerprint
        )
        if implementation_fingerprint != self.implementation.identity_fingerprint:
            raise QualificationGovernanceError(
                "Qualification implementation identity mismatch."
            )
        _identifier(self.qualification_id, "Qualification ID")
        _identifier(self.qualification_version, "Qualification version")
        _identifier(self.qualification_evidence_reference, "Evidence reference")
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _fingerprint_value(self.evidence_fingerprint, "Evidence fingerprint"),
        )
        if self.status is not GovernedQualificationState.QUALIFIED:
            raise QualificationGovernanceError(
                "Admission records must explicitly begin as QUALIFIED."
            )
        for value, label in (
            (self.qualified_at, "qualified_at"),
            (self.effective_from, "effective_from"),
            (self.recorded_at, "recorded_at"),
        ):
            _aware(value, f"Qualification {label}")
        if self.effective_through is not None:
            _aware(self.effective_through, "Qualification effective_through")
        if self.qualified_at > self.recorded_at:
            raise QualificationGovernanceError(
                "Qualification cannot be recorded before it was granted."
            )
        if self.effective_from < self.qualified_at:
            raise QualificationGovernanceError(
                "Qualification cannot be effective before it was granted."
            )
        if self.no_expiry == (self.effective_through is not None):
            raise QualificationGovernanceError(
                "Declare either effective_through or explicit no_expiry."
            )
        if (
            self.effective_through is not None
            and self.effective_through < self.effective_from
        ):
            raise QualificationGovernanceError("Effective interval is reversed.")
        if not isinstance(self.governance_authority, QualificationAuthorityIdentity):
            raise QualificationGovernanceError("Governance authority is required.")
        if self.governance_authority.authority_kind is not QualificationAuthorityKind.GOVERNANCE:
            raise QualificationGovernanceError(
                "Research, Shadow, and ML identities cannot grant qualification."
            )
        if self.predecessor_qualification_fingerprint is not None:
            object.__setattr__(
                self,
                "predecessor_qualification_fingerprint",
                _fingerprint_value(
                    self.predecessor_qualification_fingerprint,
                    "Predecessor qualification fingerprint",
                ),
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "implementation": self.implementation.as_dict(),
            "implementation_fingerprint": self.implementation_fingerprint,
            "qualification_id": self.qualification_id,
            "qualification_version": self.qualification_version,
            "qualification_evidence_reference": self.qualification_evidence_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "status": self.status.value,
            "qualified_at": _timestamp(self.qualified_at),
            "effective_from": _timestamp(self.effective_from),
            "effective_through": (
                _timestamp(self.effective_through) if self.effective_through else None
            ),
            "no_expiry": self.no_expiry,
            "recorded_at": _timestamp(self.recorded_at),
            "governance_authority": self.governance_authority.as_dict(),
            "predecessor_qualification_fingerprint": self.predecessor_qualification_fingerprint,
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())

    def state_at(self, cutoff: datetime) -> GovernedQualificationState | None:
        _aware(cutoff, "Qualification state cutoff")
        if self.recorded_at > cutoff or self.effective_from > cutoff:
            return None
        if self.effective_through is not None and cutoff > self.effective_through:
            return GovernedQualificationState.EXPIRED
        return GovernedQualificationState.QUALIFIED


@dataclass(frozen=True, slots=True)
class QualificationRevocationRecord:
    qualification_fingerprint: str
    implementation_fingerprint: str
    revocation_id: str
    revocation_version: str
    revocation_reference: str
    evidence_fingerprint: str
    revoked_at: datetime
    recorded_at: datetime
    governance_authority: QualificationAuthorityIdentity
    schema_version: int = GOVERNANCE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != GOVERNANCE_SCHEMA_VERSION:
            raise QualificationGovernanceError("Unsupported revocation schema.")
        for field_name in ("qualification_fingerprint", "implementation_fingerprint"):
            object.__setattr__(
                self,
                field_name,
                _fingerprint_value(getattr(self, field_name), field_name),
            )
        _identifier(self.revocation_id, "Revocation ID")
        _identifier(self.revocation_version, "Revocation version")
        _identifier(self.revocation_reference, "Revocation reference")
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _fingerprint_value(self.evidence_fingerprint, "Evidence fingerprint"),
        )
        _aware(self.revoked_at, "Revocation revoked_at")
        _aware(self.recorded_at, "Revocation recorded_at")
        if self.revoked_at > self.recorded_at:
            raise QualificationGovernanceError(
                "Revocation cannot be recorded before it occurred."
            )
        if not isinstance(self.governance_authority, QualificationAuthorityIdentity):
            raise QualificationGovernanceError("Revocation authority is required.")
        if self.governance_authority.authority_kind is not QualificationAuthorityKind.GOVERNANCE:
            raise QualificationGovernanceError(
                "Research, Shadow, and ML identities cannot revoke qualification."
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "qualification_fingerprint": self.qualification_fingerprint,
            "implementation_fingerprint": self.implementation_fingerprint,
            "revocation_id": self.revocation_id,
            "revocation_version": self.revocation_version,
            "revocation_reference": self.revocation_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "revoked_at": _timestamp(self.revoked_at),
            "recorded_at": _timestamp(self.recorded_at),
            "governance_authority": self.governance_authority.as_dict(),
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


class GovernedIncomeQualificationRegistryBuilder:
    """Emit selector snapshots from governance artifacts; never assess merit."""

    def __init__(
        self,
        *,
        registry_id: str,
        registry_version: str,
        implementations: tuple[IncomeImplementationIdentity, ...],
        governance_authorities: tuple[QualificationAuthorityIdentity, ...],
        schema_version: int = GOVERNANCE_SCHEMA_VERSION,
    ) -> None:
        if schema_version != GOVERNANCE_SCHEMA_VERSION:
            raise QualificationGovernanceError("Unsupported registry-builder schema.")
        self._registry_id = _identifier(registry_id, "Registry ID")
        self._registry_version = _identifier(registry_version, "Registry version")
        identities = {item.identity_fingerprint: item for item in implementations}
        if len(identities) != len(implementations):
            raise QualificationGovernanceError("Implementations must be unique.")
        authorities = {item.identity_fingerprint: item for item in governance_authorities}
        if not authorities or len(authorities) != len(governance_authorities):
            raise QualificationGovernanceError(
                "Trusted governance authorities must be nonempty and unique."
            )
        if any(
            item.authority_kind is not QualificationAuthorityKind.GOVERNANCE
            for item in governance_authorities
        ):
            raise QualificationGovernanceError(
                "Only governance identities may enter the trusted authority set."
            )
        self._governance_authorities = authorities
        self._implementations = identities

    def build(
        self,
        *,
        information_cutoff: datetime,
        qualifications: tuple[GovernedQualificationRecord, ...],
        revocations: tuple[QualificationRevocationRecord, ...] = (),
        evidence: tuple[QualificationEvidenceAvailability, ...] = (),
    ) -> QualificationRegistrySnapshot:
        _aware(information_cutoff, "Registry information cutoff")
        admissions = tuple(q for q in qualifications if q.recorded_at <= information_cutoff)
        withdrawals = tuple(r for r in revocations if r.recorded_at <= information_cutoff)
        available = tuple(e for e in evidence if e.available_at <= information_cutoff)
        self._validate_unique(admissions, withdrawals)
        evidence_map = self._evidence_map(available)
        by_fingerprint = {q.identity_fingerprint: q for q in admissions}
        revocation_map: dict[str, QualificationRevocationRecord] = {}
        for revocation in withdrawals:
            if (
                revocation.governance_authority.identity_fingerprint
                not in self._governance_authorities
            ):
                raise QualificationGovernanceError("Untrusted revocation authority.")
            target = by_fingerprint.get(revocation.qualification_fingerprint)
            if target is None:
                raise QualificationGovernanceError(
                    "Revocation targets an unknown causal qualification."
                )
            if revocation.implementation_fingerprint != target.implementation_fingerprint:
                raise QualificationGovernanceError("Revocation implementation mismatch.")
            self._require_evidence(
                revocation.revocation_reference,
                revocation.evidence_fingerprint,
                evidence_map,
            )
            revocation_map[revocation.qualification_fingerprint] = revocation

        active: dict[str, list[GovernedQualificationRecord]] = {}
        for admission in admissions:
            if (
                admission.governance_authority.identity_fingerprint
                not in self._governance_authorities
            ):
                raise QualificationGovernanceError("Untrusted qualification authority.")
            if admission.implementation_fingerprint not in self._implementations:
                raise QualificationGovernanceError(
                    "Qualification targets an unknown implementation."
                )
            self._require_evidence(
                admission.qualification_evidence_reference,
                admission.evidence_fingerprint,
                evidence_map,
            )
            state = admission.state_at(information_cutoff)
            revocation = revocation_map.get(admission.identity_fingerprint)
            if revocation is not None and revocation.revoked_at <= information_cutoff:
                state = GovernedQualificationState.REVOKED
            if state is GovernedQualificationState.QUALIFIED:
                active.setdefault(admission.implementation_fingerprint, []).append(admission)

        self._validate_requalification(admissions, revocation_map)
        if any(len(records) > 1 for records in active.values()):
            raise QualificationGovernanceError(
                "Conflicting active qualifications exist for an implementation."
            )
        references = tuple(
            self._selector_reference(records[0])
            for _, records in sorted(active.items())
        )
        return QualificationRegistrySnapshot(
            registry_id=self._registry_id,
            registry_version=self._registry_version,
            snapshot_timestamp=information_cutoff,
            qualifications=references,
        )

    @staticmethod
    def _validate_unique(
        admissions: tuple[GovernedQualificationRecord, ...],
        revocations: tuple[QualificationRevocationRecord, ...],
    ) -> None:
        keys = [(item.qualification_id, item.qualification_version) for item in admissions]
        if len(keys) != len(set(keys)):
            raise QualificationGovernanceError("Qualification ID/version must be unique.")
        targets = [item.qualification_fingerprint for item in revocations]
        if len(targets) != len(set(targets)):
            raise QualificationGovernanceError("Conflicting revocations are forbidden.")

    @staticmethod
    def _evidence_map(
        evidence: tuple[QualificationEvidenceAvailability, ...],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for artifact in evidence:
            previous = result.get(artifact.evidence_reference)
            if previous is not None and previous != artifact.evidence_fingerprint:
                raise QualificationGovernanceError("Conflicting evidence fingerprints.")
            result[artifact.evidence_reference] = artifact.evidence_fingerprint
        return result

    @staticmethod
    def _require_evidence(reference: str, expected: str, available: dict[str, str]) -> None:
        observed = available.get(reference)
        if observed is None:
            raise QualificationGovernanceError(
                "Qualification evidence was unavailable at the causal cutoff."
            )
        if observed != expected:
            raise QualificationGovernanceError("Qualification evidence fingerprint mismatch.")

    @staticmethod
    def _validate_requalification(
        admissions: tuple[GovernedQualificationRecord, ...],
        revocations: dict[str, QualificationRevocationRecord],
    ) -> None:
        grouped: dict[str, list[GovernedQualificationRecord]] = {}
        for admission in admissions:
            grouped.setdefault(admission.implementation_fingerprint, []).append(admission)
        for records in grouped.values():
            ordered = sorted(records, key=lambda item: (item.qualified_at, item.identity_fingerprint))
            for earlier, later in zip(ordered, ordered[1:]):
                revocation = revocations.get(earlier.identity_fingerprint)
                if revocation is None or revocation.revoked_at > later.qualified_at:
                    continue
                if later.predecessor_qualification_fingerprint != earlier.identity_fingerprint:
                    raise QualificationGovernanceError(
                        "Post-revocation qualification requires explicit new lineage."
                    )
                if (
                    later.qualification_id == earlier.qualification_id
                    and later.qualification_version == earlier.qualification_version
                ):
                    raise QualificationGovernanceError(
                        "Post-revocation qualification requires a new ID/version."
                    )

    @staticmethod
    def _selector_reference(record: GovernedQualificationRecord) -> QualificationReference:
        return QualificationReference(
            implementation_fingerprint=record.implementation_fingerprint,
            qualification_id=record.qualification_id,
            qualification_version=record.qualification_version,
            qualification_reference=f"governed-income-qualification:{record.identity_fingerprint}",
            evidence_fingerprint=record.evidence_fingerprint,
            status=QualificationStatus.QUALIFIED,
            eligible_from=record.effective_from,
            eligible_through=record.effective_through,
        )


def candidate_v1_qdte_implementation() -> IncomeImplementationIdentity:
    """Return the existing QDTE identity without invoking Candidate V1."""
    return IncomeImplementationIdentity(
        implementation_id="candidate_v1_qdte_income",
        implementation_version="qualified-2026-08-11",
        instrument_symbol="QDTE",
    )


def candidate_v1_qdte_compatibility_qualification() -> GovernedQualificationRecord:
    """Represent existing provenance; this function grants no qualification."""
    implementation = candidate_v1_qdte_implementation()
    evidence_fingerprint = fingerprint(
        {
            "qualification_scope": "candidate_v1",
            "authoritative_commit": CANDIDATE_V1_QUALIFICATION_COMMIT,
            "implementation_fingerprint": implementation.identity_fingerprint,
        }
    )
    qualified_at = datetime(2026, 8, 11, tzinfo=timezone.utc)
    return GovernedQualificationRecord(
        implementation=implementation,
        implementation_fingerprint=implementation.identity_fingerprint,
        qualification_id="candidate_v1_strict_causal",
        qualification_version="qualified-2026-08-11",
        qualification_evidence_reference=(
            f"git:{CANDIDATE_V1_QUALIFICATION_COMMIT}:"
            f"{CANDIDATE_V1_QUALIFICATION_DOCUMENT}"
        ),
        evidence_fingerprint=evidence_fingerprint,
        status=GovernedQualificationState.QUALIFIED,
        qualified_at=qualified_at,
        effective_from=qualified_at,
        effective_through=None,
        no_expiry=True,
        recorded_at=qualified_at,
        governance_authority=QualificationAuthorityIdentity(
            authority_id="candidate_v1_existing_qualification_governance",
            authority_version="frozen-2026-08-11",
            authority_kind=QualificationAuthorityKind.GOVERNANCE,
        ),
    )


def candidate_v1_qdte_compatibility_evidence() -> QualificationEvidenceAvailability:
    """Declare when the already-qualified Candidate V1 evidence became available."""
    record = candidate_v1_qdte_compatibility_qualification()
    return QualificationEvidenceAvailability(
        evidence_reference=record.qualification_evidence_reference,
        evidence_fingerprint=record.evidence_fingerprint,
        available_at=record.recorded_at,
    )
