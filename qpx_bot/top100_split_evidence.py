"""Build checksummed provider-identity and split evidence for frozen Top-100 replay.

This is a narrow evidence-repair builder.  It never requests price bars and it
does not alter the frozen selection, the reservoir acquisition state, or any
runtime service.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from qpx_bot.ml_historical_acquisition import (
    ASSET_URL,
    CORPORATE_ACTION_URL,
    Acquisition,
    DEFAULT_ROOT,
    fingerprint,
    load_provider_population,
    read_gzip_jsonl,
    sha256_path,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = (
    ROOT / "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json"
)
DEFAULT_OUTPUT = (
    ROOT / "qpx_bot/research_universes/alpaca_top100_asset_id_split_v1.json"
)
SCHEMA_VERSION = 1
SEMANTIC_VERSION = "QPX_FROZEN_TOP100_ASSET_ID_SPLIT_EVIDENCE_V1"
SPLIT_ACCOUNTING_VERSION = "QPX_CAUSAL_SPLIT_ACCOUNTING_V1"
SPLIT_ACTIONS = frozenset({"forward_split", "reverse_split"})
AMBIGUOUS_LABELS = frozenset({"ECHO", "EVLV", "HIVE", "PRME", "VISN"})


def _load_selection(path: Path) -> tuple[dict[str, Any], str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    claimed = value.get("manifest_fingerprint")
    core = {key: item for key, item in value.items() if key != "manifest_fingerprint"}
    if claimed != fingerprint(core):
        raise RuntimeError("Frozen Top-100 selection fingerprint is invalid.")
    members = value.get("top100")
    if (
        not isinstance(members, list)
        or len(members) != 100
        or len(set(members)) != 100
        or any(not isinstance(item, str) or item != item.strip().upper() for item in members)
    ):
        raise RuntimeError("Frozen Top-100 membership is not exactly 100 canonical labels.")
    return value, str(claimed)


def _name_change_components(records: Iterable[Mapping[str, Any]]) -> dict[str, set[str]]:
    parent: dict[str, str] = {}

    def find(symbol: str) -> str:
        parent.setdefault(symbol, symbol)
        while parent[symbol] != symbol:
            parent[symbol] = parent[parent[symbol]]
            symbol = parent[symbol]
        return symbol

    def union(left: str, right: str) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            if left_root > right_root:
                left_root, right_root = right_root, left_root
            parent[right_root] = left_root

    for record in records:
        for key in ("symbol", "old_symbol", "new_symbol"):
            value = record.get(key)
            if isinstance(value, str) and value:
                find(value)
        if record.get("action_type") == "name_change":
            old_symbol, new_symbol = record.get("old_symbol"), record.get("new_symbol")
            if isinstance(old_symbol, str) and isinstance(new_symbol, str):
                union(old_symbol, new_symbol)
    groups: dict[str, set[str]] = {}
    for symbol in parent:
        groups.setdefault(find(symbol), set()).add(symbol)
    return {symbol: groups[find(symbol)] for symbol in parent}


def _provider_asset_fact(raw: Mapping[str, Any]) -> dict[str, Any]:
    asset_id = str(raw.get("id", "")).strip()
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not asset_id or not symbol or raw.get("class") != "us_equity":
        raise RuntimeError("Targeted provider identity response is malformed.")
    return {
        "provider_asset_id": asset_id,
        "symbol": symbol,
        "name": raw.get("name"),
        "exchange": raw.get("exchange"),
        "status": raw.get("status"),
        "provider_response_fingerprint": fingerprint(raw),
    }


def _partition_rows(
    dataset: Path, state: Mapping[str, Any], asset_id: str,
) -> dict[str, tuple[str, str, str, str, str]]:
    result: dict[str, tuple[str, str, str, str, str]] = {}
    partitions = [item for item in state["partitions"] if asset_id in item["asset_ids"]]
    for item in partitions:
        path = dataset / (
            f"bars_15m/year={int(item['year'])}/batch={int(item['batch']):05d}.csv.gz"
        )
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row["provider_asset_id"] != asset_id:
                    continue
                result[row["market_timestamp"]] = (
                    row["open"], row["high"], row["low"], row["close"], row["volume"],
                )
    return result


def _source_rows(path: Path) -> dict[str, tuple[str, str, str, str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["TimestampMarket"]: (
                row["Open"], row["High"], row["Low"], row["Close"], row["Volume"],
            )
            for row in csv.DictReader(handle)
        }


def _overlap_evidence(
    *, dataset: Path, state: Mapping[str, Any], asset_id: str, source: Path,
) -> dict[str, Any]:
    source_values = _source_rows(source)
    reservoir_values = _partition_rows(dataset, state, asset_id)
    common = sorted(set(source_values) & set(reservoir_values))
    mismatches = [stamp for stamp in common if source_values[stamp] != reservoir_values[stamp]]
    if not common or mismatches:
        raise RuntimeError(
            f"Historical overlap failed for {source.name}: common={len(common)} "
            f"mismatches={len(mismatches)}."
        )
    core = {
        "source_path": str(source.relative_to(ROOT)),
        "source_sha256": sha256_path(source),
        "provider_asset_id": asset_id,
        "common_bar_count": len(common),
        "first_common_bar": common[0],
        "last_common_bar": common[-1],
        "mismatch_count": 0,
    }
    return {**core, "overlap_fingerprint": fingerprint(core)}


def _split_records(
    *, client: Any, event_ids: list[str], source_by_id: Mapping[str, Mapping[str, Any]],
    asset_by_event: Mapping[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request = {"ids": ",".join(event_ids), "limit": str(len(event_ids))}
    payload = client.request(CORPORATE_ACTION_URL, request)
    if not isinstance(payload, Mapping) or not isinstance(payload.get("corporate_actions"), Mapping):
        raise RuntimeError("Targeted split response is malformed.")
    if payload.get("next_page_token") is not None:
        raise RuntimeError("Targeted split response unexpectedly paginated.")
    returned: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for collection, values in payload["corporate_actions"].items():
        if not isinstance(values, list):
            raise RuntimeError("Targeted split collection is malformed.")
        action_type = str(collection).removesuffix("s")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise RuntimeError("Targeted split record is malformed.")
            event_id = str(raw.get("id", ""))
            if event_id in returned:
                raise RuntimeError("Targeted split response contains a duplicate event ID.")
            returned[event_id] = (action_type, raw)
    if set(returned) != set(event_ids):
        raise RuntimeError("Targeted split response does not reconcile to requested event IDs.")
    records: list[dict[str, Any]] = []
    for event_id in event_ids:
        action_type, raw = returned[event_id]
        source = source_by_id[event_id]
        if action_type != source["action_type"] or action_type not in SPLIT_ACTIONS:
            raise RuntimeError(f"Split action type changed for {event_id}.")
        old_rate, new_rate = raw.get("old_rate"), raw.get("new_rate")
        if (
            isinstance(old_rate, bool) or isinstance(new_rate, bool)
            or not isinstance(old_rate, (int, float))
            or not isinstance(new_rate, (int, float))
            or float(old_rate) <= 0 or float(new_rate) <= 0
        ):
            raise RuntimeError(f"Provider split ratio is unusable for {event_id}.")
        effective_date = raw.get("ex_date")
        if effective_date != source.get("ex_or_effective_date"):
            raise RuntimeError(f"Provider split effective date changed for {event_id}.")
        share_multiplier = float(new_rate) / float(old_rate)
        core = {
            "provider_event_id": event_id,
            "action_type": action_type,
            "affected_provider_asset_id": asset_by_event[event_id],
            "symbol_label": source.get("symbol") or source.get("new_symbol") or source.get("old_symbol"),
            "effective_date": effective_date,
            "old_rate": float(old_rate),
            "new_rate": float(new_rate),
            "share_multiplier": share_multiplier,
            "price_multiplier": 1.0 / share_multiplier,
            "ratio_convention": "NEW_SHARES_PER_OLD_SHARES_EQUALS_NEW_RATE_DIVIDED_BY_OLD_RATE",
            "source_corporate_action_provenance_fingerprint": source["provenance_fingerprint"],
            "raw_provider_record_fingerprint": fingerprint(raw),
        }
        records.append({**core, "split_record_fingerprint": fingerprint(core)})
    request_core = {
        "provider": "alpaca", "endpoint": CORPORATE_ACTION_URL, "params": request,
        "response_fingerprint": fingerprint(payload),
    }
    return records, {**request_core, "request_evidence_fingerprint": fingerprint(request_core)}


def build(
    *, dataset: Path = DEFAULT_ROOT, selection_path: Path = DEFAULT_SELECTION,
    output_path: Path = DEFAULT_OUTPUT, acquisition: Acquisition | None = None,
) -> dict[str, Any]:
    dataset = dataset.resolve()
    selection_path = selection_path.resolve()
    output_path = output_path.resolve()
    acquisition = acquisition or Acquisition(dataset)
    state = acquisition.load_state()
    if state is None or state.get("corporate_action_status") != "COMPLETE":
        raise RuntimeError("Governed corporate-action acquisition is incomplete.")
    selection, selection_fingerprint = _load_selection(selection_path)
    population = load_provider_population(dataset)
    source_records = read_gzip_jsonl(dataset / str(state["corporate_action_artifact_path"]))
    resolution = json.loads(
        (dataset / str(state["corporate_action_identity_resolution_path"])).read_text(
            encoding="utf-8"
        )
    )
    by_symbol: dict[str, list[str]] = {}
    for member in population["members"]:
        by_symbol.setdefault(member["canonical_symbol"], []).append(member["provider_asset_id"])
    resolved_by_event = {item["provider_event_id"]: item for item in resolution["records"]}
    components = _name_change_components(source_records)

    identity_requests: list[dict[str, Any]] = []
    members: list[dict[str, Any]] = []
    for rank, label in enumerate(selection["top100"], 1):
        candidates = sorted(by_symbol.get(label, ()))
        method: str
        overlap: dict[str, Any] | None = None
        if len(candidates) == 1:
            asset_id = candidates[0]
            method = "GOVERNED_PROVIDER_POPULATION_UNIQUE_SYMBOL"
        elif label in AMBIGUOUS_LABELS and len(candidates) > 1:
            raw = acquisition.client.request(f"{ASSET_URL}/{label}", {})
            if not isinstance(raw, Mapping):
                raise RuntimeError(f"Provider identity response is malformed for {label}.")
            fact = _provider_asset_fact(raw)
            asset_id = fact["provider_asset_id"]
            if asset_id not in candidates:
                raise RuntimeError(f"Provider symbol identity is outside governed candidates for {label}.")
            request_core = {
                "provider": "alpaca", "endpoint": f"{ASSET_URL}/{{symbol}}",
                "symbol": label, "candidate_provider_asset_ids": candidates,
                "selected_provider_asset_id": asset_id, "provider_fact": fact,
            }
            identity_requests.append(
                {**request_core, "request_evidence_fingerprint": fingerprint(request_core)}
            )
            method = "TARGETED_PROVIDER_SYMBOL_IDENTITY"
            source = ROOT / f"research_data/qpx_frozen_alpaca_top100_v1/bars/{label}_15M.csv"
            if source.exists():
                overlap = _overlap_evidence(
                    dataset=dataset, state=state, asset_id=asset_id, source=source,
                )
        elif label == "BBBY" and not candidates:
            lineage = components.get(label, {label})
            resolved = {
                item.get("provider_asset_id")
                for item in resolution["records"]
                if label in set(item.get("evidence_symbols", ()))
                and item.get("outcome") == "RESOLVED_PROVIDER_IDENTITY"
            }
            resolved.discard(None)
            if len(resolved) != 1:
                raise RuntimeError("BBBY provider identity lineage is not uniquely resolved.")
            asset_id = str(next(iter(resolved)))
            population_ids = {item["provider_asset_id"] for item in population["members"]}
            if asset_id not in population_ids:
                raise RuntimeError("BBBY lineage resolves outside the governed provider population.")
            method = "GOVERNED_NAME_CHANGE_LINEAGE_AND_EXACT_BAR_OVERLAP"
            source = ROOT / "research_data/qpx_alpaca_sip/shared/aggregate_15m/BBBY_15M.csv"
            overlap = _overlap_evidence(
                dataset=dataset, state=state, asset_id=asset_id, source=source,
            )
            request_core = {
                "provider": "alpaca", "label": label,
                "lineage_symbols": sorted(lineage),
                "provider_asset_id": asset_id,
                "lineage_event_ids": sorted(
                    item["provider_event_id"] for item in resolution["records"]
                    if label in set(item.get("evidence_symbols", ()))
                ),
            }
            identity_requests.append(
                {**request_core, "request_evidence_fingerprint": fingerprint(request_core)}
            )
        else:
            raise RuntimeError(
                f"Frozen label {label} has unresolved provider identities: {candidates}."
            )
        member_core = {
            "rank": rank, "symbol_label": label, "provider_asset_id": asset_id,
            "identity_resolution_method": method,
            "historical_overlap": overlap,
        }
        members.append({**member_core, "member_fingerprint": fingerprint(member_core)})
    if len(members) != 100 or len({item["provider_asset_id"] for item in members}) != 100:
        raise RuntimeError("Derived Top-100 provider identities are not exactly 100 unique assets.")

    income_candidates = sorted(by_symbol.get("QDTE", ()))
    if len(income_candidates) != 1:
        raise RuntimeError("QDTE income identity is not unique in the governed population.")
    income_asset = {
        "symbol_label": "QDTE", "provider_asset_id": income_candidates[0],
        "identity_resolution_method": "GOVERNED_PROVIDER_POPULATION_UNIQUE_SYMBOL",
    }
    income_asset["member_fingerprint"] = fingerprint(income_asset)

    member_by_label = {item["symbol_label"]: item["provider_asset_id"] for item in members}
    source_by_id = {item["provider_event_id"]: item for item in source_records}
    selected_events: dict[str, str] = {}
    for record in source_records:
        if record.get("action_type") not in SPLIT_ACTIONS:
            continue
        symbols = {
            value for value in (
                record.get("symbol"), record.get("old_symbol"), record.get("new_symbol")
            ) if isinstance(value, str) and value
        }
        matches = [
            label for label in member_by_label
            if symbols & components.get(label, {label})
        ]
        if not matches:
            continue
        asset_ids = {member_by_label[label] for label in matches}
        if len(asset_ids) != 1:
            raise RuntimeError(
                f"Split event {record['provider_event_id']} maps to multiple selected assets."
            )
        selected_events[record["provider_event_id"]] = next(iter(asset_ids))
    event_ids = sorted(selected_events)
    split_records, split_request = _split_records(
        client=acquisition.client, event_ids=event_ids, source_by_id=source_by_id,
        asset_by_event=selected_events,
    )

    dataset_state_path = dataset / "acquisition_state/state.json"
    ordered_identity_requests = sorted(
        identity_requests, key=lambda item: item.get("symbol", item.get("label", ""))
    )
    derived_universe_fingerprint = fingerprint({
        "members": members,
        "income_asset": income_asset,
    })
    derived_identity_resolution_fingerprint = fingerprint({
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "security_master_fingerprint": population["security_master_fingerprint"],
        "source_identity_resolution_fingerprint": state[
            "corporate_action_identity_resolution_fingerprint"
        ],
        "identity_requests": ordered_identity_requests,
        "members": members,
        "income_asset": income_asset,
    })
    corporate_action_ratio_artifact_fingerprint = fingerprint({
        "source_corporate_action_artifact_fingerprint": state[
            "corporate_action_artifact_fingerprint"
        ],
        "split_events": split_records,
        "split_request_evidence": split_request,
    })
    core = {
        "schema_version": SCHEMA_VERSION,
        "semantic_version": SEMANTIC_VERSION,
        "split_accounting_semantic_version": SPLIT_ACCOUNTING_VERSION,
        "selection_bias_label": "RETROSPECTIVELY_SELECTED_SELECTION_BIASED_IN_SAMPLE",
        "frozen_selection_reference": str(selection_path.relative_to(ROOT)),
        "frozen_selection_fingerprint": selection_fingerprint,
        "frozen_source_selection_fingerprint": selection["source_selection_fingerprint"],
        "frozen_source_progress_sha256": selection["source_progress_sha256"],
        "dataset_root_identity": str(dataset.relative_to(ROOT)),
        "dataset_state_sha256": sha256_path(dataset_state_path),
        "dataset_state_checksum": (dataset_state_path.with_suffix(".sha256")).read_text(
            encoding="utf-8"
        ).strip(),
        "dataset_snapshot_fingerprint": "bcace64bb55c68de66c256c5b9ed443e6384f80904cff7debaefeb862792d595",
        "provider_population_fingerprint": population["provider_population_fingerprint"],
        "security_master_fingerprint": population["security_master_fingerprint"],
        "source_corporate_action_artifact_fingerprint": state[
            "corporate_action_artifact_fingerprint"
        ],
        "source_identity_resolution_fingerprint": state[
            "corporate_action_identity_resolution_fingerprint"
        ],
        "derived_identity_resolution_fingerprint": derived_identity_resolution_fingerprint,
        "identity_requests": ordered_identity_requests,
        "members": members,
        "selected_count": len(members),
        "income_asset": income_asset,
        "derived_asset_id_universe_fingerprint": derived_universe_fingerprint,
        "split_policy": "CAUSAL_APPLY_AT_EFFECTIVE_OPEN",
        "split_excluded_count": 0,
        "split_events": split_records,
        "split_event_count": len(split_records),
        "split_request_evidence": split_request,
        "corporate_action_ratio_artifact_fingerprint": corporate_action_ratio_artifact_fingerprint,
        "price_bar_requests": 0,
        "fractional_share_policy": "CORPORATE_ACTIONS_ONLY_EXACT_NO_CASH_IN_LIEU",
        "entry_share_policy": "INTEGER_ONLY",
    }
    result = {**core, "manifest_fingerprint": fingerprint(core)}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(result, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    temporary.replace(output_path)
    checksum = hashlib.sha256(encoded).hexdigest()
    checksum_path = output_path.with_suffix(output_path.suffix + ".sha256")
    checksum_path.write_text(checksum + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--selection", type=Path, default=DEFAULT_SELECTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    result = build(
        dataset=args.dataset, selection_path=args.selection, output_path=args.output,
    )
    print(json.dumps({
        "manifest_fingerprint": result["manifest_fingerprint"],
        "selected_count": result["selected_count"],
        "split_event_count": result["split_event_count"],
        "output": str(args.output.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
