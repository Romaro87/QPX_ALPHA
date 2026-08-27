"""Isolated causal Dividend Opportunity Engine Foundation V1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
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
    OPPORTUNITY_IDENTIFIED = "OPPORTUNITY_IDENTIFIED"


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


@dataclass(frozen=True, slots=True)
class PostExRecoveryConfig:
    enabled: bool
    accelerator_version: str
    configuration_version: str
    recovery_threshold: float
    evaluation_window_seconds: float
    lookback_window_seconds: float
    research_only: bool = True
    capital_authority: bool = False
    execution_authority: bool = False
    qualification_authority: bool = False
    promotion_authority: bool = False

    def validate(self) -> None:
        if not self.enabled or self.accelerator_version != VERSION:
            raise ValueError("Post-Ex Recovery V1 must be enabled research policy")
        _require_text("configuration_version", self.configuration_version)
        if not self.research_only:
            raise ValueError("Post-Ex Recovery V1 is research-only")
        for name in ("recovery_threshold", "evaluation_window_seconds", "lookback_window_seconds"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"Invalid {name}")
        if not 0.0 < self.recovery_threshold <= 1.0:
            raise ValueError("Recovery threshold must be in (0, 1]")
        if self.evaluation_window_seconds <= 0 or self.lookback_window_seconds <= 0:
            raise ValueError("Recovery windows must be positive")
        if any((self.capital_authority, self.execution_authority,
                self.qualification_authority, self.promotion_authority)):
            raise ValueError("Post-Ex Recovery V1 has no capital or governance authority")

    @property
    def fingerprint(self) -> str:
        self.validate()
        return canonical_fingerprint(asdict(self))


@dataclass(frozen=True, slots=True)
class PostExRecoveryObservation:
    observed_at: datetime
    information_available_at: datetime
    price: float
    causal_input_fingerprint: str

    def __post_init__(self) -> None:
        _require_aware("observed_at", self.observed_at)
        _require_aware("information_available_at", self.information_available_at)
        _require_fingerprint("causal_input_fingerprint", self.causal_input_fingerprint)
        if not isinstance(self.price, (int, float)) or not math.isfinite(self.price) or self.price <= 0:
            raise ValueError("Invalid recovery observation price")
        if self.information_available_at < self.observed_at:
            raise ValueError("Observation availability cannot predate observation")


@dataclass(frozen=True, slots=True)
class PostExRecoveryContext:
    base_context: DividendOpportunityContext
    ex_dividend_reference_price: float
    observations: tuple[PostExRecoveryObservation, ...]

    def __post_init__(self) -> None:
        if self.base_context.opportunity_type != OpportunityType.POST_EX_DIVIDEND_RECOVERY:
            raise ValueError("Post-Ex Recovery requires its distinct opportunity type")
        if self.base_context.evaluation_timestamp < self.base_context.event_effective_time:
            raise ValueError("Post-Ex Recovery cannot evaluate before the ex-dividend event")
        if not isinstance(self.ex_dividend_reference_price, (int, float)) or not math.isfinite(self.ex_dividend_reference_price) or self.ex_dividend_reference_price <= 0:
            raise ValueError("Invalid ex-dividend reference price")
        if not isinstance(self.observations, tuple):
            raise ValueError("Recovery observations must be an immutable tuple")
        previous: datetime | None = None
        for observation in self.observations:
            if observation.observed_at < self.base_context.event_effective_time:
                raise ValueError("Recovery observation predates ex-dividend event")
            if observation.observed_at > self.base_context.evaluation_timestamp:
                raise ValueError("Future recovery observation is unavailable at evaluation time")
            if observation.information_available_at > self.base_context.evaluation_timestamp:
                raise ValueError("Future recovery information is unavailable at evaluation time")
            if previous is not None and observation.observed_at <= previous:
                raise ValueError("Recovery observations must be strictly chronological")
            previous = observation.observed_at

    @property
    def observation_fingerprint(self) -> str:
        return canonical_fingerprint([
            {
                "observed_at": item.observed_at.isoformat(),
                "information_available_at": item.information_available_at.isoformat(),
                "price": item.price,
                "causal_input_fingerprint": item.causal_input_fingerprint,
            }
            for item in self.observations
        ])


@dataclass(frozen=True, slots=True)
class PostExRecoveryDecision:
    accelerator_version: str
    configuration_fingerprint: str
    opportunity_type: OpportunityType
    symbol: str
    corporate_action_event_id: str
    event_effective_time: datetime
    information_available_time: datetime
    evaluation_timestamp: datetime
    causal_input_fingerprint: str
    observation_fingerprint: str
    evidence_identity: str
    provenance_identity: str
    ex_dividend_reference_price: float
    latest_observation_at: datetime | None
    latest_observation_price: float | None
    recovery_progress: float | None
    elapsed_causal_seconds: float | None
    recovery_threshold: float
    evaluation_window_seconds: float
    lookback_window_seconds: float
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


class PostExRecoveryV1:
    def __init__(self, config: PostExRecoveryConfig):
        config.validate()
        self.config = config

    def evaluate(self, context: PostExRecoveryContext) -> PostExRecoveryDecision:
        config = self.config
        base = context.base_context
        eligible_observations = tuple(
            observation
            for observation in context.observations
            if (base.evaluation_timestamp - observation.observed_at).total_seconds()
            <= config.lookback_window_seconds
        )
        latest = eligible_observations[-1] if eligible_observations else None
        elapsed = (
            (base.evaluation_timestamp - base.event_effective_time).total_seconds()
            if base.evaluation_timestamp >= base.event_effective_time else None
        )
        progress = (
            (latest.price - context.ex_dividend_reference_price) / context.ex_dividend_reference_price
            if latest is not None else None
        )
        reasons: tuple[str, ...]
        state = OpportunityState.NO_OPPORTUNITY
        if latest is None and context.observations:
            reasons = ("LOOKBACK_WINDOW_EMPTY", NO_QUALIFIED_OPPORTUNITY)
        elif latest is None:
            reasons = ("NO_POST_EX_OBSERVATION", NO_QUALIFIED_OPPORTUNITY)
        elif elapsed is not None and elapsed > config.evaluation_window_seconds:
            reasons = ("EVALUATION_WINDOW_EXPIRED", NO_QUALIFIED_OPPORTUNITY)
        elif progress is not None and progress >= config.recovery_threshold:
            state = OpportunityState.OPPORTUNITY_IDENTIFIED
            reasons = ("RECOVERY_THRESHOLD_REACHED",)
        else:
            reasons = ("RECOVERY_THRESHOLD_NOT_REACHED", NO_QUALIFIED_OPPORTUNITY)
        core = {
            "accelerator_version": VERSION,
            "configuration_fingerprint": config.fingerprint,
            "opportunity_type": base.opportunity_type.value,
            "symbol": base.symbol,
            "corporate_action_event_id": base.corporate_action_event_id,
            "event_effective_time": base.event_effective_time.isoformat(),
            "information_available_time": base.information_available_time.isoformat(),
            "evaluation_timestamp": base.evaluation_timestamp.isoformat(),
            "causal_input_fingerprint": base.causal_input_fingerprint,
            "observation_fingerprint": context.observation_fingerprint,
            "evidence_identity": base.evidence.evidence_identity,
            "provenance_identity": base.evidence.provenance_identity,
            "ex_dividend_reference_price": context.ex_dividend_reference_price,
            "latest_observation_at": latest.observed_at.isoformat() if latest else None,
            "latest_observation_price": latest.price if latest else None,
            "recovery_progress": progress,
            "elapsed_causal_seconds": elapsed,
            "recovery_threshold": config.recovery_threshold,
            "evaluation_window_seconds": config.evaluation_window_seconds,
            "lookback_window_seconds": config.lookback_window_seconds,
            "opportunity_state": state.value,
            "reason_codes": reasons,
            "proposed_action": NO_ACTION,
            "proposed_capital": None,
            "capital_authority": False,
            "execution_authority": False,
            "qualification_authority": False,
            "promotion_authority": False,
        }
        opportunity_id = canonical_fingerprint({key: core[key] for key in (
            "accelerator_version", "configuration_fingerprint", "opportunity_type", "symbol",
            "corporate_action_event_id", "event_effective_time", "information_available_time",
            "causal_input_fingerprint", "observation_fingerprint", "evidence_identity",
            "provenance_identity", "ex_dividend_reference_price",
        )})
        core["opportunity_id"] = opportunity_id
        return PostExRecoveryDecision(
            accelerator_version=VERSION,
            configuration_fingerprint=config.fingerprint,
            opportunity_type=base.opportunity_type,
            symbol=base.symbol,
            corporate_action_event_id=base.corporate_action_event_id,
            event_effective_time=base.event_effective_time,
            information_available_time=base.information_available_time,
            evaluation_timestamp=base.evaluation_timestamp,
            causal_input_fingerprint=base.causal_input_fingerprint,
            observation_fingerprint=context.observation_fingerprint,
            evidence_identity=base.evidence.evidence_identity,
            provenance_identity=base.evidence.provenance_identity,
            ex_dividend_reference_price=context.ex_dividend_reference_price,
            latest_observation_at=latest.observed_at if latest else None,
            latest_observation_price=latest.price if latest else None,
            recovery_progress=progress,
            elapsed_causal_seconds=elapsed,
            recovery_threshold=config.recovery_threshold,
            evaluation_window_seconds=config.evaluation_window_seconds,
            lookback_window_seconds=config.lookback_window_seconds,
            opportunity_state=state,
            reason_codes=reasons,
            proposed_action=NO_ACTION,
            proposed_capital=None,
            capital_authority=False,
            execution_authority=False,
            qualification_authority=False,
            promotion_authority=False,
            opportunity_id=opportunity_id,
            decision_id=canonical_fingerprint(core),
        )


def load_post_ex_recovery_config(path: Path) -> PostExRecoveryConfig:
    config = PostExRecoveryConfig(**json.loads(path.read_text(encoding="utf-8")))
    config.validate()
    return config
