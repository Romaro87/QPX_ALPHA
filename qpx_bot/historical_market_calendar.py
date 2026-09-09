"""Frozen offline NYSE session authority for the historical ML reservoir.

This module deliberately does not derive sessions from ``qpx_bot.market_calendar``.
The committed manifest is the authority; this loader only validates and exposes
that exact immutable reference evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


REFERENCE_DIRECTORY = Path(__file__).with_name("historical_reference")
FROZEN_HISTORICAL_CALENDAR_PATH = (
    REFERENCE_DIRECTORY
    / "nyse_regular_sessions_2016-09-06_2026-09-03_v1.json"
)

SCHEMA_VERSION = 1
CALENDAR_SEMANTIC_VERSION = "qpx_nyse_historical_regular_sessions_v1"
CANONICALIZATION_CONTRACT = (
    "utf8_nfc_sorted_keys_compact_json_no_trailing_newline_v1"
)
TIMEZONE_IDENTITY = "America/New_York"
COVERED_START = date(2016, 9, 6)
COVERED_END = date(2026, 9, 3)
SESSION_COUNT = 2_513
FROZEN_CALENDAR_CONTENT_FINGERPRINT = (
    "095767b90300c94d38c4aebeb5eccf2f24e8218890e9f95258fa3f0290338373"
)

EXPECTED_MARKET_IDENTITY = {
    "asset_class": "US_CASH_EQUITIES",
    "exchange_group": "NYSE_GROUP",
    "primary_mic": "XNYS",
    "session_type": "REGULAR_TRADING_SESSION",
}
EXPECTED_EXCEPTIONAL_CLOSURES = {
    date(2018, 12, 5): (
        "NATIONAL_DAY_OF_MOURNING_GEORGE_H_W_BUSH",
        "ice_nyse_bush_mourning_closure_2018",
    ),
    date(2025, 1, 9): (
        "NATIONAL_DAY_OF_MOURNING_JIMMY_CARTER",
        "ice_nyse_carter_mourning_closure_2025",
    ),
}
EXPECTED_SOURCE_IDS = frozenset(
    {
        "ice_nyse_2016_calendar",
        "ice_nyse_2017_2019_calendar",
        "ice_nyse_2020_2022_calendar",
        "ice_nyse_2022_2024_calendar",
        "ice_nyse_2024_2026_calendar",
        "sec_nyse_juneteenth_rule_2021",
        "ice_nyse_bush_mourning_closure_2018",
        "ice_nyse_carter_mourning_closure_2025",
    }
)
EXPECTED_EARLY_CLOSES = frozenset(
    date.fromisoformat(value)
    for value in (
        "2016-11-25",
        "2017-07-03",
        "2017-11-24",
        "2018-07-03",
        "2018-11-23",
        "2018-12-24",
        "2019-07-03",
        "2019-11-29",
        "2019-12-24",
        "2020-11-27",
        "2020-12-24",
        "2021-11-26",
        "2022-11-25",
        "2023-07-03",
        "2023-11-24",
        "2024-07-03",
        "2024-11-29",
        "2024-12-24",
        "2025-07-03",
        "2025-11-28",
        "2025-12-24",
    )
)

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ENVELOPE_KEYS = frozenset({"content", "content_fingerprint"})
_CONTENT_KEYS = frozenset(
    {
        "schema_version",
        "calendar_semantic_version",
        "market_identity",
        "timezone_identity",
        "covered_start",
        "covered_end",
        "session_count",
        "exceptional_closures",
        "sources",
        "canonicalization_contract",
        "sessions",
    }
)
_MARKET_KEYS = frozenset(EXPECTED_MARKET_IDENTITY)
_SESSION_KEYS = frozenset(
    {
        "date",
        "regular_open_local",
        "regular_close_local",
        "regular_open_utc",
        "regular_close_utc",
        "early_close",
    }
)
_EXCEPTION_KEYS = frozenset({"date", "reason", "source_id"})
_SOURCE_KEYS = frozenset({"source_id", "publisher", "title", "url"})
_NEW_YORK = ZoneInfo(TIMEZONE_IDENTITY)


class HistoricalMarketCalendarError(ValueError):
    """The frozen historical calendar evidence is missing or invalid."""


@dataclass(frozen=True, slots=True)
class HistoricalMarketSession:
    trading_date: date
    regular_open: datetime
    regular_close: datetime
    regular_open_utc: datetime
    regular_close_utc: datetime
    early_close: bool


@dataclass(frozen=True, slots=True)
class HistoricalCalendarSource:
    source_id: str
    publisher: str
    title: str
    url: str


@dataclass(frozen=True, slots=True)
class ExceptionalClosure:
    trading_date: date
    reason: str
    source_id: str


@dataclass(frozen=True, slots=True)
class FrozenHistoricalMarketCalendar:
    schema_version: int
    calendar_semantic_version: str
    market_identity: tuple[tuple[str, str], ...]
    timezone_identity: str
    covered_start: date
    covered_end: date
    sessions: tuple[HistoricalMarketSession, ...]
    exceptional_closures: tuple[ExceptionalClosure, ...]
    sources: tuple[HistoricalCalendarSource, ...]
    canonicalization_contract: str
    content_fingerprint: str

    def session_on(self, trading_date: date) -> HistoricalMarketSession | None:
        dates = tuple(session.trading_date for session in self.sessions)
        index = bisect_left(dates, trading_date)
        if index < len(dates) and dates[index] == trading_date:
            return self.sessions[index]
        return None

    def is_session(self, trading_date: date) -> bool:
        return self.session_on(trading_date) is not None


def _canonical_value(value: Any) -> Any:
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if normalized != value:
            raise HistoricalMarketCalendarError(
                "Historical calendar strings must already be Unicode NFC."
            )
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise HistoricalMarketCalendarError(
                    "Historical calendar object keys must be strings."
                )
            normalized_key = unicodedata.normalize("NFC", key)
            if normalized_key != key or key in result:
                raise HistoricalMarketCalendarError(
                    "Historical calendar object keys must be unique Unicode NFC."
                )
            result[key] = _canonical_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    raise HistoricalMarketCalendarError(
        f"Unsupported historical calendar value type: {type(value).__name__}."
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        _canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _content_fingerprint(content: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(content)).hexdigest()


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise HistoricalMarketCalendarError(
                f"Duplicate historical calendar field: {key!r}."
            )
        result[key] = value
    return result


def _strict_json(raw: bytes) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise HistoricalMarketCalendarError(
            "Historical calendar manifest must not contain a UTF-8 BOM."
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HistoricalMarketCalendarError(
            "Historical calendar manifest is not valid UTF-8."
        ) from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_strict_pairs,
            parse_float=lambda value: _reject_number(value),
            parse_constant=lambda value: _reject_number(value),
        )
    except (json.JSONDecodeError, TypeError) as exc:
        raise HistoricalMarketCalendarError(
            "Historical calendar manifest is not valid strict JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise HistoricalMarketCalendarError(
            "Historical calendar manifest root must be an object."
        )
    return payload


def _reject_number(value: str) -> None:
    raise HistoricalMarketCalendarError(
        f"Historical calendar manifest contains a prohibited number: {value}."
    )


def _require_exact_keys(
    value: Any, expected: frozenset[str], *, label: str
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise HistoricalMarketCalendarError(f"{label} must be an object.")
    observed = frozenset(value)
    if observed != expected:
        raise HistoricalMarketCalendarError(
            f"{label} fields differ; missing={sorted(expected - observed)!r}, "
            f"unknown={sorted(observed - expected)!r}."
        )
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise HistoricalMarketCalendarError(f"{label} must be a nonempty string.")
    if unicodedata.normalize("NFC", value) != value:
        raise HistoricalMarketCalendarError(f"{label} must be Unicode NFC.")
    return value


def _parse_date(value: Any, *, label: str) -> date:
    text = _require_string(value, label=label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise HistoricalMarketCalendarError(
            f"{label} must be a canonical ISO date."
        ) from exc
    if parsed.isoformat() != text:
        raise HistoricalMarketCalendarError(f"{label} is not canonical.")
    return parsed


def _parse_session(value: Any, *, index: int) -> HistoricalMarketSession:
    item = _require_exact_keys(value, _SESSION_KEYS, label=f"sessions[{index}]")
    trading_date = _parse_date(item["date"], label=f"sessions[{index}].date")
    early_close = item["early_close"]
    if type(early_close) is not bool:
        raise HistoricalMarketCalendarError(
            f"sessions[{index}].early_close must be boolean."
        )

    expected_open = datetime.combine(trading_date, time(9, 30), _NEW_YORK)
    expected_close = datetime.combine(
        trading_date, time(13 if early_close else 16), _NEW_YORK
    )
    expected_open_utc = expected_open.astimezone(timezone.utc)
    expected_close_utc = expected_close.astimezone(timezone.utc)
    expected_text = {
        "regular_open_local": expected_open.isoformat(),
        "regular_close_local": expected_close.isoformat(),
        "regular_open_utc": expected_open_utc.isoformat().replace("+00:00", "Z"),
        "regular_close_utc": expected_close_utc.isoformat().replace("+00:00", "Z"),
    }
    for field, expected in expected_text.items():
        if item[field] != expected:
            raise HistoricalMarketCalendarError(
                f"sessions[{index}].{field} is not the authoritative boundary."
            )

    return HistoricalMarketSession(
        trading_date=trading_date,
        regular_open=expected_open,
        regular_close=expected_close,
        regular_open_utc=expected_open_utc,
        regular_close_utc=expected_close_utc,
        early_close=early_close,
    )


def _parse_sources(value: Any) -> tuple[HistoricalCalendarSource, ...]:
    if not isinstance(value, list):
        raise HistoricalMarketCalendarError("sources must be an array.")
    sources: list[HistoricalCalendarSource] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _require_exact_keys(raw, _SOURCE_KEYS, label=f"sources[{index}]")
        source = HistoricalCalendarSource(
            source_id=_require_string(item["source_id"], label="source_id"),
            publisher=_require_string(item["publisher"], label="publisher"),
            title=_require_string(item["title"], label="title"),
            url=_require_string(item["url"], label="url"),
        )
        if source.source_id in seen:
            raise HistoricalMarketCalendarError(
                f"Duplicate source identity: {source.source_id}."
            )
        seen.add(source.source_id)
        sources.append(source)
    if frozenset(seen) != EXPECTED_SOURCE_IDS:
        raise HistoricalMarketCalendarError(
            "Historical calendar source identities are incomplete or unexpected."
        )
    return tuple(sources)


def _parse_exceptional_closures(
    value: Any, *, source_ids: frozenset[str]
) -> tuple[ExceptionalClosure, ...]:
    if not isinstance(value, list):
        raise HistoricalMarketCalendarError("exceptional_closures must be an array.")
    closures: list[ExceptionalClosure] = []
    for index, raw in enumerate(value):
        item = _require_exact_keys(
            raw, _EXCEPTION_KEYS, label=f"exceptional_closures[{index}]"
        )
        closure = ExceptionalClosure(
            trading_date=_parse_date(item["date"], label="exceptional closure date"),
            reason=_require_string(item["reason"], label="exceptional closure reason"),
            source_id=_require_string(
                item["source_id"], label="exceptional closure source_id"
            ),
        )
        if closure.source_id not in source_ids:
            raise HistoricalMarketCalendarError(
                "Exceptional closure references unknown source evidence."
            )
        closures.append(closure)
    observed = {
        closure.trading_date: (closure.reason, closure.source_id)
        for closure in closures
    }
    if len(observed) != len(closures) or observed != EXPECTED_EXCEPTIONAL_CLOSURES:
        raise HistoricalMarketCalendarError(
            "Exceptional closure evidence differs from the frozen authority."
        )
    return tuple(closures)


def _load_manifest_bytes(raw: bytes) -> FrozenHistoricalMarketCalendar:
    envelope = _strict_json(raw)
    _require_exact_keys(envelope, _ENVELOPE_KEYS, label="manifest envelope")
    if raw != _canonical_bytes(envelope):
        raise HistoricalMarketCalendarError(
            "Historical calendar manifest bytes are not canonical."
        )

    content = _require_exact_keys(
        envelope["content"], _CONTENT_KEYS, label="manifest content"
    )
    fingerprint = envelope["content_fingerprint"]
    if not isinstance(fingerprint, str) or not _SHA256_PATTERN.fullmatch(fingerprint):
        raise HistoricalMarketCalendarError(
            "Historical calendar content fingerprint is malformed."
        )
    computed = _content_fingerprint(content)
    if fingerprint != computed:
        raise HistoricalMarketCalendarError(
            "Historical calendar content fingerprint does not match."
        )
    if fingerprint != FROZEN_CALENDAR_CONTENT_FINGERPRINT:
        raise HistoricalMarketCalendarError(
            "Historical calendar content is not the governed frozen authority."
        )

    if type(content["schema_version"]) is not int or content["schema_version"] != SCHEMA_VERSION:
        raise HistoricalMarketCalendarError("Unsupported historical calendar schema.")
    if content["calendar_semantic_version"] != CALENDAR_SEMANTIC_VERSION:
        raise HistoricalMarketCalendarError("Unexpected calendar semantic version.")
    if content["canonicalization_contract"] != CANONICALIZATION_CONTRACT:
        raise HistoricalMarketCalendarError("Unexpected canonicalization contract.")
    if content["timezone_identity"] != TIMEZONE_IDENTITY:
        raise HistoricalMarketCalendarError("Unexpected historical calendar timezone.")
    if _parse_date(content["covered_start"], label="covered_start") != COVERED_START:
        raise HistoricalMarketCalendarError("Unexpected historical calendar start.")
    if _parse_date(content["covered_end"], label="covered_end") != COVERED_END:
        raise HistoricalMarketCalendarError("Unexpected historical calendar end.")
    if type(content["session_count"]) is not int or content["session_count"] != SESSION_COUNT:
        raise HistoricalMarketCalendarError("Unexpected historical calendar session count.")

    market = _require_exact_keys(
        content["market_identity"], _MARKET_KEYS, label="market_identity"
    )
    if dict(market) != EXPECTED_MARKET_IDENTITY:
        raise HistoricalMarketCalendarError("Unexpected market/exchange identity.")

    sources = _parse_sources(content["sources"])
    source_ids = frozenset(source.source_id for source in sources)
    exceptional_closures = _parse_exceptional_closures(
        content["exceptional_closures"], source_ids=source_ids
    )

    raw_sessions = content["sessions"]
    if not isinstance(raw_sessions, list) or len(raw_sessions) != SESSION_COUNT:
        raise HistoricalMarketCalendarError("Historical session list is incomplete.")
    sessions = tuple(
        _parse_session(item, index=index) for index, item in enumerate(raw_sessions)
    )
    session_dates = tuple(session.trading_date for session in sessions)
    if session_dates != tuple(sorted(set(session_dates))):
        raise HistoricalMarketCalendarError(
            "Historical session dates must be unique and strictly increasing."
        )
    if session_dates[0] != COVERED_START or session_dates[-1] != COVERED_END:
        raise HistoricalMarketCalendarError(
            "Historical session list does not span the governed endpoints."
        )
    if any(day in session_dates for day in EXPECTED_EXCEPTIONAL_CLOSURES):
        raise HistoricalMarketCalendarError(
            "Exceptional full closure appears in the historical session list."
        )
    early_closes = frozenset(
        session.trading_date for session in sessions if session.early_close
    )
    if early_closes != EXPECTED_EARLY_CLOSES:
        raise HistoricalMarketCalendarError(
            "Historical early-close evidence differs from the frozen authority."
        )

    return FrozenHistoricalMarketCalendar(
        schema_version=SCHEMA_VERSION,
        calendar_semantic_version=CALENDAR_SEMANTIC_VERSION,
        market_identity=tuple(sorted(EXPECTED_MARKET_IDENTITY.items())),
        timezone_identity=TIMEZONE_IDENTITY,
        covered_start=COVERED_START,
        covered_end=COVERED_END,
        sessions=sessions,
        exceptional_closures=exceptional_closures,
        sources=sources,
        canonicalization_contract=CANONICALIZATION_CONTRACT,
        content_fingerprint=fingerprint,
    )


def load_frozen_historical_calendar() -> FrozenHistoricalMarketCalendar:
    """Load and strictly validate the exact committed historical authority."""
    try:
        raw = FROZEN_HISTORICAL_CALENDAR_PATH.read_bytes()
    except FileNotFoundError as exc:
        raise HistoricalMarketCalendarError(
            f"Frozen historical calendar is missing: {FROZEN_HISTORICAL_CALENDAR_PATH}"
        ) from exc
    except OSError as exc:
        raise HistoricalMarketCalendarError(
            "Frozen historical calendar could not be read."
        ) from exc
    return _load_manifest_bytes(raw)
