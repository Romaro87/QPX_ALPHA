"""Durable targeted identity enrichment for historical corporate actions."""
from __future__ import annotations

import json
import urllib.parse
import argparse
from pathlib import Path
from typing import Any, Iterable, Mapping

from qpx_bot.ml_historical_acquisition import (
    ASSET_URL, CORPORATE_ACTION_URL, Acquisition, DEFAULT_ROOT, PROVIDER,
    atomic_content_addressed_json, atomic_json, canonical_provider_asset_id,
    fingerprint, load_provider_population, read_gzip_jsonl, sha256_path,
)

IDENTITY_ENRICHMENT_SCHEMA_VERSION = 1
IDENTITY_ENRICHMENT_SEMANTIC_VERSION = "ALPACA_CA_CUSIP_ISIN_TARGETED_V1"
IDENTITY_ENRICHMENT_BATCH_SIZE = 1000
IDENTITY_FIELD_NAMES = ("symbol", "old_symbol", "new_symbol")


def _canonical_token(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Provider {label} identity value is not text.")
    return value.strip().upper() or None


def _identity_fields(raw: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in raw.items():
        lowered = str(key).lower()
        if (
            lowered in IDENTITY_FIELD_NAMES
            or lowered == "cusip" or lowered.endswith("_cusip")
            or lowered == "isin" or lowered.endswith("_isin")
        ):
            if value is not None and not isinstance(value, str):
                raise RuntimeError(f"Provider corporate-action {key} is not text.")
            result[str(key)] = value
    return dict(sorted(result.items()))


def _response_records(payload: Any, requested_ids: set[str]) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("corporate_actions"), Mapping):
        raise RuntimeError("Malformed targeted corporate-action response.")
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    for collection, records in sorted(payload["corporate_actions"].items()):
        if not isinstance(records, list):
            raise RuntimeError("Malformed targeted corporate-action collection.")
        action_type = collection.removesuffix("s")
        for raw in records:
            if not isinstance(raw, Mapping):
                raise RuntimeError("Malformed targeted corporate-action record.")
            event_id = raw.get("id")
            if not isinstance(event_id, str) or not event_id.strip():
                raise RuntimeError("Targeted corporate-action record has no provider ID.")
            event_id = event_id.strip()
            if event_id not in requested_ids:
                raise RuntimeError("Targeted corporate-action response contains an unexpected ID.")
            if event_id in seen:
                raise RuntimeError("Targeted corporate-action response contains a duplicate ID.")
            seen.add(event_id)
            core = {
                "provider_event_id": event_id,
                "action_type": action_type,
                "identity_fields": _identity_fields(raw),
                "raw_provider_record_fingerprint": fingerprint(raw),
            }
            values.append({**core, "record_fingerprint": fingerprint(core)})
    return sorted(values, key=lambda item: item["provider_event_id"])


def _validate_bundle(path: Path, expected_core: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Identity-enrichment durable batch is corrupt.") from exc
    core = {key: item for key, item in value.items() if key != "bundle_fingerprint"}
    if value.get("bundle_fingerprint") != fingerprint(core):
        raise RuntimeError("Identity-enrichment durable batch fingerprint is invalid.")
    for key, item in expected_core.items():
        if value.get(key) != item:
            raise RuntimeError("Identity-enrichment durable batch identity mismatch.")
    records = value.get("records")
    if not isinstance(records, list):
        raise RuntimeError("Identity-enrichment durable batch records are malformed.")
    requested = set(value["requested_provider_event_ids"])
    if requested:
        returned = [item.get("provider_event_id") for item in records if isinstance(item, Mapping)]
        if len(returned) != len(set(returned)) or not set(returned).issubset(requested):
            raise RuntimeError("Identity-enrichment durable batch event IDs are invalid.")
        if value.get("missing_provider_event_ids") != sorted(requested - set(returned)):
            raise RuntimeError("Identity-enrichment durable batch missing-ID evidence is invalid.")
    return value


def _asset_facts(raw: Mapping[str, Any]) -> dict[str, Any]:
    asset_id = canonical_provider_asset_id(raw.get("id", ""))
    if str(raw.get("class")) != "us_equity":
        raise RuntimeError("Identity snapshot contains a non-US-equity asset.")
    return {
        "provider_asset_id": asset_id,
        "symbol": _canonical_token(raw.get("symbol"), "asset symbol"),
        "cusip": _canonical_token(raw.get("cusip"), "asset CUSIP"),
        "isin": _canonical_token(raw.get("isin"), "asset ISIN"),
        "status": raw.get("status"),
        "provider_response_fingerprint": fingerprint(raw),
    }


def acquire_identity_enrichment(
    acquisition: Acquisition, state: dict[str, Any], target_event_ids: Iterable[str],
) -> dict[str, Any]:
    root = acquisition.root
    population = acquisition._provider_population()
    target_ids = sorted(set(target_event_ids))
    if not target_ids:
        raise RuntimeError("Identity enrichment has no target provider event IDs.")
    artifact_path = root / str(state["corporate_action_artifact_path"])
    source_records = read_gzip_jsonl(artifact_path)
    source_ids = {record["provider_event_id"] for record in source_records}
    if not set(target_ids).issubset(source_ids):
        raise RuntimeError("Identity-enrichment targets are outside the corporate-action archive.")
    target_core = {
        "schema_version": IDENTITY_ENRICHMENT_SCHEMA_VERSION,
        "semantic_version": IDENTITY_ENRICHMENT_SEMANTIC_VERSION,
        "provider": PROVIDER,
        "corporate_action_artifact_sha256": sha256_path(artifact_path),
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "target_provider_event_ids": target_ids,
        "batch_size": IDENTITY_ENRICHMENT_BATCH_SIZE,
    }
    target_fp = fingerprint(target_core)
    evidence_root = root / "corporate_actions" / "identity_enrichment" / target_fp
    batches_root = evidence_root / "event_batches"
    all_records: dict[str, dict[str, Any]] = {}
    batch_fps: list[str] = []
    provider_requests = 0
    for offset in range(0, len(target_ids), IDENTITY_ENRICHMENT_BATCH_SIZE):
        batch_number = offset // IDENTITY_ENRICHMENT_BATCH_SIZE + 1
        ids = target_ids[offset:offset + IDENTITY_ENRICHMENT_BATCH_SIZE]
        request_core = {
            "provider": PROVIDER, "endpoint": CORPORATE_ACTION_URL,
            "params": {"ids": ",".join(ids), "limit": str(len(ids))},
        }
        request_fp = fingerprint(request_core)
        expected = {
            "schema_version": IDENTITY_ENRICHMENT_SCHEMA_VERSION,
            "semantic_version": IDENTITY_ENRICHMENT_SEMANTIC_VERSION,
            "target_fingerprint": target_fp, "batch": batch_number,
            "requested_provider_event_ids": ids, "request_core": request_core,
            "request_fingerprint": request_fp,
        }
        path = batches_root / f"batch-{batch_number:06d}.json"
        if path.exists():
            bundle = _validate_bundle(path, expected)
        else:
            acquisition._capacity_gate(state, {"year": "corporate_action_identity_enrichment", "batch": batch_number})
            payload = acquisition.client.request(CORPORATE_ACTION_URL, request_core["params"])
            provider_requests += 1
            if isinstance(payload, Mapping) and payload.get("next_page_token") is not None:
                raise RuntimeError("Targeted corporate-action ID response unexpectedly paginated.")
            records = _response_records(payload, set(ids))
            core = {
                **expected, "records": records,
                "returned_provider_event_ids": [item["provider_event_id"] for item in records],
                "missing_provider_event_ids": sorted(set(ids) - {item["provider_event_id"] for item in records}),
                "provider_response_fingerprint": fingerprint(payload),
            }
            bundle = {**core, "bundle_fingerprint": fingerprint(core)}
            atomic_json(path, bundle)
        for record in bundle["records"]:
            event_id = record["provider_event_id"]
            if event_id in all_records:
                raise RuntimeError("Duplicate event ID across identity-enrichment batches.")
            all_records[event_id] = record
        batch_fps.append(bundle["bundle_fingerprint"])

    # Current active and inactive asset responses are durable identity evidence,
    # not a replacement for the frozen provider population.
    snapshot_records: dict[str, dict[str, Any]] = {}
    snapshot_fps: list[str] = []
    for status in ("active", "inactive"):
        request_core = {"provider": PROVIDER, "endpoint": ASSET_URL, "params": {"status": status, "asset_class": "us_equity"}}
        request_fp = fingerprint(request_core); path = evidence_root / f"asset-snapshot-{status}.json"
        expected = {"schema_version": IDENTITY_ENRICHMENT_SCHEMA_VERSION, "semantic_version": IDENTITY_ENRICHMENT_SEMANTIC_VERSION, "target_fingerprint": target_fp, "request_core": request_core, "request_fingerprint": request_fp}
        if path.exists(): bundle = _validate_bundle(path, expected)
        else:
            acquisition._capacity_gate(state, {"year": "identity_asset_snapshot", "batch": 0})
            payload = acquisition.client.request(ASSET_URL, request_core["params"]); provider_requests += 1
            if not isinstance(payload, list) or any(not isinstance(item, Mapping) for item in payload): raise RuntimeError("Malformed provider asset snapshot.")
            records = sorted((_asset_facts(item) for item in payload), key=lambda item:item["provider_asset_id"])
            core = {**expected, "requested_provider_event_ids": [], "records": records, "missing_provider_event_ids": [], "provider_response_fingerprint": fingerprint(payload)}
            bundle = {**core, "bundle_fingerprint": fingerprint(core)}; atomic_json(path,bundle)
        for record in bundle["records"]:
            asset_id=record["provider_asset_id"]
            if asset_id in snapshot_records and snapshot_records[asset_id] != record: raise RuntimeError("Conflicting provider asset snapshot identity.")
            snapshot_records[asset_id]=record
        snapshot_fps.append(bundle["bundle_fingerprint"])

    by_token: dict[tuple[str,str], set[str]] = {}
    for asset in snapshot_records.values():
        for kind in ("cusip","isin"):
            token=asset.get(kind)
            if token: by_token.setdefault((kind,token),set()).add(asset["provider_asset_id"])
    cusips = sorted({_canonical_token(v,"corporate-action CUSIP") for record in all_records.values() for k,v in record["identity_fields"].items() if k.lower()=="cusip" or k.lower().endswith("_cusip")} - {None})
    lookup_fps: list[str] = []
    for index,cusip in enumerate(cusips,1):
        if by_token.get(("cusip",cusip)): continue
        request_core={"provider":PROVIDER,"endpoint":f"{ASSET_URL}/{{cusip}}","cusip":cusip}; request_fp=fingerprint(request_core); path=evidence_root/"cusip_lookups"/f"{fingerprint({'cusip':cusip})}.json"
        expected={"schema_version":IDENTITY_ENRICHMENT_SCHEMA_VERSION,"semantic_version":IDENTITY_ENRICHMENT_SEMANTIC_VERSION,"target_fingerprint":target_fp,"request_core":request_core,"request_fingerprint":request_fp,"queried_cusip":cusip}
        if path.exists(): bundle=_validate_bundle(path,expected)
        else:
            acquisition._capacity_gate(state,{"year":"identity_cusip_lookup","batch":index})
            try:
                payload=acquisition.client.request(f"{ASSET_URL}/{urllib.parse.quote(cusip,safe='')}",{}); provider_requests+=1
                if not isinstance(payload,Mapping): raise RuntimeError("Malformed CUSIP asset lookup response.")
                records=[_asset_facts(payload)]; lookup_status="PROVIDER_ASSET_MATCH"
            except Exception as exc:
                if getattr(exc,"status",None)!=404: raise
                provider_requests+=1; records=[]; lookup_status="NO_PROVIDER_ASSET_LOOKUP_RESULT"; payload={"http_status":404}
            core={**expected,"requested_provider_event_ids":[],"records":records,"missing_provider_event_ids":[],"lookup_status":lookup_status,"provider_response_fingerprint":fingerprint(payload)}
            bundle={**core,"bundle_fingerprint":fingerprint(core)}; atomic_json(path,bundle)
        if bundle.get("lookup_status")=="PROVIDER_ASSET_MATCH":
            for asset in bundle["records"]: by_token.setdefault(("cusip",cusip),set()).add(asset["provider_asset_id"])
        lookup_fps.append(bundle["bundle_fingerprint"])

    enriched=[]
    for event_id in target_ids:
        record=all_records.get(event_id); tokens=[]
        if record:
            for field,value in record["identity_fields"].items():
                lowered=field.lower(); kind="cusip" if lowered=="cusip" or lowered.endswith("_cusip") else "isin" if lowered=="isin" or lowered.endswith("_isin") else None
                token=_canonical_token(value,f"corporate-action {field}") if kind else None
                if token:
                    ids=sorted(by_token.get((kind,token),()))
                    status="PROVIDER_ASSET_MATCH" if ids else "NO_PROVIDER_ASSET_LOOKUP_RESULT" if kind=="cusip" else "NO_PROVIDER_ASSET_SNAPSHOT_MATCH"
                    tokens.append({"field":field,"kind":kind,"value":token,"provider_asset_ids":ids,"lookup_status":status})
        core={"provider_event_id":event_id,"identity_tokens":sorted(tokens,key=lambda x:(x["kind"],x["field"],x["value"])),"targeted_record_fingerprint":record.get("record_fingerprint") if record else None}
        enriched.append({**core,"record_fingerprint":fingerprint(core)})
    core={**target_core,"target_fingerprint":target_fp,"event_batch_fingerprints":batch_fps,"asset_snapshot_fingerprints":snapshot_fps,"cusip_lookup_fingerprints":lookup_fps,"records":enriched}
    result={**core,"identity_enrichment_fingerprint":fingerprint(core)}
    path=atomic_content_addressed_json(evidence_root/"artifacts",result["identity_enrichment_fingerprint"],result,label="identity enrichment")
    state["corporate_action_identity_enrichment_path"]=str(path.relative_to(root)); state["corporate_action_identity_enrichment_fingerprint"]=result["identity_enrichment_fingerprint"]; acquisition.save_state(state)
    return result


def load_identity_enrichment(root: Path, state: Mapping[str, Any], population: Mapping[str, Any], source_records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    path=root/str(state["corporate_action_identity_enrichment_path"])
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: raise RuntimeError("Corporate-action identity enrichment is missing or corrupt.") from exc
    core={k:v for k,v in value.items() if k != "identity_enrichment_fingerprint"}
    if value.get("schema_version")!=IDENTITY_ENRICHMENT_SCHEMA_VERSION or value.get("semantic_version")!=IDENTITY_ENRICHMENT_SEMANTIC_VERSION or value.get("identity_enrichment_fingerprint")!=fingerprint(core) or value.get("identity_enrichment_fingerprint")!=state.get("corporate_action_identity_enrichment_fingerprint") or value.get("provider_population_fingerprint")!=population["provider_population_fingerprint"] or value.get("corporate_action_artifact_sha256")!=sha256_path(root/str(state["corporate_action_artifact_path"])):
        raise RuntimeError("Corporate-action identity enrichment validation failed.")
    source_ids={record["provider_event_id"] for record in source_records}
    if set(value.get("target_provider_event_ids",()))-source_ids: raise RuntimeError("Identity enrichment references an unknown event.")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    acquisition = Acquisition(args.root)
    state = acquisition.load_state()
    if state is None or state.get("corporate_action_status") != "COMPLETE":
        raise RuntimeError("Corporate-action acquisition is not complete.")
    resolution_path = args.root / str(state["corporate_action_identity_resolution_path"])
    resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
    target_ids = [
        record["provider_event_id"]
        for record in resolution.get("records", ())
        if record.get("outcome") == "UNRESOLVED_CORPORATE_ACTION_IDENTITY"
        and (
            not record.get("excluded_provider_asset_ids")
            or not record.get("bounded_dates")
        )
    ]
    result = acquire_identity_enrichment(acquisition, state, target_ids)
    from qpx_bot.ml_historical_acquisition import rebuild_corporate_action_identity_resolution
    rebuilt = rebuild_corporate_action_identity_resolution(args.root, state)
    acquisition.save_state(state)
    print(json.dumps({
        "identity_enrichment_fingerprint": result["identity_enrichment_fingerprint"],
        "target_event_count": len(target_ids),
        "resolved_count": rebuilt["resolved_count"],
        "unresolved_count": rebuilt["unresolved_count"],
        "identity_resolution_fingerprint": rebuilt["identity_resolution_fingerprint"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
