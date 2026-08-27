"""Isolated causal Dividend Opportunity Engine Foundation V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any

VERSION = "1.0.0"
NO_ACTION = "NO_ACTION"
NO_QUALIFIED_OPPORTUNITY = "NO QUALIFIED / NO ACTIONABLE OPPORTUNITY"


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Incomplete {name}")


def _require_fingerprint(name: str, value: str) -> None:
    _require_text(name, value)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"Invalid {name}")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class OpportunityType(StrEnum):
    DIVIDEND_CAPTURE = "DIVIDEND_CAPTURE"
    POST_EX_DIVIDEND_RECOVERY = "POST_EX_DIVIDEND_RECOVERY"
    PRE_EX_DIVIDEND_MOMENTUM = "PRE_EX_DIVIDEND_MOMENTUM"
    QUALITY_INCOME_ROTATION = "QUALITY_INCOME_ROTATION"
    RELATED_DIVIDEND_OPPORTUNITY = "RELATED_DIVIDEND_OPPORTUNITY"


class OpportunityState(StrEnum):
    NO_OPPORTUNITY = "NO_OPPORTUNITY"


@dataclass(frozen=True, slots=True)
class DividendOpportunityConfig:
    enabled: bool
    accelerator_version: str
    configuration_version: str
    policy_identity: str | None = None
    scoring_policy_identity: str | None = None
    capital_authority: bool = False
    execution_authority: bool = False
    qualification_authority: bool = False
    promotion_authority: bool = False

    def validate(self) -> None:
        if self.enabled is not False or self.accelerator_version != VERSION:
            raise ValueError("Foundation V1 must remain disabled research infrastructure")
        _require_text("configuration_version", self.configuration_version)
        if self.policy_identity is not None or self.scoring_policy_identity is not None:
            raise ValueError("Foundation V1 cannot declare scoring or opportunity policy")
        if any((self.capital_authority, self.execution_authority,
                self.qualification_authority, self.promotion_authority)):
            raise ValueError("Foundation V1 has no allocation, execution, or governance authority")

    @property
    def fingerprint(self) -> str:
        self.validate()
        return canonical_fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class DividendOpportunityEvidence:
    evidence_identity: str
    source_identity: str
    source_fingerprint: str
    provenance_identity: str
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_text("evidence_identity", self.evidence_identity)
        _require_text("source_identity", self.source_identity)
        _require_fingerprint("source_fingerprint", self.source_fingerprint)
        _require_text("provenance_identity", self.provenance_identity)
        _require_aware("observed_at", self.observed_at)


@dataclass(frozen=True, slots=True)
class DividendOpportunityContext:
    opportunity_type: OpportunityType
    symbol: str
    corporate_action_event_id: str
    event_effective_time: datetime
    information_available_time: datetime
    evaluation_timestamp: datetime
    causal_input_fingerprint: str
    evidence: DividendOpportunityEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.opportunity_type, OpportunityType):
            raise ValueError("Unknown opportunity type")
        _require_text("symbol", self.symbol)
        if self.symbol != self.symbol.strip().upper():
            raise ValueError("Symbol must be normalized uppercase")
        _require_fingerprint("corporate_action_event_id", self.corporate_action_event_id)
        _require_aware("event_effective_time", self.event_effective_time)
        _require_aware("information_available_time", self.information_available_time)
        _require_aware("evaluation_timestamp", self.evaluation_timestamp)
        _require_fingerprint("causal_input_fingerprint", self.causal_input_fingerprint)
        if self.information_available_time > self.evaluation_timestamp:
            raise ValueError("Future dividend information is unavailable at evaluation time")
        if self.evidence.observed_at > self.evaluation_timestamp:
            raise ValueError("Future evidence is unavailable at evaluation time")
        if self.evidence.observed_at < self.information_available_time:
            raise ValueError("Evidence predates declared information availability")

    @property
    def input_fingerprint(self) -> str:
        evidence = asdict(self.evidence)
        evidence["observed_at"] = self.evidence.observed_at.isoformat()
        return canonical_fingerprint({
            "opportunity_type": self.opportunity_type.value,
            "symbol": self.symbol,
            "corporate_action_event_id": self.corporate_action_event_id,
            "event_effective_time": self.event_effective_time.isoformat(),
            "information_available_time": self.information_available_time.isoformat(),
            "evaluation_timestamp": self.evaluation_timestamp.isoformat(),
            "causal_input_fingerprint": self.causal_input_fingerprint,
            "evidence": evidence,
        })


@dataclass(frozen=True, slots=True)
class DividendOpportunityDecision:
    accelerator_version: str
    configuration_fingerprint: str
    opportunity_type: OpportunityType
    symbol: str
    corporate_action_event_id: str
    event_effective_time: datetime
    information_available_time: datetime
    evaluation_timestamp: datetime
    causal_input_fingerprint: str
    evidence_identity: str
    provenance_identity: str
    opportunity_state: OpportunityState
    reason_codes: tuple[str, ...]
    proposed_action: str
    proposed_capital: None
    capital_authority: bool
    execution_authority: bool
    qualification_authority: bool
    promotion_authority: bool
    opportunity_id: str
    decision_id: str


class DividendOpportunityEngineV1:
    def __init__(self, config: DividendOpportunityConfig):
        config.validate()
        self.config = config

    def evaluate(self, context: DividendOpportunityContext) -> DividendOpportunityDecision:
        opportunity_core = {
            "accelerator_version": VERSION,
            "configuration_fingerprint": self.config.fingerprint,
            "opportunity_type": context.opportunity_type.value,
            "symbol": context.symbol,
            "corporate_action_event_id": context.corporate_action_event_id,
            "event_effective_time": context.event_effective_time.isoformat(),
            "information_available_time": context.information_available_time.isoformat(),
            "evaluation_timestamp": context.evaluation_timestamp.isoformat(),
            "causal_input_fingerprint": context.causal_input_fingerprint,
            "validated_input_fingerprint": context.input_fingerprint,
            "evidence_identity": context.evidence.evidence_identity,
            "provenance_identity": context.evidence.provenance_identity,
        }
        opportunity_id = canonical_fingerprint(opportunity_core)
        reasons = ("FOUNDATION_NO_SCORING_POLICY", NO_QUALIFIED_OPPORTUNITY)
        decision_core = {
            **opportunity_core,
            "opportunity_id": opportunity_id,
            "opportunity_state": OpportunityState.NO_OPPORTUNITY.value,
            "reason_codes": reasons,
            "proposed_action": NO_ACTION,
            "proposed_capital": None,
            "capital_authority": False,
            "execution_authority": False,
            "qualification_authority": False,
            "promotion_authority": False,
        }
        return DividendOpportunityDecision(
            accelerator_version=VERSION,
            configuration_fingerprint=self.config.fingerprint,
            opportunity_type=context.opportunity_type,
            symbol=context.symbol,
            corporate_action_event_id=context.corporate_action_event_id,
            event_effective_time=context.event_effective_time,
            information_available_time=context.information_available_time,
            evaluation_timestamp=context.evaluation_timestamp,
            causal_input_fingerprint=context.causal_input_fingerprint,
            evidence_identity=context.evidence.evidence_identity,
            provenance_identity=context.evidence.provenance_identity,
            opportunity_state=OpportunityState.NO_OPPORTUNITY,
            reason_codes=reasons,
            proposed_action=NO_ACTION,
            proposed_capital=None,
            capital_authority=False,
            execution_authority=False,
            qualification_authority=False,
            promotion_authority=False,
            opportunity_id=opportunity_id,
            decision_id=canonical_fingerprint(decision_core),
        )


def load_dividend_opportunity_config(path: Path) -> DividendOpportunityConfig:
    config = DividendOpportunityConfig(**json.loads(path.read_text(encoding="utf-8")))
    config.validate()
    return config
