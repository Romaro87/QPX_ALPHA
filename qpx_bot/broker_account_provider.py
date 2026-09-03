"""Canonical, observation-only broker-account provider boundary for QPX.

Broker adapters normalize their native account payloads into
``BrokerAccountSnapshot`` and expose only ``observe``.  They must not submit,
cancel, replace, or otherwise mutate broker orders or positions.  Observation
timestamps represent when QPX received the broker response, never an inferred
earlier effective time.

A future Schwab adapter must implement ``BrokerAccountProvider``, validate and
normalize Schwab account/position responses into the canonical objects below,
fingerprint the account identity without persisting the raw identifier, and
register one factory under the ``SCHWAB`` identity.  Candidate V1, accounting,
market data, execution, reconciliation, and scheduling code must not change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


SCHEMA_VERSION = 1
DUMMY_PROVIDER_IDENTITY = "DUMMY"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identity(value: Any, field: str) -> str:
    normalized = str(value).strip().upper()
    if not normalized or not all(
        character.isalnum() or character in "_-" for character in normalized
    ):
        raise ValueError(f"{field} is invalid.")
    return normalized


def _symbol(value: Any) -> str:
    normalized = str(value).strip().upper()
    if not normalized or any(character.isspace() or ord(character) < 32 for character in normalized):
        raise ValueError("Broker position symbol is invalid.")
    return normalized


def _decimal(value: Any, field: str, *, positive: bool = False) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric.") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError(f"{field} is invalid.")
    return number


def decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _optional_decimal(value: Any, field: str) -> Decimal | None:
    return None if value in (None, "") else _decimal(value, field)


@dataclass(frozen=True, slots=True)
class BrokerPosition:
    symbol: str
    side: str
    quantity: Decimal
    average_entry_price: Decimal
    cost_basis: Decimal | None = None
    market_value: Decimal | None = None
    current_price: Decimal | None = None
    asset_class: str | None = None

    def __post_init__(self) -> None:
        symbol = _symbol(self.symbol)
        side = str(self.side).strip().lower()
        if side not in {"long", "short"}:
            raise ValueError("Broker position side must be long or short.")
        quantity = _decimal(self.quantity, f"{symbol} quantity", positive=True)
        average = _decimal(
            self.average_entry_price,
            f"{symbol} average entry price",
            positive=True,
        )
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "quantity", quantity)
        object.__setattr__(self, "average_entry_price", average)
        for name in ("cost_basis", "market_value", "current_price"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, f"{symbol} {name}"))
        if self.current_price is not None and self.current_price <= 0:
            raise ValueError(f"{symbol} current price must be positive.")
        asset_class = str(self.asset_class).strip() if self.asset_class else None
        object.__setattr__(self, "asset_class", asset_class)

    @property
    def signed_quantity(self) -> Decimal:
        return self.quantity if self.side == "long" else -self.quantity

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": decimal_text(self.signed_quantity),
            "average_entry_price": decimal_text(self.average_entry_price),
            "cost_basis": (
                decimal_text(self.cost_basis) if self.cost_basis is not None else None
            ),
            "market_value": (
                decimal_text(self.market_value) if self.market_value is not None else None
            ),
            "current_price": (
                decimal_text(self.current_price) if self.current_price is not None else None
            ),
            "asset_class": self.asset_class,
        }

    def identity_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": decimal_text(self.signed_quantity),
            "average_entry_price": decimal_text(self.average_entry_price),
            "cost_basis": (
                decimal_text(self.cost_basis) if self.cost_basis is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class BrokerAccountSnapshot:
    provider_identity: str
    account_identity_fingerprint: str
    account_status: str
    cash: Decimal
    currency: str
    positions: tuple[BrokerPosition, ...]
    observed_at_utc: datetime
    equity: Decimal | None = None
    portfolio_value: Decimal | None = None
    buying_power: Decimal | None = None
    trading_blocked: bool | None = None
    account_blocked: bool | None = None
    restriction_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = _identity(self.provider_identity, "Broker provider identity")
        account_fingerprint = str(self.account_identity_fingerprint).strip().lower()
        if len(account_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in account_fingerprint
        ):
            raise ValueError("Broker account identity fingerprint is invalid.")
        status = _identity(self.account_status, "Broker account status")
        currency = str(self.currency).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValueError("Broker account currency is invalid.")
        if self.observed_at_utc.tzinfo is None:
            raise ValueError("Broker observation timestamp must be timezone-aware.")
        positions = tuple(sorted(self.positions, key=lambda value: value.symbol))
        if any(not isinstance(position, BrokerPosition) for position in positions):
            raise ValueError("Broker positions must use canonical BrokerPosition objects.")
        if len({position.symbol for position in positions}) != len(positions):
            raise ValueError("Broker snapshot contains duplicate position symbols.")
        flags = tuple(sorted({
            _identity(value, "Broker restriction flag")
            for value in self.restriction_flags
        }))
        for name in ("trading_blocked", "account_blocked"):
            if getattr(self, name) is not None and type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean or unavailable.")
        object.__setattr__(self, "provider_identity", provider)
        object.__setattr__(self, "account_identity_fingerprint", account_fingerprint)
        object.__setattr__(self, "account_status", status)
        object.__setattr__(self, "currency", currency)
        object.__setattr__(self, "cash", _decimal(self.cash, "Broker cash"))
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "observed_at_utc", self.observed_at_utc.astimezone(timezone.utc))
        object.__setattr__(self, "restriction_flags", flags)
        for name in ("equity", "portfolio_value", "buying_power"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _decimal(value, f"Broker {name}"))

    @property
    def identity_fingerprint(self) -> str:
        return _fingerprint({
            "provider_identity": self.provider_identity,
            "account_identity_fingerprint": self.account_identity_fingerprint,
            "account_status": self.account_status,
            "cash": decimal_text(self.cash),
            "currency": self.currency,
            "positions": [position.identity_dict() for position in self.positions],
            "trading_blocked": self.trading_blocked,
            "account_blocked": self.account_blocked,
            "restriction_flags": self.restriction_flags,
        })

    @property
    def observation_fingerprint(self) -> str:
        payload = self._observation_payload()
        payload.pop("observed_at_utc")
        return _fingerprint(payload)

    def _observation_payload(self) -> dict[str, Any]:
        return {
            "provider_identity": self.provider_identity,
            "account_identity_fingerprint": self.account_identity_fingerprint,
            "account_status": self.account_status,
            "cash": decimal_text(self.cash),
            "currency": self.currency,
            "positions": [position.as_dict() for position in self.positions],
            "observed_at_utc": self.observed_at_utc.isoformat(),
            "equity": decimal_text(self.equity) if self.equity is not None else None,
            "portfolio_value": (
                decimal_text(self.portfolio_value)
                if self.portfolio_value is not None
                else None
            ),
            "buying_power": (
                decimal_text(self.buying_power)
                if self.buying_power is not None
                else None
            ),
            "trading_blocked": self.trading_blocked,
            "account_blocked": self.account_blocked,
            "restriction_flags": list(self.restriction_flags),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            **self._observation_payload(),
            "identity_fingerprint": self.identity_fingerprint,
            "observation_fingerprint": self.observation_fingerprint,
        }


@runtime_checkable
class BrokerAccountProvider(Protocol):
    """Read-only contract implemented by every future broker adapter.

    An adapter must expose a stable registered ``provider_identity`` and one
    side-effect-free ``observe`` operation.  ``observe`` must normalize native
    account and position fields into ``BrokerAccountSnapshot``, hash rather
    than expose the native account identifier, stamp the time the response was
    actually available to QPX, use ``None`` for unavailable optional fields,
    and raise on malformed or ambiguous data.  Credentials and native payloads
    remain inside the adapter.  Order methods do not belong to this interface.
    """

    @property
    def provider_identity(self) -> str: ...

    def observe(self, observed_at: datetime) -> BrokerAccountSnapshot: ...


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    schema_version: int
    market_data_provider: str
    broker_account_provider: str
    order_execution_provider: str
    broker_account_configuration: Mapping[str, Any]
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported broker-provider selection schema.")
        object.__setattr__(
            self,
            "market_data_provider",
            _identity(self.market_data_provider, "Market-data provider identity"),
        )
        object.__setattr__(
            self,
            "broker_account_provider",
            _identity(self.broker_account_provider, "Broker-account provider identity"),
        )
        object.__setattr__(
            self,
            "order_execution_provider",
            _identity(self.order_execution_provider, "Order-execution provider identity"),
        )
        if not isinstance(self.broker_account_configuration, Mapping):
            raise ValueError("Broker-account provider configuration must be an object.")
        canonical_configuration = json.loads(_canonical(dict(self.broker_account_configuration)))
        object.__setattr__(self, "broker_account_configuration", canonical_configuration)
        if self.source_path is not None:
            object.__setattr__(self, "source_path", self.source_path.expanduser().resolve())

    @property
    def fingerprint(self) -> str:
        return _fingerprint({
            "schema_version": self.schema_version,
            "market_data_provider": self.market_data_provider,
            "broker_account_provider": self.broker_account_provider,
            "order_execution_provider": self.order_execution_provider,
            "broker_account_configuration": self.broker_account_configuration,
        })


def load_provider_selection(path: str | Path) -> ProviderSelection:
    source = Path(path).expanduser().resolve()
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("Provider selection root must be an object.")
    return ProviderSelection(
        schema_version=int(payload.get("schema_version", 0)),
        market_data_provider=str(payload.get("market_data_provider", "")),
        broker_account_provider=str(payload.get("broker_account_provider", "")),
        order_execution_provider=str(payload.get("order_execution_provider", "")),
        broker_account_configuration=payload.get("broker_account_configuration", {}),
        source_path=source,
    )


BrokerAccountProviderFactory = Callable[[ProviderSelection], BrokerAccountProvider]


class BrokerAccountProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, BrokerAccountProviderFactory] = {}

    def register(self, identity: str, factory: BrokerAccountProviderFactory) -> None:
        normalized = _identity(identity, "Broker-account provider identity")
        if normalized in self._factories:
            raise ValueError(f"Broker-account provider {normalized} is already registered.")
        self._factories[normalized] = factory

    def build(self, selection: ProviderSelection) -> BrokerAccountProvider:
        try:
            factory = self._factories[selection.broker_account_provider]
        except KeyError as exc:
            raise ValueError(
                f"Broker-account provider {selection.broker_account_provider} is not registered."
            ) from exc
        provider = factory(selection)
        if not isinstance(provider, BrokerAccountProvider):
            raise TypeError("Broker-account provider does not satisfy the canonical interface.")
        if provider.provider_identity != selection.broker_account_provider:
            raise ValueError("Broker-account provider identity differs from configuration.")
        return provider


class DummyBrokerAccountProvider:
    """Observe an external checksummed JSON file; never access QPX strategy state."""

    provider_identity = DUMMY_PROVIDER_IDENTITY

    def __init__(self, state_path: Path, checksum_path: Path) -> None:
        self.state_path = state_path.expanduser().resolve()
        self.checksum_path = checksum_path.expanduser().resolve()

    def load_state(self) -> dict[str, Any]:
        """Read and validate only the external dummy brokerage state."""
        encoded = read_checksummed_state(
            self.state_path,
            self.checksum_path,
            label="Dummy broker-account state",
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise ValueError("Dummy broker-account state root must be an object.")
        snapshot_from_dummy_state(payload, datetime.now(timezone.utc))
        return payload

    def observe(self, observed_at: datetime) -> BrokerAccountSnapshot:
        return snapshot_from_dummy_state(self.load_state(), observed_at)


def snapshot_from_dummy_state(
    payload: Mapping[str, Any], observed_at: datetime
) -> BrokerAccountSnapshot:
    if int(payload.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError("Unsupported dummy broker-account state schema.")
    provider = _identity(payload.get("provider_identity", ""), "Dummy provider identity")
    if provider != DUMMY_PROVIDER_IDENTITY:
        raise ValueError("Dummy broker-account state has the wrong provider identity.")
    raw_account_identity = str(payload.get("account_identity", "")).strip()
    if not raw_account_identity:
        raise ValueError("Dummy broker-account identity is required.")
    raw_positions = payload.get("positions")
    if not isinstance(raw_positions, list):
        raise ValueError("Dummy broker positions must be a list.")
    positions: list[BrokerPosition] = []
    for raw in raw_positions:
        if not isinstance(raw, Mapping):
            raise ValueError("Dummy broker position must be an object.")
        raw_asset_class = raw.get("asset_class")
        positions.append(BrokerPosition(
            symbol=str(raw.get("symbol", "")),
            side=str(raw.get("side", "")),
            quantity=_decimal(raw.get("quantity"), "Dummy position quantity"),
            average_entry_price=_decimal(
                raw.get("average_entry_price"),
                "Dummy position average entry price",
            ),
            cost_basis=_optional_decimal(raw.get("cost_basis"), "Dummy position cost basis"),
            market_value=_optional_decimal(raw.get("market_value"), "Dummy position market value"),
            current_price=_optional_decimal(raw.get("current_price"), "Dummy position current price"),
            asset_class=(
                str(raw_asset_class).strip()
                if raw_asset_class not in (None, "")
                else None
            ),
        ))
    restrictions = payload.get("restriction_flags", [])
    if not isinstance(restrictions, list):
        raise ValueError("Dummy restriction flags must be a list.")
    return BrokerAccountSnapshot(
        provider_identity=provider,
        account_identity_fingerprint=_fingerprint({
            "provider_identity": provider,
            "account_identity": raw_account_identity,
        }),
        account_status=str(payload.get("account_status", "")),
        cash=_decimal(payload.get("cash"), "Dummy broker cash"),
        currency=str(payload.get("currency", "")),
        positions=tuple(positions),
        observed_at_utc=observed_at,
        equity=_optional_decimal(payload.get("equity"), "Dummy broker equity"),
        portfolio_value=_optional_decimal(
            payload.get("portfolio_value"),
            "Dummy broker portfolio value",
        ),
        buying_power=_optional_decimal(
            payload.get("buying_power"),
            "Dummy broker buying power",
        ),
        trading_blocked=payload.get("trading_blocked"),
        account_blocked=payload.get("account_blocked"),
        restriction_flags=tuple(str(value) for value in restrictions),
    )


def write_dummy_broker_account_state(
    path: str | Path,
    payload: Mapping[str, Any],
    *,
    checksum_path: str | Path | None = None,
) -> None:
    """Atomically replace the external dummy observation input and its checksum."""
    destination = Path(path).expanduser().resolve()
    snapshot_from_dummy_state(payload, datetime.now(timezone.utc))
    encoded = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    write_checksummed_state(
        destination,
        (
            Path(checksum_path).expanduser().resolve()
            if checksum_path is not None
            else destination.with_suffix(destination.suffix + ".sha256")
        ),
        encoded,
    )


def _resolve_configured_path(selection: ProviderSelection, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        if selection.source_path is None:
            raise ValueError("Relative broker-account paths require a source configuration path.")
        path = selection.source_path.parent / path
    return path.resolve()


def _dummy_factory(selection: ProviderSelection) -> BrokerAccountProvider:
    configuration = selection.broker_account_configuration
    if "state_path" not in configuration:
        raise ValueError("Dummy broker-account configuration requires state_path.")
    state_path = _resolve_configured_path(selection, configuration["state_path"])
    checksum_value = configuration.get("checksum_path")
    checksum_path = (
        _resolve_configured_path(selection, checksum_value)
        if checksum_value
        else state_path.with_suffix(state_path.suffix + ".sha256")
    )
    return DummyBrokerAccountProvider(state_path, checksum_path)


BROKER_ACCOUNT_PROVIDERS = BrokerAccountProviderRegistry()
BROKER_ACCOUNT_PROVIDERS.register(DUMMY_PROVIDER_IDENTITY, _dummy_factory)


def build_broker_account_provider(selection: ProviderSelection) -> BrokerAccountProvider:
    return BROKER_ACCOUNT_PROVIDERS.build(selection)
