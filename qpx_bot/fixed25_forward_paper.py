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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping
from zoneinfo import ZoneInfo

from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import Position
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_exit
from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs, evaluate_candidate_v1_causal
from qpx_bot.allocation import rebalance_income_allocation
import QPX_RUN_FROZEN_TOP100_STRICT_CAUSAL as qualified

ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = Path.home() / ".config/qpx/alpaca.json"
UNIVERSE = ROOT / "qpx_bot/research_universes/alpaca_top100_qdte1300_thursday_v1.json"
QUALIFICATION = ROOT / "qpx_bot/challenger_25pct_qualification.json"
DEFAULT_RUNTIME = ROOT / "runtime/qpx_fixed25_forward_paper"
DATA_URL = "https://data.alpaca.markets/v2/stocks/bars"
NY = ZoneInfo("America/New_York")
QUALIFIED_COMMIT = "bba0f48273815ede42374015db7c5770bf446962"
DATASET_FINGERPRINT = "8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8"
STARTING_CAPITAL = 1470.0
NOTIONAL_CAP = 0.25
SLIPPAGE = 0.00075
SCHEMA = 1


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
            except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                last = exc
                if attempt == 3: raise RuntimeError("Alpaca market-data request exhausted bounded retries.") from exc
                time.sleep(2 ** attempt)
        bars = payload.get("bars", {})
        if not isinstance(bars, Mapping): raise RuntimeError("Malformed Alpaca bars response.")
        for symbol, rows in bars.items():
            if symbol in collected and isinstance(rows, list): collected[symbol].extend(rows)
        token = payload.get("next_page_token")
        if not token: return collected


class Store:
    def __init__(self, directory: Path):
        self.directory = directory.resolve()
        self.state = self.directory / "paper_state.json"
        self.checksum = self.directory / "paper_state.sha256"
        self.journal = self.directory / "paper_audit.jsonl"
        self.lock = self.directory / "paper.lock"

    @contextmanager
    def locked(self) -> Iterator[None]:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Forward-paper runner is already active.") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode()); yield
        finally:
            os.close(descriptor); self.lock.unlink(missing_ok=True)

    def load(self) -> dict[str, Any] | None:
        if not self.state.exists(): return None
        encoded = self.state.read_bytes()
        if hashlib.sha256(encoded).hexdigest() != self.checksum.read_text().strip():
            raise RuntimeError("Paper-state checksum mismatch.")
        return json.loads(encoded)

    def save(self, state: dict[str, Any]) -> None:
        encoded = json.dumps(state, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
        state_tmp, sum_tmp = self.state.with_suffix(".json.tmp"), self.checksum.with_suffix(".sha256.tmp")
        state_tmp.write_bytes(encoded); sum_tmp.write_text(hashlib.sha256(encoded).hexdigest() + "\n")
        state_tmp.replace(self.state); sum_tmp.replace(self.checksum)

    def event(self, event_type: str, details: Mapping[str, Any]) -> None:
        previous = "0" * 64
        if self.journal.exists():
            with self.journal.open("rb") as handle:
                for line in handle:
                    if line.strip(): previous = json.loads(line)["record_hash"]
        core = {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type, "previous_record_hash": previous,
                "details": dict(details)}
        record = {**core, "record_hash": fingerprint(core)}
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(canonical(record).decode() + "\n"); handle.flush(); os.fsync(handle.fileno())


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

        # Qualified Thursday-only 12.5% QDTE / 87.5% swing allocation.
        if bar_time.weekday() == 3 and bar_time in indices.get("QDTE", {}):
            iso = bar_time.isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"
            if week_key != state.get("last_rebalance_week"):
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
                })

        # OPEN: execute only signals staged by an earlier completed 15-minute bar.
        for symbol, signal in sorted(list(state["pending"].items())):
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
            qdte_row = histories["QDTE"][indices["QDTE"][bar_time]]
            equity = state["cash"] + state.get("tax_reserve_cash", 0.0) + swing_value + state["qdte_shares"] * qdte_row["open"]
            active_risk = sum(pos.shares * max(0.0, pos.entry_price - pos.stop_price) for pos in positions.values())
            sizing = calculate_position_size(account_equity=equity, available_cash=state["cash"], entry_price=open_price,
                atr=signal["atr"], active_risk=active_risk, config=config, trade_results_r=())
            share_cap = math.floor((equity * NOTIONAL_CAP) / sizing.entry_fill) if sizing.entry_fill else 0
            shares = min(sizing.shares, share_cap)
            if not sizing.is_tradeable or shares < 1:
                store.event("SIMULATED_ENTRY_REJECTED", {"symbol": symbol, "execution_id": execution_id, "reason": sizing.blocked_reason or "NOTIONAL_CAP"})
            else:
                cost = shares * sizing.entry_fill; state["cash"] -= cost
                positions[symbol] = Position(symbol=symbol, shares=shares, entry_date=bar_time.date(),
                    entry_price=sizing.entry_fill, entry_atr=signal["atr"], stop_price=sizing.stop_price,
                    target_price=sizing.target_price, highest_price=sizing.entry_fill)
                store.event("SIMULATED_ENTRY_FILLED", {"symbol": symbol, "execution_id": execution_id,
                    "shares": shares, "fill_price": sizing.entry_fill, "sip_1m_bar": str(one["t"])})
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
                    state["cash"] += proceeds; state["realized_pnl"] = state.get("realized_pnl", 0.0) + pnl
                    target_tax = max(0.0, state["realized_pnl"]) * config.annual_tax_reserve_rate
                    delta = target_tax - state.get("tax_reserve_cash", 0.0)
                    state["cash"] -= delta; state["tax_reserve_cash"] = target_tax
                    store.event("SIMULATED_EXIT_FILLED", {"symbol": symbol, "execution_id": execution_id,
                        "shares": position.shares, "fill_price": fill, "reason": evaluation.reason,
                        "sip_1m_bar": str(minute["t"])})
                    state["completed_execution_ids"].append(execution_id)
                positions.pop(symbol, None)
            else:
                position.stop_price = evaluation.next_stop_price; position.highest_price = evaluation.highest_price

        # Stage new Candidate V1 signals from completed 15-minute data only.
        qualifying = []
        try: vix = _vix_previous_close(bar_time.date())
        except RuntimeError as exc:
            store.event("ENTRY_EVALUATION_FAILED_CLOSED", {"bar": bar_time.isoformat(), "reason": str(exc)})
            vix = None
        if vix is not None:
            for symbol in symbols:
                index = indices.get(symbol, {}).get(bar_time)
                if index is None or symbol in positions or symbol in state["pending"]: continue
                inputs = _entry_inputs(histories[symbol], index, indicators[symbol], vix, config)
                if inputs is None: continue
                result = evaluate_candidate_v1_causal(inputs=inputs, config=config)
                if result.should_enter: qualifying.append((hashlib.sha256((bar_time.isoformat()+"|"+symbol).encode()).hexdigest(), symbol, inputs.current_atr, inputs.current_close))
        slots = max(0, 6 - len(positions) - len(state["pending"]))
        for _, symbol, atr, close in sorted(qualifying)[:slots]:
            signal_id = fingerprint({"symbol": symbol, "bar": bar_time.isoformat(), "atr": atr,
                                     "contract": state["contract_fingerprint"]})
            state["pending"][symbol] = {"signal_id": signal_id, "signal_bar": bar_time.isoformat(), "atr": atr, "prior_close": close}
            store.event("ENTRY_STAGED_15M", {"symbol": symbol, "signal_id": signal_id, "bar": bar_time.isoformat()})
        state["positions"] = {symbol: _position_dict(value) for symbol, value in positions.items()}
        state["completed_execution_ids"].append(completed_id)
        state["last_decision_bar"] = bar_time.isoformat(); state["revision"] += 1; store.save(state)


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
    state = {"schema_version": SCHEMA, "mode": "FORWARD_PAPER_ONLY",
             "live_broker_enabled": False, "simulated_fills_only": True,
             "contract": persisted_contract, "contract_fingerprint": fingerprint(contract),
             "initialization": identity, "initialization_fingerprint": fingerprint(identity),
             "contributed_capital": STARTING_CAPITAL, "cash": cash,
             "qdte_shares": shares, "qdte_cost": cost, "positions": {}, "pending": {},
             "tax_reserve_cash": 0.0, "realized_pnl": 0.0,
             "completed_execution_ids": [fingerprint(identity)], "last_decision_bar": None,
             "last_rebalance_week": None,
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
