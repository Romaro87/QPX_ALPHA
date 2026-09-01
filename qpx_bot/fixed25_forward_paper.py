"""Forward-only, simulated Fixed-25 Challenger paper bridge.

The module has no broker/order client.  Alpaca is used only through its stock
market-data endpoint; every persisted fill is simulated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import Position
from qpx_bot.paper_state import (
    read_checksummed_state,
    runtime_lock,
    write_checksummed_state,
)
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_exit
from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs, evaluate_candidate_v1_causal
from qpx_bot.allocation import rebalance_income_allocation
from qpx_bot.accelerators.profit_recycling import (
    ProfitRecyclingContext,
    ProfitRecyclingRuntime,
    ProfitSource,
    ProfitSourceLedger,
    load_profit_recycling_config,
)
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as qualified

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = Path.home() / ".config/qpx/alpaca.json"
UNIVERSE = ROOT / "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json"
QUALIFICATION = ROOT / "qpx_bot/challenger_25pct_qualification.json"
PROFIT_CONFIG = ROOT / "qpx_bot/accelerators/configs/profit_recycling_fraction_50_v1.json"
DEFAULT_RUNTIME = ROOT / "runtime/qpx_fixed25_forward_paper"
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
CORPORATE_ACTION_URL = "https://data.alpaca.markets/v1/corporate-actions"
NY = ZoneInfo("America/New_York")
QUALIFIED_COMMIT = "bba0f48273815ede42374015db7c5770bf446962"
DATASET_FINGERPRINT = "8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8"
STARTING_CAPITAL = 1470.0
NOTIONAL_CAP = 0.25
SLIPPAGE = 0.00075
PROFIT_FINGERPRINT = "c8d634fcd6a5c1c9503f5dbe38de807b5ee607e21afbb6ea06d1903ba0b5c049"
SCHEMA = 2
DECISION_CYCLE_TELEMETRY_EVENT = "IEX_RESEARCH_DECISION_CYCLE_TELEMETRY"
MISSING_SPARSE_BAR = "MISSING_SPARSE_EXACT_CAUSAL_BAR"
INSUFFICIENT_INDICATOR_HISTORY = "INSUFFICIENT_INDICATOR_HISTORY"
OPEN_POSITION = "OPEN_POSITION"
PENDING_SIGNAL = "PENDING_SIGNAL"
VIX_UNAVAILABLE = "VIX_UNAVAILABLE_FAIL_CLOSED"


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def load_contract() -> dict[str, Any]:
    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))
    qualification = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    symbols = tuple(str(x).upper() for x in universe["top100"])
    if len(symbols) != 100 or len(set(symbols)) != 100:
        raise RuntimeError("Frozen Top-100 identity is invalid.")
    if qualification["dataset_fingerprint"] != DATASET_FINGERPRINT:
        raise RuntimeError("Qualified dataset fingerprint changed.")
    if float(qualification["maximum_position_notional_fraction"]) != NOTIONAL_CAP:
        raise RuntimeError("Qualified Fixed-25 cap changed.")
    profit_config = load_profit_recycling_config(PROFIT_CONFIG)
    if profit_config.fingerprint != PROFIT_FINGERPRINT:
        raise RuntimeError("PR_FRACTION_50 configuration fingerprint changed.")
    return {
        "qualified_reference_commit": QUALIFIED_COMMIT,
        "dataset_fingerprint": DATASET_FINGERPRINT,
        "universe_manifest_fingerprint": universe["manifest_fingerprint"],
        "symbols": symbols,
        "decision_timeframe": "15Min",
        "execution_timeframe": "1Min",
        "feed": "sip",
        "live_broker_enabled": False,
        "simulated_fills_only": True,
        "maximum_position_notional_fraction": NOTIONAL_CAP,
        "pyramiding_enabled": False,
        "profit_recycling_policy": "PR_FRACTION_50",
        "profit_recycling_configuration_fingerprint": PROFIT_FINGERPRINT,
    }


def credentials() -> tuple[str, str]:
    raw = json.loads(KEY_FILE.read_text(encoding="utf-8"))
    key, secret = str(raw.get("key_id", "")).strip(), str(raw.get("secret_key", "")).strip()
    if not key or not secret:
        raise RuntimeError("Alpaca market-data credentials are incomplete.")
    return key, secret


def request_bars(symbols: tuple[str, ...], timeframe: str, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
    key, secret = credentials()
    params = {
        "symbols": ",".join(symbols), "timeframe": timeframe,
        "start": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "end": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "feed": "sip", "adjustment": "raw", "limit": "10000", "sort": "asc",
    }
    collected: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    token: str | None = None
    while True:
        if token: params["page_token"] = token
        request = urllib.request.Request(
            DATA_URL + "?" + urllib.parse.urlencode(params),
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                     "Accept": "application/json", "Connection": "close",
                     "User-Agent": "QPX-FIXED25-FORWARD-PAPER/1"},
        )
        last: Exception | None = None
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode())
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")[:1000]
                message = (
                    f"Alpaca market-data HTTP {exc.code} {exc.reason}; "
                    f"endpoint={DATA_URL}; feed={params['feed']}; "
                    f"symbols={params['symbols']}; timeframe={params['timeframe']}; "
                    f"response={body}"
                )
                if exc.code not in (429, 500, 502, 503, 504):
                    raise RuntimeError(message) from exc
                if attempt == 3:
                    raise RuntimeError(message) from exc
                time.sleep(2 ** attempt)
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last = exc
                if attempt == 3:
                    raise RuntimeError(
                        f"Alpaca market-data request failed after bounded retries; "
                        f"endpoint={DATA_URL}; feed={params['feed']}; "
                        f"symbols={params['symbols']}; timeframe={params['timeframe']}; "
                        f"exception={type(exc).__name__}: {exc}"
                    ) from exc
                time.sleep(2 ** attempt)
        bars = payload.get("bars", {})
        if not isinstance(bars, Mapping): raise RuntimeError("Malformed Alpaca bars response.")
        for symbol, rows in bars.items():
            if symbol in collected and isinstance(rows, list): collected[symbol].extend(rows)
        token = payload.get("next_page_token")
        if not token: return collected


def _find_action_records(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, dict):
        if ("symbol" in value or "ticker" in value) and (
            "ex_date" in value or "ex_dividend_date" in value
        ):
            output.append(value)
        for child in value.values():
            _find_action_records(child, output)
    elif isinstance(value, list):
        for child in value:
            _find_action_records(child, output)


def request_qdte_corporate_actions(start: date, end: date) -> list[dict[str, Any]]:
    key, secret = credentials()
    params = {
        "symbols": "QDTE", "types": "cash_dividend", "region": "us",
        "start": start.isoformat(), "end": end.isoformat(), "limit": "1000",
        "data_quality": "complete", "sort": "asc",
    }
    records: list[dict[str, Any]] = []
    while True:
        request = urllib.request.Request(
            CORPORATE_ACTION_URL + "?" + urllib.parse.urlencode(params),
            headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                     "Accept": "application/json", "Connection": "close",
                     "User-Agent": "QPX-PR50-FORWARD-PAPER/1"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode())
                if not isinstance(payload, dict):
                    raise RuntimeError("Malformed Alpaca corporate-actions response.")
                break
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                if attempt == 3:
                    raise RuntimeError("Alpaca corporate-actions request exhausted bounded retries.") from exc
                time.sleep(2 ** attempt)
        _find_action_records(payload, records)
        token = payload.get("next_page_token")
        if not token:
            return records
        params["page_token"] = str(token)


def _profit_runtime(state: Mapping[str, Any]) -> ProfitRecyclingRuntime:
    config = load_profit_recycling_config(PROFIT_CONFIG)
    persisted = state["profit_recycling"]
    if persisted["configuration_fingerprint"] != config.fingerprint:
        raise RuntimeError("Persisted Profit Recycling configuration differs from PR_FRACTION_50.")
    runtime = ProfitRecyclingRuntime(config, STARTING_CAPITAL)
    runtime.ledger = ProfitSourceLedger.from_dict(persisted["ledger"])
    return runtime


def _persist_profit_runtime(state: dict[str, Any], runtime: ProfitRecyclingRuntime) -> None:
    state["profit_recycling"]["ledger"] = runtime.ledger.as_dict()


def observe_qdte_corporate_actions(
    state: dict[str, Any], store: "Store", observed_at: datetime
) -> None:
    start = date.fromisoformat(state["initialization"]["observed_at_utc"][:10])
    records = request_qdte_corporate_actions(start, observed_at.date() + timedelta(days=370))
    observed = observed_at.astimezone(timezone.utc).isoformat()
    actions = state["qdte_corporate_actions"]
    invalid: list[dict[str, Any]] = []
    for raw in records:
        symbol = str(raw.get("symbol", raw.get("ticker", ""))).upper()
        if symbol != "QDTE":
            continue
        event_id = str(raw.get("id", "")).strip()
        ex_date = str(raw.get("ex_date", raw.get("ex_dividend_date", "")))[:10]
        rate = raw.get("rate", raw.get("cash_amount", raw.get("cash")))
        if not event_id or not ex_date or rate in (None, ""):
            invalid.append({"raw_fingerprint": fingerprint(raw), "first_observed_at_utc": observed})
            continue
        try:
            date.fromisoformat(ex_date)
            amount = float(rate)
            if not math.isfinite(amount) or amount <= 0:
                raise ValueError
        except ValueError:
            invalid.append({"raw_fingerprint": fingerprint(raw), "first_observed_at_utc": observed})
            continue
        event = actions.setdefault(event_id, {
            "event_id": event_id, "symbol": "QDTE", "action_type": "cash_dividend",
            "first_observed_at_utc": observed, "fields": {}, "entitlement": None,
            "cash_released_at_utc": None,
        })
        for name, value in {
            "ex_date": ex_date, "record_date": raw.get("record_date"),
            "payable_date": raw.get("payable_date"), "process_date": raw.get("process_date"),
            "rate": amount, "subtype": raw.get("subtype"),
        }.items():
            if value in (None, ""):
                continue
            field = event["fields"].get(name)
            if field is None:
                event["fields"][name] = {"value": value, "first_observed_at_utc": observed}
            elif field["value"] != value:
                raise RuntimeError(f"QDTE corporate-action field changed for {event_id}: {name}.")
        event["last_observed_at_utc"] = observed
        event["observation_fingerprint"] = fingerprint({
            "event_id": event_id, "fields": event["fields"]
        })
    if invalid:
        state["invalid_qdte_corporate_actions"].extend(invalid)
    state["last_corporate_action_observation_at_utc"] = observed
    store.save(state)
    store.event("QDTE_CORPORATE_ACTIONS_OBSERVED", {
        "records": len(records), "known_events": len(actions), "invalid_records": len(invalid)
    })
    if invalid:
        raise RuntimeError("QDTE corporate action lacks required event identity, ex-date, or rate.")


def apply_qdte_corporate_actions(
    state: dict[str, Any], store: "Store", bar_time: datetime
) -> None:
    is_market_open = (bar_time.hour, bar_time.minute) == (9, 30)
    day = bar_time.date().isoformat()
    if is_market_open:
        state["qdte_open_share_snapshots"].setdefault(day, {
            "shares": state["qdte_shares"], "captured_at_market": bar_time.isoformat()
        })
    for event_id, event in sorted(state["qdte_corporate_actions"].items()):
        fields = event["fields"]
        ex_field = fields.get("ex_date")
        rate_field = fields.get("rate")
        if ex_field is None or rate_field is None:
            continue
        ex_date = str(ex_field["value"])
        first_observed = datetime.fromisoformat(event["first_observed_at_utc"])
        causally_known = first_observed <= bar_time.astimezone(timezone.utc)
        if (event["entitlement"] is None and causally_known
                and ex_date in state["qdte_open_share_snapshots"]):
            snapshot = state["qdte_open_share_snapshots"][ex_date]
            event["entitlement"] = {
                "entitled_shares": snapshot["shares"], "ex_date": ex_date,
                "rate": float(rate_field["value"]), "recognized_at_market": bar_time.isoformat(),
                "recognition_used_persisted_open_snapshot": ex_date != day,
            }
            store.event("QDTE_DIVIDEND_ENTITLEMENT_RECORDED", {
                "event_id": event_id, **event["entitlement"]
            })
        entitlement = event["entitlement"]
        if (not is_market_open or entitlement is None
                or event["cash_released_at_utc"] is not None):
            continue
        payable = fields.get("payable_date")
        process = fields.get("process_date")
        if payable is None or process is None:
            event["settlement_status"] = "FAIL_CLOSED_MISSING_PAYABLE_OR_PROCESS_DATE"
            continue
        available = max(date.fromisoformat(str(payable["value"])[:10]),
                        date.fromisoformat(str(process["value"])[:10]))
        fields_known = max(datetime.fromisoformat(payable["first_observed_at_utc"]),
                           datetime.fromisoformat(process["first_observed_at_utc"]))
        if bar_time.date() < available or bar_time.astimezone(timezone.utc) < fields_known:
            continue
        cash = float(entitlement["entitled_shares"]) * float(entitlement["rate"])
        state["cash"] += cash
        event["cash_released_at_utc"] = bar_time.astimezone(timezone.utc).isoformat()
        event["cash_released"] = cash
        event["settlement_status"] = "RELEASED_FIRST_CAUSAL_MARKET_OPEN"
        store.event("QDTE_DIVIDEND_CASH_RELEASED", {
            "event_id": event_id, "cash": cash, "available_date": available.isoformat(),
            "released_at_market": bar_time.isoformat(),
        })


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.state = self.directory / "paper_state.json"
        self.checksum = self.directory / "paper_state.sha256"
        self.journal = self.directory / "paper_audit.jsonl"
        self.lock = self.directory / "paper.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        with runtime_lock(self.lock):
            yield

    def load(self) -> dict[str, Any] | None:
        if not self.state.exists():
            return None
        encoded = read_checksummed_state(
            self.state,
            self.checksum,
            label="Forward-paper state",
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise RuntimeError("Forward-paper state root must be an object.")
        return payload

    def save(self, state: dict[str, Any]) -> None:
        encoded = json.dumps(state, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
        write_checksummed_state(self.state, self.checksum, encoded)

    def verify_journal(self) -> tuple[set[str], str, int]:
        if not self.journal.exists():
            return set(), "0" * 64, 0
        event_ids: set[str] = set()
        previous = "0" * 64
        sequence = 0
        for line_number, raw in enumerate(
            self.journal.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not raw.strip():
                continue
            record = json.loads(raw)
            if not isinstance(record, dict):
                raise RuntimeError(f"Audit line {line_number} is not an object.")
            claimed = str(record.pop("record_hash", ""))
            if fingerprint(record) != claimed:
                raise RuntimeError(f"Audit hash mismatch on line {line_number}.")
            if record.get("previous_record_hash") != previous:
                raise RuntimeError(f"Audit hash chain is broken on line {line_number}.")
            sequence += 1
            if "sequence" in record and int(record["sequence"]) != sequence:
                raise RuntimeError(f"Audit sequence mismatch on line {line_number}.")
            event_id = record.get("event_id")
            if event_id is not None:
                normalized = str(event_id)
                if not normalized or normalized in event_ids:
                    raise RuntimeError(
                        f"Audit event ID is empty or duplicated on line {line_number}."
                    )
                event_ids.add(normalized)
            previous = claimed
        return event_ids, previous, sequence

    def reconcile(self) -> dict[str, Any] | None:
        if not self.state.exists():
            if self.checksum.exists() or self.journal.exists():
                raise RuntimeError(
                    "Forward-paper state is missing while recovery artifacts exist."
                )
            return None
        state = self.load()
        if not self.journal.exists():
            raise RuntimeError("Forward-paper audit journal is missing.")
        self.verify_journal()
        return state

    def event(self, event_type: str, details: Mapping[str, Any]) -> bool:
        normalized_details = dict(details)
        logical_identity = {
            key: normalized_details[key]
            for key in (
                "execution_id",
                "signal_id",
                "event_id",
                "revision",
                "week",
                "bar",
                "last_warmup_bar",
            )
            if key in normalized_details
        }
        event_id = fingerprint({
            "event_type": event_type,
            "logical_identity": logical_identity or normalized_details,
        })
        event_ids, previous, sequence = self.verify_journal()
        if event_id in event_ids:
            return False
        core = {
            "sequence": sequence + 1,
            "event_id": event_id,
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "previous_record_hash": previous,
            "details": normalized_details,
        }
        record = {**core, "record_hash": fingerprint(core)}
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(canonical(record).decode() + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return True


def _parse(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(NY)


def _completed_15m(rows: list[dict[str, Any]], observed_at: datetime) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        start = _parse(str(row["t"])); wall = start.time()
        if start + timedelta(minutes=15) > observed_at.astimezone(NY): continue
        if not ((wall.hour, wall.minute) >= (9, 30) and (wall.hour, wall.minute) < (16, 0)): continue
        try:
            values = tuple(float(row[key]) for key in ("o", "h", "l", "c")); volume = int(row.get("v", 0))
        except (TypeError, ValueError, KeyError): continue
        if min(values) <= 0 or not all(math.isfinite(x) for x in values): continue
        result.append({"start": start, "open": values[0], "high": values[1], "low": values[2], "close": values[3], "volume": max(0, volume)})
    return sorted({x["start"]: x for x in result}.values(), key=lambda x: x["start"])


def _position(raw: Mapping[str, Any]) -> Position:
    return Position(symbol=str(raw["symbol"]), shares=int(raw["shares"]),
                    entry_date=datetime.fromisoformat(str(raw["entry_date"])).date(),
                    entry_price=float(raw["entry_price"]), entry_atr=float(raw["entry_atr"]),
                    stop_price=float(raw["stop_price"]), target_price=float(raw["target_price"]),
                    highest_price=float(raw["highest_price"]))


def _position_dict(value: Position) -> dict[str, Any]:
    return {"symbol": value.symbol, "shares": value.shares, "entry_date": value.entry_date.isoformat(),
            "entry_price": value.entry_price, "entry_atr": value.entry_atr,
            "stop_price": value.stop_price, "target_price": value.target_price,
            "highest_price": value.highest_price}


def _minute_for_bar(rows: list[dict[str, Any]], bar_start: datetime) -> dict[str, Any]:
    candidates = [row for row in rows if bar_start <= _parse(str(row["t"])) < bar_start + timedelta(minutes=15)]
    if not candidates: raise RuntimeError(f"No SIP 1-minute execution evidence for {bar_start.isoformat()}.")
    return min(candidates, key=lambda row: _parse(str(row["t"])))


def _minute_for_exit(
    rows: list[dict[str, Any]], bar_start: datetime, position: Position, reason: str
) -> dict[str, Any]:
    candidates = sorted(
        (row for row in rows if bar_start <= _parse(str(row["t"])) < bar_start + timedelta(minutes=15)),
        key=lambda row: _parse(str(row["t"])),
    )
    if reason in {"STOP_GAP", "TARGET_GAP"}:
        return _minute_for_bar(rows, bar_start)
    if reason == "ATR_STOP":
        candidates = [row for row in candidates if float(row["l"]) <= position.stop_price]
    elif reason == "ATR_TARGET":
        candidates = [row for row in candidates if float(row["h"]) >= position.target_price]
    if not candidates:
        raise RuntimeError(f"No SIP 1-minute evidence supports {reason} at {bar_start.isoformat()}.")
    return candidates[0]


def _entry_inputs(rows: list[dict[str, Any]], index: int, indicators, vix: float, config) -> CandidateV1CausalInputs | None:
    prior = index - 1; slope = index - config.sma_slope_lookback; breakout = index - config.breakout_lookback
    if min(prior, slope, breakout) < 0: return None
    values = (indicators.ema_fast[index], indicators.ema_fast[prior], indicators.ema_slow[index],
              indicators.ema_slow[prior], indicators.rsi[index], indicators.rsi[prior],
              indicators.rmi[index], indicators.rmi[prior], indicators.sma_trend[index],
              indicators.sma_trend[slope], indicators.average_volume[prior], indicators.atr[index])
    if any(value is None for value in values): return None
    current = rows[index]
    return CandidateV1CausalInputs(index=index, current_close=current["close"], current_volume=current["volume"],
        current_fast=float(values[0]), previous_fast=float(values[1]), current_slow=float(values[2]),
        previous_slow=float(values[3]), current_rsi=float(values[4]), previous_rsi=float(values[5]),
        current_rmi=float(values[6]), previous_rmi=float(values[7]), current_sma=float(values[8]),
        slope_sma=float(values[9]), baseline_volume=float(values[10]), current_atr=float(values[11]),
        prior_high=max(item["high"] for item in rows[breakout:index]), vix=vix)


def _evaluate_candidate_v1_cycle(
    *,
    symbols: tuple[str, ...],
    histories: Mapping[str, list[dict[str, Any]]],
    indices: Mapping[str, Mapping[datetime, int]],
    indicators: Mapping[str, Any],
    positions: Mapping[str, Position],
    pending: Mapping[str, Any],
    bar_time: datetime,
    vix: float | None,
    config: Any,
) -> tuple[list[tuple[str, str, float, float]], dict[str, Any]]:
    """Evaluate one universe boundary and retain only compact eligibility evidence."""
    usable: list[str] = []
    missing: list[str] = []
    insufficient: list[str] = []
    other: list[dict[str, str]] = []
    evaluated: list[str] = []
    no_action_count = 0
    qualifying: list[tuple[str, str, float, float]] = []

    for symbol in symbols:
        index = indices.get(symbol, {}).get(bar_time)
        if index is None:
            missing.append(symbol)
            continue
        usable.append(symbol)
        if vix is None:
            other.append({"symbol": symbol, "reason_code": VIX_UNAVAILABLE})
            continue
        if symbol in positions:
            other.append({"symbol": symbol, "reason_code": OPEN_POSITION})
            continue
        if symbol in pending:
            other.append({"symbol": symbol, "reason_code": PENDING_SIGNAL})
            continue
        inputs = _entry_inputs(histories[symbol], index, indicators[symbol], vix, config)
        if inputs is None:
            insufficient.append(symbol)
            continue
        evaluated.append(symbol)
        result = evaluate_candidate_v1_causal(inputs=inputs, config=config)
        if result.should_enter:
            qualifying.append((
                hashlib.sha256((bar_time.isoformat() + "|" + symbol).encode()).hexdigest(),
                symbol,
                inputs.current_atr,
                inputs.current_close,
            ))
        else:
            no_action_count += 1

    census = {
        "usable": usable,
        "missing": missing,
        "insufficient": insufficient,
        "other": other,
        "evaluated": evaluated,
        "no_action_count": no_action_count,
        "signaled": [symbol for _, symbol, _, _ in qualifying],
    }
    return qualifying, census


def _decision_cycle_telemetry(
    *,
    symbols: tuple[str, ...],
    bar_time: datetime,
    decision_id: str,
    state_revision: int,
    feed: str,
    vix: float | None,
    census: Mapping[str, Any],
) -> dict[str, Any]:
    """Build and validate one bounded, deterministic Top-100 cycle summary."""
    requested = list(symbols)
    if len(requested) != 100 or len(set(requested)) != 100:
        raise RuntimeError("Decision-cycle telemetry requires exactly 100 unique symbols.")
    usable = list(census["usable"])
    missing = list(census["missing"])
    insufficient = list(census["insufficient"])
    other = [dict(value) for value in census["other"]]
    evaluated = list(census["evaluated"])
    signaled = list(census["signaled"])
    no_action_count = int(census["no_action_count"])
    skipped = (
        [{"symbol": symbol, "reason_code": MISSING_SPARSE_BAR} for symbol in missing]
        + [{"symbol": symbol, "reason_code": INSUFFICIENT_INDICATOR_HISTORY}
           for symbol in insufficient]
        + other
    )
    skipped_by_symbol = {value["symbol"]: value["reason_code"] for value in skipped}
    if len(skipped_by_symbol) != len(skipped):
        raise RuntimeError("Decision-cycle telemetry assigned multiple skip reasons.")
    if set(requested) != set(usable) | set(missing) or set(usable) & set(missing):
        raise RuntimeError("Decision-cycle usable/sparse counts do not reconcile.")
    if set(requested) != set(evaluated) | set(skipped_by_symbol):
        raise RuntimeError("Decision-cycle evaluation/skip counts do not reconcile.")
    if set(evaluated) & set(skipped_by_symbol):
        raise RuntimeError("Decision-cycle symbol was both evaluated and skipped.")
    if not set(signaled).issubset(evaluated):
        raise RuntimeError("Decision-cycle signal was not evaluated by Candidate V1.")
    if len(evaluated) != no_action_count + len(signaled):
        raise RuntimeError("Candidate V1 outcomes do not reconcile with evaluations.")
    if vix is None:
        input_status = VIX_UNAVAILABLE
    elif insufficient:
        input_status = "PARTIAL_INSUFFICIENT_INDICATOR_HISTORY"
    else:
        input_status = "AVAILABLE_FOR_ALL_ELIGIBLE_SYMBOLS"
    return {
        "bar": bar_time.isoformat(),
        "decision_bar_interval": {
            "start_market": bar_time.isoformat(),
            "end_market": (bar_time + timedelta(minutes=15)).isoformat(),
        },
        "decision_id": decision_id,
        "provider_feed": feed,
        "state_revision": state_revision,
        "requested_symbol_count": len(requested),
        "requested_symbols": requested,
        "usable_exact_causal_bar_count": len(usable),
        "symbols_with_usable_exact_causal_bar": usable,
        "missing_sparse_bar_count": len(missing),
        "symbols_skipped_missing_sparse_bar": missing,
        "insufficient_indicator_history_count": len(insufficient),
        "symbols_skipped_insufficient_indicator_history": insufficient,
        "other_eligibility_skip_count": len(other),
        "symbols_skipped_other_eligibility": other,
        "skipped_symbol_count": len(skipped),
        "skipped_symbols": skipped,
        "candidate_v1_evaluated_count": len(evaluated),
        "symbols_passed_to_candidate_v1": evaluated,
        "candidate_v1_no_action_count": no_action_count,
        "signal_count": len(signaled),
        "signaled_symbols": signaled,
        "vix_status": "AVAILABLE" if vix is not None else "UNAVAILABLE_FAIL_CLOSED",
        "input_availability_status": input_status,
    }


def _flush_pending_decision_cycle_telemetry(
    state: dict[str, Any], store: "Store"
) -> bool:
    """Finish an already-durable telemetry append without refetching provider data."""
    pending = state.get("decision_cycle_telemetry_pending")
    if pending is None:
        return False
    store.event(DECISION_CYCLE_TELEMETRY_EVENT, pending)
    state.pop("decision_cycle_telemetry_pending", None)
    store.save(state)
    return True


def _iex_qdte_sizing_mark(
    histories: Mapping[str, list[dict[str, Any]]],
    indices: Mapping[str, Mapping[datetime, int]],
    bar_time: datetime,
) -> tuple[float | None, datetime | None]:
    """Return an exact open or prior completed close; never construct a bar."""
    qdte_index = indices.get("QDTE", {}).get(bar_time)
    if qdte_index is not None:
        row = histories["QDTE"][qdte_index]
        return float(row["open"]), row["start"]
    prior = [row for row in histories.get("QDTE", []) if row["start"] < bar_time]
    if not prior:
        return None, None
    row = prior[-1]
    return float(row["close"]), row["start"]


def _vix_previous_close(day) -> float:
    import csv
    import io
    values = {}
    request = urllib.request.Request(
        "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
        headers={"User-Agent": "QPX-FIXED25-FORWARD-PAPER/1", "Connection": "close"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        handle = io.StringIO(response.read().decode("utf-8-sig"))
        for row in csv.DictReader(handle):
            try:
                raw_day = row.get("DATE") or row.get("Date"); close = row.get("CLOSE") or row.get("Close")
                values[datetime.strptime(str(raw_day), "%m/%d/%Y").date()] = float(close)
            except (TypeError, ValueError): continue
    prior = [key for key in values if key < day]
    if not prior: raise RuntimeError("Previous-session VIX is unavailable; entries fail closed.")
    latest = max(prior)
    # A stale historical close must never authorize a current entry.
    if (day - latest).days > 7: raise RuntimeError("Previous-session VIX is stale; entries fail closed.")
    return values[latest]


def process_latest_decision(state: dict[str, Any], store: Store, observed_at: datetime) -> None:
    """Process each newly completed 15-minute timestamp exactly once."""
    if state["contract"].get("feed") == "iex":
        _flush_pending_decision_cycle_telemetry(state, store)
    symbols = tuple(state["contract"]["symbols"])
    raw: dict[str, list[dict[str, Any]]] = {}
    start = observed_at - timedelta(days=60)
    for offset in range(0, len(symbols), 20):
        raw.update(request_bars(symbols[offset:offset + 20], "15Min", start, observed_at))
    raw.update(request_bars(("QDTE",), "15Min", start, observed_at))
    histories = {symbol: _completed_15m(rows, observed_at) for symbol, rows in raw.items()}
    clock = sorted({row["start"] for rows in histories.values() for row in rows})
    if not clock: raise RuntimeError("No completed Alpaca SIP 15-minute decision bars are available.")
    if state["last_decision_bar"] is None:
        # Forward experiment begins now; downloaded warm-up bars are indicators,
        # never backtested decisions.
        state["last_decision_bar"] = clock[-1].isoformat()
        store.event("FORWARD_DECISION_BOUNDARY_ESTABLISHED", {"last_warmup_bar": state["last_decision_bar"]})
        return
    last = datetime.fromisoformat(state["last_decision_bar"])
    new_times = [value for value in clock if value > last]
    if not new_times: return
    if len(new_times) > 26:
        raise RuntimeError("More than one session of decisions is missing; fail closed for operator review.")
    config = qualified.candidate_config()
    profit_runtime = _profit_runtime(state)
    candle_sets = {symbol: [Candle(date=row["start"].date(), open=row["open"], high=row["high"],
                    low=row["low"], close=row["close"], volume=row["volume"]) for row in rows]
                   for symbol, rows in histories.items()}
    indicators = {symbol: calculate_indicators(candles, config) for symbol, candles in candle_sets.items()}
    indices = {symbol: {row["start"]: index for index, row in enumerate(rows)} for symbol, rows in histories.items()}
    minute_symbols = tuple(dict.fromkeys((*symbols, "QDTE")))
    minute_raw: dict[str, list[dict[str, Any]]] = {}
    minute_start = min(new_times) - timedelta(minutes=1)
    for offset in range(0, len(minute_symbols), 20):
        minute_raw.update(request_bars(minute_symbols[offset:offset + 20], "1Min", minute_start, observed_at))

    for bar_time in new_times:
        completed_id = fingerprint({"kind": "decision", "bar": bar_time.isoformat(),
                                    "contract": state["contract_fingerprint"]})
        if completed_id in state["completed_execution_ids"]:
            state["last_decision_bar"] = bar_time.isoformat(); continue
        positions = {symbol: _position(value) for symbol, value in state["positions"].items()}
        apply_qdte_corporate_actions(state, store, bar_time)

        # Qualified Thursday-only 12.5% QDTE / 87.5% swing allocation.
        if bar_time.weekday() == 3 and bar_time in indices.get("QDTE", {}):
            iso = bar_time.isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"
            if week_key != state.get("last_rebalance_week"):
                state["profit_recycling"]["event_sequence"] += 1
                sequence = state["profit_recycling"]["event_sequence"]
                released = profit_runtime.ledger.on_sleeve_rebalance(state["cash"], sequence)
                state["profit_recycling"]["current_event_sequence"] = sequence
                one = _minute_for_bar(minute_raw.get("QDTE", []), bar_time)
                qdte_price = float(one["o"])
                marks = {
                    name: histories[name][indices[name][bar_time]]["open"]
                    for name in positions
                    if bar_time in indices.get(name, {})
                }
                result = rebalance_income_allocation(
                    income_shares=state["qdte_shares"], income_cost=state["qdte_cost"],
                    swing_cash=state["cash"],
                    swing_market_value=sum(pos.shares * marks.get(name, pos.entry_price) for name, pos in positions.items()),
                    income_price=qdte_price, target_income_weight=0.125,
                    slippage_rate=config.slippage_rate,
                    tax_reserve_rate=config.annual_tax_reserve_rate,
                    tolerance=config.allocation_rebalance_tolerance,
                    minimum_trade=config.minimum_rebalance_trade,
                )
                state["qdte_shares"] = result.shares_after
                state["qdte_cost"] = result.income_cost_after
                state["cash"] = result.swing_cash_after
                state["tax_reserve_cash"] += result.tax_reserved
                state["realized_pnl"] += result.realized_pnl
                state["last_rebalance_week"] = week_key
                store.event("SIMULATED_THURSDAY_REBALANCE", {
                    "week": week_key, "action": result.action,
                    "shares_before": result.shares_before, "shares_after": result.shares_after,
                    "target_income_weight": 0.125, "sip_1m_bar": str(one["t"]),
                    "profit_recycling_event_sequence": sequence,
                    "profit_recycling_released": released,
                })

        # OPEN: execute only signals staged by an earlier completed 15-minute bar.
        for symbol, signal in sorted(list(state["pending"].items())):
            if state["contract"].get("feed") == "iex":
                # The IEX variant owns an independent real-time one-minute
                # execution clock. Decision catch-up must never fill here.
                continue
            if datetime.fromisoformat(signal["signal_bar"]) >= bar_time: continue
            if symbol not in indices or bar_time not in indices[symbol]: continue
            one = _minute_for_bar(minute_raw.get(symbol, []), bar_time)
            open_price = float(one["o"]); gap = abs(open_price - signal["prior_close"]) / signal["atr"]
            execution_id = fingerprint({"kind": "entry", "symbol": symbol, "bar": bar_time.isoformat(),
                                        "signal": signal["signal_id"], "contract": state["contract_fingerprint"]})
            if execution_id in state["completed_execution_ids"]:
                state["pending"].pop(symbol, None); continue
            if gap > 2.0 or len(positions) >= 6:
                store.event("SIMULATED_ENTRY_CANCELLED", {"symbol": symbol, "execution_id": execution_id,
                            "reason": "GAP" if gap > 2.0 else "CAPACITY"})
                state["completed_execution_ids"].append(execution_id); state["pending"].pop(symbol, None); continue
            marks = {name: histories[name][indices[name][bar_time]]["open"] for name in positions if bar_time in indices.get(name, {})}
            swing_value = sum(pos.shares * marks.get(name, pos.entry_price) for name, pos in positions.items())
            if state["contract"].get("feed") == "iex":
                qdte_mark, qdte_source = _iex_qdte_sizing_mark(histories, indices, bar_time)
                if qdte_mark is None or qdte_source is None:
                    store.event("PENDING_ENTRY_SKIPPED_MISSING_CAUSAL_QDTE_MARK", {
                        "symbol": symbol, "bar": bar_time.isoformat(),
                        "signal_id": signal["signal_id"], "reason": "NO_EXACT_OR_PRIOR_QDTE_OBSERVATION",
                    })
                    continue
                if qdte_source != bar_time:
                    store.event("CAUSAL_STALE_QDTE_VALUATION_MARK_USED", {
                        "symbol": symbol, "bar": bar_time.isoformat(),
                        "qdte_source_bar": qdte_source.isoformat(),
                        "use": "ACCOUNT_EQUITY_SIZING_ONLY",
                    })
            else:
                qdte_row = histories["QDTE"][indices["QDTE"][bar_time]]
                qdte_mark = qdte_row["open"]
            equity = state["cash"] + state.get("tax_reserve_cash", 0.0) + swing_value + state["qdte_shares"] * qdte_mark
            active_risk = sum(pos.shares * max(0.0, pos.entry_price - pos.stop_price) for pos in positions.values())
            next_sequence = max(
                state["profit_recycling"]["current_event_sequence"],
                state["profit_recycling"]["event_sequence"] + 1,
            )
            state["profit_recycling"]["current_event_sequence"] = next_sequence
            deployable_cash = profit_runtime.ledger.available_swing_cash(state["cash"], next_sequence)
            sizing = calculate_position_size(account_equity=equity, available_cash=deployable_cash, entry_price=open_price,
                atr=signal["atr"], active_risk=active_risk, config=config, trade_results_r=())
            share_cap = math.floor((equity * NOTIONAL_CAP) / sizing.entry_fill) if sizing.entry_fill else 0
            shares = min(sizing.shares, share_cap)
            if not sizing.is_tradeable or shares < 1:
                store.event("SIMULATED_ENTRY_REJECTED", {"symbol": symbol, "execution_id": execution_id, "reason": sizing.blocked_reason or "NOTIONAL_CAP"})
            else:
                cost = shares * sizing.entry_fill
                used = min(cost, profit_runtime.ledger.recycled_profit_balance)
                if used:
                    profit_runtime.ledger.consume(used, next_sequence, state["cash"])
                state["cash"] -= cost
                positions[symbol] = Position(symbol=symbol, shares=shares, entry_date=bar_time.date(),
                    entry_price=sizing.entry_fill, entry_atr=signal["atr"], stop_price=sizing.stop_price,
                    target_price=sizing.target_price, highest_price=sizing.entry_fill)
                store.event("SIMULATED_ENTRY_FILLED", {"symbol": symbol, "execution_id": execution_id,
                    "shares": shares, "fill_price": sizing.entry_fill, "sip_1m_bar": str(one["t"]),
                    "recycled_profit_consumed": used})
            state["completed_execution_ids"].append(execution_id); state["pending"].pop(symbol, None)

        # CLOSE: preserve qualified 15-minute exit logic; 1-minute bars provide
        # the causal hit timestamp, while the qualified threshold determines price.
        for symbol, position in list(positions.items()):
            index = indices.get(symbol, {}).get(bar_time)
            if index is None: continue
            atr = indicators[symbol].atr[index]
            if atr is None or atr <= 0: continue
            row = histories[symbol][index]
            evaluation = evaluate_exit(position=position, candle=candle_sets[symbol][index], current_atr=float(atr), config=config)
            if evaluation.should_exit:
                execution_id = fingerprint({"kind": "exit", "symbol": symbol, "bar": bar_time.isoformat(),
                                            "reason": evaluation.reason, "contract": state["contract_fingerprint"]})
                if execution_id not in state["completed_execution_ids"]:
                    minute = _minute_for_exit(
                        minute_raw.get(symbol, []), bar_time, position, str(evaluation.reason)
                    )
                    fill = float(evaluation.exit_price); proceeds = position.shares * fill
                    pnl = (fill - position.entry_price) * position.shares
                    tax_reserved = max(0.0, pnl) * config.annual_tax_reserve_rate
                    state["cash"] += proceeds - tax_reserved
                    state["realized_pnl"] = state.get("realized_pnl", 0.0) + pnl
                    state["tax_reserve_cash"] += tax_reserved
                    state["profit_recycling"]["event_sequence"] += 1
                    sequence = state["profit_recycling"]["event_sequence"]
                    state["profit_recycling"]["current_event_sequence"] = sequence
                    source = ProfitSource.SWING_REALIZED_PROFIT if pnl > 0 else ProfitSource.SWING_REALIZED_LOSS
                    decision = profit_runtime.decide(ProfitRecyclingContext(
                        decision_timestamp=bar_time, realized_event_id=execution_id,
                        event_sequence=sequence, realized_event_source=source,
                        gross_realized_pnl=pnl, tax_reserved=tax_reserved,
                        ordinary_investable_cash=state["cash"],
                        recycled_profit_balance=profit_runtime.ledger.recycled_profit_balance,
                        current_portfolio_equity=equity,
                    ))
                    state["profit_recycling"]["decision_ids"].append(decision.decision_id)
                    store.event("SIMULATED_EXIT_FILLED", {"symbol": symbol, "execution_id": execution_id,
                        "shares": position.shares, "fill_price": fill, "reason": evaluation.reason,
                        "sip_1m_bar": str(minute["t"]), "tax_reserved": tax_reserved,
                        "eligible_after_tax_profit": decision.eligible_net_profit,
                        "recyclable_profit": decision.destination_amount,
                        "profit_recycling_event_sequence": sequence})
                    state["completed_execution_ids"].append(execution_id)
                positions.pop(symbol, None)
            else:
                position.stop_price = evaluation.next_stop_price; position.highest_price = evaluation.highest_price

        # Stage new Candidate V1 signals from completed 15-minute data only.
        try: vix = _vix_previous_close(bar_time.date())
        except RuntimeError as exc:
            store.event("ENTRY_EVALUATION_FAILED_CLOSED", {"bar": bar_time.isoformat(), "reason": str(exc)})
            vix = None
        decision_census = None
        if state["contract"].get("feed") == "iex":
            qualifying, decision_census = _evaluate_candidate_v1_cycle(
                symbols=symbols,
                histories=histories,
                indices=indices,
                indicators=indicators,
                positions=positions,
                pending=state["pending"],
                bar_time=bar_time,
                vix=vix,
                config=config,
            )
        else:
            qualifying = []
            if vix is not None:
                for symbol in symbols:
                    index = indices.get(symbol, {}).get(bar_time)
                    if (index is None or symbol in positions
                            or symbol in state["pending"]):
                        continue
                    inputs = _entry_inputs(
                        histories[symbol], index, indicators[symbol], vix, config
                    )
                    if inputs is None:
                        continue
                    result = evaluate_candidate_v1_causal(inputs=inputs, config=config)
                    if result.should_enter:
                        qualifying.append((hashlib.sha256(
                            (bar_time.isoformat() + "|" + symbol).encode()
                        ).hexdigest(), symbol, inputs.current_atr, inputs.current_close))
        slots = max(0, 6 - len(positions) - len(state["pending"]))
        for _, symbol, atr, close in sorted(qualifying)[:slots]:
            signal_id = fingerprint({"symbol": symbol, "bar": bar_time.isoformat(), "atr": atr,
                                     "contract": state["contract_fingerprint"]})
            pending_signal = {"signal_id": signal_id, "signal_bar": bar_time.isoformat(),
                              "atr": atr, "prior_close": close}
            event_details = {"symbol": symbol, "signal_id": signal_id, "bar": bar_time.isoformat()}
            if state["contract"].get("feed") == "iex":
                decision_observed = datetime.now(timezone.utc)
                eligible = decision_observed.replace(second=0, microsecond=0) + timedelta(minutes=1)
                pending_signal.update({
                    "decision_bar_interval": {
                        "start_market": bar_time.isoformat(),
                        "end_market": (bar_time + timedelta(minutes=15)).isoformat(),
                    },
                    "decision_observed_at_utc": decision_observed.isoformat(),
                    "first_eligible_execution_minute_utc": eligible.isoformat(),
                    "execution_window_observed_at_utc": None,
                })
                event_details.update({
                    "decision_bar_interval": pending_signal["decision_bar_interval"],
                    "decision_observed_at_utc": pending_signal["decision_observed_at_utc"],
                    "first_eligible_execution_minute_utc": pending_signal["first_eligible_execution_minute_utc"],
                })
            state["pending"][symbol] = pending_signal
            store.event("ENTRY_STAGED_15M", event_details)
        state["positions"] = {symbol: _position_dict(value) for symbol, value in positions.items()}
        _persist_profit_runtime(state, profit_runtime)
        state["completed_execution_ids"].append(completed_id)
        state["last_decision_bar"] = bar_time.isoformat()
        state["revision"] += 1
        if state["contract"].get("feed") == "iex":
            if decision_census is None:
                raise RuntimeError("IEX decision-cycle telemetry census is missing.")
            state["decision_cycle_telemetry_pending"] = _decision_cycle_telemetry(
                symbols=symbols,
                bar_time=bar_time,
                decision_id=completed_id,
                state_revision=state["revision"],
                feed="iex",
                vix=vix,
                census=decision_census,
            )
        store.save(state)
        _flush_pending_decision_cycle_telemetry(state, store)


def select_causal_execution_bar(rows: list[dict[str, Any]], observed_at: datetime) -> dict[str, Any]:
    eligible = []
    for row in rows:
        start = _parse(str(row["t"])); wall = start.time()
        if start + timedelta(minutes=1) <= observed_at.astimezone(NY) and (wall.hour, wall.minute) >= (9, 30) and (wall.hour, wall.minute) < (16, 0):
            price = float(row["c"])
            if math.isfinite(price) and price > 0: eligible.append((start, price, row))
    if not eligible: raise RuntimeError("No causally completed regular-session QDTE 1-minute bar is available.")
    start, price, raw = max(eligible, key=lambda item: item[0])
    return {"bar_start_market": start.isoformat(), "observed_at_utc": observed_at.astimezone(timezone.utc).isoformat(),
            "source_price": price, "feed": "sip", "timeframe": "1Min", "raw": raw}


def initialize(store: Store, contract: Mapping[str, Any], observed_at: datetime) -> dict[str, Any]:
    rows = request_bars(("QDTE",), "1Min", observed_at - timedelta(days=7), observed_at)["QDTE"]
    execution = select_causal_execution_bar(rows, observed_at)
    fill = execution["source_price"] * (1.0 + SLIPPAGE)
    shares = math.floor(STARTING_CAPITAL / fill)
    if shares < 1: raise RuntimeError("Starting capital cannot purchase one simulated QDTE share.")
    cost = shares * fill; cash = STARTING_CAPITAL - cost
    identity = {"capital": STARTING_CAPITAL, "symbol": "QDTE", "shares": shares,
                "cash_remainder": cash, "fill_price": fill, **execution,
                "contract_fingerprint": fingerprint(contract)}
    persisted_contract = json.loads(canonical(contract))
    profit_config = load_profit_recycling_config(PROFIT_CONFIG)
    profit_runtime = ProfitRecyclingRuntime(profit_config, STARTING_CAPITAL)
    state = {"schema_version": SCHEMA, "mode": "FORWARD_PAPER_ONLY",
             "live_broker_enabled": False, "simulated_fills_only": True,
             "contract": persisted_contract, "contract_fingerprint": fingerprint(contract),
             "initialization": identity, "initialization_fingerprint": fingerprint(identity),
             "contributed_capital": STARTING_CAPITAL, "cash": cash,
             "qdte_shares": shares, "qdte_cost": cost, "positions": {}, "pending": {},
             "tax_reserve_cash": 0.0, "realized_pnl": 0.0,
             "completed_execution_ids": [fingerprint(identity)], "last_decision_bar": None,
             "last_rebalance_week": None,
             "profit_recycling": {
                 "policy_identity": "PR_FRACTION_50",
                 "configuration_fingerprint": profit_config.fingerprint,
                 "event_sequence": 0, "current_event_sequence": 0,
                 "decision_ids": [], "ledger": profit_runtime.ledger.as_dict(),
             },
             "qdte_corporate_actions": {}, "invalid_qdte_corporate_actions": [],
             "qdte_open_share_snapshots": {},
             "last_corporate_action_observation_at_utc": None,
             "revision": 1}
    store.event("ACCOUNT_INITIALIZED_SIMULATED_QDTE", identity); store.save(state)
    return state


def cycle(runtime: Path, observed_at: datetime | None = None) -> dict[str, Any]:
    observed_at = observed_at or datetime.now(timezone.utc)
    contract = load_contract(); store = Store(runtime)
    with store.locked():
        state = store.load()
        if state is None: state = initialize(store, contract, observed_at)
        elif state.get("contract_fingerprint") != fingerprint(contract):
            raise RuntimeError("Persisted paper strategy identity differs from the qualified contract.")
        if state.get("schema_version") != SCHEMA:
            raise RuntimeError("Persisted paper-state schema is incompatible; refusing migration.")
        observe_qdte_corporate_actions(state, store, observed_at)
        process_latest_decision(state, store, observed_at)
        state["last_observed_at_utc"] = observed_at.astimezone(timezone.utc).isoformat()
        state["revision"] += 1; store.save(state)
        store.event("PAPER_HEARTBEAT", {"revision": state["revision"], "live_broker_enabled": False})
        return state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--runtime-dir", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--daemon", action="store_true"); parser.add_argument("--poll-seconds", type=int, default=30)
    args = parser.parse_args(argv)
    if args.poll_seconds < 15: raise ValueError("Poll interval must be at least 15 seconds.")
    while True:
        state = cycle(args.runtime_dir)
        print(json.dumps({"status": "PAPER_ONLY", "revision": state["revision"], "initialized": True,
                          "live_broker_enabled": False}, sort_keys=True), flush=True)
        if not args.daemon: return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__": raise SystemExit(main())
