"""Non-destructive repair overlays for the six audited false-closed sessions."""

from __future__ import annotations

import hashlib
import json
import re
import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from qpx_bot.historical_market_calendar import FROZEN_CALENDAR_CONTENT_FINGERPRINT
from qpx_bot.ml_historical_acquisition import (
    ACQUISITION_PROVENANCE_VERSION,
    ADJUSTMENT,
    BARS_URL,
    BAR_COLUMNS,
    FEED,
    DEFAULT_ROOT,
    LIVE_REQUESTS_PER_MINUTE,
    PAGE_LIMIT,
    PROVIDER_INPUT_SEMANTIC_VERSION,
    REQUESTS_PER_MINUTE,
    REJECTION_CATEGORIES,
    TIMEFRAME,
    Acquisition,
    AlpacaHistoricalClient,
    ProviderError,
    atomic_bytes,
    atomic_json,
    batch_descriptor,
    canonical_provider_asset_id,
    classify_bar,
    encode_gzip_csv,
    encode_gzip_jsonl,
    fingerprint,
    partition_population_disposition,
    rejection_record,
    request_identity,
    sha256_path,
)


CALENDAR_REPAIR_SCHEMA_VERSION = 1
CALENDAR_REPAIR_SEMANTIC_VERSION = "QPX_HISTORICAL_FALSE_CLOSED_SESSIONS_V1"
CALENDAR_REPAIR_PAGE_SCHEMA_VERSION = 1
CALENDAR_REPAIR_SESSIONS = tuple(
    date.fromisoformat(value)
    for value in (
        "2017-06-19",
        "2018-06-19",
        "2019-06-19",
        "2020-06-19",
        "2021-06-18",
        "2021-12-31",
    )
)
AUDITED_FALSE_OPEN_DATES = (date(2018, 12, 5), date(2025, 1, 9))


def _existing_repair(directory: Path) -> dict[str, Any] | None:
    manifests = sorted(directory.glob("*.manifest.json")) if directory.exists() else []
    if not manifests:
        return None
    if len(manifests) != 1:
        raise RuntimeError("Calendar-repair final evidence is ambiguous.")
    try:
        manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Calendar-repair final manifest is corrupt.") from exc
    core = {key: value for key, value in manifest.items() if key != "repair_fingerprint"}
    base = manifests[0].with_name(manifests[0].name.removesuffix(".manifest.json"))
    accepted = base.with_suffix(".csv.gz")
    rejected = base.with_suffix(".rejections.jsonl.gz")
    if (
        manifest.get("repair_fingerprint") != fingerprint(core)
        or manifest.get("accepted_patch_sha256") != sha256_path(accepted)
        or manifest.get("rejection_evidence_sha256") != sha256_path(rejected)
    ):
        raise RuntimeError("Calendar-repair final evidence is corrupt.")
    return manifest


def _load_repair_pages(staging: Path, context_fingerprint: str) -> list[dict[str, Any]]:
    if not staging.exists():
        return []
    paths = sorted(staging.glob("session=*/page-*.json"))
    bundles: list[dict[str, Any]] = []
    for path in paths:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Calendar-repair durable page is corrupt.") from exc
        core = {key: item for key, item in value.items() if key != "bundle_fingerprint"}
        page = value.get("page_evidence")
        page_core = (
            {key: item for key, item in page.items() if key != "page_evidence_fingerprint"}
            if isinstance(page, Mapping) else {}
        )
        if (
            value.get("schema_version") != CALENDAR_REPAIR_PAGE_SCHEMA_VERSION
            or value.get("calendar_repair_semantic_version") != CALENDAR_REPAIR_SEMANTIC_VERSION
            or value.get("repair_context_fingerprint") != context_fingerprint
            or value.get("bundle_fingerprint") != fingerprint(core)
            or not isinstance(page, Mapping)
            or page.get("page_evidence_fingerprint") != fingerprint(page_core)
            or not isinstance(value.get("accepted_rows"), list)
            or not isinstance(value.get("rejection_records"), list)
            or page.get("accepted_row_count") != len(value["accepted_rows"])
            or page.get("rejected_row_count") != len(value["rejection_records"])
            or page.get("source_row_count")
            != len(value["accepted_rows"]) + len(value["rejection_records"])
        ):
            raise RuntimeError("Calendar-repair durable page identity is invalid.")
        bundles.append(value)
    bundles.sort(key=lambda value: int(value["page_evidence"]["page"]))
    if [int(value["page_evidence"]["page"]) for value in bundles] != list(
        range(1, len(bundles) + 1)
    ):
        raise RuntimeError("Calendar-repair durable page sequence is invalid.")
    prior_next_by_session: dict[str, str | None] = {}
    terminal_by_session: dict[str, bool] = {}
    last_session_index = -1
    observed_keys: set[tuple[str, str]] = set()
    observed_rejections: set[tuple[int, int]] = set()
    for value in bundles:
        page = value["page_evidence"]
        session = str(value.get("session_date"))
        targets = value.get("target_sessions")
        if not isinstance(targets, list) or session not in targets:
            raise RuntimeError("Calendar-repair durable page session is invalid.")
        session_index = targets.index(session)
        if session_index < last_session_index:
            raise RuntimeError("Calendar-repair durable page session order is invalid.")
        if session_index > last_session_index and last_session_index >= 0:
            previous_session = targets[last_session_index]
            if not terminal_by_session.get(previous_session):
                raise RuntimeError("Calendar-repair durable page skips an unfinished session.")
        last_session_index = session_index
        input_token = value.get("input_page_token")
        next_token = value.get("next_page_token")
        expected_input = prior_next_by_session.get(session)
        counts = {category: 0 for category in REJECTION_CATEGORIES}
        if (
            page.get("session_date") != session
            or input_token != page.get("input_page_token")
            or input_token != expected_input
            or page.get("next_page_token_fingerprint")
            != (fingerprint({"page_token": next_token}) if next_token else None)
            or (page.get("terminal_page") is True) != (next_token is None)
            or value.get("provider_request_fingerprint")
            != request_identity(value["request_core"], value["session_batch_fingerprint"])
            or page.get("request_fingerprint") != fingerprint({
                "schema_version": CALENDAR_REPAIR_SCHEMA_VERSION,
                "calendar_repair_semantic_version": CALENDAR_REPAIR_SEMANTIC_VERSION,
                "original_manifest_fingerprint": value["original_manifest_fingerprint"],
                "provider_request_fingerprint": value["provider_request_fingerprint"],
                "session_date": session,
            })
        ):
            raise RuntimeError("Calendar-repair durable page token/request chain is invalid.")
        for row in value["accepted_rows"]:
            key = (str(row.get("provider_asset_id")), str(row.get("market_timestamp")))
            if key in observed_keys:
                raise RuntimeError("Calendar-repair durable pages contain duplicate observations.")
            observed_keys.add(key)
        for record in value["rejection_records"]:
            core = {key: item for key, item in record.items() if key != "rejection_fingerprint"}
            key = (record.get("page"), record.get("source_row_ordinal"))
            category = record.get("rejection_category")
            if (
                key in observed_rejections
                or category not in counts
                or record.get("rejection_fingerprint") != fingerprint(core)
                or record.get("request_fingerprint") != page.get("request_fingerprint")
            ):
                raise RuntimeError("Calendar-repair durable rejection evidence is invalid.")
            observed_rejections.add(key)
            counts[category] += 1
        if counts != page.get("rejection_counts_by_category"):
            raise RuntimeError("Calendar-repair durable rejection counts are invalid.")
        prior_next_by_session[session] = next_token
        terminal_by_session[session] = next_token is None
    return bundles


def _validate_original_partition(root: Path, item: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    year, batch = int(item["year"]), int(item["batch"])
    part_id = f"year={year}/batch={batch:05d}"
    path = root / "bars_15m" / f"year={year}" / f"batch={batch:05d}.csv.gz"
    manifest_path = path.with_suffix(path.suffix + ".manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Original partition evidence is missing or corrupt: {part_id}.") from exc
    if manifest.get("partition") != part_id or manifest.get("sha256") != sha256_path(path):
        raise RuntimeError(f"Original partition identity/checksum mismatch: {part_id}.")
    claimed = manifest.get("manifest_fingerprint")
    if claimed != fingerprint({key: value for key, value in manifest.items() if key != "manifest_fingerprint"}):
        raise RuntimeError(f"Original partition manifest fingerprint mismatch: {part_id}.")
    if manifest.get("schema_version") not in {1, 2, 3}:
        raise RuntimeError(f"Unsupported original partition schema: {part_id}.")
    return path, manifest


class HistoricalCalendarRepair:
    """Acquire immutable overlays while retaining each original partition unchanged."""

    def __init__(
        self,
        root: Path,
        client: AlpacaHistoricalClient,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        capacity_probe: Callable[[datetime], Mapping[str, Any]] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"now": now}
        if capacity_probe is not None:
            kwargs["capacity_probe"] = capacity_probe
        self.acquisition = Acquisition(root, client, **kwargs)
        self.root = self.acquisition.root
        self.client = client
        self.now = now

    def repair_partition(self, state: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
        year, batch = int(item["year"]), int(item["batch"])
        part_id = f"year={year}/batch={batch:05d}"
        targets = [value for value in CALENDAR_REPAIR_SESSIONS if value.year == year]
        if not targets:
            raise RuntimeError(f"Partition has no governed calendar-repair session: {part_id}.")
        _original_path, original_manifest = _validate_original_partition(self.root, item)
        original_manifest_fp = original_manifest["manifest_fingerprint"]
        population = self.acquisition._provider_population()
        final_directory = self.root / "calendar_repairs" / f"year={year}" / f"batch={batch:05d}"
        existing = _existing_repair(final_directory)
        if existing is not None:
            if (
                existing.get("schema_version") != CALENDAR_REPAIR_SCHEMA_VERSION
                or existing.get("calendar_repair_semantic_version") != CALENDAR_REPAIR_SEMANTIC_VERSION
                or existing.get("partition") != part_id
                or existing.get("original_manifest_fingerprint") != original_manifest_fp
                or existing.get("target_sessions") != [value.isoformat() for value in targets]
                or existing.get("security_master_fingerprint") != population["security_master_fingerprint"]
                or existing.get("provider_population_fingerprint") != population["provider_population_fingerprint"]
                or existing.get("ambiguous_exclusion_set_fingerprint")
                != population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"]
                or existing.get("frozen_calendar_fingerprint") != FROZEN_CALENDAR_CONTENT_FINGERPRINT
            ):
                raise RuntimeError("Calendar-repair final evidence belongs to another identity.")
            return existing
        provider_rejections = list(state.get("unqueryable_symbols", ()))
        context_core = {
            "schema_version": CALENDAR_REPAIR_PAGE_SCHEMA_VERSION,
            "calendar_repair_semantic_version": CALENDAR_REPAIR_SEMANTIC_VERSION,
            "partition": part_id,
            "original_manifest_fingerprint": original_manifest_fp,
            "target_sessions": [value.isoformat() for value in targets],
            "security_master_fingerprint": population["security_master_fingerprint"],
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "ambiguous_exclusion_set_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
            "initial_provider_rejections_fingerprint": fingerprint(provider_rejections),
        }
        context_fingerprint = fingerprint(context_core)
        staging = self.root / "calendar_repairs" / "durable_pages" / context_fingerprint
        durable_pages = _load_repair_pages(staging, context_fingerprint)
        all_rows: dict[tuple[str, str], dict[str, Any]] = {}
        all_rejections: list[dict[str, Any]] = []
        page_evidence: list[dict[str, Any]] = []
        request_fingerprints: list[str] = []
        session_batch_fingerprints: list[str] = []
        page_number = 0

        for bundle in durable_pages:
            page = bundle["page_evidence"]
            page_number += 1
            if page["page"] != page_number:
                raise RuntimeError("Calendar-repair durable page order is invalid.")
            for row in bundle["accepted_rows"]:
                key = (row["provider_asset_id"], row["market_timestamp"])
                if key in all_rows:
                    raise RuntimeError("Duplicate observation across durable calendar-repair pages.")
                all_rows[key] = row
            all_rejections.extend(bundle["rejection_records"])
            page_evidence.append(page)
            provider_rejections = list(bundle["provider_rejections"])

        for session_date in targets:
            while True:
                disposition = partition_population_disposition(item, population, provider_rejections)
                descriptor = batch_descriptor(
                    year=year,
                    start=session_date,
                    end=session_date,
                    symbols=item["symbols"],
                    asset_ids=item["asset_ids"],
                )
                identity = {
                    member["canonical_symbol"]: member["provider_asset_id"]
                    for member in disposition["requested_members"]
                }
                request_core = {
                    "symbols": ",".join(identity),
                    "timeframe": TIMEFRAME,
                    "start": session_date.isoformat() + "T00:00:00Z",
                    "end": (session_date + timedelta(days=1)).isoformat() + "T00:00:00Z",
                    "limit": str(PAGE_LIMIT),
                    "feed": FEED,
                    "adjustment": ADJUSTMENT,
                    "sort": "asc",
                }
                provider_request_fp = request_identity(request_core, descriptor["batch_fingerprint"])
                repair_request_fp = fingerprint({
                    "schema_version": CALENDAR_REPAIR_SCHEMA_VERSION,
                    "calendar_repair_semantic_version": CALENDAR_REPAIR_SEMANTIC_VERSION,
                    "original_manifest_fingerprint": original_manifest_fp,
                    "provider_request_fingerprint": provider_request_fp,
                    "session_date": session_date.isoformat(),
                })
                break

            request_fingerprints.append(repair_request_fp)
            session_batch_fingerprints.append(descriptor["batch_fingerprint"])
            if not identity:
                continue
            session_pages = [
                bundle for bundle in durable_pages
                if bundle["page_evidence"]["session_date"] == session_date.isoformat()
            ]
            if any(
                bundle["page_evidence"]["session_date"] not in {
                    value.isoformat() for value in targets
                }
                for bundle in durable_pages
            ):
                raise RuntimeError("Calendar-repair durable page has an unexpected session.")
            if session_pages:
                latest = session_pages[-1]
                provider_rejections = list(latest["provider_rejections"])
                disposition = partition_population_disposition(item, population, provider_rejections)
                identity = {
                    member["canonical_symbol"]: member["provider_asset_id"]
                    for member in disposition["requested_members"]
                }
                request_core = dict(latest["request_core"])
                provider_request_fp = str(latest["provider_request_fingerprint"])
                repair_request_fp = str(latest["page_evidence"]["request_fingerprint"])
                request_fingerprints[-1] = repair_request_fp
                if latest["page_evidence"]["terminal_page"]:
                    continue
                token = latest.get("next_page_token")
            else:
                token = None
            seen_tokens: set[str] = set()
            if token:
                seen_tokens.add(token)
            while True:
                params = dict(request_core)
                if token:
                    params["page_token"] = token
                assessment = self.acquisition._capacity_assessment(provider_request=True)
                mode = assessment.get("mode")
                if mode not in {"OFF_MARKET", "LIVE_COEXISTENCE"}:
                    raise RuntimeError("REAL_DATA_EXECUTION_DEFERRED_BY_EXISTING_LIFECYCLE")
                self.acquisition._set_request_rate(
                    LIVE_REQUESTS_PER_MINUTE if mode == "LIVE_COEXISTENCE"
                    else REQUESTS_PER_MINUTE
                )
                try:
                    payload = self.client.request(BARS_URL, params)
                except ProviderError as exc:
                    invalid = re.search(r"invalid symbol:\s*([^\"}\s]+)", str(exc), re.IGNORECASE)
                    bad_symbol = invalid.group(1).upper() if invalid else None
                    if exc.status != 400 or bad_symbol not in identity or token:
                        raise
                    rejected_asset_id = identity[bad_symbol]
                    if any(key[0] == rejected_asset_id for key in all_rows):
                        raise RuntimeError(
                            "Provider rejection conflicts with already accepted repair evidence."
                        )
                    provider_rejections.append({
                        "symbol": bad_symbol,
                        "provider_asset_id": rejected_asset_id,
                        "reason": "PROVIDER_REJECTED_SYMBOL",
                    })
                    disposition = partition_population_disposition(item, population, provider_rejections)
                    identity = {
                        member["canonical_symbol"]: member["provider_asset_id"]
                        for member in disposition["requested_members"]
                    }
                    request_core["symbols"] = ",".join(identity)
                    provider_request_fp = request_identity(request_core, descriptor["batch_fingerprint"])
                    repair_request_fp = fingerprint({
                        "schema_version": CALENDAR_REPAIR_SCHEMA_VERSION,
                        "calendar_repair_semantic_version": CALENDAR_REPAIR_SEMANTIC_VERSION,
                        "original_manifest_fingerprint": original_manifest_fp,
                        "provider_request_fingerprint": provider_request_fp,
                        "session_date": session_date.isoformat(),
                    })
                    request_fingerprints[-1] = repair_request_fp
                    if identity:
                        continue
                    break
                if not isinstance(payload, dict) or not isinstance(payload.get("bars"), dict):
                    raise ProviderError("Malformed calendar-repair bars response.", systemic=True)
                unexpected = sorted(symbol for symbol in payload["bars"] if symbol not in identity)
                if unexpected:
                    raise ProviderError(
                        f"Unexpected provider response symbols: {unexpected}", systemic=True
                    )
                page_number += 1
                source = accepted = 0
                page_rows: list[dict[str, Any]] = []
                counts = {category: 0 for category in REJECTION_CATEGORIES}
                page_now = self.now()
                for symbol in sorted(payload["bars"]):
                    rows = payload["bars"][symbol]
                    if not isinstance(rows, list):
                        raise ProviderError("Malformed calendar-repair row collection.", systemic=True)
                    for raw in rows:
                        source += 1
                        outcome = classify_bar(
                            raw,
                            symbol,
                            identity[symbol],
                            repair_request_fp,
                            session_date,
                            session_date,
                            page_now,
                            self.acquisition.historical_calendar,
                        )
                        if outcome.outcome == "ACCEPTED":
                            assert outcome.accepted_row is not None
                            key = (
                                outcome.accepted_row["provider_asset_id"],
                                outcome.accepted_row["market_timestamp"],
                            )
                            if key in all_rows:
                                raise RuntimeError(f"Duplicate calendar-repair observation: {key}.")
                            all_rows[key] = outcome.accepted_row
                            page_rows.append(outcome.accepted_row)
                            accepted += 1
                        else:
                            counts[outcome.outcome] += 1
                            all_rejections.append(rejection_record(
                                raw=raw,
                                outcome=outcome,
                                partition=f"calendar-repair:{part_id}",
                                page=page_number,
                                ordinal=source - 1,
                                symbol=symbol,
                                asset_id=identity[symbol],
                                request_fingerprint=repair_request_fp,
                                batch_fingerprint=descriptor["batch_fingerprint"],
                                calendar_fingerprint=FROZEN_CALENDAR_CONTENT_FINGERPRINT,
                            ))
                rejected = source - accepted
                page_core = {
                    "page": page_number,
                    "session_date": session_date.isoformat(),
                    "request_fingerprint": repair_request_fp,
                    "input_page_token": token,
                    "source_row_count": source,
                    "accepted_row_count": accepted,
                    "rejected_row_count": rejected,
                    "rejection_counts_by_category": counts,
                    "terminal_page": payload.get("next_page_token") is None,
                    "next_page_token_fingerprint": (
                        fingerprint({"page_token": payload.get("next_page_token")})
                        if payload.get("next_page_token") else None
                    ),
                }
                page_record = {
                    **page_core, "page_evidence_fingerprint": fingerprint(page_core)
                }
                next_token = payload.get("next_page_token")
                bundle_core = {
                    **context_core,
                    "repair_context_fingerprint": context_fingerprint,
                    "session_date": session_date.isoformat(),
                    "request_core": request_core,
                    "provider_request_fingerprint": provider_request_fp,
                    "session_batch_fingerprint": descriptor["batch_fingerprint"],
                    "page_evidence": page_record,
                    "accepted_rows": page_rows,
                    "rejection_records": all_rejections[-rejected:] if rejected else [],
                    "provider_rejections": provider_rejections,
                    "input_page_token": token,
                    "next_page_token": next_token,
                }
                # Persist the complete validated page before advancing its provider token.
                bundle = {**bundle_core, "bundle_fingerprint": fingerprint(bundle_core)}
                durable_path = staging / f"session={session_date.isoformat()}" / f"page-{page_number:06d}.json"
                if durable_path.exists():
                    raise RuntimeError("Calendar-repair durable page identity already exists.")
                atomic_json(durable_path, bundle)
                durable_pages.append(bundle)
                session_pages.append(bundle)
                page_evidence.append(page_record)
                token = next_token
                if token is not None and (not isinstance(token, str) or not token):
                    raise ProviderError("Malformed calendar-repair page token.", systemic=True)
                if token is not None and token in seen_tokens:
                    raise ProviderError("Repeated calendar-repair page token.", systemic=True)
                if token is not None:
                    seen_tokens.add(token)
                if not token:
                    break

        disposition = partition_population_disposition(item, population, provider_rejections)
        ordered = [all_rows[key] for key in sorted(all_rows)]
        source_count = sum(page["source_row_count"] for page in page_evidence)
        rejected_count = len(all_rejections)
        if source_count != len(ordered) + rejected_count:
            raise RuntimeError("Calendar-repair source-row reconciliation failed.")
        counts = {category: 0 for category in REJECTION_CATEGORIES}
        for record in all_rejections:
            counts[record["rejection_category"]] += 1
        accepted_bytes = encode_gzip_csv(ordered, BAR_COLUMNS)
        rejection_bytes = encode_gzip_jsonl(all_rejections)
        repair_core = {
            "schema_version": CALENDAR_REPAIR_SCHEMA_VERSION,
            "calendar_repair_semantic_version": CALENDAR_REPAIR_SEMANTIC_VERSION,
            "acquisition_provenance_version": ACQUISITION_PROVENANCE_VERSION,
            "provider_input_semantic_version": PROVIDER_INPUT_SEMANTIC_VERSION,
            "partition": part_id,
            "original_manifest_fingerprint": original_manifest_fp,
            "target_sessions": [value.isoformat() for value in targets],
            "request_fingerprints": request_fingerprints,
            "session_batch_fingerprints": session_batch_fingerprints,
            "planned_membership_fingerprint": fingerprint({
                "members": sorted(
                    (
                        {
                            "provider_asset_id": canonical_provider_asset_id(asset_id),
                            "canonical_symbol": str(symbol).strip().upper(),
                        }
                        for symbol, asset_id in zip(item["symbols"], item["asset_ids"])
                    ),
                    key=lambda member: (
                        member["provider_asset_id"], member["canonical_symbol"]
                    ),
                ),
                "partition": part_id,
            }),
            "provider_population_fingerprint": population["provider_population_fingerprint"],
            "security_master_fingerprint": population["security_master_fingerprint"],
            "ambiguous_exclusion_set_fingerprint": population["ambiguous_exclusion_set"]["exclusion_set_fingerprint"],
            "population_disposition": disposition,
            "population_disposition_fingerprint": disposition["population_disposition_fingerprint"],
            "frozen_calendar_fingerprint": FROZEN_CALENDAR_CONTENT_FINGERPRINT,
            "source_row_count": source_count,
            "accepted_row_count": len(ordered),
            "rejected_row_count": rejected_count,
            "rejection_counts_by_category": counts,
            "page_evidence": page_evidence,
            "accepted_patch_sha256": hashlib.sha256(accepted_bytes).hexdigest(),
            "rejection_evidence_sha256": hashlib.sha256(rejection_bytes).hexdigest(),
            "rejection_evidence_fingerprint": fingerprint(all_rejections),
            "synthetic_bars": False,
            "forward_fill": False,
            "timestamp_substitution": False,
        }
        repair_fp = fingerprint(repair_core)
        base = self.root / "calendar_repairs" / f"year={year}" / f"batch={batch:05d}" / repair_fp
        accepted_path = base.with_suffix(".csv.gz")
        rejection_path = base.with_suffix(".rejections.jsonl.gz")
        manifest_path = base.with_suffix(".manifest.json")
        for path, encoded in ((accepted_path, accepted_bytes), (rejection_path, rejection_bytes)):
            if path.exists() and path.read_bytes() != encoded:
                raise RuntimeError("Content-addressed calendar-repair artifact conflicts.")
            if not path.exists():
                atomic_bytes(path, encoded)
        manifest = {**repair_core, "repair_fingerprint": repair_fp}
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise RuntimeError("Content-addressed calendar-repair manifest conflicts.")
        if not manifest_path.exists():
            atomic_json(manifest_path, manifest)
        return manifest


def applicable_repair_partitions(state: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    completed = set(state.get("completed", ()))
    years = {value.year for value in CALENDAR_REPAIR_SESSIONS}
    return [
        item for item in state.get("partitions", ())
        if int(item["year"]) in years
        and f"year={int(item['year'])}/batch={int(item['batch']):05d}" in completed
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    acquisition = Acquisition(args.root)
    state = acquisition.load_state()
    if (
        state is None
        or state.get("partitions_complete") != state.get("partitions_total")
        or state.get("corporate_action_status") != "COMPLETE"
    ):
        raise RuntimeError("Historical acquisition prerequisites are incomplete.")
    repair = HistoricalCalendarRepair(
        args.root, acquisition.client, capacity_probe=acquisition.capacity_probe,
    )
    items = applicable_repair_partitions(state)
    for index, item in enumerate(items, 1):
        manifest = repair.repair_partition(state, item)
        print(json.dumps({
            "completed": index, "total": len(items),
            "partition": manifest["partition"],
            "repair_fingerprint": manifest["repair_fingerprint"],
            "accepted_row_count": manifest["accepted_row_count"],
            "rejected_row_count": manifest["rejected_row_count"],
        }, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
