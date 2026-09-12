"""Deterministic, sterile Wildcard V1 market/account world.

The archive driver owns history.  This module accepts exactly one causal event
at a time and exposes no archive-navigation API or broker authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping, Protocol

from qpx_bot.causal_replay import CausalAccessError
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state
from qpx_bot.wildcard.reward_policy import ApprovedRewardPolicy


WORLD_SCHEMA_VERSION = 1
WORLD_SEMANTIC_VERSION = "ADR-0012_WILDCARD_WORLD_V1"
STATE_SCHEMA_VERSION = 1
STARTING_CASH = Decimal("100000.00")
INTERNAL_QUANTUM = Decimal("0.00000001")
CASH_QUANTUM = Decimal("0.01")
QUANTITY_QUANTUM = Decimal("0.001")
MINIMUM_NOTIONAL = Decimal("1.00")
PARTICIPATION_RATE = Decimal("0.01")
SLIPPAGE_RATE = Decimal("0.0005")
ROUNDING = ROUND_HALF_EVEN


class WorldError(RuntimeError):
    pass


class ActionType(StrEnum):
    NO_ACTION = "NO_ACTION"
    BUY = "BUY"
    SELL = "SELL"
    CANCEL = "CANCEL"
    REPLACE = "REPLACE"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class WorldStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ACCOUNT_RECONCILIATION_BLOCKED = "ACCOUNT_RECONCILIATION_BLOCKED"
    FAILED_BANKRUPTCY = "FAILED_BANKRUPTCY"
    ECONOMIC_DEAD_END = "ECONOMIC_DEAD_END"
    HISTORICAL_COMPLETE = "HISTORICAL_COMPLETE"


def _canon(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(_canon(value)).hexdigest()


def _d(value: Decimal | str | int) -> Decimal:
    if isinstance(value, bool):
        raise WorldError("Boolean is not a valid economic number.")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except Exception as exc:
        raise WorldError("Invalid economic number.") from exc
    if not number.is_finite():
        raise WorldError("Economic numbers must be finite.")
    return number


def _internal(value: Decimal) -> Decimal:
    return value.quantize(INTERNAL_QUANTUM, rounding=ROUNDING)


def _cash(value: Decimal) -> Decimal:
    return value.quantize(CASH_QUANTUM, rounding=ROUNDING)


def _text(value: Decimal) -> str:
    return format(value, "f")


@dataclass(frozen=True, order=True, slots=True)
class CausalBoundary:
    effective_time: datetime
    available_time: datetime
    sequence: int

    def __post_init__(self) -> None:
        if self.effective_time.tzinfo is None or self.available_time.tzinfo is None:
            raise WorldError("Causal boundary timestamps must be timezone-aware.")
        if self.available_time < self.effective_time:
            raise WorldError("Information cannot be available before its effective time.")
        if type(self.sequence) is not int or self.sequence < 0:
            raise WorldError("Causal sequence must be nonnegative.")

    def payload(self) -> dict[str, Any]:
        return {"effective_time": self.effective_time.isoformat(),
                "available_time": self.available_time.isoformat(), "sequence": self.sequence}


@dataclass(frozen=True, slots=True)
class MarketEvent:
    event_id: str
    boundary: CausalBoundary
    event_type: str
    provider_asset_id: str | None = None
    session_date: date | None = None
    open_price: Decimal | None = None
    close_price: Decimal | None = None
    volume: int | None = None
    regular_session_end: bool = False
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.event_id.strip():
            raise WorldError("Event identity cannot be empty.")
        if self.event_type == "BAR":
            if not self.provider_asset_id or self.session_date is None:
                raise WorldError("Bar requires stable asset identity and session date.")
            if self.open_price is None or self.close_price is None or min(self.open_price, self.close_price) <= 0:
                raise WorldError("Bar prices must be positive.")
            if type(self.volume) is not int or self.volume < 0:
                raise WorldError("Bar volume must be a nonnegative integer.")

    @property
    def identity(self) -> str:
        return fingerprint(self.as_dict())

    def as_dict(self) -> dict[str, Any]:
        return {"event_id": self.event_id, "boundary": self.boundary.payload(),
                "event_type": self.event_type, "provider_asset_id": self.provider_asset_id,
                "session_date": self.session_date.isoformat() if self.session_date else None,
                "open_price": _text(self.open_price) if self.open_price is not None else None,
                "close_price": _text(self.close_price) if self.close_price is not None else None,
                "volume": self.volume, "regular_session_end": self.regular_session_end,
                "payload": dict(self.payload)}


class WriteOnlyArchiveSink(Protocol):
    def append(self, record: Mapping[str, Any]) -> None: ...


class CausalGateway:
    """One-event ingress. It intentionally has no archive read/list/search method."""

    def __init__(self, source_identity: str) -> None:
        if not source_identity.strip():
            raise WorldError("Event source identity cannot be empty.")
        self.source_identity = source_identity
        self._last_boundary: CausalBoundary | None = None
        self._seen: set[str] = set()

    def deliver(self, event: MarketEvent) -> MarketEvent:
        if event.event_id in self._seen:
            raise WorldError("Duplicate causal event identity.")
        if self._last_boundary is not None and event.boundary <= self._last_boundary:
            raise CausalAccessError("Causal events must be strictly forward-only.")
        self._seen.add(event.event_id)
        self._last_boundary = event.boundary
        return event

    def handoff(self, source_identity: str) -> None:
        if not source_identity.strip() or source_identity == self.source_identity:
            raise WorldError("Forward source handoff requires a distinct identity.")
        self.source_identity = source_identity


@dataclass(frozen=True, slots=True)
class Action:
    kind: ActionType
    provider_asset_id: str | None = None
    quantity: Decimal | None = None
    order_id: str | None = None
    fractional_eligibility_fingerprint: str | None = None


@dataclass(slots=True)
class Order:
    order_id: str
    side: OrderSide
    provider_asset_id: str
    remaining: Decimal
    sequence: int
    created_boundary: CausalBoundary
    session_date: date

    def as_dict(self) -> dict[str, Any]:
        return {"order_id": self.order_id, "side": self.side.value,
                "provider_asset_id": self.provider_asset_id, "remaining": _text(self.remaining),
                "sequence": self.sequence, "created_boundary": self.created_boundary.payload(),
                "session_date": self.session_date.isoformat()}


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    order_id: str
    provider_asset_id: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    notional: Decimal
    boundary: CausalBoundary


@dataclass(frozen=True, slots=True)
class InstrumentEvidence:
    provider_asset_id: str
    whole_share_eligible: bool = True
    fractional_eligible: bool | None = None
    fractional_evidence_fingerprint: str | None = None


class WildcardWorld:
    """Cash-only long V1 world with no broker, live, capital, or promotion authority."""

    def __init__(self, *, world_id: str, gateway: CausalGateway,
                 instruments: Mapping[str, InstrumentEvidence], archive_sink: WriteOnlyArchiveSink,
                 reward_policy: ApprovedRewardPolicy | None = None) -> None:
        self.world_id = world_id
        self.gateway = gateway
        self.instruments = dict(instruments)
        self.archive_sink = archive_sink
        self.reward_policy = reward_policy
        self.cash = STARTING_CASH
        self.positions: dict[str, Decimal] = {}
        self.pending: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.last_marks: dict[str, tuple[Decimal, bool]] = {}
        self.liabilities = Decimal("0")
        self.status = WorldStatus.ACTIVE
        self.next_sequence = 1
        self.current_event: MarketEvent | None = None
        self.audit_tip = ""
        self.audit_sequence = 0
        self.rewards: list[str] = []
        self.previous_equity = STARTING_CASH
        self.scheduled_market_minutes = 0

    @property
    def world_fingerprint(self) -> str:
        return fingerprint({"schema_version": WORLD_SCHEMA_VERSION,
            "semantic_version": WORLD_SEMANTIC_VERSION, "world_id": self.world_id,
            "starting_cash": _text(STARTING_CASH), "internal_scale": 8,
            "rounding": "ROUND_HALF_EVEN", "cash_scale": 2, "quantity_scale": 3,
            "minimum_notional": _text(MINIMUM_NOTIONAL),
            "participation_rate": _text(PARTICIPATION_RATE),
            "slippage_rate": _text(SLIPPAGE_RATE), "commission": "0",
            "fee_model": "NO_FEE_UNLESS_EXPLICIT_EFFECTIVE_DATED_RULE",
            "action_space": [x.value for x in ActionType],
            "fractional_evidence": sorted((k, v.fractional_eligible,
                v.fractional_evidence_fingerprint) for k, v in self.instruments.items()),
            "reward_policy": self.reward_policy.reward_policy_fingerprint if self.reward_policy else None,
            "authority": {"promotion": "NONE", "live": "NONE", "broker": "NONE", "capital": "NONE"}})

    def _audit(self, kind: str, details: Mapping[str, Any]) -> None:
        base = {"sequence": self.audit_sequence + 1, "previous_hash": self.audit_tip,
                "kind": kind, "details": dict(details),
                "boundary": self.current_event.boundary.payload() if self.current_event else None}
        record = {**base, "record_hash": fingerprint(base)}
        self.archive_sink.append(record)
        self.audit_sequence += 1
        self.audit_tip = record["record_hash"]

    def observe(self, event: MarketEvent) -> None:
        if self.status is not WorldStatus.ACTIVE:
            raise WorldError("Terminal or blocked world cannot advance.")
        event = self.gateway.deliver(event)
        self.current_event = event
        if event.event_type == "BAR":
            self._expire_prior_day(event.session_date)
            self._fill_pending(event)
            self.last_marks[event.provider_asset_id] = (_internal(event.close_price), True)
            self.scheduled_market_minutes += 15
            if event.regular_session_end:
                self._expire_session(event.session_date)
        elif event.event_type == "CORPORATE_ACTION":
            if not event.payload.get("economics_supported", False):
                self.status = WorldStatus.ACCOUNT_RECONCILIATION_BLOCKED
        self._reconcile()
        self._audit("EVENT", {"event_id": event.event_id, "event_identity": event.identity,
                              "status": self.status.value})

    def act(self, action: Action) -> str | None:
        if self.status is not WorldStatus.ACTIVE or self.current_event is None:
            raise WorldError("Action requires an active observed boundary.")
        if action.kind is ActionType.NO_ACTION:
            self._audit("NO_ACTION", {})
            return None
        if action.kind is ActionType.CANCEL:
            return self._cancel(action.order_id)
        if action.kind is ActionType.REPLACE:
            old = self.pending.get(action.order_id or "")
            if old is None:
                raise WorldError("Pending order was not found.")
            replacement = Action(
                ActionType.BUY if old.side is OrderSide.BUY else ActionType.SELL,
                action.provider_asset_id or old.provider_asset_id,
                action.quantity,
                fractional_eligibility_fingerprint=action.fractional_eligibility_fingerprint,
            )
            self._submission_terms(replacement)
            self._cancel(old.order_id)
            return self._submit(replacement)
        return self._submit(action)

    def _submission_terms(
        self, action: Action
    ) -> tuple[str, Decimal, OrderSide]:
        if action.kind not in (ActionType.BUY, ActionType.SELL):
            raise WorldError("Unsupported action.")
        asset = (action.provider_asset_id or "").strip()
        evidence = self.instruments.get(asset)
        if evidence is None or not evidence.whole_share_eligible:
            raise WorldError("Instrument is not eligible in this world.")
        quantity = _d(action.quantity)
        if quantity <= 0 or quantity.quantize(QUANTITY_QUANTUM) != quantity:
            raise WorldError("Quantity must be positive with 0.001-share precision.")
        if quantity != quantity.to_integral_value():
            if evidence.fractional_eligible is not True or not evidence.fractional_evidence_fingerprint:
                raise WorldError("Fractional eligibility is not authoritatively proven.")
            if action.fractional_eligibility_fingerprint != evidence.fractional_evidence_fingerprint:
                raise WorldError("Fractional eligibility evidence mismatch.")
        mark = self.last_marks.get(asset)
        if mark is None or not mark[1]:
            raise WorldError("Causally realizable price is unavailable.")
        if _cash(quantity * mark[0]) < MINIMUM_NOTIONAL:
            raise WorldError("Order notional is below $1.00.")
        side = OrderSide.BUY if action.kind in (ActionType.BUY, ActionType.REPLACE) else OrderSide.SELL
        if side is OrderSide.SELL and quantity > self.positions.get(asset, Decimal("0")):
            raise WorldError("Sell quantity exceeds owned quantity.")
        return asset, quantity, side

    def _submit(self, action: Action) -> str:
        asset, quantity, side = self._submission_terms(action)
        sequence = self.next_sequence
        self.next_sequence += 1
        oid = fingerprint({"world": self.world_id, "sequence": sequence,
                           "boundary": self.current_event.boundary.payload()})
        self.pending[oid] = Order(oid, side, asset, quantity, sequence,
                                  self.current_event.boundary, self.current_event.session_date)
        self._audit("ORDER_SUBMITTED", self.pending[oid].as_dict())
        return oid

    def _cancel(self, order_id: str | None) -> str:
        if not order_id or order_id not in self.pending:
            raise WorldError("Pending order was not found.")
        old = self.pending.pop(order_id)
        self._audit("ORDER_CANCELLED", {"order_id": old.order_id,
                                        "remaining": _text(old.remaining)})
        return old.order_id

    def _fill_pending(self, event: MarketEvent) -> None:
        assert event.provider_asset_id and event.open_price is not None and event.volume is not None
        available = _internal(Decimal(event.volume) * PARTICIPATION_RATE)
        for order in sorted(tuple(self.pending.values()), key=lambda item: item.sequence):
            if order.provider_asset_id != event.provider_asset_id or event.boundary <= order.created_boundary:
                continue
            quantity = min(order.remaining, available)
            if order.side is OrderSide.SELL:
                quantity = min(quantity, self.positions.get(order.provider_asset_id, Decimal("0")))
            adverse = Decimal("1") + SLIPPAGE_RATE if order.side is OrderSide.BUY else Decimal("1") - SLIPPAGE_RATE
            price = _internal(event.open_price * adverse)
            if order.side is OrderSide.BUY:
                affordable = (self.cash / price).quantize(QUANTITY_QUANTUM, rounding="ROUND_DOWN")
                quantity = min(quantity, affordable)
            quantity = quantity.quantize(QUANTITY_QUANTUM, rounding="ROUND_DOWN")
            if quantity <= 0:
                continue
            notional = _cash(quantity * price)
            if order.side is OrderSide.BUY:
                self.cash = _cash(self.cash - notional)
                self.positions[order.provider_asset_id] = _internal(
                    self.positions.get(order.provider_asset_id, Decimal("0")) + quantity)
            else:
                self.cash = _cash(self.cash + notional)
                remaining_position = _internal(self.positions[order.provider_asset_id] - quantity)
                if remaining_position:
                    self.positions[order.provider_asset_id] = remaining_position
                else:
                    del self.positions[order.provider_asset_id]
            order.remaining = _internal(order.remaining - quantity)
            available = _internal(available - quantity)
            fill_id = fingerprint({"order": order.order_id, "event": event.event_id,
                                   "quantity": _text(quantity), "price": _text(price)})
            fill = Fill(fill_id, order.order_id, order.provider_asset_id, order.side,
                        quantity, price, notional, event.boundary)
            self.fills.append(fill)
            self._audit("FILL", {"fill_id": fill_id, "order_id": order.order_id,
                                  "quantity": _text(quantity), "price": _text(price)})
            if order.remaining == 0:
                self.pending.pop(order.order_id)
            if available <= 0:
                break

    def _expire_prior_day(self, current: date) -> None:
        for oid, order in tuple(self.pending.items()):
            if order.session_date < current:
                del self.pending[oid]
                self._audit("ORDER_EXPIRED", {"order_id": oid})

    def _expire_session(self, current: date) -> None:
        for oid, order in tuple(self.pending.items()):
            if order.session_date == current:
                del self.pending[oid]
                self._audit("ORDER_EXPIRED", {"order_id": oid})

    def equity(self) -> Decimal:
        value = self.cash - self.liabilities
        for asset, quantity in self.positions.items():
            mark = self.last_marks.get(asset)
            if mark is None or not mark[1]:
                raise WorldError("Account cannot reconcile a stale/non-realizable holding.")
            value += quantity * mark[0]
        return _cash(value)

    def buying_power(self) -> Decimal:
        return self.cash

    def mark_stale(self, provider_asset_id: str) -> None:
        if provider_asset_id in self.last_marks:
            price, _ = self.last_marks[provider_asset_id]
            self.last_marks[provider_asset_id] = (price, False)

    def _reconcile(self) -> None:
        try:
            equity = self.equity()
        except WorldError:
            self.status = WorldStatus.ACCOUNT_RECONCILIATION_BLOCKED
            return
        if equity <= 0 or self.liabilities > self.cash + max(Decimal("0"), equity - self.cash):
            self.status = WorldStatus.FAILED_BANKRUPTCY
        if self.reward_policy and self.previous_equity > 0 and equity > 0:
            growth = self.reward_policy.content.term("growth").effective_weight
            speed = self.reward_policy.content.term("speed_bonus")
            half = Decimal(speed.parameter_mapping["half_life_scheduled_market_minutes"])
            with localcontext() as ctx:
                ctx.prec = 34
                delta = (equity / self.previous_equity).ln()
                bonus = (-(Decimal(2).ln()) * Decimal(self.scheduled_market_minutes) / half).exp()
                self.rewards.append(_text(_internal(growth * delta + speed.effective_weight * bonus * delta)))
        self.previous_equity = equity

    def declare_economic_dead_end(self, *, permanent_no_transaction_path_proven: bool) -> None:
        if not permanent_no_transaction_path_proven or self.equity() <= 0:
            raise WorldError("Economic dead end requires explicit solvent permanence proof.")
        self.status = WorldStatus.ECONOMIC_DEAD_END

    def complete_history(self) -> None:
        if self.status is not WorldStatus.ACTIVE:
            raise WorldError("Only an active solvent world can complete history.")
        self.status = WorldStatus.HISTORICAL_COMPLETE

    def state_payload(self) -> dict[str, Any]:
        return {"schema_version": STATE_SCHEMA_VERSION, "world_fingerprint": self.world_fingerprint,
                "world_id": self.world_id, "source_identity": self.gateway.source_identity,
                "last_boundary": self.current_event.boundary.payload() if self.current_event else None,
                "last_event": self.current_event.as_dict() if self.current_event else None,
                "cash": _text(self.cash), "positions": {k: _text(v) for k, v in sorted(self.positions.items())},
                "pending": [o.as_dict() for o in sorted(self.pending.values(), key=lambda x: x.sequence)],
                "fills": [{"fill_id": f.fill_id, "order_id": f.order_id,
                    "provider_asset_id": f.provider_asset_id, "side": f.side.value,
                    "quantity": _text(f.quantity), "price": _text(f.price), "notional": _text(f.notional),
                    "boundary": f.boundary.payload()} for f in self.fills],
                "marks": {k: [_text(v[0]), v[1]] for k, v in sorted(self.last_marks.items())},
                "liabilities": _text(self.liabilities), "status": self.status.value,
                "next_sequence": self.next_sequence, "audit_tip": self.audit_tip,
                "audit_sequence": self.audit_sequence, "scheduled_market_minutes": self.scheduled_market_minutes,
                "previous_equity": _text(self.previous_equity), "rewards": list(self.rewards),
                "rng_identity": fingerprint({"world": self.world_id, "purpose": "deterministic_episode_v1"}),
                "authority": {"promotion": "NONE", "live": "NONE", "broker": "NONE", "capital": "NONE"}}

    def checkpoint(self, directory: Path) -> str:
        core = self.state_payload()
        payload = {**core, "checkpoint_fingerprint": fingerprint(core)}
        encoded = _canon(payload)
        directory = Path(directory)
        write_checksummed_state(directory / "world_state.json", directory / "world_state.sha256", encoded)
        return payload["checkpoint_fingerprint"]

    @classmethod
    def restore(cls, directory: Path, *, world_id: str, gateway: CausalGateway,
                instruments: Mapping[str, InstrumentEvidence], archive_sink: WriteOnlyArchiveSink,
                reward_policy: ApprovedRewardPolicy | None = None) -> "WildcardWorld":
        encoded = read_checksummed_state(Path(directory) / "world_state.json",
                                         Path(directory) / "world_state.sha256", label="Wildcard world state")
        payload = json.loads(encoded)
        declared = payload.pop("checkpoint_fingerprint", "")
        if fingerprint(payload) != declared:
            raise WorldError("Wildcard checkpoint fingerprint mismatch.")
        world = cls(world_id=world_id, gateway=gateway, instruments=instruments,
                    archive_sink=archive_sink, reward_policy=reward_policy)
        if payload["world_fingerprint"] != world.world_fingerprint or payload["world_id"] != world_id:
            raise WorldError("Wildcard checkpoint belongs to another world.")
        def boundary(raw: Mapping[str, Any]) -> CausalBoundary:
            return CausalBoundary(datetime.fromisoformat(raw["effective_time"]),
                                  datetime.fromisoformat(raw["available_time"]), int(raw["sequence"]))
        last = payload["last_event"]
        if last:
            b = boundary(last["boundary"])
            world.current_event = MarketEvent(last["event_id"], b, last["event_type"],
                last["provider_asset_id"], date.fromisoformat(last["session_date"]) if last["session_date"] else None,
                _d(last["open_price"]) if last["open_price"] else None,
                _d(last["close_price"]) if last["close_price"] else None,
                last["volume"], last["regular_session_end"], last["payload"])
            gateway._last_boundary = b
            gateway._seen.add(last["event_id"])
        world.cash = _d(payload["cash"]); world.positions = {k: _d(v) for k, v in payload["positions"].items()}
        world.pending = {raw["order_id"]: Order(raw["order_id"], OrderSide(raw["side"]),
            raw["provider_asset_id"], _d(raw["remaining"]), int(raw["sequence"]),
            boundary(raw["created_boundary"]), date.fromisoformat(raw["session_date"])) for raw in payload["pending"]}
        world.fills = [Fill(raw["fill_id"], raw["order_id"], raw["provider_asset_id"],
            OrderSide(raw["side"]), _d(raw["quantity"]), _d(raw["price"]), _d(raw["notional"]),
            boundary(raw["boundary"])) for raw in payload["fills"]]
        world.last_marks = {k: (_d(v[0]), bool(v[1])) for k, v in payload["marks"].items()}
        world.liabilities = _d(payload["liabilities"]); world.status = WorldStatus(payload["status"])
        world.next_sequence = int(payload["next_sequence"]); world.audit_tip = payload["audit_tip"]
        world.audit_sequence = int(payload["audit_sequence"]); world.scheduled_market_minutes = int(payload["scheduled_market_minutes"])
        world.previous_equity = _d(payload["previous_equity"]); world.rewards = list(payload["rewards"])
        return world
