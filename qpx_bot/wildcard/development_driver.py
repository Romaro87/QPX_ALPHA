"""External DEVELOPMENT_ONLY boundary driver and sterile Wildcard reporter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from qpx_bot.paper_state import write_checksummed_state
from qpx_bot.wildcard.world import (
    CausalBoundary,
    MarketEvent,
    WildcardWorld,
    WorldError,
    WorldStatus,
    _canon,
    _text,
    fingerprint,
)


DRIVER_SCHEMA_VERSION = 1
DRIVER_SEMANTIC_VERSION = "QPX_WILDCARD_DEVELOPMENT_BOUNDARY_DRIVER_V1"
REPORT_SCHEMA_VERSION = 1
REPORT_CADENCE_MINUTES = 8190


class WriteOnlyReportSink(Protocol):
    def append(self, report: Mapping[str, Any]) -> None: ...


@dataclass(frozen=True, slots=True)
class BoundaryBatch:
    boundary_id: str
    effective_time: datetime
    available_time: datetime
    scheduled_market_minutes: int
    events: tuple[MarketEvent, ...]

    def __post_init__(self) -> None:
        if not self.boundary_id.strip():
            raise WorldError("Boundary identity cannot be empty.")
        if self.effective_time.tzinfo is None or self.available_time.tzinfo is None:
            raise WorldError("Boundary timestamps must be timezone-aware.")
        if self.available_time < self.effective_time:
            raise WorldError("Boundary availability cannot precede effective time.")
        if type(self.scheduled_market_minutes) is not int or self.scheduled_market_minutes < 0:
            raise WorldError("Scheduled market minutes must be nonnegative.")
        sequences = [event.boundary.sequence for event in self.events]
        if len(sequences) != len(set(sequences)):
            raise WorldError("Within-boundary event sequences must be unique.")
        if tuple(sequences) != tuple(sorted(sequences)):
            raise WorldError("Boundary events must use deterministic sequence order.")
        for event in self.events:
            if event.event_type == "BOUNDARY_COMPLETE":
                raise WorldError("Archive batches cannot contain their own completion event.")
            if (event.boundary.effective_time, event.boundary.available_time) != (
                self.effective_time, self.available_time
            ):
                raise WorldError("Every event must belong to the declared world boundary.")


class SterileReporter:
    """One-way factual output. It exposes no input method to the world."""

    def __init__(self, sink: WriteOnlyReportSink) -> None:
        self._sink = sink
        self.next_cadence_minutes = REPORT_CADENCE_MINUTES
        self.report_count = 0

    def after_completion(self, world: WildcardWorld) -> None:
        terminal = world.status is not WorldStatus.ACTIVE
        if not terminal and world.scheduled_market_minutes < self.next_cadence_minutes:
            return
        try:
            equity = world.equity()
            reconciliation_problem = None
        except WorldError as exc:
            equity = None
            reconciliation_problem = str(exc)
        realizable = sum(
            (quantity * world.last_marks[asset][0] for asset, quantity in world.positions.items()
             if asset in world.last_marks and world.last_marks[asset][1]),
            start=world.cash * 0,
        )
        stale = sum(
            (quantity * world.last_marks[asset][0] for asset, quantity in world.positions.items()
             if asset in world.last_marks and not world.last_marks[asset][1]),
            start=world.cash * 0,
        )
        core = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "development_state": "DEVELOPMENT_ONLY",
            "world_id": world.world_id,
            "world_fingerprint": world.world_fingerprint,
            "causal_boundary": world.current_event.boundary.payload() if world.current_event else None,
            "completed_boundary_id": world.last_completed_boundary_id,
            "completed_boundary_count": world.completed_boundary_count,
            "scheduled_market_minutes": world.scheduled_market_minutes,
            "cash": _text(world.cash),
            "realizable_value": _text(realizable),
            "stale_nonrealizable_value": _text(stale),
            "liabilities": _text(world.liabilities),
            "equity": _text(equity) if equity is not None else None,
            "positions": {key: _text(value) for key, value in sorted(world.positions.items())},
            "pending_order_count": len(world.pending),
            "fill_count": len(world.fills),
            "reward_count": len(world.rewards),
            "status": world.status.value,
            "reconciliation_problem": reconciliation_problem,
            "audit_tip": world.audit_tip,
            "reward_policy_fingerprint": (
                world.reward_policy.reward_policy_fingerprint if world.reward_policy else None
            ),
            "authority": {"promotion": "NONE", "live": "NONE", "broker": "NONE", "capital": "NONE"},
        }
        self._sink.append({**core, "report_fingerprint": fingerprint(core)})
        self.report_count += 1
        self.next_cadence_minutes = (
            world.scheduled_market_minutes // REPORT_CADENCE_MINUTES + 1
        ) * REPORT_CADENCE_MINUTES


class DevelopmentBoundaryDriver:
    """Archive-owning driver; Wildcard receives only its event stream."""

    def __init__(self, *, world: WildcardWorld, checkpoint_directory: Path,
                 reporter: SterileReporter | None = None) -> None:
        self.world = world
        self.checkpoint_directory = Path(checkpoint_directory)
        self.reporter = reporter

    def _persist(self) -> None:
        world_fingerprint = self.world.checkpoint(self.checkpoint_directory)
        core = {
            "schema_version": DRIVER_SCHEMA_VERSION,
            "semantic_version": DRIVER_SEMANTIC_VERSION,
            "world_fingerprint": self.world.world_fingerprint,
            "world_checkpoint_fingerprint": world_fingerprint,
            "completed_boundary_count": self.world.completed_boundary_count,
            "last_completed_boundary_id": self.world.last_completed_boundary_id,
            "open_boundary_id": self.world.open_boundary_id,
            "open_boundary_event_ids": list(self.world.open_boundary_event_ids),
            "development_state": "DEVELOPMENT_ONLY",
            "authority": {"promotion": "NONE", "live": "NONE", "broker": "NONE", "capital": "NONE"},
        }
        payload = {**core, "driver_checkpoint_fingerprint": fingerprint(core)}
        write_checksummed_state(
            self.checkpoint_directory / "driver_state.json",
            self.checkpoint_directory / "driver_state.sha256",
            _canon(payload),
        )

    def deliver_boundary(self, batch: BoundaryBatch) -> None:
        if batch.boundary_id == self.world.last_completed_boundary_id:
            raise WorldError("Boundary was already completed.")
        if self.world.open_boundary_id not in (None, batch.boundary_id):
            raise WorldError("Driver cannot skip an unfinished boundary.")
        completed_ids = set(self.world.open_boundary_event_ids)
        for source_event in batch.events:
            event = replace(source_event, world_boundary_id=batch.boundary_id)
            if event.event_id in completed_ids:
                continue
            self.world.observe(event)
            self._persist()
            if self.world.status is not WorldStatus.ACTIVE:
                if self.reporter:
                    self.reporter.after_completion(self.world)
                return
        completion_sequence = max((event.boundary.sequence for event in batch.events), default=-1) + 1
        completion = MarketEvent(
            event_id=f"boundary-complete:{batch.boundary_id}",
            boundary=CausalBoundary(batch.effective_time, batch.available_time, completion_sequence),
            event_type="BOUNDARY_COMPLETE",
            payload={"scheduled_market_minutes": batch.scheduled_market_minutes},
            world_boundary_id=batch.boundary_id,
        )
        self.world.observe(completion)
        self._persist()
        if self.reporter:
            self.reporter.after_completion(self.world)

    def handoff_to_forward(self, source_identity: str) -> None:
        if self.world.open_boundary_id is not None:
            raise WorldError("Cannot hand off with an incomplete world boundary.")
        self.world.gateway.handoff(source_identity)
        self._persist()
