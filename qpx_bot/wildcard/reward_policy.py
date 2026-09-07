"""Immutable, externally configured Wildcard reward-policy foundation.

This module validates and fingerprints policy configuration.  It deliberately
does not calculate rewards, maintain accounts, execute orders, or select an ML
model.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state


ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIRECTORY = Path(__file__).with_name("configs")
DEFAULT_POLICY_PATH = CONFIG_DIRECTORY / "reward_policy_default_v1.json"
DEFAULT_APPROVAL_PATH = CONFIG_DIRECTORY / "reward_policy_default_v1.approval.json"

POLICY_SCHEMA_VERSION = 1
APPROVAL_SCHEMA_VERSION = 1
CAPTURE_SCHEMA_VERSION = 1
EXPERIMENT_IDENTITY_SCHEMA_VERSION = 1
CONSEQUENCE_SCHEMA_VERSION = "wildcard_consequence_channels_v1"
REQUIRED_WORLD_CONTRACT_ID = "ADR-0012_WILDCARD_WORLD_V1"
TERMINAL_POLICY_ID = "solvency_lexicographic_v1"
APPROVAL_AUTHORITY = "QPX_USER_GOVERNANCE"

TERM_NAMES = (
    "growth",
    "speed_bonus",
    "cash_exposure",
    "inactivity",
    "turnover",
    "concentration",
    "drawdown",
    "volatility",
    "costs",
)
OPTIONAL_DISABLED_TERMS = frozenset(TERM_NAMES[2:])

POLICY_KEYS = frozenset({
    "schema_version",
    "policy_name",
    "policy_version",
    "required_world_contract_id",
    "consequence_schema_version",
    "terminal_policy_id",
    "terms",
})
TERM_KEYS = frozenset({"enabled", "function_id", "parameters"})
APPROVAL_KEYS = frozenset({
    "approval_schema_version",
    "policy_content_fingerprint",
    "approval_status",
    "approval_authority",
    "created_at_utc",
    "approved_at_utc",
    "approval_reference",
    "parent_policy_fingerprint",
    "change_note",
})
APPROVAL_REFERENCE_KEYS = frozenset({
    "kind", "commit", "document_path", "decision_identity",
})
CAPTURE_KEYS = frozenset({
    "capture_schema_version",
    "world_fingerprint",
    "reward_policy_fingerprint",
    "experiment_id",
    "policy",
    "approval",
})

DECIMAL_PATTERN = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
POLICY_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
SEMVER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
DECISION_IDENTITY_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,127}\Z")
LOWER_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
LOWER_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
MAX_DECIMAL_MAGNITUDE = Decimal("1000000000000")
MAX_INTEGER_TIME = (1 << 63) - 1


class RewardPolicyError(ValueError):
    """Policy configuration or provenance is invalid."""


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _canonical_value(value: Any) -> Any:
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value
    if isinstance(value, Decimal):
        return canonical_decimal_text(value)
    if type(value) is float:
        raise RewardPolicyError("Binary floating-point values are not canonical policy data.")
    if isinstance(value, str):
        return _nfc(value)
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, item in value.items():
            if not isinstance(raw_key, str):
                raise RewardPolicyError("Canonical JSON object keys must be strings.")
            key = _nfc(raw_key)
            if key in normalized:
                raise RewardPolicyError(f"Duplicate canonical JSON key: {key!r}.")
            normalized[key] = _canonical_value(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise RewardPolicyError(
        f"Unsupported canonical policy value: {type(value).__name__}."
    )


def canonical_bytes(value: Any) -> bytes:
    """Return canonical compact UTF-8 JSON without a trailing newline."""
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _reject_json_float(_value: str) -> None:
    raise RewardPolicyError(
        "JSON floating-point numbers are prohibited in reward-policy configuration."
    )


def _reject_json_constant(value: str) -> None:
    raise RewardPolicyError(f"Non-finite JSON constant is prohibited: {value}.")


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw_key, value in pairs:
        key = _nfc(raw_key)
        if key in result:
            raise RewardPolicyError(f"Duplicate JSON field: {key!r}.")
        result[key] = value
    return result


def _strict_json(data: bytes | str, *, label: str) -> dict[str, Any]:
    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as exc:
        raise RewardPolicyError(f"{label} is not valid UTF-8.") from exc
    if text.startswith("\ufeff"):
        raise RewardPolicyError(f"{label} must not contain a UTF-8 BOM.")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=_reject_json_float,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise RewardPolicyError(f"{label} is not valid strict JSON.") from exc
    if not isinstance(payload, dict):
        raise RewardPolicyError(f"{label} root must be a JSON object.")
    return payload


def _read_strict_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        encoded = path.read_bytes()
    except FileNotFoundError as exc:
        raise RewardPolicyError(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise RewardPolicyError(f"Unable to read {label}: {path}") from exc
    return _strict_json(encoded, label=label)


def _require_exact_keys(
    payload: Mapping[str, Any], expected: frozenset[str], *, label: str
) -> None:
    observed = frozenset(payload)
    missing = sorted(expected - observed)
    unknown = sorted(observed - expected)
    if missing or unknown:
        raise RewardPolicyError(
            f"{label} fields differ; missing={missing!r}, unknown={unknown!r}."
        )


def canonical_decimal_text(value: Decimal) -> str:
    if not value.is_finite():
        raise RewardPolicyError("Policy decimals must be finite.")
    if value == 0:
        return "0"
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def parse_decimal(value: Any, *, field: str, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, str) or not DECIMAL_PATTERN.fullmatch(value):
        raise RewardPolicyError(
            f"{field} must be a non-exponent canonical decimal string."
        )
    fraction = value.lstrip("-").partition(".")[2]
    if len(fraction) > 12:
        raise RewardPolicyError(f"{field} exceeds 12 fractional digits.")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise RewardPolicyError(f"{field} is not a valid decimal.") from exc
    canonical = canonical_decimal_text(number)
    significant = canonical.lstrip("-").replace(".", "").lstrip("0")
    if len(significant or "0") > 18:
        raise RewardPolicyError(f"{field} exceeds 18 significant digits.")
    if abs(number) >= MAX_DECIMAL_MAGNITUDE:
        raise RewardPolicyError(f"{field} magnitude must be below 10^12.")
    if nonnegative and number < 0:
        raise RewardPolicyError(f"{field} must be nonnegative.")
    return Decimal(canonical)


def _positive_time(value: Any, *, field: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_INTEGER_TIME:
        raise RewardPolicyError(f"{field} must be a positive signed-64-bit integer.")
    return value


def _validate_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not LOWER_SHA256_PATTERN.fullmatch(value):
        raise RewardPolicyError(f"{field} must be a lowercase SHA-256 fingerprint.")
    return value


@dataclass(frozen=True, slots=True)
class RewardTerm:
    enabled: bool
    function_id: str | None
    parameters: tuple[tuple[str, Decimal | int], ...] | None

    @property
    def effective_weight(self) -> Decimal:
        if not self.enabled:
            return Decimal("0")
        assert self.parameters is not None
        values = dict(self.parameters)
        weight = values.get("weight")
        if not isinstance(weight, Decimal):
            raise RewardPolicyError("Enabled reward term has no Decimal weight.")
        return weight

    @property
    def effective_contribution_when_disabled(self) -> Decimal:
        """Return the only contribution defined here; enabled arithmetic is deferred."""
        if self.enabled:
            raise RewardPolicyError(
                "Enabled-term reward arithmetic is outside the configuration foundation."
            )
        return Decimal("0")

    @property
    def parameter_mapping(self) -> Mapping[str, Decimal | int]:
        return MappingProxyType(dict(self.parameters or ()))

    def as_dict(self) -> dict[str, Any]:
        parameters = None
        if self.parameters is not None:
            parameters = {
                key: canonical_decimal_text(value)
                if isinstance(value, Decimal)
                else value
                for key, value in self.parameters
            }
        return {
            "enabled": self.enabled,
            "function_id": self.function_id,
            "parameters": parameters,
        }


def _parse_term(name: str, payload: Any) -> RewardTerm:
    if not isinstance(payload, Mapping):
        raise RewardPolicyError(f"Reward term {name!r} must be an object.")
    _require_exact_keys(payload, TERM_KEYS, label=f"Reward term {name!r}")
    enabled = payload["enabled"]
    if type(enabled) is not bool:
        raise RewardPolicyError(f"Reward term {name!r} enabled must be boolean.")
    function_id = payload["function_id"]
    parameters = payload["parameters"]
    if not enabled:
        if function_id is not None or parameters is not None:
            raise RewardPolicyError(
                f"Disabled reward term {name!r} must have null function and parameters."
            )
        return RewardTerm(False, None, None)
    if name in OPTIONAL_DISABLED_TERMS:
        raise RewardPolicyError(
            f"Reward term {name!r} has no approved V1 function and must remain disabled."
        )
    if not isinstance(parameters, Mapping):
        raise RewardPolicyError(f"Enabled reward term {name!r} needs parameters.")
    if name == "growth":
        if function_id != "delta_log_equity_v1":
            raise RewardPolicyError("Growth uses only delta_log_equity_v1 in schema V1.")
        _require_exact_keys(
            parameters, frozenset({"weight"}), label="Growth parameters"
        )
        parsed = ((
            "weight",
            parse_decimal(parameters["weight"], field="growth.weight", nonnegative=True),
        ),)
    elif name == "speed_bonus":
        if function_id != "exp_half_life_delta_log_equity_v1":
            raise RewardPolicyError(
                "Speed bonus uses only exp_half_life_delta_log_equity_v1 in schema V1."
            )
        _require_exact_keys(
            parameters,
            frozenset({"weight", "half_life_scheduled_market_minutes"}),
            label="Speed-bonus parameters",
        )
        parsed = (
            (
                "half_life_scheduled_market_minutes",
                _positive_time(
                    parameters["half_life_scheduled_market_minutes"],
                    field="speed_bonus.half_life_scheduled_market_minutes",
                ),
            ),
            (
                "weight",
                parse_decimal(
                    parameters["weight"], field="speed_bonus.weight", nonnegative=True
                ),
            ),
        )
    else:  # pragma: no cover - TERM_NAMES and OPTIONAL_DISABLED_TERMS are closed.
        raise RewardPolicyError(f"Unknown reward term: {name!r}.")
    return RewardTerm(True, str(function_id), tuple(sorted(parsed)))


@dataclass(frozen=True, slots=True)
class RewardPolicyContent:
    schema_version: int
    policy_name: str
    policy_version: str
    required_world_contract_id: str
    consequence_schema_version: str
    terminal_policy_id: str
    terms: tuple[tuple[str, RewardTerm], ...]

    def __post_init__(self) -> None:
        if self.schema_version != POLICY_SCHEMA_VERSION:
            raise RewardPolicyError("Unsupported reward-policy schema version.")
        if not POLICY_NAME_PATTERN.fullmatch(self.policy_name):
            raise RewardPolicyError("Reward-policy name is malformed.")
        if not SEMVER_PATTERN.fullmatch(self.policy_version):
            raise RewardPolicyError("Reward-policy version must be strict SemVer core form.")
        if self.required_world_contract_id != REQUIRED_WORLD_CONTRACT_ID:
            raise RewardPolicyError("Reward policy is incompatible with the V1 world contract.")
        if self.consequence_schema_version != CONSEQUENCE_SCHEMA_VERSION:
            raise RewardPolicyError("Unsupported consequence-channel schema.")
        if self.terminal_policy_id != TERMINAL_POLICY_ID:
            raise RewardPolicyError("Unsupported terminal policy identity.")
        if tuple(name for name, _term in self.terms) != tuple(sorted(TERM_NAMES)):
            raise RewardPolicyError("Reward terms are incomplete or non-canonical.")

    def term(self, name: str) -> RewardTerm:
        try:
            return dict(self.terms)[name]
        except KeyError as exc:
            raise RewardPolicyError(f"Unknown reward term: {name!r}.") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_name": self.policy_name,
            "policy_version": self.policy_version,
            "required_world_contract_id": self.required_world_contract_id,
            "consequence_schema_version": self.consequence_schema_version,
            "terminal_policy_id": self.terminal_policy_id,
            "terms": {name: term.as_dict() for name, term in self.terms},
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())

    @property
    def policy_content_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def policy_content_from_payload(payload: Mapping[str, Any]) -> RewardPolicyContent:
    _require_exact_keys(payload, POLICY_KEYS, label="Reward policy")
    if type(payload["schema_version"]) is not int:
        raise RewardPolicyError("Reward-policy schema_version must be an integer.")
    for field in (
        "policy_name",
        "policy_version",
        "required_world_contract_id",
        "consequence_schema_version",
        "terminal_policy_id",
    ):
        if not isinstance(payload[field], str):
            raise RewardPolicyError(f"Reward-policy {field} must be a string.")
    raw_terms = payload["terms"]
    if not isinstance(raw_terms, Mapping):
        raise RewardPolicyError("Reward-policy terms must be an object.")
    if frozenset(raw_terms) != frozenset(TERM_NAMES):
        missing = sorted(set(TERM_NAMES) - set(raw_terms))
        unknown = sorted(set(raw_terms) - set(TERM_NAMES))
        raise RewardPolicyError(
            f"Reward terms differ; missing={missing!r}, unknown={unknown!r}."
        )
    terms = tuple(
        (name, _parse_term(name, raw_terms[name])) for name in sorted(TERM_NAMES)
    )
    return RewardPolicyContent(
        schema_version=payload["schema_version"],
        policy_name=_nfc(payload["policy_name"]),
        policy_version=payload["policy_version"],
        required_world_contract_id=payload["required_world_contract_id"],
        consequence_schema_version=payload["consequence_schema_version"],
        terminal_policy_id=payload["terminal_policy_id"],
        terms=terms,
    )


def load_policy_content(path: Path = DEFAULT_POLICY_PATH) -> RewardPolicyContent:
    return policy_content_from_payload(
        _read_strict_json(Path(path), label="Reward-policy profile")
    )


@dataclass(frozen=True, slots=True)
class ApprovalReference:
    kind: str
    commit: str
    document_path: str
    decision_identity: str

    def __post_init__(self) -> None:
        if not all(
            isinstance(value, str)
            for value in (
                self.kind,
                self.commit,
                self.document_path,
                self.decision_identity,
            )
        ):
            raise RewardPolicyError("Approval reference fields must be strings.")
        if self.kind != "git_commit":
            raise RewardPolicyError("Approval reference kind must be git_commit.")
        if not LOWER_GIT_SHA_PATTERN.fullmatch(self.commit):
            raise RewardPolicyError("Approval reference requires a full lowercase Git SHA.")
        path = Path(self.document_path)
        if (
            not self.document_path
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in self.document_path
        ):
            raise RewardPolicyError("Approval document path must be repository-relative.")
        if not DECISION_IDENTITY_PATTERN.fullmatch(self.decision_identity):
            raise RewardPolicyError("Approval decision identity is malformed.")

    def as_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind,
            "commit": self.commit,
            "document_path": self.document_path,
            "decision_identity": self.decision_identity,
        }


def _canonical_utc_timestamp(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise RewardPolicyError(f"{field} must be a canonical UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RewardPolicyError(f"{field} is not a valid timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RewardPolicyError(f"{field} must use UTC.")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    if canonical != value:
        raise RewardPolicyError(f"{field} must use canonical second-resolution RFC3339 UTC.")
    return value


@dataclass(frozen=True, slots=True)
class RewardPolicyApproval:
    approval_schema_version: int
    policy_content_fingerprint: str
    approval_status: str
    approval_authority: str
    created_at_utc: str
    approved_at_utc: str
    approval_reference: ApprovalReference
    parent_policy_fingerprint: str | None
    change_note: str

    def __post_init__(self) -> None:
        if self.approval_schema_version != APPROVAL_SCHEMA_VERSION:
            raise RewardPolicyError("Unsupported reward-policy approval schema.")
        _validate_sha256(
            self.policy_content_fingerprint, field="policy_content_fingerprint"
        )
        if self.approval_status != "APPROVED":
            raise RewardPolicyError("Reward-policy approval status must be APPROVED.")
        if self.approval_authority != APPROVAL_AUTHORITY:
            raise RewardPolicyError("Reward-policy approval authority is not recognized.")
        _canonical_utc_timestamp(self.created_at_utc, field="created_at_utc")
        _canonical_utc_timestamp(self.approved_at_utc, field="approved_at_utc")
        if self.parent_policy_fingerprint is not None:
            _validate_sha256(
                self.parent_policy_fingerprint, field="parent_policy_fingerprint"
            )
        note = _nfc(self.change_note)
        if not note.strip() or len(note) > 1024 or any(ord(c) < 32 for c in note):
            raise RewardPolicyError("Reward-policy change note is invalid.")
        object.__setattr__(self, "change_note", note)

    def as_dict(self) -> dict[str, Any]:
        return {
            "approval_schema_version": self.approval_schema_version,
            "policy_content_fingerprint": self.policy_content_fingerprint,
            "approval_status": self.approval_status,
            "approval_authority": self.approval_authority,
            "created_at_utc": self.created_at_utc,
            "approved_at_utc": self.approved_at_utc,
            "approval_reference": self.approval_reference.as_dict(),
            "parent_policy_fingerprint": self.parent_policy_fingerprint,
            "change_note": self.change_note,
        }


def approval_from_payload(payload: Mapping[str, Any]) -> RewardPolicyApproval:
    _require_exact_keys(payload, APPROVAL_KEYS, label="Reward-policy approval")
    reference = payload["approval_reference"]
    if not isinstance(reference, Mapping):
        raise RewardPolicyError("Approval reference must be an object.")
    _require_exact_keys(
        reference, APPROVAL_REFERENCE_KEYS, label="Reward-policy approval reference"
    )
    if type(payload["approval_schema_version"]) is not int:
        raise RewardPolicyError("Approval schema version must be an integer.")
    for field in (
        "policy_content_fingerprint",
        "approval_status",
        "approval_authority",
        "created_at_utc",
        "approved_at_utc",
        "change_note",
    ):
        if not isinstance(payload[field], str):
            raise RewardPolicyError(f"Approval field {field} must be a string.")
    parent = payload["parent_policy_fingerprint"]
    if parent is not None and not isinstance(parent, str):
        raise RewardPolicyError("Parent policy fingerprint must be null or a string.")
    return RewardPolicyApproval(
        approval_schema_version=payload["approval_schema_version"],
        policy_content_fingerprint=payload["policy_content_fingerprint"],
        approval_status=payload["approval_status"],
        approval_authority=payload["approval_authority"],
        created_at_utc=payload["created_at_utc"],
        approved_at_utc=payload["approved_at_utc"],
        approval_reference=ApprovalReference(
            kind=reference["kind"],
            commit=reference["commit"],
            document_path=reference["document_path"],
            decision_identity=reference["decision_identity"],
        ),
        parent_policy_fingerprint=parent,
        change_note=payload["change_note"],
    )


def _verify_git_approval(reference: ApprovalReference, repository_root: Path) -> None:
    try:
        result = subprocess.run(
            (
                "git",
                "cat-file",
                "-e",
                f"{reference.commit}:{reference.document_path}",
            ),
            cwd=repository_root,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RewardPolicyError("Unable to verify reward-policy Git provenance.") from exc
    if result.returncode != 0:
        raise RewardPolicyError(
            "Reward-policy approval commit/document provenance is unavailable."
        )


@dataclass(frozen=True, slots=True)
class ApprovedRewardPolicy:
    content: RewardPolicyContent
    approval: RewardPolicyApproval

    def __post_init__(self) -> None:
        if self.approval.policy_content_fingerprint != self.content.policy_content_fingerprint:
            raise RewardPolicyError("Approval/content fingerprint mismatch.")

    def as_dict(self) -> dict[str, Any]:
        return {"policy": self.content.as_dict(), "approval": self.approval.as_dict()}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_bytes(self.as_dict())

    @property
    def reward_policy_fingerprint(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()


def approved_policy_from_payloads(
    policy_payload: Mapping[str, Any],
    approval_payload: Mapping[str, Any],
    *,
    repository_root: Path = ROOT,
    verify_git_provenance: bool = True,
) -> ApprovedRewardPolicy:
    content = policy_content_from_payload(policy_payload)
    approval = approval_from_payload(approval_payload)
    approved = ApprovedRewardPolicy(content, approval)
    if verify_git_provenance:
        _verify_git_approval(approval.approval_reference, repository_root)
    return approved


def load_approved_policy(
    policy_path: Path = DEFAULT_POLICY_PATH,
    approval_path: Path = DEFAULT_APPROVAL_PATH,
    *,
    repository_root: Path = ROOT,
) -> ApprovedRewardPolicy:
    return approved_policy_from_payloads(
        _read_strict_json(Path(policy_path), label="Reward-policy profile"),
        _read_strict_json(Path(approval_path), label="Reward-policy approval"),
        repository_root=repository_root,
    )


class ConsequenceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE_BLOCKING = "UNAVAILABLE_BLOCKING"


@dataclass(frozen=True, slots=True)
class ConsequenceChannelSpec:
    name: str
    units: str
    sign_convention: str
    causal_boundary: str
    availability_rule: str
    mandatory_for_terms: tuple[str, ...]
    calculation_status: str


CONSEQUENCE_CHANNELS = (
    ConsequenceChannelSpec(
        "delta_log_equity",
        "dimensionless",
        "positive=growth; negative=loss",
        "consecutive fully reconciled positive-equity decision boundaries",
        "blocking when required equity is nonpositive or unreconciled",
        ("growth", "speed_bonus"),
        "DEFINED_BY_ADR_0012",
    ),
    ConsequenceChannelSpec(
        "scheduled_market_minutes",
        "scheduled regular-session market minutes",
        "nonnegative and monotonic",
        "authoritative exchange calendar at the current decision boundary",
        "blocking when required calendar progression is unavailable",
        ("speed_bonus",),
        "DEFINED_BY_ADR_0012",
    ),
    ConsequenceChannelSpec(
        "cash_exposure", "dimensionless ratio", "higher=more cash exposure",
        "fully reconciled account boundary", "optional; never imputed",
        ("cash_exposure",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "inactivity", "scheduled market minutes", "higher=longer inactivity",
        "current causal decision boundary", "optional; never imputed",
        ("inactivity",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "turnover", "dimensionless ratio", "nonnegative",
        "fills causally available by the current boundary", "optional; never imputed",
        ("turnover",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "concentration", "dimensionless ratio in [0,1]", "higher=more concentrated",
        "causally realizable reconciled holdings", "optional; never imputed",
        ("concentration",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "drawdown", "dimensionless ratio in [0,1]", "zero=causal high-water mark",
        "reconciled causal equity history", "optional; never imputed",
        ("drawdown",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "volatility", "dimensionless causal-horizon measure", "nonnegative",
        "observations strictly available before the boundary", "optional; never imputed",
        ("volatility",), "ESTIMATOR_DEFERRED",
    ),
    ConsequenceChannelSpec(
        "modeled_cost", "USD Decimal cost magnitude", "nonnegative cost",
        "reconciled fill/fee event", "zero only when deterministically no cost occurred",
        ("costs",), "DEFINED_BY_WORLD_ACCOUNTING",
    ),
)
CONSEQUENCE_CHANNEL_BY_NAME = MappingProxyType(
    {item.name: item for item in CONSEQUENCE_CHANNELS}
)


def required_consequence_channels(policy: RewardPolicyContent) -> tuple[str, ...]:
    required: set[str] = set()
    for spec in CONSEQUENCE_CHANNELS:
        if any(policy.term(term_name).enabled for term_name in spec.mandatory_for_terms):
            required.add(spec.name)
    return tuple(sorted(required))


def validate_consequence_availability(
    policy: RewardPolicyContent,
    availability: Mapping[str, ConsequenceAvailability],
) -> None:
    unknown = sorted(set(availability) - set(CONSEQUENCE_CHANNEL_BY_NAME))
    if unknown:
        raise RewardPolicyError(f"Unknown consequence channels: {unknown!r}.")
    for name, value in availability.items():
        if not isinstance(value, ConsequenceAvailability):
            raise RewardPolicyError(
                f"Consequence availability for {name!r} must use the closed enum."
            )
    for name in required_consequence_channels(policy):
        if availability.get(name) is not ConsequenceAvailability.AVAILABLE:
            raise RewardPolicyError(
                f"Enabled reward policy requires AVAILABLE consequence {name!r}."
            )


REWARD_EMISSION_PHASES = (
    "CAUSALLY_AVAILABLE_EARLIER_EVENTS_PROCESSED",
    "ELIGIBLE_FILLS_AND_PARTIAL_FILLS_APPLIED",
    "CAUSALLY_LEGAL_MARKS_APPLIED",
    "ACCOUNT_RECONCILED",
    "EQUITY_ESTABLISHED",
    "PRIOR_TRANSITION_REWARD_ELIGIBLE",
    "NEXT_OBSERVATION_ACTION_EXPOSED",
)


@dataclass(frozen=True, slots=True)
class RewardEmissionBoundary:
    boundary_index: int
    earlier_events_processed: bool
    fills_applied: bool
    marks_applied: bool
    account_reconciled: bool
    equity_established: bool
    next_action_exposed: bool = False

    def __post_init__(self) -> None:
        if type(self.boundary_index) is not int or self.boundary_index < 0:
            raise RewardPolicyError("Reward boundary index must be nonnegative.")
        flags = (
            self.earlier_events_processed,
            self.fills_applied,
            self.marks_applied,
            self.account_reconciled,
            self.equity_established,
            self.next_action_exposed,
        )
        if any(type(value) is not bool for value in flags):
            raise RewardPolicyError("Reward boundary completion flags must be boolean.")
        for earlier, later in zip(flags, flags[1:]):
            if later and not earlier:
                raise RewardPolicyError("Reward boundary phases must complete in order.")

    @property
    def transition_reward_eligible(self) -> bool:
        return (
            self.boundary_index > 0
            and self.equity_established
            and not self.next_action_exposed
        )


def experiment_identity_payload(
    world_fingerprint: str, reward_policy_fingerprint: str
) -> dict[str, Any]:
    return {
        "schema_version": EXPERIMENT_IDENTITY_SCHEMA_VERSION,
        "world_fingerprint": _validate_sha256(
            world_fingerprint, field="world_fingerprint"
        ),
        "reward_policy_fingerprint": _validate_sha256(
            reward_policy_fingerprint, field="reward_policy_fingerprint"
        ),
    }


def experiment_identity(
    world_fingerprint: str, reward_policy_fingerprint: str
) -> str:
    return fingerprint(
        experiment_identity_payload(world_fingerprint, reward_policy_fingerprint)
    )


@dataclass(frozen=True, slots=True)
class CapturedRewardPolicy:
    approved_policy: ApprovedRewardPolicy
    world_fingerprint: str
    experiment_id: str


def capture_approved_policy(
    directory: Path,
    approved_policy: ApprovedRewardPolicy,
    *,
    world_fingerprint: str,
) -> CapturedRewardPolicy:
    world = _validate_sha256(world_fingerprint, field="world_fingerprint")
    reward_fingerprint = approved_policy.reward_policy_fingerprint
    identity = experiment_identity(world, reward_fingerprint)
    payload = {
        "capture_schema_version": CAPTURE_SCHEMA_VERSION,
        "world_fingerprint": world,
        "reward_policy_fingerprint": reward_fingerprint,
        "experiment_id": identity,
        "policy": approved_policy.content.as_dict(),
        "approval": approved_policy.approval.as_dict(),
    }
    state_path = Path(directory) / "reward_policy.canonical.json"
    checksum_path = Path(directory) / "reward_policy.sha256"
    if state_path.exists() or checksum_path.exists():
        existing = load_captured_policy(
            directory,
            expected_world_fingerprint=world,
        )
        if existing.approved_policy.reward_policy_fingerprint != reward_fingerprint:
            raise RewardPolicyError(
                "Existing experiment capture uses a different reward policy."
            )
        if existing.experiment_id != identity:
            raise RewardPolicyError("Existing experiment capture identity differs.")
        return existing
    write_checksummed_state(state_path, checksum_path, canonical_bytes(payload))
    return CapturedRewardPolicy(approved_policy, world, identity)


def load_captured_policy(
    directory: Path,
    *,
    expected_world_fingerprint: str | None = None,
    repository_root: Path = ROOT,
) -> CapturedRewardPolicy:
    state_path = Path(directory) / "reward_policy.canonical.json"
    checksum_path = Path(directory) / "reward_policy.sha256"
    try:
        encoded = read_checksummed_state(
            state_path, checksum_path, label="Captured Wildcard reward policy"
        )
    except (FileNotFoundError, OSError, RuntimeError) as exc:
        raise RewardPolicyError(
            "Captured Wildcard reward policy is unavailable or corrupt."
        ) from exc
    payload = _strict_json(encoded, label="Captured Wildcard reward policy")
    _require_exact_keys(payload, CAPTURE_KEYS, label="Captured reward policy")
    if payload["capture_schema_version"] != CAPTURE_SCHEMA_VERSION or type(
        payload["capture_schema_version"]
    ) is not int:
        raise RewardPolicyError("Unsupported reward-policy capture schema.")
    if not isinstance(payload["policy"], Mapping) or not isinstance(
        payload["approval"], Mapping
    ):
        raise RewardPolicyError("Captured policy and approval must be objects.")
    approved = approved_policy_from_payloads(
        payload["policy"],
        payload["approval"],
        repository_root=repository_root,
    )
    world = _validate_sha256(payload["world_fingerprint"], field="world_fingerprint")
    declared_reward = _validate_sha256(
        payload["reward_policy_fingerprint"], field="reward_policy_fingerprint"
    )
    if declared_reward != approved.reward_policy_fingerprint:
        raise RewardPolicyError("Captured reward-policy fingerprint mismatch.")
    identity = experiment_identity(world, declared_reward)
    if payload["experiment_id"] != identity:
        raise RewardPolicyError("Captured experiment identity mismatch.")
    if expected_world_fingerprint is not None:
        expected = _validate_sha256(
            expected_world_fingerprint, field="expected_world_fingerprint"
        )
        if world != expected:
            raise RewardPolicyError("Captured reward policy belongs to another world.")
    if canonical_bytes(payload) != encoded:
        raise RewardPolicyError("Captured reward policy is not canonical byte-for-byte.")
    return CapturedRewardPolicy(approved, world, identity)
