"""Frozen, asset-ID keyed universes for reservoir replay experiments."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from qpx_bot.ml_historical_acquisition import canonical_provider_asset_id, fingerprint


SPLIT_ACTIONS = frozenset({"stock_split", "reverse_split"})
UNVERIFIED_PREVIOUS_FINGERPRINT = "0087954d86f089584e237f3c37aa91962aa4ec52830d2375c75b247abe1a5212"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _state(root: Path) -> Mapping[str, Any]:
    return json.loads((root / "acquisition_state/state.json").read_text(encoding="utf-8"))


def split_excluded_asset_ids(root: Path, state: Mapping[str, Any] | None = None) -> set[str]:
    state = state or _state(root)
    resolution = json.loads((root / str(state["corporate_action_identity_resolution_path"])).read_text(encoding="utf-8"))
    resolved = {
        str(item["provider_event_id"]): canonical_provider_asset_id(item["provider_asset_id"])
        for item in resolution["records"]
        if item.get("outcome") == "RESOLVED_PROVIDER_IDENTITY"
    }
    excluded: set[str] = set()
    with gzip.open(root / str(state["corporate_action_artifact_path"]), "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("action_type") in SPLIT_ACTIONS:
                asset_id = resolved.get(str(item.get("provider_event_id")))
                if asset_id:
                    excluded.add(asset_id)
    return excluded


def build_manifest(root: Path) -> dict[str, Any]:
    """Derive all reservoir assets less resolved split assets; status is non-eligibility evidence."""
    state = _state(root)
    population_path = root / "manifests/provider_populations/31d74c00c6a0a6b48b29d876285cd9581310e4b07a911fef2ff435dfbe090b34.json"
    population = json.loads(population_path.read_text(encoding="utf-8"))
    members = population["members"]
    excluded = split_excluded_asset_ids(root, state)
    selected = sorted(({
        "provider_asset_id": canonical_provider_asset_id(item["provider_asset_id"]),
        "canonical_symbol": str(item["canonical_symbol"]).strip().upper(),
        "provider_status": "UNKNOWN",
    } for item in members if canonical_provider_asset_id(item["provider_asset_id"]) not in excluded), key=lambda item: (item["provider_asset_id"], item["canonical_symbol"]))
    if len(members) != 33475 or len(excluded) != 2044 or len(selected) != 31431:
        raise RuntimeError("Frozen reservoir/split evidence differs from the approved V3 counts.")
    core = {
        "schema_version": 1,
        "identity": "QPX.RESERVOIR.SPLIT.EXCLUDED.ASSET.ID.V3",
        "source_provider_population_fingerprint": population["provider_population_fingerprint"],
        "source_corporate_action_fingerprint": state["corporate_action_artifact_fingerprint"],
        "source_identity_resolution_fingerprint": state["corporate_action_identity_resolution_fingerprint"],
        "prior_reported_unverified_fingerprint": UNVERIFIED_PREVIOUS_FINGERPRINT,
        "prior_fingerprint_status": "UNVERIFIED_CANONICALIZATION_UNRECOVERED",
        "population_count": len(members), "split_excluded_count": len(excluded),
        "selected_count": len(selected), "members": selected,
    }
    return {**core, "manifest_fingerprint": hashlib.sha256(canonical_bytes(core)).hexdigest()}


def write_manifest(root: Path, destination: Path) -> dict[str, Any]:
    manifest = build_manifest(root)
    encoded = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(encoded)
    destination.with_suffix(destination.suffix + ".sha256").write_text(hashlib.sha256(encoded).hexdigest() + "\n", encoding="utf-8")
    return manifest
