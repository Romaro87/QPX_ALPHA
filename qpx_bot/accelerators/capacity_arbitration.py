"""Fixed, causal Capacity Arbitration V1 research accelerator."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Iterable

POLICIES = ("hash_control", "frozen_order", "breakout_strength", "trend_strength", "volume_confirmation")


def tie_identity(timestamp: datetime, symbol: str) -> str:
    return hashlib.sha256((timestamp.isoformat() + "|" + symbol.strip().upper()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CapacityArbitrationConfig:
    policy: str
    policy_version: str = "1.0.0"

    def validate(self) -> None:
        if self.policy not in POLICIES or self.policy_version != "1.0.0":
            raise ValueError("Capacity Arbitration V1 policy/version is fixed.")

    @property
    def fingerprint(self) -> str:
        self.validate()
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CapacityCandidate:
    symbol: str
    current_close: float
    prior_high: float
    current_atr: float
    current_fast: float
    current_slow: float
    current_volume: float
    baseline_volume: float
    frozen_top100_rank: int
    tie_break_identity: str

    def __post_init__(self) -> None:
        if not self.symbol.strip() or self.frozen_top100_rank < 1 or len(self.tie_break_identity) != 64:
            raise ValueError("Candidate identity/rank is invalid.")
        for name in ("current_close", "prior_high", "current_atr", "current_fast", "current_slow", "current_volume", "baseline_volume"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite causal scalar.")


@dataclass(frozen=True, slots=True)
class CapacityArbitrationContext:
    event_timestamp: datetime
    available_slots: int
    candidates: tuple[CapacityCandidate, ...]

    def __post_init__(self) -> None:
        if self.event_timestamp.tzinfo is None or self.available_slots < 0:
            raise ValueError("Timestamp must be aware and slots non-negative.")
        symbols = [item.symbol.upper() for item in self.candidates]
        if len(symbols) != len(set(symbols)):
            raise ValueError("Qualifying candidates must be unique.")


@dataclass(frozen=True, slots=True)
class CapacityScore:
    symbol: str
    priority: float | int | str
    tie_break_identity: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CapacityArbitrationDecision:
    policy: str
    policy_version: str
    configuration_fingerprint: str
    event_timestamp: datetime
    available_slots: int
    qualifying_symbols: tuple[str, ...]
    scores: tuple[CapacityScore, ...]
    selected_candidates: tuple[str, ...]
    deferred_candidates: tuple[str, ...]
    decision_id: str


class CapacityArbitrationV1:
    def __init__(self, config: CapacityArbitrationConfig):
        config.validate()
        self.config = config

    def _priority(self, candidate: CapacityCandidate) -> float | int | str:
        policy = self.config.policy
        if policy == "hash_control":
            return candidate.tie_break_identity
        if policy == "frozen_order":
            return candidate.frozen_top100_rank
        if policy == "breakout_strength":
            if candidate.current_atr <= 0:
                raise ValueError("INVALID_ATR_FAIL_CLOSED")
            return (candidate.current_close - candidate.prior_high) / candidate.current_atr
        if policy == "trend_strength":
            if candidate.current_atr <= 0:
                raise ValueError("INVALID_ATR_FAIL_CLOSED")
            return (candidate.current_fast - candidate.current_slow) / candidate.current_atr
        if candidate.baseline_volume <= 0:
            raise ValueError("INVALID_BASELINE_VOLUME_FAIL_CLOSED")
        return candidate.current_volume / candidate.baseline_volume

    def decide(self, context: CapacityArbitrationContext) -> CapacityArbitrationDecision:
        if len(context.candidates) <= context.available_slots and self.config.policy != "hash_control":
            control = CapacityArbitrationV1(CapacityArbitrationConfig("hash_control")).decide(context)
            core = {"policy": self.config.policy, "policy_version": self.config.policy_version, "configuration_fingerprint": self.config.fingerprint, "event_timestamp": context.event_timestamp.isoformat(), "available_slots": context.available_slots, "qualifying_symbols": control.qualifying_symbols, "scores": [item.as_dict() for item in control.scores], "selected_candidates": control.selected_candidates, "deferred_candidates": control.deferred_candidates}
            identity = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            return CapacityArbitrationDecision(self.config.policy, self.config.policy_version, self.config.fingerprint, context.event_timestamp, context.available_slots, control.qualifying_symbols, control.scores, control.selected_candidates, control.deferred_candidates, identity)
        scored = [(item, self._priority(item)) for item in context.candidates]
        descending = self.config.policy in ("breakout_strength", "trend_strength", "volume_confirmation")
        ordered = sorted(scored, key=lambda pair: ((-pair[1]) if descending else pair[1], pair[0].tie_break_identity, pair[0].symbol))
        selected = tuple(item.symbol.upper() for item, _ in ordered[:context.available_slots])
        deferred = tuple(item.symbol.upper() for item, _ in ordered[context.available_slots:])
        scores = tuple(CapacityScore(item.symbol.upper(), score, item.tie_break_identity) for item, score in ordered)
        core = {"policy": self.config.policy, "policy_version": self.config.policy_version, "configuration_fingerprint": self.config.fingerprint, "event_timestamp": context.event_timestamp.isoformat(), "available_slots": context.available_slots, "qualifying_symbols": sorted(item.symbol.upper() for item in context.candidates), "scores": [item.as_dict() for item in scores], "selected_candidates": selected, "deferred_candidates": deferred}
        decision_id = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return CapacityArbitrationDecision(self.config.policy, self.config.policy_version, self.config.fingerprint, context.event_timestamp, context.available_slots, tuple(core["qualifying_symbols"]), scores, selected, deferred, decision_id)


@dataclass(frozen=True, slots=True)
class SelectionDivergence:
    event_timestamp: datetime
    qualifying_symbols: tuple[str, ...]
    available_slots: int
    hash_selected: tuple[str, ...]
    alternative_selected: tuple[str, ...]
    overlap_count: int
    displaced_symbols: tuple[str, ...]
    replacement_symbols: tuple[str, ...]
    divergence_id: str


def selection_divergence(decision: CapacityArbitrationDecision, hash_selected: Iterable[str]) -> SelectionDivergence:
    control = tuple(hash_selected); alternative = decision.selected_candidates
    overlap = len(set(control) & set(alternative)); displaced = tuple(sorted(set(control) - set(alternative))); replacements = tuple(sorted(set(alternative) - set(control)))
    core = {"event_timestamp": decision.event_timestamp.isoformat(), "qualifying_symbols": decision.qualifying_symbols, "available_slots": decision.available_slots, "hash_selected": control, "alternative_selected": alternative, "overlap_count": overlap, "displaced_symbols": displaced, "replacement_symbols": replacements}
    identity = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return SelectionDivergence(decision.event_timestamp, decision.qualifying_symbols, decision.available_slots, control, alternative, overlap, displaced, replacements, identity)
