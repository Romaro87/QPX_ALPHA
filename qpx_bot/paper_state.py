"""Atomic paper-account persistence, locking, and audit integrity."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
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


def write_checksummed_state(
    state_path: Path,
    checksum_path: Path,
    encoded: bytes,
) -> None:
    """Persist an encoded state using the established QPX temp/fsync/replace contract."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    checksum = _sha256_bytes(encoded)
    state_temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    checksum_temporary = checksum_path.with_suffix(checksum_path.suffix + ".tmp")
    with state_temporary.open("wb") as file:
        file.write(encoded)
        file.flush()
        os.fsync(file.fileno())
    with checksum_temporary.open("w", encoding="utf-8") as file:
        file.write(checksum + "\n")
        file.flush()
        os.fsync(file.fileno())
    state_temporary.replace(state_path)
    checksum_temporary.replace(checksum_path)


def read_checksummed_state(
    state_path: Path,
    checksum_path: Path,
    *,
    label: str = "Paper state",
) -> bytes:
    if not state_path.exists():
        raise FileNotFoundError(f"{label} was not found: {state_path}")
    if not checksum_path.exists():
        raise RuntimeError(f"{label} checksum is missing.")
    encoded = state_path.read_bytes()
    expected = checksum_path.read_text(encoding="utf-8").strip()
    if _sha256_bytes(encoded) != expected:
        raise RuntimeError(
            f"{label} checksum mismatch. Runtime state may be incomplete or corrupted."
        )
    return encoded


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("Cannot establish lock-owner boot identity.") from exc


def _process_start_ticks(pid: int) -> int | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RuntimeError(f"Cannot establish process identity for lock owner pid={pid}.") from exc
    closing = raw.rfind(")")
    fields = raw[closing + 2:].split() if closing >= 0 else []
    if len(fields) <= 19:
        raise RuntimeError(f"Malformed process identity for lock owner pid={pid}.")
    return int(fields[19])


def _read_lock_owner(lock_path: Path) -> dict[str, Any] | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if raw.isdigit():
        return {"pid": int(raw), "legacy_pid_only": True}
    try:
        owner = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Lock owner identity is malformed; refusing unsafe recovery.") from exc
    if not isinstance(owner, dict) or "pid" not in owner:
        raise RuntimeError("Lock owner identity is incomplete; refusing unsafe recovery.")
    if not {"process_start_ticks", "boot_id", "token"}.issubset(owner):
        return {**owner, "legacy_pid_only": True}
    return owner


def _lock_owner_is_live(owner: Mapping[str, Any]) -> bool:
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Lock owner pid is invalid; refusing unsafe recovery.") from exc
    if pid <= 0:
        raise RuntimeError("Lock owner pid is invalid; refusing unsafe recovery.")
    actual_start = _process_start_ticks(pid)
    if actual_start is None:
        return False
    if owner.get("legacy_pid_only"):
        return True
    if str(owner.get("boot_id")) != _boot_id():
        return False
    try:
        expected_start = int(owner["process_start_ticks"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("Lock owner process identity is invalid; refusing unsafe recovery.") from exc
    return actual_start == expected_start


@contextmanager
def runtime_lock(lock_path: str | Path) -> Iterator[None]:
    """Own one QPX runtime with live/dead process identity and safe stale recovery."""
    path = Path(lock_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    guard = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    owner = {
        "schema_version": 1,
        "pid": os.getpid(),
        "process_start_ticks": _process_start_ticks(os.getpid()),
        "boot_id": _boot_id(),
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "token": secrets.token_hex(32),
    }
    try:
        fcntl.flock(guard, fcntl.LOCK_EX)
        existing = _read_lock_owner(path)
        if existing is not None:
            if _lock_owner_is_live(existing):
                raise RuntimeError(
                    "Another QPX paper runner is active "
                    f"(owner pid={existing.get('pid', 'unknown')}). Lock file: {path}"
                )
            path.unlink()
        temporary = path.with_name(
            f".{path.name}.{owner['pid']}.{owner['token']}.tmp"
        )
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            encoded_owner = (_canonical_json(owner) + "\n").encode("utf-8")
            if os.write(descriptor, encoded_owner) != len(encoded_owner):
                raise OSError("Incomplete lock-owner identity write.")
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.link(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
    finally:
        fcntl.flock(guard, fcntl.LOCK_UN)
        os.close(guard)
    try:
        yield
    finally:
        guard = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(guard, fcntl.LOCK_EX)
            existing = _read_lock_owner(path)
            if existing is not None and existing.get("token") == owner["token"]:
                path.unlink()
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)
            os.close(guard)


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
        encoded = (
            json.dumps(
                state.to_dict(),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
        write_checksummed_state(self.state_path, self.checksum_path, encoded)

    def load(self) -> PaperState:
        encoded = read_checksummed_state(self.state_path, self.checksum_path)

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
        del stale_after_seconds
        with runtime_lock(self.lock_path):
            yield

    def activate_kill_switch(
        self,
        reason: str,
        *,
        owner: str = "manual",
    ) -> None:
        normalized_reason = reason.strip() or "manual"
        normalized_owner = owner.strip() or "manual"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.write_text(
            json.dumps(
                {
                    "activated_utc": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "reason": normalized_reason,
                    "owner": normalized_owner,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    def kill_switch_details(
        self,
    ) -> Mapping[str, Any] | None:
        if not self.kill_switch_path.exists():
            return None

        raw = self.kill_switch_path.read_text(
            encoding="utf-8"
        ).strip()

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = None

        if isinstance(payload, Mapping):
            reason = str(
                payload.get("reason", "")
            ).strip()
            owner = str(
                payload.get("owner", "")
            ).strip()

            if not owner:
                if reason == (
                    "QPX automated operations circuit breaker"
                ):
                    owner = "operations_circuit_breaker"
                elif (
                    reason.startswith(
                        "Restored from verified backup"
                    )
                    or reason.startswith(
                        "QPX recovery restore"
                    )
                ):
                    owner = "restore_guard"
                else:
                    owner = "manual_or_legacy"

            return {
                "activated_utc": (
                    str(payload.get("activated_utc"))
                    if payload.get("activated_utc")
                    else None
                ),
                "reason": reason or "unspecified",
                "owner": owner,
            }

        owner = (
            "restore_guard"
            if (
                raw.startswith(
                    "Restored from verified backup"
                )
                or raw.startswith(
                    "QPX recovery restore"
                )
            )
            else "manual_or_legacy"
        )
        return {
            "activated_utc": None,
            "reason": raw or "unspecified",
            "owner": owner,
        }

    def deactivate_kill_switch(
        self,
        *,
        expected_owner: str | None = None,
    ) -> bool:
        if not self.kill_switch_path.exists():
            return False

        if expected_owner is not None:
            details = self.kill_switch_details()
            actual_owner = (
                str(details.get("owner"))
                if details
                else ""
            )

            if actual_owner != expected_owner:
                return False

        self.kill_switch_path.unlink(missing_ok=True)
        return True

    def kill_switch_active(self) -> bool:
        return self.kill_switch_path.exists()
