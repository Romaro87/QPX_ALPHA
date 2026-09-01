#!/usr/bin/env python3
"""Acquire Alpaca Top-100 dividend corporate actions only.

This research-data collector reads canonical universe metadata but never reads,
downloads, validates, or modifies OHLCV data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SELECTION_PATH = (
    ROOT / "qpx_bot" / "research_universes"
    / "alpaca_top100_qdte1300_thursday_v1.json"
)
REFERENCE_MANIFEST_PATH = (
    ROOT / "docs" / "research_results"
    / "PROFIT_RECYCLING_V1_FRACTION_MATRIX_MANIFEST_2026-08-12.json"
)
OUTPUT_ROOT = ROOT / "research_data" / "qpx_top100_dividend_actions_v1"
RAW_ROOT = OUTPUT_ROOT / "raw"
STATE_PATH = OUTPUT_ROOT / "checkpoint.json"
FAILURE_LOG = OUTPUT_ROOT / "failures.jsonl"
NORMALIZED_PATH = OUTPUT_ROOT / "dividend_actions.jsonl"
PROVENANCE_PATH = OUTPUT_ROOT / "provenance.json"
MANIFEST_PATH = OUTPUT_ROOT / "dataset_manifest.json"
RUN_LOG = OUTPUT_ROOT / "acquisition.log"
KEY_FILE = Path.home() / ".config" / "qpx" / "alpaca.json"

URL = "https://data.alpaca.markets/v1/corporate-actions"
ACTION_TYPES = ("cash_dividend", "stock_dividend")
BATCH_SIZE = 20
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 4
MAX_RETRY_DELAY_SECONDS = 30
EXPECTED_SELECTION_FINGERPRINT = (
    "5e271e4a9e0d4a20b6f4d0cecc08e8b"
    "f9efe1d2123a64832d09ba1c1eb9ffd23"
)
EXPECTED_TOP100_FINGERPRINT = (
    "8549b0cf69631a974cacb8b429c52da4"
    "e36c40665dce9d1d7c3f1800641cd914"
)
EXPECTED_DATASET_FINGERPRINT = (
    "8a9b1786680fe09af35807a2e33417b1"
    "6a2c7b1fdcb79ba999d1cba959d986f8"
)


class AcquisitionError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def load_source() -> dict[str, Any]:
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    reference = json.loads(REFERENCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    symbols = selection.get("top100")
    window = selection.get("discovery_window")
    if selection.get("manifest_fingerprint") != EXPECTED_SELECTION_FINGERPRINT:
        raise RuntimeError("Canonical Top-100 selection fingerprint changed.")
    if not isinstance(symbols, list) or len(symbols) != 100:
        raise RuntimeError("Canonical Top-100 universe must contain 100 symbols.")
    symbols = [str(symbol).strip().upper() for symbol in symbols]
    if len(set(symbols)) != 100 or any(not symbol for symbol in symbols):
        raise RuntimeError("Canonical Top-100 universe is invalid.")
    if not isinstance(window, dict):
        raise RuntimeError("Canonical replay interval is missing.")
    if reference.get("frozen_top100_fingerprint") != EXPECTED_TOP100_FINGERPRINT:
        raise RuntimeError("Canonical frozen Top-100 fingerprint changed.")
    if reference.get("dataset_fingerprint") != EXPECTED_DATASET_FINGERPRINT:
        raise RuntimeError("Canonical historical dataset fingerprint changed.")
    full_period = reference.get("periods", {}).get("full_2024_2026")
    if full_period != [window.get("start"), window.get("end")]:
        raise RuntimeError("Canonical replay intervals disagree.")
    return {
        "symbols": symbols,
        "start": str(window["start"]),
        "end": str(window["end"]),
        "selection_fingerprint": EXPECTED_SELECTION_FINGERPRINT,
        "frozen_top100_fingerprint": EXPECTED_TOP100_FINGERPRINT,
        "historical_dataset_fingerprint": EXPECTED_DATASET_FINGERPRINT,
    }


def credentials() -> tuple[str, str]:
    payload = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    key = str(payload.get("key_id", "")).strip()
    secret = str(payload.get("secret_key", "")).strip()
    if not key or not secret:
        raise RuntimeError("Alpaca credentials are missing or incomplete.")
    return key, secret


def request_page(params: dict[str, str]) -> dict[str, Any]:
    key, secret = credentials()
    request = urllib.request.Request(
        URL + "?" + urllib.parse.urlencode(params),
        headers={
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Connection": "close",
            "User-Agent": "QPX-ALPHA-DIVIDEND-ACTIONS-V1",
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(
                request, timeout=REQUEST_TIMEOUT_SECONDS
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict):
                raise AcquisitionError("Alpaca returned non-object JSON.")
            return payload
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            last_error = AcquisitionError(f"Alpaca HTTP {exc.code}: {body[:500]}")
            if exc.code not in (429, 500, 502, 503, 504):
                raise last_error from exc
            retry_after = exc.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after else 2.0 * attempt
            except ValueError:
                delay = 2.0 * attempt
        except (OSError, socket.timeout, urllib.error.URLError, json.JSONDecodeError) as exc:
            last_error = exc
            delay = 2.0 * attempt
        if attempt < MAX_ATTEMPTS:
            time.sleep(min(MAX_RETRY_DELAY_SECONDS, max(0.0, delay)))
    raise AcquisitionError(
        f"Alpaca request failed after {MAX_ATTEMPTS} attempts: "
        f"{type(last_error).__name__}: {last_error}"
    )


def initial_state(source: dict[str, Any]) -> dict[str, Any]:
    identity = fingerprint(source)
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if state.get("source_identity") != identity:
            raise RuntimeError("Checkpoint source identity does not match canonical input.")
        return state
    return {
        "schema_version": 1,
        "status": "IN_PROGRESS",
        "source_identity": identity,
        "completed_units": [],
        "queried": {},
        "failures": {},
        "pages_saved": 0,
    }


def unit_key(action_type: str, symbols: list[str]) -> str:
    return fingerprint({"action_type": action_type, "symbols": symbols})


def save_raw(
    action_type: str,
    symbols: list[str],
    page: int,
    payload: dict[str, Any],
) -> None:
    key = unit_key(action_type, symbols)
    wrapper = {
        "schema_version": 1,
        "endpoint": "/v1/corporate-actions",
        "action_type": action_type,
        "symbols": symbols,
        "page": page,
        "response": payload,
    }
    digest = fingerprint(wrapper)
    path = RAW_ROOT / action_type / key / f"page_{page:04d}_{digest}.json"
    if not path.exists():
        atomic_json(path, wrapper)


def append_failure(record: dict[str, Any]) -> None:
    FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with FAILURE_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()


def acquire_unit(
    action_type: str,
    symbols: list[str],
    source: dict[str, Any],
    state: dict[str, Any],
) -> None:
    key = unit_key(action_type, symbols)
    if key in state["completed_units"]:
        return
    params = {
        "symbols": ",".join(symbols),
        "types": action_type,
        "region": "us",
        "start": source["start"],
        "end": source["end"],
        "limit": "1000",
        "data_quality": "complete",
        "sort": "asc",
    }
    page = 0
    try:
        while True:
            page += 1
            payload = request_page(params)
            save_raw(action_type, symbols, page, payload)
            state["pages_saved"] += 1
            atomic_json(STATE_PATH, state)
            token = payload.get("next_page_token")
            if not token:
                break
            params["page_token"] = str(token)
    except Exception as exc:
        if len(symbols) > 1:
            midpoint = len(symbols) // 2
            acquire_unit(action_type, symbols[:midpoint], source, state)
            acquire_unit(action_type, symbols[midpoint:], source, state)
            state["completed_units"].append(key)
            atomic_json(STATE_PATH, state)
            return
        symbol = symbols[0]
        failure = {
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "action_type": action_type,
            "symbol": symbol,
            "error_type": type(exc).__name__,
            "message": str(exc)[:1000],
        }
        state["failures"][f"{action_type}:{symbol}"] = failure
        append_failure(failure)
        atomic_json(STATE_PATH, state)
        print(f"FAILED {action_type} {symbol}: {exc}", flush=True)
        return
    for symbol in symbols:
        state["queried"][f"{action_type}:{symbol}"] = True
        state["failures"].pop(f"{action_type}:{symbol}", None)
    state["completed_units"].append(key)
    atomic_json(STATE_PATH, state)
    print(f"COMPLETE {action_type}: {','.join(symbols)}", flush=True)


def find_records(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        has_symbol = "symbol" in value or "ticker" in value
        has_date = "ex_date" in value or "ex_dividend_date" in value
        if has_symbol and has_date:
            output.append(value)
        for child in value.values():
            find_records(child, output)
    elif isinstance(value, list):
        for child in value:
            find_records(child, output)


def normalized_records(source: dict[str, Any]) -> list[dict[str, Any]]:
    allowed = set(source["symbols"])
    deduplicated: dict[str, dict[str, Any]] = {}
    for path in sorted(RAW_ROOT.glob("*/*/page_*.json")):
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        found: list[dict[str, Any]] = []
        find_records(wrapper.get("response"), found)
        for raw in found:
            symbol = str(raw.get("symbol", raw.get("ticker", ""))).strip().upper()
            ex_date = str(raw.get("ex_date", raw.get("ex_dividend_date", "")))[:10]
            if symbol not in allowed or not (source["start"] <= ex_date <= source["end"]):
                continue
            provider_fields = {
                str(key): value for key, value in sorted(raw.items())
                if value is None or isinstance(value, (str, int, float, bool))
            }
            core = {
                "schema_version": 1,
                "action_type": wrapper["action_type"],
                "symbol": symbol,
                "ex_date": ex_date,
                "record_date": raw.get("record_date"),
                "payable_date": raw.get("payable_date"),
                "process_date": raw.get("process_date"),
                "rate": raw.get("rate", raw.get("cash_amount")),
                "provider_event_id": raw.get("id"),
                "provider_fields": provider_fields,
            }
            event_identity = fingerprint(core)
            deduplicated[event_identity] = {**core, "event_fingerprint": event_identity}
    return sorted(
        deduplicated.values(),
        key=lambda row: (
            row["symbol"], row["ex_date"], row["action_type"], row["event_fingerprint"]
        ),
    )


def finalize(source: dict[str, Any], state: dict[str, Any]) -> None:
    records = normalized_records(source)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = NORMALIZED_PATH.with_suffix(".jsonl.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(canonical_bytes(record).decode("utf-8") + "\n")
    temporary.replace(NORMALIZED_PATH)
    raw_files = sorted(RAW_ROOT.glob("*/*/page_*.json"))
    raw_hashes = {str(path.relative_to(OUTPUT_ROOT)): file_sha256(path) for path in raw_files}
    counts = Counter(record["action_type"] for record in records)
    per_symbol = Counter(record["symbol"] for record in records)
    expected_queries = len(source["symbols"]) * len(ACTION_TYPES)
    provenance = {
        "schema_version": 1,
        "provider": "Alpaca",
        "endpoint": "/v1/corporate-actions",
        "research_only": True,
        "ohlcv_accessed": False,
        "source_selection": str(SELECTION_PATH.relative_to(ROOT)),
        "source_reference_manifest": str(REFERENCE_MANIFEST_PATH.relative_to(ROOT)),
        **source,
    }
    atomic_json(PROVENANCE_PATH, provenance)
    manifest = {
        "schema_version": 1,
        "status": "COMPLETE" if not state["failures"] else "COMPLETE_WITH_FAILURES",
        "action_types": list(ACTION_TYPES),
        "symbol_count": 100,
        "expected_symbol_type_queries": expected_queries,
        "completed_symbol_type_queries": len(state["queried"]),
        "failed_symbol_type_queries": len(state["failures"]),
        "event_counts": dict(sorted(counts.items())),
        "events_per_symbol": {symbol: per_symbol.get(symbol, 0) for symbol in source["symbols"]},
        "normalized_event_count": len(records),
        "normalized_sha256": file_sha256(NORMALIZED_PATH),
        "provenance_sha256": file_sha256(PROVENANCE_PATH),
        "raw_response_count": len(raw_files),
        "raw_response_hashes": raw_hashes,
        "source_identity": state["source_identity"],
    }
    manifest["dataset_fingerprint"] = fingerprint(manifest)
    atomic_json(MANIFEST_PATH, manifest)
    state["status"] = manifest["status"]
    state["output_dataset_fingerprint"] = manifest["dataset_fingerprint"]
    atomic_json(STATE_PATH, state)


def run() -> None:
    source = load_source()
    state = initial_state(source)
    for action_type in ACTION_TYPES:
        for offset in range(0, len(source["symbols"]), BATCH_SIZE):
            acquire_unit(
                action_type,
                source["symbols"][offset:offset + BATCH_SIZE],
                source,
                state,
            )
    finalize(source, state)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    source = load_source()
    if args.plan:
        print(json.dumps({
            "action_types": ACTION_TYPES,
            "batch_size": BATCH_SIZE,
            "output_root": str(OUTPUT_ROOT),
            **source,
        }, indent=2, sort_keys=True))
        return
    run()


if __name__ == "__main__":
    main()
