"""Isolated, deterministic income-role identity and selection foundation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Mapping


SCHEMA_VERSION = 1
FINGERPRINT_LENGTH = 64
CANDIDATE_V1_QUALIFICATION_COMMIT = (
    "7213db1e17fedce9e923889b116775cca121f766"
)


class QualificationStatus(StrEnum):
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"
    REVOKED = "REVOKED"


class IncomeDecisionOutcome(StrEnum):
    IMPLEMENTATION = "IMPLEMENTATION"
    CASH = "CASH"


class NonCausalInputError(ValueError):
    """A selector input was unavailable at the decision-time cutoff."""


def _aware(value: datetime, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be a timezone-aware datetime.")
    if value.utcoffset() is None:
        raise ValueError(f"{name} must have a valid UTC offset.")
    return value


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _identifier(value: str, name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{name} cannot be empty.")
    return normalized


def _fingerprint_value(value: str, name: str) -> str:
    normalized = str(value).strip().lower()
    if (
        len(normalized) != FINGERPRINT_LENGTH
        or any(character not in "0123456789abcdef" for character in normalized)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 fingerprint.")
    return normalized


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Return the canonical JSON representation used for every identity."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def fingerprint(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 identity of a canonical payload."""
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PortfolioRoleIdentity:
    role_id: str
    role_version: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported portfolio-role schema version.")
        if self.role_id != "income":
            raise ValueError("This foundation supports only the income role.")
        _identifier(self.role_version, "Role version")

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role_id": self.role_id,
            "role_version": self.role_version,
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


INCOME_ROLE_V1 = PortfolioRoleIdentity(
    role_id="income",
    role_version="1.0.0",
)


@dataclass(frozen=True, slots=True)
class IncomeImplementationIdentity:
    implementation_id: str
    implementation_version: str
    instrument_symbol: str
    role_fingerprint: str = INCOME_ROLE_V1.identity_fingerprint
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported income-implementation schema version.")
        _identifier(self.implementation_id, "Implementation ID")
        _identifier(self.implementation_version, "Implementation version")
        symbol = _identifier(self.instrument_symbol, "Instrument symbol").upper()
        object.__setattr__(self, "instrument_symbol", symbol)
        object.__setattr__(
            self,
            "role_fingerprint",
            _fingerprint_value(self.role_fingerprint, "Role fingerprint"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role_fingerprint": self.role_fingerprint,
            "implementation_id": self.implementation_id,
            "implementation_version": self.implementation_version,
            "instrument_symbol": self.instrument_symbol,
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class QualificationReference:
    implementation_fingerprint: str
    qualification_id: str
    qualification_version: str
    qualification_reference: str
    evidence_fingerprint: str
    status: QualificationStatus
    eligible_from: datetime | None = None
    eligible_through: datetime | None = None
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported qualification-reference schema version.")
        object.__setattr__(
            self,
            "implementation_fingerprint",
            _fingerprint_value(
                self.implementation_fingerprint,
                "Implementation fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "evidence_fingerprint",
            _fingerprint_value(self.evidence_fingerprint, "Evidence fingerprint"),
        )
        _identifier(self.qualification_id, "Qualification ID")
        _identifier(self.qualification_version, "Qualification version")
        _identifier(self.qualification_reference, "Qualification reference")
        if not isinstance(self.status, QualificationStatus):
            raise ValueError("Qualification status is invalid.")
        if self.eligible_from is not None:
            _aware(self.eligible_from, "Qualification eligible_from")
        if self.eligible_through is not None:
            _aware(self.eligible_through, "Qualification eligible_through")
        if (
            self.eligible_from is not None
            and self.eligible_through is not None
            and self.eligible_through < self.eligible_from
        ):
            raise ValueError("Qualification eligibility interval is reversed.")

    def is_eligible_at(self, cutoff: datetime) -> bool:
        _aware(cutoff, "Qualification cutoff")
        if self.status is not QualificationStatus.QUALIFIED:
            return False
        if self.eligible_from is not None and cutoff < self.eligible_from:
            return False
        if self.eligible_through is not None and cutoff > self.eligible_through:
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "implementation_fingerprint": self.implementation_fingerprint,
            "qualification_id": self.qualification_id,
            "qualification_version": self.qualification_version,
            "qualification_reference": self.qualification_reference,
            "evidence_fingerprint": self.evidence_fingerprint,
            "status": self.status.value,
            "eligible_from": (
                _timestamp(self.eligible_from) if self.eligible_from else None
            ),
            "eligible_through": (
                _timestamp(self.eligible_through) if self.eligible_through else None
            ),
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class QualificationRegistrySnapshot:
    registry_id: str
    registry_version: str
    snapshot_timestamp: datetime
    qualifications: tuple[QualificationReference, ...]
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported qualification-registry schema version.")
        _identifier(self.registry_id, "Registry ID")
        _identifier(self.registry_version, "Registry version")
        _aware(self.snapshot_timestamp, "Registry snapshot timestamp")
        ordered = tuple(
            sorted(
                self.qualifications,
                key=lambda item: item.implementation_fingerprint,
            )
        )
        identities = [item.implementation_fingerprint for item in ordered]
        if len(identities) != len(set(identities)):
            raise ValueError("Qualification registry contains duplicate implementations.")
        object.__setattr__(self, "qualifications", ordered)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "registry_id": self.registry_id,
            "registry_version": self.registry_version,
            "snapshot_timestamp": _timestamp(self.snapshot_timestamp),
            "qualifications": [item.as_dict() for item in self.qualifications],
        }

    @property
    def identity_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class IncomeSelectorConfig:
    selector_id: str
    selector_version: str
    candidate_implementation_fingerprints: tuple[str, ...]
    allow_cash: bool = True
    role_fingerprint: str = INCOME_ROLE_V1.identity_fingerprint
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported income-selector schema version.")
        _identifier(self.selector_id, "Selector ID")
        _identifier(self.selector_version, "Selector version")
        if self.allow_cash is not True:
            raise ValueError("Income-role selection must fail closed to CASH.")
        object.__setattr__(
            self,
            "role_fingerprint",
            _fingerprint_value(self.role_fingerprint, "Role fingerprint"),
        )
        normalized = tuple(
            _fingerprint_value(value, "Candidate implementation fingerprint")
            for value in self.candidate_implementation_fingerprints
        )
        if not normalized:
            raise ValueError("Selector must declare at least one candidate identity.")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Selector candidate identities must be unique.")
        object.__setattr__(self, "candidate_implementation_fingerprints", normalized)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role_fingerprint": self.role_fingerprint,
            "selector_id": self.selector_id,
            "selector_version": self.selector_version,
            "candidate_implementation_fingerprints": list(
                self.candidate_implementation_fingerprints
            ),
            "allow_cash": self.allow_cash,
        }

    @property
    def configuration_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class IncomeSelectionContext:
    decision_timestamp: datetime
    information_cutoff: datetime
    qualification_registry_fingerprint: str
    available_implementation_fingerprints: tuple[str, ...]
    role_fingerprint: str = INCOME_ROLE_V1.identity_fingerprint
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported income-selection-context schema version.")
        _aware(self.decision_timestamp, "Decision timestamp")
        _aware(self.information_cutoff, "Information cutoff")
        if self.information_cutoff > self.decision_timestamp:
            raise NonCausalInputError(
                "Information cutoff cannot be later than the decision timestamp."
            )
        object.__setattr__(
            self,
            "qualification_registry_fingerprint",
            _fingerprint_value(
                self.qualification_registry_fingerprint,
                "Qualification registry fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "role_fingerprint",
            _fingerprint_value(self.role_fingerprint, "Role fingerprint"),
        )
        available = tuple(
            sorted(
                {
                    _fingerprint_value(value, "Available implementation fingerprint")
                    for value in self.available_implementation_fingerprints
                }
            )
        )
        object.__setattr__(self, "available_implementation_fingerprints", available)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role_fingerprint": self.role_fingerprint,
            "decision_timestamp": _timestamp(self.decision_timestamp),
            "information_cutoff": _timestamp(self.information_cutoff),
            "qualification_registry_fingerprint": (
                self.qualification_registry_fingerprint
            ),
            "available_implementation_fingerprints": list(
                self.available_implementation_fingerprints
            ),
        }

    @property
    def context_fingerprint(self) -> str:
        return fingerprint(self.as_dict())


@dataclass(frozen=True, slots=True)
class IncomeSelectorDecision:
    outcome: IncomeDecisionOutcome
    role: PortfolioRoleIdentity
    selector_id: str
    selector_version: str
    selector_configuration_fingerprint: str
    qualification_registry_fingerprint: str
    context_fingerprint: str
    decision_timestamp: datetime
    information_cutoff: datetime
    selected_implementation: IncomeImplementationIdentity | None
    qualification_reference: QualificationReference | None
    qualification_fingerprint: str | None
    reason_codes: tuple[str, ...]
    decision_id: str
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported income-selector-decision schema version.")
        if not isinstance(self.outcome, IncomeDecisionOutcome):
            raise ValueError("Income decision outcome is invalid.")
        _identifier(self.selector_id, "Selector ID")
        _identifier(self.selector_version, "Selector version")
        for value, name in (
            (self.selector_configuration_fingerprint, "Selector fingerprint"),
            (self.qualification_registry_fingerprint, "Registry fingerprint"),
            (self.context_fingerprint, "Context fingerprint"),
            (self.decision_id, "Decision ID"),
        ):
            _fingerprint_value(value, name)
        _aware(self.decision_timestamp, "Decision timestamp")
        _aware(self.information_cutoff, "Information cutoff")
        if not self.reason_codes:
            raise ValueError("Income decision must contain reason codes.")
        if self.outcome is IncomeDecisionOutcome.CASH:
            if self.selected_implementation is not None:
                raise ValueError("CASH cannot contain an implementation identity.")
            if self.qualification_reference is not None:
                raise ValueError("CASH cannot contain a qualification reference.")
            if self.qualification_fingerprint is not None:
                raise ValueError("CASH cannot contain a qualification fingerprint.")
        else:
            if self.selected_implementation is None:
                raise ValueError("Implementation decision lacks an identity.")
            if self.qualification_reference is None:
                raise ValueError("Implementation decision lacks qualification lineage.")
            if self.qualification_fingerprint is None:
                raise ValueError("Implementation decision lacks qualification fingerprint.")
            _fingerprint_value(
                self.qualification_fingerprint,
                "Qualification fingerprint",
            )
            if (
                self.qualification_fingerprint
                != self.qualification_reference.identity_fingerprint
            ):
                raise ValueError("Qualification fingerprint does not match reference.")
            if (
                self.qualification_reference.implementation_fingerprint
                != self.selected_implementation.identity_fingerprint
            ):
                raise ValueError("Selected implementation and qualification differ.")

    def lineage_dict(self) -> dict[str, Any]:
        """Return immutable identity sufficient for future position lineage."""
        return {
            "role": self.role.as_dict(),
            "outcome": self.outcome.value,
            "selected_implementation": (
                self.selected_implementation.as_dict()
                if self.selected_implementation
                else None
            ),
            "selector_id": self.selector_id,
            "selector_version": self.selector_version,
            "selector_configuration_fingerprint": (
                self.selector_configuration_fingerprint
            ),
            "qualification_reference": (
                self.qualification_reference.as_dict()
                if self.qualification_reference
                else None
            ),
            "qualification_fingerprint": self.qualification_fingerprint,
            "qualification_registry_fingerprint": (
                self.qualification_registry_fingerprint
            ),
            "context_fingerprint": self.context_fingerprint,
            "decision_timestamp": _timestamp(self.decision_timestamp),
            "information_cutoff": _timestamp(self.information_cutoff),
            "decision_id": self.decision_id,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            **self.lineage_dict(),
            "reason_codes": list(self.reason_codes),
        }

    @property
    def decision_fingerprint(self) -> str:
        """Fingerprint the complete persisted decision record."""
        return fingerprint(self.as_dict())


class IncomeRoleSelector:
    """Stateless selector over explicit causal and qualified identities."""

    def __init__(
        self,
        *,
        config: IncomeSelectorConfig,
        implementations: tuple[IncomeImplementationIdentity, ...],
        qualification_registry: QualificationRegistrySnapshot,
    ) -> None:
        if config.role_fingerprint != INCOME_ROLE_V1.identity_fingerprint:
            raise ValueError("Selector configuration targets another role.")
        identities = {
            item.identity_fingerprint: item
            for item in implementations
        }
        if len(identities) != len(implementations):
            raise ValueError("Implementation identities must be unique.")
        if any(
            item.role_fingerprint != config.role_fingerprint
            for item in implementations
        ):
            raise ValueError("Implementation targets another portfolio role.")
        self._config = config
        self._implementations = identities
        self._registry = qualification_registry

    def select(self, context: IncomeSelectionContext) -> IncomeSelectorDecision:
        if context.role_fingerprint != self._config.role_fingerprint:
            raise ValueError("Selection context targets another role.")
        if (
            context.qualification_registry_fingerprint
            != self._registry.identity_fingerprint
        ):
            raise ValueError("Qualification registry identity mismatch.")
        if self._registry.snapshot_timestamp > context.information_cutoff:
            raise NonCausalInputError(
                "Qualification snapshot was not available at the causal cutoff."
            )

        qualifications = {
            item.implementation_fingerprint: item
            for item in self._registry.qualifications
        }
        reasons: list[str] = []

        for candidate in self._config.candidate_implementation_fingerprints:
            implementation = self._implementations.get(candidate)
            if implementation is None:
                reasons.append(f"UNKNOWN_IMPLEMENTATION:{candidate}")
                continue
            qualification = qualifications.get(candidate)
            if qualification is None:
                reasons.append(f"MISSING_QUALIFICATION:{candidate}")
                continue
            if qualification.status is not QualificationStatus.QUALIFIED:
                reasons.append(f"NOT_QUALIFIED:{candidate}")
                continue
            if not qualification.is_eligible_at(context.information_cutoff):
                reasons.append(f"STALE_OR_NOT_YET_ELIGIBLE:{candidate}")
                continue
            if candidate not in context.available_implementation_fingerprints:
                reasons.append(f"NOT_AVAILABLE_AT_DECISION:{candidate}")
                continue
            return self._decision(
                context=context,
                outcome=IncomeDecisionOutcome.IMPLEMENTATION,
                implementation=implementation,
                qualification=qualification,
                reason_codes=("SELECTED_QUALIFIED_IMPLEMENTATION",),
            )

        return self._decision(
            context=context,
            outcome=IncomeDecisionOutcome.CASH,
            implementation=None,
            qualification=None,
            reason_codes=tuple(reasons) + ("NO_QUALIFIED_IMPLEMENTATION_DEPLOYED",),
        )

    def _decision(
        self,
        *,
        context: IncomeSelectionContext,
        outcome: IncomeDecisionOutcome,
        implementation: IncomeImplementationIdentity | None,
        qualification: QualificationReference | None,
        reason_codes: tuple[str, ...],
    ) -> IncomeSelectorDecision:
        core = {
            "schema_version": SCHEMA_VERSION,
            "role": INCOME_ROLE_V1.as_dict(),
            "outcome": outcome.value,
            "selector_id": self._config.selector_id,
            "selector_version": self._config.selector_version,
            "selector_configuration_fingerprint": (
                self._config.configuration_fingerprint
            ),
            "qualification_registry_fingerprint": (
                self._registry.identity_fingerprint
            ),
            "context_fingerprint": context.context_fingerprint,
            "decision_timestamp": _timestamp(context.decision_timestamp),
            "information_cutoff": _timestamp(context.information_cutoff),
            "selected_implementation": (
                implementation.as_dict() if implementation else None
            ),
            "qualification_reference": (
                qualification.as_dict() if qualification else None
            ),
            "qualification_fingerprint": (
                qualification.identity_fingerprint if qualification else None
            ),
            "reason_codes": list(reason_codes),
        }
        return IncomeSelectorDecision(
            outcome=outcome,
            role=INCOME_ROLE_V1,
            selector_id=self._config.selector_id,
            selector_version=self._config.selector_version,
            selector_configuration_fingerprint=(
                self._config.configuration_fingerprint
            ),
            qualification_registry_fingerprint=(
                self._registry.identity_fingerprint
            ),
            context_fingerprint=context.context_fingerprint,
            decision_timestamp=context.decision_timestamp,
            information_cutoff=context.information_cutoff,
            selected_implementation=implementation,
            qualification_reference=qualification,
            qualification_fingerprint=(
                qualification.identity_fingerprint if qualification else None
            ),
            reason_codes=reason_codes,
            decision_id=fingerprint(core),
        )


def candidate_v1_legacy_decision(
    *,
    decision_timestamp: datetime,
    information_cutoff: datetime,
) -> IncomeSelectorDecision:
    """Represent, but do not invoke, Candidate V1's fixed qualified QDTE choice."""
    qdte = IncomeImplementationIdentity(
        implementation_id="candidate_v1_qdte_income",
        implementation_version="qualified-2026-08-11",
        instrument_symbol="QDTE",
    )
    evidence = fingerprint(
        {
            "qualification_scope": "candidate_v1",
            "authoritative_commit": CANDIDATE_V1_QUALIFICATION_COMMIT,
            "implementation_fingerprint": qdte.identity_fingerprint,
        }
    )
    qualification = QualificationReference(
        implementation_fingerprint=qdte.identity_fingerprint,
        qualification_id="candidate_v1_strict_causal",
        qualification_version="qualified-2026-08-11",
        qualification_reference=(
            f"git:{CANDIDATE_V1_QUALIFICATION_COMMIT}:candidate_v1"
        ),
        evidence_fingerprint=evidence,
        status=QualificationStatus.QUALIFIED,
    )
    registry = QualificationRegistrySnapshot(
        registry_id="candidate_v1_legacy_income_registry",
        registry_version="frozen-2026-08-11",
        snapshot_timestamp=information_cutoff,
        qualifications=(qualification,),
    )
    config = IncomeSelectorConfig(
        selector_id="candidate_v1_legacy_fixed_income",
        selector_version="frozen-1.0.0",
        candidate_implementation_fingerprints=(qdte.identity_fingerprint,),
    )
    context = IncomeSelectionContext(
        decision_timestamp=decision_timestamp,
        information_cutoff=information_cutoff,
        qualification_registry_fingerprint=registry.identity_fingerprint,
        available_implementation_fingerprints=(qdte.identity_fingerprint,),
    )
    return IncomeRoleSelector(
        config=config,
        implementations=(qdte,),
        qualification_registry=registry,
    ).select(context)
