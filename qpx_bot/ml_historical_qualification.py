"""Independent mechanical eligibility gate for the historical ML reservoir.

This module validates acquisition evidence and emits attestations.  It never
downloads data, starts training, or mutates acquisition state.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from qpx_bot.historical_market_calendar import (
    FROZEN_CALENDAR_CONTENT_FINGERPRINT,
    FrozenHistoricalMarketCalendar,
    load_frozen_historical_calendar,
)
from qpx_bot.ml_historical_acquisition import (
    BAR_COLUMNS,
    CA_TYPES,
    CORPORATE_ACTION_EVIDENCE_SCHEMA_VERSION,
    CORPORATE_ACTION_IDENTITY_RESOLUTION_SCHEMA_VERSION,
    CORPORATE_ACTION_SEMANTIC_VERSION,
    LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION,
    REJECTION_CATEGORIES,
    Acquisition,
    atomic_content_addressed_json,
    batch_descriptor,
    canonical_provider_asset_id,
    corporate_action_identity_resolution,
    fingerprint,
    load_provider_population,
    observational_coverage_evidence,
    partition_population_disposition,
    read_gzip_csv,
    read_gzip_jsonl,
    sha256_path,
)
from qpx_bot.ml_historical_calendar_repair import (
    CALENDAR_REPAIR_SCHEMA_VERSION,
    CALENDAR_REPAIR_SEMANTIC_VERSION,
    CALENDAR_REPAIR_SESSIONS,
)
from qpx_bot.paper_state import read_checksummed_state


QUALIFICATION_SCHEMA_VERSION = 1
QUALIFICATION_SEMANTIC_VERSION = "QPX_ML_HISTORICAL_QUALIFICATION_V1"
LEGACY_AUDIT_SCHEMA_VERSION = 1
PROVIDER_SCOPED_V1_IDENTITY = "ALPACA_ENUMERATED_US_EQUITY_PROVIDER_POPULATION_V1"
MISSINGNESS_POLICY = "UNAVAILABLE_OBSERVATION_UNKNOWN_REASON"
MISSINGNESS_ATTESTATION = (
    "MISSING_OBSERVATIONS_ARE_NOT_INTERPRETED_AS_NONEXISTENCE_OR_ZERO_ACTIVITY"
)
SOURCE_LEGACY = "LEGACY_VALIDATED_ACCEPTED_DATA"
SOURCE_V3 = "V3_ACCEPTED_DATA"
SOURCE_REPAIR = "CALENDAR_REPAIR_DATA"


class HistoricalQualificationError(RuntimeError):
    """Required qualification evidence is missing, corrupt, or inconsistent."""


class _NoNetworkClient:
    request_count = 0
    retry_count = 0

    def request(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Historical qualification has no provider network authority.")


def _load_state(root: Path) -> dict[str, Any]:
    path = root / "acquisition_state" / "state.json"
    checksum = path.with_suffix(".sha256")
    try:
        value = json.loads(read_checksummed_state(path, checksum, label="Historical acquisition state"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HistoricalQualificationError("Acquisition state is missing or corrupt.") from exc
    if not isinstance(value, dict):
        raise HistoricalQualificationError("Acquisition state root is malformed.")
    return value


def _partition_id(item: Mapping[str, Any]) -> str:
    return f"year={int(item['year'])}/batch={int(item['batch']):05d}"


def _partition_paths(root: Path, item: Mapping[str, Any]) -> tuple[Path, Path]:
    path = root / "bars_15m" / f"year={int(item['year'])}" / f"batch={int(item['batch']):05d}.csv.gz"
    return path, path.with_suffix(path.suffix + ".manifest.json")


def _validate_partition_manifest(path: Path, manifest_path: Path, part_id: str) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalQualificationError(f"Partition manifest is missing/corrupt: {part_id}.") from exc
    if manifest.get("partition") != part_id or manifest.get("sha256") != sha256_path(path):
        raise HistoricalQualificationError(f"Partition checksum/identity mismatch: {part_id}.")
    schema = manifest.get("schema_version")
    if schema not in {1, 2, 3}:
        raise HistoricalQualificationError(f"Unsupported partition schema: {part_id}.")
    excluded = {"manifest_fingerprint"}
    if schema == 3:
        excluded.add("completed_at_utc")
    core = {key: value for key, value in manifest.items() if key not in excluded}
    if manifest.get("manifest_fingerprint") != fingerprint(core):
        raise HistoricalQualificationError(f"Partition manifest fingerprint mismatch: {part_id}.")
    return manifest


def _partition_bounds(item: Mapping[str, Any], state: Mapping[str, Any]) -> tuple[date, date]:
    requested = state["requested_range"]
    year = int(item["year"])
    return (
        max(date(year, 1, 1), date.fromisoformat(requested["actual_first_requested_session"])),
        min(date(year, 12, 31), date.fromisoformat(requested["actual_last_completed_session"])),
    )


def _validate_partition_plan(state: Mapping[str, Any], population: Mapping[str, Any]) -> None:
    partitions = state.get("partitions")
    if not isinstance(partitions, list) or state.get("partitions_total") != len(partitions):
        raise HistoricalQualificationError("Partition plan count is inconsistent.")
    if partitions != sorted(partitions, key=lambda item: (int(item["year"]), int(item["batch"]))):
        raise HistoricalQualificationError("Partition plan ordering is not canonical.")
    population_members = {
        (member["provider_asset_id"], member["canonical_symbol"])
        for member in population["members"]
    }
    requested = state.get("requested_range", {})
    try:
        first_year = date.fromisoformat(requested["actual_first_requested_session"]).year
        last_year = date.fromisoformat(requested["actual_last_completed_session"]).year
    except (KeyError, TypeError, ValueError) as exc:
        raise HistoricalQualificationError("Partition plan range is malformed.") from exc
    by_year: dict[int, list[Mapping[str, Any]]] = {}
    identities: set[str] = set()
    for item in partitions:
        part_id = _partition_id(item)
        if part_id in identities:
            raise HistoricalQualificationError("Partition plan contains duplicate identity.")
        identities.add(part_id)
        by_year.setdefault(int(item["year"]), []).append(item)
    if set(by_year) != set(range(first_year, last_year + 1)):
        raise HistoricalQualificationError("Partition plan year coverage is incomplete.")
    for year, items in by_year.items():
        observed: list[tuple[str, str]] = []
        batches: list[int] = []
        for item in items:
            symbols, asset_ids = item.get("symbols"), item.get("asset_ids")
            if not isinstance(symbols, list) or not isinstance(asset_ids, list) or len(symbols) != len(asset_ids):
                raise HistoricalQualificationError("Partition plan membership is malformed.")
            batches.append(int(item["batch"]))
            observed.extend(
                (canonical_provider_asset_id(asset_id), str(symbol).strip().upper())
                for symbol, asset_id in zip(symbols, asset_ids)
            )
        if batches != list(range(len(items))) or len(observed) != len(set(observed)):
            raise HistoricalQualificationError(f"Partition plan batches are not canonical for {year}.")
        if set(observed) != population_members:
            raise HistoricalQualificationError(f"Partition plan does not reconcile provider population for {year}.")


def _accepted_row_error(
    row: Mapping[str, Any], *, expected_members: Mapping[str, str],
    start: date, end: date, calendar: FrozenHistoricalMarketCalendar,
    expected_request_fingerprint: str | None,
) -> str | None:
    if set(row) != set(BAR_COLUMNS):
        return "MALFORMED_ACCEPTED_ROW_SCHEMA"
    asset_id = str(row.get("provider_asset_id", ""))
    symbol = str(row.get("observation_symbol", ""))
    if expected_members.get(asset_id) != symbol:
        return "PROVIDER_IDENTITY_OR_MEMBERSHIP_MISMATCH"
    if (row.get("provider"), row.get("feed"), row.get("adjustment")) != ("alpaca", "sip", "raw"):
        return "PROVIDER_PROVENANCE_MISMATCH"
    if expected_request_fingerprint is not None and row.get("request_fingerprint") != expected_request_fingerprint:
        return "REQUEST_FINGERPRINT_MISMATCH"
    try:
        stamp = datetime.fromisoformat(str(row["market_timestamp"]))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return "BAD_TIMESTAMP"
        if stamp.minute % 15 or stamp.second or stamp.microsecond:
            return "OFF_15M_GRID"
        if not start <= stamp.date() <= end:
            return "FUTURE_OR_OUT_OF_RANGE"
        session = calendar.session_on(stamp.date())
        if session is None:
            return "CALENDAR_REJECTED"
        local = stamp.astimezone(session.regular_open.tzinfo)
        if not session.regular_open <= local < session.regular_close:
            return "OUTSIDE_REGULAR_SESSION"
        if row.get("session_date") != local.date().isoformat():
            return "SESSION_DATE_MISMATCH"
        prices = [Decimal(str(row[name])) for name in ("open", "high", "low", "close")]
        volume = Decimal(str(row["volume"]))
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return "MALFORMED_ACCEPTED_NUMERIC"
    if any(not value.is_finite() for value in prices) or not volume.is_finite():
        return "MALFORMED_ACCEPTED_NUMERIC"
    if min(prices) <= 0 or prices[1] < max(prices[0], prices[2], prices[3]) or prices[2] > min(prices[0], prices[1], prices[3]):
        return "INVALID_OHLC"
    if volume < 0 or volume != volume.to_integral_value():
        return "INVALID_VOLUME"
    return None


def audit_legacy_partition(
    root: Path, state: Mapping[str, Any], item: Mapping[str, Any],
    population: Mapping[str, Any], calendar: FrozenHistoricalMarketCalendar,
    *, additional_excluded_provider_ids: Iterable[str] = (), write: bool = True,
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    part_id = _partition_id(item)
    path, manifest_path = _partition_paths(root, item)
    manifest = _validate_partition_manifest(path, manifest_path, part_id)
    if manifest["schema_version"] not in {1, 2}:
        raise HistoricalQualificationError(f"Legacy audit received non-legacy partition: {part_id}.")
    start, end = _partition_bounds(item, state)
    planned = sorted(
        ({"provider_asset_id": canonical_provider_asset_id(asset_id), "canonical_symbol": str(symbol).strip().upper()}
         for symbol, asset_id in zip(item["symbols"], item["asset_ids"])),
        key=lambda value: (value["provider_asset_id"], value["canonical_symbol"]),
    )
    if len(planned) != len(item["symbols"]):
        raise HistoricalQualificationError(f"Legacy planned membership is malformed: {part_id}.")
    expected = {value["provider_asset_id"]: value["canonical_symbol"] for value in planned}
    ambiguous_symbols = set(population["ambiguous_by_symbol"])
    ambiguous_ids = {
        asset_id for values in population["ambiguous_by_symbol"].values() for asset_id in values
    }
    governed_excluded_ids = {
        canonical_provider_asset_id(value) for value in additional_excluded_provider_ids
    }
    descriptor = batch_descriptor(
        year=int(item["year"]), start=start, end=end,
        symbols=item["symbols"], asset_ids=item["asset_ids"],
        provider_input_semantic_version=LEGACY_PROVIDER_INPUT_SEMANTIC_VERSION,
    )
    if manifest["schema_version"] == 2:
        if manifest.get("ordered_symbol_mapping") != descriptor["members"] or manifest.get("batch_fingerprint") != descriptor["batch_fingerprint"]:
            raise HistoricalQualificationError(f"Legacy V2 membership mismatch: {part_id}.")
    rows = read_gzip_csv(path)
    if manifest.get("row_count") != len(rows):
        raise HistoricalQualificationError(f"Legacy row-count mismatch: {part_id}.")
    eligible_keys: set[tuple[str, str]] = set()
    all_keys: set[tuple[str, str]] = set()
    ambiguous_row_count = 0
    governed_excluded_row_count = 0
    invalid_scopes: list[dict[str, Any]] = []
    for row in rows:
        key = (str(row.get("provider_asset_id", "")), str(row.get("market_timestamp", "")))
        if key in all_keys:
            invalid_scopes.append({"provider_asset_id": key[0], "market_timestamp": key[1], "reason": "DUPLICATE_ACCEPTED_OBSERVATION"})
            continue
        all_keys.add(key)
        if row.get("observation_symbol") in ambiguous_symbols or row.get("provider_asset_id") in ambiguous_ids:
            ambiguous_row_count += 1
            continue
        if row.get("provider_asset_id") in governed_excluded_ids:
            governed_excluded_row_count += 1
            continue
        error = _accepted_row_error(
            row, expected_members=expected, start=start, end=end, calendar=calendar,
            expected_request_fingerprint=str(manifest["request_fingerprint"]),
        )
        if error:
            invalid_scopes.append({
                "provider_asset_id": row.get("provider_asset_id"),
                "market_timestamp": row.get("market_timestamp"),
                "reason": error,
            })
        else:
            eligible_keys.add(key)
    audit_core = {
        "schema_version": LEGACY_AUDIT_SCHEMA_VERSION,
        "partition": part_id,
        "source_manifest_schema_version": manifest["schema_version"],
        "source_manifest_fingerprint": manifest["manifest_fingerprint"],
        "source_partition_sha256": manifest["sha256"],
        "source_request_fingerprint": manifest["request_fingerprint"],
        "reconstructed_planned_membership": descriptor["members"],
        "reconstructed_membership_fingerprint": descriptor["batch_fingerprint"],
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "ambiguous_exclusion_set_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
        "frozen_calendar_fingerprint": calendar.content_fingerprint,
        "accepted_row_count": len(rows),
        "eligible_accepted_row_count": len(eligible_keys),
        "ambiguous_identity_excluded_row_count": ambiguous_row_count,
        "governed_identity_excluded_row_count": governed_excluded_row_count,
        "invalid_accepted_scopes": invalid_scopes,
        "legacy_rejected_source_rows": "LEGACY_UNBOUNDED_REJECTION_EVIDENCE",
        "missing_observation_policy": MISSINGNESS_POLICY,
        "synthetic_bars": manifest.get("synthetic_bars"),
        "forward_fill": manifest.get("forward_fill"),
        "timestamp_substitution": manifest.get("timestamp_substitution"),
        "source_semantics_valid": (
            manifest.get("provider") == "alpaca"
            and manifest.get("feed") == "sip"
            and manifest.get("adjustment") == "raw"
            and (manifest.get("resolution") or manifest.get("timeframe")) == "15Min"
            and all(
                manifest.get(field) is False
                for field in ("synthetic_bars", "forward_fill", "timestamp_substitution")
            )
            and isinstance(manifest.get("request_fingerprint"), str)
            and len(manifest["request_fingerprint"]) == 64
        ),
        "result": "VALIDATED" if not invalid_scopes else "BOUNDED_INELIGIBLE_SCOPE",
    }
    if not audit_core["source_semantics_valid"]:
        audit_core["result"] = "BOUNDED_INELIGIBLE_SCOPE"
    audit = {**audit_core, "legacy_audit_fingerprint": fingerprint(audit_core)}
    if write:
        atomic_content_addressed_json(
            root / "qualification_evidence" / "legacy_partition_audits",
            audit["legacy_audit_fingerprint"], audit, label="legacy partition audit",
        )
    return audit, eligible_keys


def _load_repair(
    root: Path, item: Mapping[str, Any], original_manifest_fp: str,
    expected_members: Mapping[str, str], calendar: FrozenHistoricalMarketCalendar,
    population: Mapping[str, Any],
    additional_excluded_provider_ids: Iterable[str] = (),
) -> tuple[dict[str, Any], set[tuple[str, str]]]:
    directory = root / "calendar_repairs" / f"year={int(item['year'])}" / f"batch={int(item['batch']):05d}"
    manifests = sorted(directory.glob("*.manifest.json")) if directory.exists() else []
    if len(manifests) != 1:
        raise HistoricalQualificationError(f"Calendar repair evidence is missing or ambiguous: {_partition_id(item)}.")
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    core = {key: value for key, value in manifest.items() if key != "repair_fingerprint"}
    disposition = manifest.get("population_disposition")
    provider_rejections = (
        disposition.get("provider_rejected_exclusions", ())
        if isinstance(disposition, Mapping) else ()
    )
    expected_disposition = partition_population_disposition(
        item, population, provider_rejections,
    )
    target_dates = [
        value.isoformat() for value in CALENDAR_REPAIR_SESSIONS
        if value.year == int(item["year"])
    ]
    planned_membership_fingerprint = fingerprint({
        "members": sorted(
            (
                {
                    "provider_asset_id": canonical_provider_asset_id(asset_id),
                    "canonical_symbol": str(symbol).strip().upper(),
                }
                for symbol, asset_id in zip(item["symbols"], item["asset_ids"])
            ),
            key=lambda member: (member["provider_asset_id"], member["canonical_symbol"]),
        ),
        "partition": _partition_id(item),
    })
    session_batch_fingerprints = [
        batch_descriptor(
            year=int(item["year"]), start=value, end=value,
            symbols=item["symbols"], asset_ids=item["asset_ids"],
        )["batch_fingerprint"]
        for value in CALENDAR_REPAIR_SESSIONS if value.year == int(item["year"])
    ]
    if (
        manifest.get("schema_version") != CALENDAR_REPAIR_SCHEMA_VERSION
        or manifest.get("calendar_repair_semantic_version") != CALENDAR_REPAIR_SEMANTIC_VERSION
        or manifest.get("original_manifest_fingerprint") != original_manifest_fp
        or manifest.get("frozen_calendar_fingerprint") != calendar.content_fingerprint
        or manifest.get("repair_fingerprint") != fingerprint(core)
        or manifest.get("target_sessions") != target_dates
        or manifest.get("planned_membership_fingerprint") != planned_membership_fingerprint
        or manifest.get("session_batch_fingerprints") != session_batch_fingerprints
        or manifest.get("provider_population_fingerprint") != population["provider_population_fingerprint"]
        or manifest.get("security_master_fingerprint") != population["security_master_fingerprint"]
        or manifest.get("ambiguous_exclusion_set_fingerprint") != population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"]
        or disposition != expected_disposition
        or manifest.get("population_disposition_fingerprint") != expected_disposition["population_disposition_fingerprint"]
    ):
        raise HistoricalQualificationError(f"Calendar repair identity mismatch: {_partition_id(item)}.")
    base = manifests[0].with_name(manifests[0].name.removesuffix(".manifest.json"))
    accepted_path = base.with_suffix(".csv.gz")
    rejection_path = base.with_suffix(".rejections.jsonl.gz")
    if (
        manifest.get("accepted_patch_sha256") != sha256_path(accepted_path)
        or manifest.get("rejection_evidence_sha256") != sha256_path(rejection_path)
    ):
        raise HistoricalQualificationError(f"Calendar repair checksum mismatch: {_partition_id(item)}.")
    rows = read_gzip_csv(accepted_path)
    rejections = read_gzip_jsonl(rejection_path)
    if (
        len(rows) != manifest.get("accepted_row_count")
        or len(rejections) != manifest.get("rejected_row_count")
        or manifest.get("source_row_count") != len(rows) + len(rejections)
        or fingerprint(rejections) != manifest.get("rejection_evidence_fingerprint")
    ):
        raise HistoricalQualificationError(f"Calendar repair reconciliation mismatch: {_partition_id(item)}.")
    page_counts = {category: 0 for category in REJECTION_CATEGORIES}
    page_source = page_accepted = page_rejected = 0
    previous_next_token_fingerprint: str | None = None
    repair_pages = manifest.get("page_evidence", ())
    for index, page in enumerate(repair_pages, 1):
        page_core = {key: value for key, value in page.items() if key != "page_evidence_fingerprint"}
        expected_input_fingerprint = (
            fingerprint({"page_token": page.get("input_page_token")})
            if page.get("input_page_token") is not None else None
        )
        next_page = repair_pages[index] if index < len(repair_pages) else None
        expected_terminal = (
            next_page is None
            or next_page.get("session_date") != page.get("session_date")
        )
        if (
            page.get("page") != index
            or page.get("page_evidence_fingerprint") != fingerprint(page_core)
            or expected_input_fingerprint != previous_next_token_fingerprint
            or (page.get("terminal_page") is True)
            != expected_terminal
            or page.get("request_fingerprint") not in manifest.get("request_fingerprints", ())
        ):
            raise HistoricalQualificationError(f"Calendar repair page evidence is invalid: {_partition_id(item)}.")
        previous_next_token_fingerprint = page.get("next_page_token_fingerprint")
        if expected_terminal:
            if previous_next_token_fingerprint is not None:
                raise HistoricalQualificationError(f"Calendar repair terminal page is invalid: {_partition_id(item)}.")
            previous_next_token_fingerprint = None
        try:
            page_source += page["source_row_count"]
            page_accepted += page["accepted_row_count"]
            page_rejected += page["rejected_row_count"]
            for category in REJECTION_CATEGORIES:
                page_counts[category] += page["rejection_counts_by_category"][category]
        except (KeyError, TypeError) as exc:
            raise HistoricalQualificationError(f"Calendar repair page counts are invalid: {_partition_id(item)}.") from exc
    if (
        page_source != manifest["source_row_count"]
        or page_accepted != manifest["accepted_row_count"]
        or page_rejected != manifest["rejected_row_count"]
        or page_counts != manifest["rejection_counts_by_category"]
        or previous_next_token_fingerprint is not None
    ):
        raise HistoricalQualificationError(f"Calendar repair page totals are invalid: {_partition_id(item)}.")
    observed_rejections = {category: 0 for category in REJECTION_CATEGORIES}
    rejection_keys: set[tuple[Any, Any]] = set()
    for record in rejections:
        record_core = {key: value for key, value in record.items() if key != "rejection_fingerprint"}
        key = (record.get("page"), record.get("source_row_ordinal"))
        category = record.get("rejection_category")
        if (
            category not in REJECTION_CATEGORIES
            or key in rejection_keys
            or record.get("rejection_fingerprint") != fingerprint(record_core)
            or record.get("frozen_calendar_fingerprint") != calendar.content_fingerprint
            or record.get("request_fingerprint") not in manifest.get("request_fingerprints", ())
        ):
            raise HistoricalQualificationError(f"Calendar repair rejection evidence is invalid: {_partition_id(item)}.")
        rejection_keys.add(key)
        observed_rejections[category] += 1
    if observed_rejections != manifest["rejection_counts_by_category"]:
        raise HistoricalQualificationError(f"Calendar repair rejection categories are invalid: {_partition_id(item)}.")
    keys: set[tuple[str, str]] = set()
    observed_keys: set[tuple[str, str]] = set()
    excluded_ids = {
        canonical_provider_asset_id(value) for value in additional_excluded_provider_ids
    }
    targets = {value for value in CALENDAR_REPAIR_SESSIONS if value.year == int(item["year"])}
    for row in rows:
        error = _accepted_row_error(
            row, expected_members=expected_members,
            start=min(targets), end=max(targets), calendar=calendar,
            expected_request_fingerprint=None,
        )
        try:
            row_date = datetime.fromisoformat(row["market_timestamp"]).date()
        except (KeyError, ValueError):
            row_date = None
        if error or row_date not in targets:
            raise HistoricalQualificationError(f"Calendar repair contains invalid accepted row: {_partition_id(item)}.")
        key = (row["provider_asset_id"], row["market_timestamp"])
        if key in observed_keys:
            raise HistoricalQualificationError(f"Calendar repair contains duplicate accepted row: {_partition_id(item)}.")
        observed_keys.add(key)
        if row["provider_asset_id"] not in excluded_ids:
            keys.add(key)
    return manifest, keys


def _validate_corporate_actions(root: Path, state: Mapping[str, Any], population: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        manifest_path = root / str(state["corporate_action_manifest_path"])
        artifact_path = root / str(state["corporate_action_artifact_path"])
        resolution_path = root / str(state["corporate_action_identity_resolution_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        records = read_gzip_jsonl(artifact_path)
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise HistoricalQualificationError("Corporate-action evidence is missing or corrupt.") from exc
    manifest_core = {key: value for key, value in manifest.items() if key != "manifest_fingerprint"}
    pages = manifest.get("page_evidence")
    pages_valid = isinstance(pages, list) and len(pages) == manifest.get("page_count")
    previous_next_token_fingerprint: str | None = None
    page_event_ids: list[str] = []
    if pages_valid:
        for index, page in enumerate(pages, 1):
            page_core = {key: value for key, value in page.items() if key != "page_evidence_fingerprint"}
            expected_input_fingerprint = (
                fingerprint({"page_token": page.get("input_page_token")})
                if page.get("input_page_token") is not None else None
            )
            if (
                page.get("page") != index
                or page.get("request_fingerprint") != manifest.get("request_fingerprint")
                or page.get("page_evidence_fingerprint") != fingerprint(page_core)
                or (page.get("terminal_page") is True) != (index == len(pages))
                or expected_input_fingerprint != previous_next_token_fingerprint
                or not isinstance(page.get("provider_event_ids"), list)
            ):
                pages_valid = False
                break
            page_event_ids.extend(page["provider_event_ids"])
            previous_next_token_fingerprint = page.get("next_page_token_fingerprint")
        pages_valid = (
            pages_valid
            and previous_next_token_fingerprint is None
            and sorted(page_event_ids)
            == sorted(record.get("provider_event_id") for record in records)
        )
    if (
        manifest.get("schema_version") != CORPORATE_ACTION_EVIDENCE_SCHEMA_VERSION
        or manifest.get("corporate_action_semantic_version") != CORPORATE_ACTION_SEMANTIC_VERSION
        or manifest.get("manifest_fingerprint") != fingerprint(manifest_core)
        or manifest.get("manifest_fingerprint") != state.get("corporate_action_manifest_fingerprint")
        or manifest.get("artifact_sha256") != sha256_path(artifact_path)
        or manifest.get("corporate_action_artifact_fingerprint") != fingerprint(records)
        or manifest.get("event_count") != len(records)
        or manifest.get("supported_types") != list(CA_TYPES)
        or manifest.get("terminal_page_token") is not None
        or not pages_valid
        or manifest.get("requested_start") != state["requested_range"]["requested_start"]
        or manifest.get("requested_end") != state["requested_range"]["requested_end"]
        or len({record.get("provider_event_id") for record in records}) != len(records)
        or manifest.get("security_master_fingerprint") != population["security_master_fingerprint"]
        or manifest.get("provider_population_fingerprint") != population["provider_population_fingerprint"]
    ):
        raise HistoricalQualificationError("Corporate-action artifact/manifest validation failed.")
    resolution_core = {key: value for key, value in resolution.items() if key != "identity_resolution_fingerprint"}
    expected_resolution = corporate_action_identity_resolution(records, population)
    unresolved_unbounded = any(
        record.get("outcome") == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
        and not record.get("excluded_provider_asset_ids")
        and not record.get("bounded_dates")
        for record in resolution.get("records", ())
    )
    if (
        resolution.get("schema_version") != CORPORATE_ACTION_IDENTITY_RESOLUTION_SCHEMA_VERSION
        or resolution.get("identity_resolution_fingerprint") != fingerprint(resolution_core)
        or resolution != expected_resolution
        or manifest.get("identity_resolution_fingerprint") != resolution["identity_resolution_fingerprint"]
        or manifest.get("identity_resolution_sha256") != sha256_path(resolution_path)
        or unresolved_unbounded
    ):
        raise HistoricalQualificationError("Corporate-action identity-resolution validation failed.")
    return manifest, resolution


def _aggregate(values: Iterable[str]) -> str:
    return fingerprint(sorted(values))


def _qualify_historical_dataset_strict(
    root: Path, *, observed_at: datetime | None = None, write: bool = True,
) -> dict[str, Any]:
    """Evaluate exact evidence and optionally emit a content-addressed attestation."""
    root = root.resolve()
    observed = observed_at or datetime.now(timezone.utc)
    state = _load_state(root)
    calendar = load_frozen_historical_calendar()
    population = load_provider_population(root)
    _validate_partition_plan(state, population)
    reasons: list[str] = []
    planned = {_partition_id(item) for item in state.get("partitions", ())}
    completed_values = state.get("completed", ())
    completed = set(completed_values)
    if (
        state.get("status") != "COMPLETE"
        or planned != completed
        or len(completed_values) != len(completed)
        or state.get("partitions_complete") != len(completed)
    ):
        reasons.append("ACQUISITION_INCOMPLETE")
    if state.get("training_eligibility") == "TRAINING_ELIGIBLE":
        reasons.append("ACQUISITION_ILLEGALLY_CLAIMS_TRAINING_AUTHORITY")
    if state.get("corporate_action_status") != "COMPLETE":
        reasons.append("CORPORATE_ACTIONS_INCOMPLETE")

    inventory: list[dict[str, Any]] = []
    legacy_fps: list[str] = []
    v3_fps: list[str] = []
    repair_fps: list[str] = []
    acquisition_versions: list[str] = []
    explicit_exclusion_fps = [
        record["exclusion_fingerprint"]
        for record in population["ambiguous_exclusion_set"]["records"]
    ]
    provider_rejection_core = {
        "schema_version": 1,
        "reason": "PROVIDER_REJECTED_SYMBOL",
        "records": sorted(
            (
                {
                    "symbol": str(record.get("symbol", "")),
                    "provider_asset_id": str(record.get("provider_asset_id", "")),
                    "reason": str(record.get("reason", "")),
                    "observed_at_utc": record.get("observed_at_utc"),
                }
                for record in state.get("unqueryable_symbols", ())
            ),
            key=lambda record: (
                record["provider_asset_id"], record["symbol"],
                str(record["observed_at_utc"]),
            ),
        ),
    }
    provider_rejection_fp = fingerprint(provider_rejection_core)
    explicit_exclusion_fps.append(provider_rejection_fp)
    known_provider_ids = {member["provider_asset_id"] for member in population["members"]}
    if any(
        record["reason"] != "PROVIDER_REJECTED_SYMBOL"
        or record["provider_asset_id"] not in known_provider_ids
        or not record["symbol"]
        for record in provider_rejection_core["records"]
    ):
        reasons.append("PROVIDER_REJECTION_EVIDENCE_INVALID")
    corporate_manifest: dict[str, Any] | None = None
    corporate_resolution: dict[str, Any] | None = None
    coverage: dict[str, Any] | None = None
    corporate_excluded_ids: set[str] = set()

    if not reasons:
        population_path = root / "manifests" / "provider_populations" / f"{population['provider_population_fingerprint']}.json"
        exclusion_path = root / "manifests" / "provider_population_exclusions" / f"{population['ambiguous_exclusion_set']['exclusion_set_fingerprint']}.json"
        try:
            stored_population = json.loads(population_path.read_text(encoding="utf-8"))
            stored_exclusions = json.loads(exclusion_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stored_population = stored_exclusions = None
        if (
            stored_population != population["provider_population_evidence"]
            or stored_exclusions != population["ambiguous_exclusion_set"]
        ):
            reasons.append("PROVIDER_POPULATION_EVIDENCE_MISSING")
        try:
            coverage_path = root / str(state["observational_coverage_path"])
            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            coverage_core = {key: value for key, value in coverage.items() if key != "observational_coverage_fingerprint"}
            expected_coverage = observational_coverage_evidence(state, population)
            if (
                coverage.get("observational_coverage_fingerprint") != fingerprint(coverage_core)
                or coverage.get("observational_coverage_fingerprint") != state.get("observational_coverage_fingerprint")
                or coverage.get("security_master_fingerprint") != population["security_master_fingerprint"]
                or coverage.get("provider_population_fingerprint") != population["provider_population_fingerprint"]
                or coverage.get("frozen_calendar_fingerprint") != calendar.content_fingerprint
                or coverage != expected_coverage
            ):
                raise HistoricalQualificationError("Observational coverage identity mismatch.")
        except (KeyError, OSError, ValueError, json.JSONDecodeError, HistoricalQualificationError):
            reasons.append("OBSERVATIONAL_COVERAGE_EVIDENCE_INVALID")
        try:
            corporate_manifest, corporate_resolution = _validate_corporate_actions(root, state, population)
            explicit_exclusion_fps.extend(
                record["resolution_fingerprint"]
                for record in corporate_resolution["records"]
                if record["outcome"] == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
            )
            corporate_excluded_ids = {
                asset_id
                for record in corporate_resolution["records"]
                if record["outcome"] == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
                for asset_id in record["excluded_provider_asset_ids"]
            }
        except HistoricalQualificationError:
            reasons.append("CORPORATE_ACTION_EVIDENCE_INVALID")

    if not reasons:
        validator = Acquisition(root, _NoNetworkClient())
        for item in state["partitions"]:
            part_id = _partition_id(item)
            path, manifest_path = _partition_paths(root, item)
            manifest = _validate_partition_manifest(path, manifest_path, part_id)
            acquisition_versions.append(str(
                manifest.get("acquisition_provenance_version")
                or "QPX_ML_HISTORICAL_15M_V1_LEGACY_UNVERSIONED_MANIFEST"
            ))
            start, end = _partition_bounds(item, state)
            planned_members = {
                canonical_provider_asset_id(asset_id): str(symbol).strip().upper()
                for symbol, asset_id in zip(item["symbols"], item["asset_ids"])
            }
            if manifest["schema_version"] in {1, 2}:
                audit, keys = audit_legacy_partition(
                    root, state, item, population, calendar,
                    additional_excluded_provider_ids=corporate_excluded_ids,
                    write=write,
                )
                legacy_fps.append(audit["legacy_audit_fingerprint"])
                if audit["result"] != "VALIDATED" or audit["synthetic_bars"] or audit["forward_fill"] or audit["timestamp_substitution"]:
                    reasons.append(f"LEGACY_ACCEPTED_SCOPE_INELIGIBLE:{part_id}")
                inventory.append({
                    "partition": part_id,
                    "source_type": SOURCE_LEGACY,
                    "source_manifest_fingerprint": manifest["manifest_fingerprint"],
                    "audit_fingerprint": audit["legacy_audit_fingerprint"],
                    "eligible_row_count": len(keys),
                })
            else:
                context = validator._partition_context(state, item)
                checked, rows = validator._validate_committed_v3_partition(context, path, manifest_path)
                keys = {
                    (row["provider_asset_id"], row["market_timestamp"])
                    for row in rows
                    if row["provider_asset_id"] not in corporate_excluded_ids
                }
                for row in rows:
                    error = _accepted_row_error(
                        row, expected_members=planned_members, start=start, end=end,
                        calendar=calendar,
                        expected_request_fingerprint=checked["request_fingerprint"],
                    )
                    if error:
                        reasons.append(f"V3_ACCEPTED_SCOPE_INELIGIBLE:{part_id}:{error}")
                v3_fps.append(checked["manifest_fingerprint"])
                inventory.append({
                    "partition": part_id,
                    "source_type": SOURCE_V3,
                    "source_manifest_fingerprint": checked["manifest_fingerprint"],
                    "eligible_row_count": len(keys),
                })
            if int(item["year"]) in {value.year for value in CALENDAR_REPAIR_SESSIONS}:
                repair, repair_keys = _load_repair(
                    root, item, manifest["manifest_fingerprint"], planned_members, calendar,
                    population, corporate_excluded_ids,
                )
                if keys & repair_keys:
                    reasons.append(f"DUPLICATE_EFFECTIVE_OBSERVATION:{part_id}")
                repair_fps.append(repair["repair_fingerprint"])
                inventory.append({
                    "partition": part_id,
                    "source_type": SOURCE_REPAIR,
                    "source_manifest_fingerprint": repair["repair_fingerprint"],
                    "eligible_row_count": len(repair_keys),
                })

    inventory_fp = fingerprint(inventory)
    content = {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "qualification_semantic_version": QUALIFICATION_SEMANTIC_VERSION,
        "result": "TRAINING_ELIGIBLE" if not reasons else "NOT_TRAINING_ELIGIBLE",
        "reasons": sorted(set(reasons)),
        "provider_scope": PROVIDER_SCOPED_V1_IDENTITY,
        "missing_observation_policy": MISSINGNESS_POLICY,
        "missingness_attestation": MISSINGNESS_ATTESTATION,
        "synthetic_or_forward_filled_observations_permitted": False,
        "effective_dataset_inventory": inventory,
        "effective_dataset_inventory_fingerprint": inventory_fp,
        "security_master_fingerprint": population["security_master_fingerprint"],
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "ambiguous_exclusion_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
        "frozen_calendar_fingerprint": calendar.content_fingerprint,
        "observational_coverage_fingerprint": coverage.get("observational_coverage_fingerprint") if coverage else None,
        "corporate_action_artifact_fingerprint": corporate_manifest.get("corporate_action_artifact_fingerprint") if corporate_manifest else None,
        "corporate_action_identity_resolution_fingerprint": corporate_resolution.get("identity_resolution_fingerprint") if corporate_resolution else None,
        "legacy_audit_aggregate_fingerprint": _aggregate(legacy_fps),
        "v3_partition_aggregate_fingerprint": _aggregate(v3_fps),
        "calendar_repair_aggregate_fingerprint": _aggregate(repair_fps),
        "explicit_exclusion_aggregate_fingerprint": _aggregate(explicit_exclusion_fps),
        "provider_rejection_evidence_fingerprint": provider_rejection_fp,
        "acquisition_provenance_versions": sorted(set(acquisition_versions)),
        "acquisition_code_sha256": sha256_path(
            Path(__file__).with_name("ml_historical_acquisition.py")
        ),
        "qualification_code_sha256": sha256_path(Path(__file__)),
        "qualification_config_fingerprint": fingerprint({
            "qualification_semantic_version": QUALIFICATION_SEMANTIC_VERSION,
            "provider_scope": PROVIDER_SCOPED_V1_IDENTITY,
            "missing_observation_policy": MISSINGNESS_POLICY,
            "calendar_repair_sessions": [value.isoformat() for value in CALENDAR_REPAIR_SESSIONS],
        }),
    }
    qualification_fp = fingerprint(content)
    envelope = {
        "content": content,
        "qualification_fingerprint": qualification_fp,
        "observed_at_utc": observed.astimezone(timezone.utc).isoformat(),
    }
    if write:
        path = root / "qualification_evidence" / "attestations" / f"{qualification_fp}.json"
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("content") != content or existing.get("qualification_fingerprint") != qualification_fp:
                raise HistoricalQualificationError("Content-addressed qualification attestation conflicts.")
            envelope = existing
        else:
            atomic_content_addressed_json(
                path.parent, qualification_fp, envelope, label="historical qualification attestation",
            )
    return envelope


def qualify_historical_dataset(
    root: Path, *, observed_at: datetime | None = None, write: bool = True,
) -> dict[str, Any]:
    """Fail closed as a NOT attestation rather than leaking validation errors."""
    try:
        return _qualify_historical_dataset_strict(
            root, observed_at=observed_at, write=write,
        )
    except (HistoricalQualificationError, RuntimeError, OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        observed = observed_at or datetime.now(timezone.utc)
        content = {
            "schema_version": QUALIFICATION_SCHEMA_VERSION,
            "qualification_semantic_version": QUALIFICATION_SEMANTIC_VERSION,
            "result": "NOT_TRAINING_ELIGIBLE",
            "reasons": [f"EVIDENCE_VALIDATION_FAILED:{type(exc).__name__}"],
            "provider_scope": PROVIDER_SCOPED_V1_IDENTITY,
            "missing_observation_policy": MISSINGNESS_POLICY,
            "missingness_attestation": MISSINGNESS_ATTESTATION,
            "synthetic_or_forward_filled_observations_permitted": False,
            "effective_dataset_inventory": [],
            "effective_dataset_inventory_fingerprint": fingerprint([]),
            "security_master_fingerprint": None,
            "provider_population_fingerprint": None,
            "ambiguous_exclusion_fingerprint": None,
            "frozen_calendar_fingerprint": None,
            "observational_coverage_fingerprint": None,
            "corporate_action_artifact_fingerprint": None,
            "corporate_action_identity_resolution_fingerprint": None,
            "legacy_audit_aggregate_fingerprint": fingerprint([]),
            "v3_partition_aggregate_fingerprint": fingerprint([]),
            "calendar_repair_aggregate_fingerprint": fingerprint([]),
            "explicit_exclusion_aggregate_fingerprint": fingerprint([]),
            "provider_rejection_evidence_fingerprint": None,
            "acquisition_provenance_versions": [],
            "acquisition_code_sha256": None,
            "qualification_code_sha256": sha256_path(Path(__file__)),
            "qualification_config_fingerprint": fingerprint({
                "qualification_semantic_version": QUALIFICATION_SEMANTIC_VERSION,
                "provider_scope": PROVIDER_SCOPED_V1_IDENTITY,
                "missing_observation_policy": MISSINGNESS_POLICY,
                "calendar_repair_sessions": [value.isoformat() for value in CALENDAR_REPAIR_SESSIONS],
            }),
        }
        qualification_fp = fingerprint(content)
        envelope = {
            "content": content,
            "qualification_fingerprint": qualification_fp,
            "observed_at_utc": observed.astimezone(timezone.utc).isoformat(),
        }
        if write:
            path = root.resolve() / "qualification_evidence" / "attestations" / f"{qualification_fp}.json"
            if path.exists():
                existing = json.loads(path.read_text(encoding="utf-8"))
                if existing.get("content") != content:
                    raise HistoricalQualificationError(
                        "Content-addressed failed qualification attestation conflicts."
                    )
                return existing
            atomic_content_addressed_json(
                path.parent, qualification_fp, envelope,
                label="failed historical qualification attestation",
            )
        return envelope


def verify_training_eligibility_attestation(root: Path, attestation_path: Path) -> dict[str, Any]:
    """Re-evaluate bound inputs; validation has no training-launch authority."""
    try:
        stored = json.loads(attestation_path.read_text(encoding="utf-8"))
        content = stored["content"]
        claimed = stored["qualification_fingerprint"]
    except (OSError, KeyError, json.JSONDecodeError, TypeError) as exc:
        raise HistoricalQualificationError("Training-eligibility attestation is missing or corrupt.") from exc
    if claimed != fingerprint(content) or content.get("result") != "TRAINING_ELIGIBLE":
        raise HistoricalQualificationError("Attestation does not prove TRAINING_ELIGIBLE.")
    current = qualify_historical_dataset(root, write=False)
    if current["qualification_fingerprint"] != claimed:
        raise HistoricalQualificationError("Qualification inputs changed after attestation.")
    return stored
