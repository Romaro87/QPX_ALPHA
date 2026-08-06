"""Atomic paper-account persistence, locking, and audit integrity."""

from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping


STATE_SCHEMA_VERSION = 1


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


@dataclass(slots=True)
class PendingEntry:
    order_id: str
    symbol: str
    signal_date: date
    signal_atr: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["signal_date"] = self.signal_date.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PendingEntry":
        return cls(
            order_id=str(payload["order_id"]),
            symbol=str(payload["symbol"]),
            signal_date=date.fromisoformat(
                str(payload["signal_date"])
            ),
            signal_atr=float(payload["signal_atr"]),
        )


@dataclass(slots=True)
class PersistentPosition:
    symbol: str
    shares: int
    entry_date: date
    entry_price: float
    entry_atr: float
    stop_price: float
    target_price: float
    highest_price: float

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entry_date"] = self.entry_date.isoformat()
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "PersistentPosition":
        return cls(
            symbol=str(payload["symbol"]),
            shares=int(payload["shares"]),
            entry_date=date.fromisoformat(
                str(payload["entry_date"])
            ),
            entry_price=float(payload["entry_price"]),
            entry_atr=float(payload["entry_atr"]),
            stop_price=float(payload["stop_price"]),
            target_price=float(payload["target_price"]),
            highest_price=float(payload["highest_price"]),
        )


@dataclass(slots=True)
class PaperState:
    state_id: str
    swing_symbol: str
    income_symbol: str
    start_date: date
    starting_cash: float
    swing_cash: float
    tax_reserve_cash: float
    total_contributions: float
    realized_pnl: float
    income_shares: float
    income_cost: float
    dividends_received: float
    last_processed_date: date | None = None
    last_contribution_month: str | None = None
    position: PersistentPosition | None = None
    pending_entry: PendingEntry | None = None
    completed_order_keys: list[str] = field(default_factory=list)
    processed_dividend_keys: list[str] = field(default_factory=list)
    trade_results_r: list[float] = field(default_factory=list)
    revision: int = 0
    schema_version: int = STATE_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != STATE_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported paper-state schema version: "
                f"{self.schema_version}"
            )

        if not self.state_id.strip():
            raise ValueError("Paper state ID cannot be empty.")

        if not self.swing_symbol.strip() or not self.income_symbol.strip():
            raise ValueError("Paper symbols cannot be empty.")

        nonnegative = {
            "starting cash": self.starting_cash,
            "swing cash": self.swing_cash,
            "tax reserve": self.tax_reserve_cash,
            "total contributions": self.total_contributions,
            "income shares": self.income_shares,
            "income cost": self.income_cost,
            "dividends received": self.dividends_received,
        }

        for name, value in nonnegative.items():
            if value < -1e-9:
                raise ValueError(f"{name.capitalize()} cannot be negative.")

        if self.total_contributions + 1e-9 < self.starting_cash:
            raise ValueError(
                "Total contributions cannot be below starting cash."
            )

        if self.revision < 0:
            raise ValueError("State revision cannot be negative.")

        if self.position is not None:
            if self.position.shares <= 0:
                raise ValueError("Open position shares must be positive.")
            if self.position.entry_price <= 0:
                raise ValueError("Position entry price must be positive.")
            if self.position.entry_atr <= 0:
                raise ValueError("Position ATR must be positive.")
            if self.pending_entry is not None:
                raise ValueError(
                    "An entry cannot be pending while a position is open."
                )

        if self.pending_entry is not None:
            if self.pending_entry.signal_atr <= 0:
                raise ValueError("Pending-entry ATR must be positive.")

        if len(self.completed_order_keys) != len(
            set(self.completed_order_keys)
        ):
            raise ValueError("Completed order keys contain duplicates.")

        if len(self.processed_dividend_keys) != len(
            set(self.processed_dividend_keys)
        ):
            raise ValueError("Dividend keys contain duplicates.")

    def equity(
        self,
        *,
        swing_price: float,
        income_price: float,
    ) -> float:
        if swing_price <= 0 or income_price <= 0:
            raise ValueError("Mark prices must be positive.")

        swing_value = (
            self.position.shares * swing_price
            if self.position is not None
            else 0.0
        )
        income_value = self.income_shares * income_price

        return (
            self.swing_cash
            + self.tax_reserve_cash
            + swing_value
            + income_value
        )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "swing_symbol": self.swing_symbol,
            "income_symbol": self.income_symbol,
            "start_date": self.start_date.isoformat(),
            "starting_cash": self.starting_cash,
            "swing_cash": self.swing_cash,
            "tax_reserve_cash": self.tax_reserve_cash,
            "total_contributions": self.total_contributions,
            "realized_pnl": self.realized_pnl,
            "income_shares": self.income_shares,
            "income_cost": self.income_cost,
            "dividends_received": self.dividends_received,
            "last_processed_date": (
                self.last_processed_date.isoformat()
                if self.last_processed_date
                else None
            ),
            "last_contribution_month": (
                self.last_contribution_month
            ),
            "position": (
                self.position.to_dict()
                if self.position
                else None
            ),
            "pending_entry": (
                self.pending_entry.to_dict()
                if self.pending_entry
                else None
            ),
            "completed_order_keys": list(
                self.completed_order_keys
            ),
            "processed_dividend_keys": list(
                self.processed_dividend_keys
            ),
            "trade_results_r": list(self.trade_results_r),
            "revision": self.revision,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "PaperState":
        position_payload = payload.get("position")
        pending_payload = payload.get("pending_entry")

        state = cls(
            schema_version=int(
                payload.get(
                    "schema_version",
                    STATE_SCHEMA_VERSION,
                )
            ),
            state_id=str(payload["state_id"]),
            swing_symbol=str(payload["swing_symbol"]),
            income_symbol=str(payload["income_symbol"]),
            start_date=date.fromisoformat(
                str(payload["start_date"])
            ),
            starting_cash=float(payload["starting_cash"]),
            swing_cash=float(payload["swing_cash"]),
            tax_reserve_cash=float(
                payload["tax_reserve_cash"]
            ),
            total_contributions=float(
                payload["total_contributions"]
            ),
            realized_pnl=float(payload["realized_pnl"]),
            income_shares=float(payload["income_shares"]),
            income_cost=float(payload["income_cost"]),
            dividends_received=float(
                payload["dividends_received"]
            ),
            last_processed_date=_parse_date(
                payload.get("last_processed_date")
            ),
            last_contribution_month=(
                str(payload["last_contribution_month"])
                if payload.get("last_contribution_month")
                else None
            ),
            position=(
                PersistentPosition.from_dict(position_payload)
                if isinstance(position_payload, Mapping)
                else None
            ),
            pending_entry=(
                PendingEntry.from_dict(pending_payload)
                if isinstance(pending_payload, Mapping)
                else None
            ),
            completed_order_keys=[
                str(value)
                for value in payload.get(
                    "completed_order_keys",
                    [],
                )
            ],
            processed_dividend_keys=[
                str(value)
                for value in payload.get(
                    "processed_dividend_keys",
                    [],
                )
            ],
            trade_results_r=[
                float(value)
                for value in payload.get(
                    "trade_results_r",
                    [],
                )
            ],
            revision=int(payload.get("revision", 0)),
        )
        state.validate()
        return state


@dataclass(frozen=True, slots=True)
class AuditEvent:
    event_id: str
    event_type: str
    event_date: date
    details: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_date": self.event_date.isoformat(),
            "details": dict(self.details),
        }


class StateStore:
    """Own the atomic state, kill switch, lock, and hash-chain journal."""

    def __init__(self, runtime_directory: str | Path) -> None:
        self.directory = Path(
            runtime_directory
        ).expanduser().resolve()
        self.state_path = self.directory / "paper_state.json"
        self.checksum_path = (
            self.directory / "paper_state.sha256"
        )
        self.journal_path = (
            self.directory / "paper_audit.jsonl"
        )
        self.lock_path = self.directory / "paper.lock"
        self.kill_switch_path = (
            self.directory / "KILL_SWITCH"
        )

    def exists(self) -> bool:
        return self.state_path.exists()

    def save(self, state: PaperState) -> None:
        state.validate()
        self.directory.mkdir(parents=True, exist_ok=True)
        encoded = (
            json.dumps(
                state.to_dict(),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        checksum = _sha256_bytes(encoded)

        state_temporary = self.state_path.with_suffix(
            ".json.tmp"
        )
        checksum_temporary = self.checksum_path.with_suffix(
            ".sha256.tmp"
        )

        with state_temporary.open("wb") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())

        with checksum_temporary.open(
            "w",
            encoding="utf-8",
        ) as file:
            file.write(checksum + "\n")
            file.flush()
            os.fsync(file.fileno())

        state_temporary.replace(self.state_path)
        checksum_temporary.replace(self.checksum_path)

    def load(self) -> PaperState:
        if not self.state_path.exists():
            raise FileNotFoundError(
                f"Paper state was not found: {self.state_path}"
            )

        if not self.checksum_path.exists():
            raise RuntimeError(
                "Paper state checksum is missing."
            )

        encoded = self.state_path.read_bytes()
        expected = self.checksum_path.read_text(
            encoding="utf-8"
        ).strip()
        actual = _sha256_bytes(encoded)

        if actual != expected:
            raise RuntimeError(
                "Paper state checksum mismatch. Runtime state "
                "may be incomplete or corrupted."
            )

        payload = json.loads(encoded.decode("utf-8"))

        if not isinstance(payload, Mapping):
            raise RuntimeError("Paper state root must be an object.")

        return PaperState.from_dict(payload)

    def journal_event_ids(self) -> set[str]:
        event_ids, _, _ = self.verify_journal()
        return event_ids

    def append_events(
        self,
        events: list[AuditEvent],
    ) -> int:
        if not events:
            return 0

        self.directory.mkdir(parents=True, exist_ok=True)
        event_ids, previous_hash, sequence = (
            self.verify_journal()
        )
        appended = 0

        with self.journal_path.open(
            "a",
            encoding="utf-8",
        ) as file:
            for event in events:
                if event.event_id in event_ids:
                    continue

                base_record = {
                    "sequence": sequence + 1,
                    "timestamp_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "previous_hash": previous_hash,
                    **event.payload(),
                }
                record_hash = hashlib.sha256(
                    _canonical_json(base_record).encode(
                        "utf-8"
                    )
                ).hexdigest()
                record = {
                    **base_record,
                    "record_hash": record_hash,
                }
                file.write(_canonical_json(record) + "\n")
                file.flush()
                os.fsync(file.fileno())

                event_ids.add(event.event_id)
                previous_hash = record_hash
                sequence += 1
                appended += 1

        return appended

    def verify_journal(
        self,
    ) -> tuple[set[str], str, int]:
        if not self.journal_path.exists():
            return set(), "", 0

        event_ids: set[str] = set()
        previous_hash = ""
        expected_sequence = 1

        for line_number, raw_line in enumerate(
            self.journal_path.read_text(
                encoding="utf-8"
            ).splitlines(),
            start=1,
        ):
            if not raw_line.strip():
                continue

            record = json.loads(raw_line)

            if not isinstance(record, dict):
                raise RuntimeError(
                    f"Audit line {line_number} is not an object."
                )

            record_hash = str(
                record.pop("record_hash", "")
            )
            calculated = hashlib.sha256(
                _canonical_json(record).encode("utf-8")
            ).hexdigest()

            if calculated != record_hash:
                raise RuntimeError(
                    f"Audit hash mismatch on line {line_number}."
                )

            if record.get("previous_hash") != previous_hash:
                raise RuntimeError(
                    "Audit hash chain is broken on line "
                    f"{line_number}."
                )

            if int(record.get("sequence", -1)) != expected_sequence:
                raise RuntimeError(
                    "Audit sequence mismatch on line "
                    f"{line_number}."
                )

            event_id = str(record.get("event_id", ""))

            if not event_id or event_id in event_ids:
                raise RuntimeError(
                    "Audit event ID is empty or duplicated on line "
                    f"{line_number}."
                )

            event_ids.add(event_id)
            previous_hash = record_hash
            expected_sequence += 1

        return (
            event_ids,
            previous_hash,
            expected_sequence - 1,
        )

    @contextmanager
    def locked(
        self,
        *,
        stale_after_seconds: float = 21_600.0,
    ) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)

        for attempt in range(2):
            try:
                descriptor = os.open(
                    self.lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
                with os.fdopen(
                    descriptor,
                    "w",
                    encoding="utf-8",
                ) as file:
                    file.write(
                        json.dumps(
                            {
                                "pid": os.getpid(),
                                "created_utc": datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            }
                        )
                    )
                break
            except FileExistsError:
                age = (
                    time.time()
                    - self.lock_path.stat().st_mtime
                )
                if (
                    attempt == 0
                    and age > stale_after_seconds
                ):
                    self.lock_path.unlink(missing_ok=True)
                    continue

                raise RuntimeError(
                    "Another QPX paper runner is active. "
                    f"Lock file: {self.lock_path}"
                )
        else:
            raise RuntimeError("Unable to acquire paper lock.")

        try:
            yield
        finally:
            self.lock_path.unlink(missing_ok=True)

    def activate_kill_switch(self, reason: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.write_text(
            json.dumps(
                {
                    "activated_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "reason": reason.strip() or "manual",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def deactivate_kill_switch(self) -> None:
        self.kill_switch_path.unlink(missing_ok=True)

    def kill_switch_active(self) -> bool:
        return self.kill_switch_path.exists()
