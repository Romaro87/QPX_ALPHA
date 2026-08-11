"""Strict-causal dividend entitlement and cash-settlement accounting."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class IncompleteDividendMetadata(ValueError):
    """A dividend cannot be settled causally from the available metadata."""


def _optional_date(raw_value: str | None) -> date | None:
    value = str(raw_value or "").strip()
    return date.fromisoformat(value[:10]) if value else None


@dataclass(frozen=True, slots=True)
class CausalDividendEvent:
    event_id: str
    ex_date: date
    cash_amount: float
    record_date: date | None = None
    payable_date: date | None = None
    process_date: date | None = None

    def validate(self) -> None:
        if not self.event_id:
            raise ValueError("Dividend event ID cannot be empty.")
        if not math.isfinite(self.cash_amount) or self.cash_amount <= 0:
            raise ValueError("Dividend cash amount must be positive and finite.")
        if self.record_date is not None and self.record_date < self.ex_date:
            raise ValueError("Dividend record date precedes ex-date.")
        for name, value in (
            ("payable", self.payable_date),
            ("process", self.process_date),
        ):
            if value is not None and value < self.ex_date:
                raise ValueError(f"Dividend {name} date precedes ex-date.")

    @property
    def cash_available_date(self) -> date:
        """Conservative first usable date: the later payable/process date."""
        self.validate()
        settlement_dates = tuple(
            value
            for value in (self.payable_date, self.process_date)
            if value is not None
        )
        if not settlement_dates:
            raise IncompleteDividendMetadata(
                f"Dividend {self.event_id} has neither payable nor process date."
            )
        return max(settlement_dates)


@dataclass(frozen=True, slots=True)
class DividendEntitlement:
    event_id: str
    ex_date: date
    entitled_shares: float
    cash_amount_per_share: float
    cash_available_date: date

    @property
    def cash_amount(self) -> float:
        return self.entitled_shares * self.cash_amount_per_share


class CausalDividendLedger:
    """Capture ex-date ownership, then release cash only on settlement."""

    def __init__(self, events: list[CausalDividendEvent]) -> None:
        self._events_by_ex_date: dict[date, list[CausalDividendEvent]] = {}
        for event in events:
            event.validate()
            event.cash_available_date
            self._events_by_ex_date.setdefault(event.ex_date, []).append(event)
        self._entitlements: dict[str, DividendEntitlement] = {}
        self._settled: set[str] = set()

    @property
    def entitlement_count(self) -> int:
        return len(self._entitlements)

    @property
    def settled_count(self) -> int:
        return len(self._settled)

    def process_open(self, *, current_date: date, income_shares: float) -> float:
        """Capture today's entitlement and settle due prior entitlements."""
        if income_shares < 0:
            raise ValueError("Income shares cannot be negative.")

        for event in self._events_by_ex_date.get(current_date, ()):
            if event.event_id in self._entitlements:
                continue
            self._entitlements[event.event_id] = DividendEntitlement(
                event_id=event.event_id,
                ex_date=event.ex_date,
                entitled_shares=income_shares,
                cash_amount_per_share=event.cash_amount,
                cash_available_date=event.cash_available_date,
            )

        cash = 0.0
        for event_id, entitlement in self._entitlements.items():
            if event_id in self._settled:
                continue
            if entitlement.cash_available_date <= current_date:
                cash += entitlement.cash_amount
                self._settled.add(event_id)
        return cash


def load_causal_dividends(path: str | Path) -> list[CausalDividendEvent]:
    """Load the enriched Alpaca corporate-action cache for strict replay."""
    source = Path(path)
    events: list[CausalDividendEvent] = []
    with source.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        required = {"EventId", "ExDividendDate", "CashAmount"}
        fields = set(reader.fieldnames or ())
        if not required.issubset(fields):
            raise ValueError(
                f"Dividend CSV is missing required columns: {sorted(required - fields)}"
            )
        for line_number, row in enumerate(reader, start=2):
            try:
                event = CausalDividendEvent(
                    event_id=str(row["EventId"]).strip(),
                    ex_date=date.fromisoformat(str(row["ExDividendDate"])[:10]),
                    cash_amount=float(row["CashAmount"]),
                    record_date=_optional_date(row.get("RecordDate")),
                    payable_date=_optional_date(row.get("PayableDate")),
                    process_date=_optional_date(row.get("ProcessDate")),
                )
                event.validate()
                event.cash_available_date
            except (KeyError, TypeError, ValueError) as exc:
                if isinstance(exc, IncompleteDividendMetadata):
                    raise
                raise ValueError(
                    f"Invalid causal dividend metadata on CSV line {line_number}: {exc}"
                ) from exc
            events.append(event)

    deduplicated = {event.event_id: event for event in events}
    return sorted(
        deduplicated.values(),
        key=lambda event: (event.ex_date, event.event_id),
    )
