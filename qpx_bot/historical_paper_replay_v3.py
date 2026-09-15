"""Resumable asset-ID keyed V3 reservoir replay."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import csv
import gzip
import json
from pathlib import Path
import sqlite3
import subprocess
from typing import Any, Iterable, Mapping, Sequence

from qpx_bot.actual_two_year_15m_six import _read_vix_daily_cache
from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.data_loader import Candle
from qpx_bot.historical_paper_replay import CandidateV1ReplayPort, ReplayConfigurationError, load_replay_configuration
from qpx_bot.historical_paper_replay_runner import (
    DEFAULT_DATASET, DEFAULT_VIX, RUN_SCHEMA, CandidateV1HistoricalPaperRuntime,
    CompletedBarEvidence, CompletedBoundary, _fingerprint, _load_dividends,
    _load_strategy_profile, _sha256, _write_evidence, _write_runtime_state,
)
from qpx_bot.indicators import calculate_indicators
from qpx_bot.intraday_six_paper import IntradayBar
from qpx_bot.ml_historical_calendar_repair import AUDITED_FALSE_OPEN_DATES
from qpx_bot.paper_state import read_checksummed_state
from qpx_bot.reservoir_replay_universe import canonical_bytes, split_excluded_asset_ids


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "qpx_bot/replay_configs/volume_confirmation_90_ten_year_sip_reservoir_split_excluded_v3.json"
DEFAULT_PROFILE = ROOT / "qpx_bot/paper_profiles/volume_confirmation_25_v1.json"
SEMANTIC = "QPX_ASSET_ID_RESERVOIR_REPLAY_V3"


def load_bound_universe(config: Any, dataset: Path) -> tuple[dict[str, str], Mapping[str, Any]]:
    universe = config.payload["universe"]
    path = (ROOT / str(universe["manifest_reference"])).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claimed = manifest.pop("manifest_fingerprint", None)
    actual = _fingerprint(manifest)
    manifest["manifest_fingerprint"] = claimed
    if actual != claimed or claimed != universe["manifest_fingerprint"]:
        raise ReplayConfigurationError("V3 universe manifest fingerprint mismatch.")
    if manifest.get("selected_count") != 31431 or manifest.get("split_excluded_count") != 2044:
        raise ReplayConfigurationError("V3 universe approved counts differ.")
    members = manifest.get("members")
    asset_symbols = {str(item["provider_asset_id"]): str(item["canonical_symbol"]).upper() for item in members}
    if len(asset_symbols) != 31431:
        raise ReplayConfigurationError("V3 universe provider asset identities are not unique.")
    if set(asset_symbols) & split_excluded_asset_ids(dataset):
        raise ReplayConfigurationError("V3 universe contains a split-excluded provider asset.")
    return asset_symbols, manifest


def _vix_for(start: datetime, vix: Mapping[Any, float], days: list[Any]) -> float | None:
    index = bisect_left(days, start.date()) - 1
    day = days[index] if index >= 0 else None
    return vix[day] if day is not None and (start.date() - day).days <= 7 else None


def _inputs(bars: list[IntradayBar], config: Any) -> list[CandidateV1CausalInputs | None]:
    candles = [Candle(date=b.start.date(), open=b.open, high=b.high, low=b.low, close=b.close, volume=b.volume) for b in bars]
    indicators = calculate_indicators(candles, config)
    result: list[CandidateV1CausalInputs | None] = []
    for index, bar in enumerate(bars):
        previous = index - 1; slope = index - config.sma_slope_lookback
        if previous < 0 or slope < 0 or index < config.breakout_lookback:
            result.append(None); continue
        needed = (indicators.ema_fast[index], indicators.ema_slow[index], indicators.rsi[index], indicators.rmi[index], indicators.atr[index], indicators.sma_trend[index], indicators.average_volume[previous])
        if any(x is None for x in needed) or indicators.ema_fast[previous] is None or indicators.ema_slow[previous] is None or indicators.rsi[previous] is None or indicators.rmi[previous] is None or indicators.sma_trend[slope] is None:
            result.append(None); continue
        result.append(CandidateV1CausalInputs(
            index=index, current_close=bar.close, current_volume=bar.volume,
            current_fast=float(indicators.ema_fast[index]), previous_fast=float(indicators.ema_fast[previous]),
            current_slow=float(indicators.ema_slow[index]), previous_slow=float(indicators.ema_slow[previous]),
            current_rsi=float(indicators.rsi[index]), previous_rsi=float(indicators.rsi[previous]),
            current_rmi=float(indicators.rmi[index]), previous_rmi=float(indicators.rmi[previous]),
            current_sma=float(indicators.sma_trend[index]), slope_sma=float(indicators.sma_trend[slope]),
            baseline_volume=float(indicators.average_volume[previous]), current_atr=float(indicators.atr[index]),
            prior_high=max(c.high for c in candles[index-config.breakout_lookback:index]), vix=0.0,
        ))
    return result


def _database(path: Path, identity: Mapping[str, str]) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.executescript("""
    PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS prepared_batches(batch INTEGER PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS boundaries(start TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS bars(asset_id TEXT NOT NULL,start TEXT NOT NULL,symbol TEXT NOT NULL,o REAL,h REAL,l REAL,c REAL,volume INTEGER,inputs TEXT,PRIMARY KEY(asset_id,start));
    CREATE TABLE IF NOT EXISTS qualifiers(start TEXT NOT NULL,asset_id TEXT NOT NULL,PRIMARY KEY(start,asset_id));
    CREATE INDEX IF NOT EXISTS qualifiers_start ON qualifiers(start);
    """)
    for key, value in identity.items():
        old = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if old and old[0] != value:
            raise ReplayConfigurationError(f"V3 preparation identity mismatch: {key}.")
        db.execute("INSERT OR IGNORE INTO meta(key,value) VALUES(?,?)", (key, value))
    db.commit(); return db


def _read_partition(path: Path, selected: set[str], rows: dict[str, dict[datetime, IntradayBar]]) -> None:
    with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            asset_id = str(raw.get("provider_asset_id"))
            if asset_id not in selected:
                continue
            start = datetime.fromisoformat(str(raw["market_timestamp"]))
            if start.date() in AUDITED_FALSE_OPEN_DATES:
                continue
            bar = IntradayBar(start=start, open=float(raw["open"]), high=float(raw["high"]), low=float(raw["low"]), close=float(raw["close"]), volume=int(raw["volume"]))
            previous = rows[asset_id].get(start)
            if previous is not None and previous != bar:
                raise ReplayConfigurationError("Conflicting bars for one provider asset identity.")
            rows[asset_id][start] = bar


def prepare(run_dir: Path, dataset: Path, asset_symbols: Mapping[str, str], snapshot: Any, identity: Mapping[str, str]) -> sqlite3.Connection:
    state_path = dataset / "acquisition_state/state.json"
    state = json.loads(read_checksummed_state(state_path, state_path.with_suffix(".sha256"), label="Historical acquisition state"))
    db = _database(run_dir / "v3_replay_cache.sqlite3", identity)
    completed = {row[0] for row in db.execute("SELECT batch FROM prepared_batches")}
    vix = _read_vix_daily_cache(DEFAULT_VIX); vix_days = sorted(vix); port = CandidateV1ReplayPort(snapshot)
    by_batch: dict[int, list[Mapping[str, Any]]] = {}
    for part in state["partitions"]:
        by_batch.setdefault(int(part["batch"]), []).append(part)
    income_ids = {asset_id for asset_id, symbol in asset_symbols.items() if symbol == "QDTE"}
    for batch, parts in sorted(by_batch.items()):
        if batch in completed:
            continue
        selected = set(asset_symbols) & {str(x) for part in parts for x in part["asset_ids"]}
        rows = {asset_id: {} for asset_id in selected}
        for part in sorted(parts, key=lambda item: int(item["year"])):
            path = dataset / f"bars_15m/year={int(part['year'])}/batch={batch:05d}.csv.gz"
            manifest = json.loads(path.with_suffix(path.suffix + ".manifest.json").read_text())
            if _sha256(path) != manifest.get("sha256"):
                raise ReplayConfigurationError(f"Bar partition checksum mismatch: {path}")
            _read_partition(path, selected, rows)
            for repair in sorted((dataset / f"calendar_repairs/year={int(part['year'])}/batch={batch:05d}").glob("*.csv.gz")):
                _read_partition(repair, selected, rows)
        with db:
            for asset_id, values in rows.items():
                bars = [bar for _, bar in sorted(values.items())]
                inputs = _inputs(bars, snapshot.bot_config)
                qualifiers: list[int] = []
                for index, item in enumerate(inputs):
                    if item is None: continue
                    actual_vix = _vix_for(bars[index].start, vix, vix_days)
                    if actual_vix is not None and port.evaluate(CandidateV1CausalInputs(**{**asdict(item), "vix": actual_vix})).should_enter:
                        qualifiers.append(index)
                db.executemany("INSERT OR IGNORE INTO boundaries(start) VALUES(?)", ((bar.start.isoformat(),) for bar in bars))
                if not qualifiers and asset_id not in income_ids:
                    continue
                db.executemany("INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?,?)", ((asset_id, bar.start.isoformat(), asset_symbols[asset_id], bar.open, bar.high, bar.low, bar.close, bar.volume, json.dumps(asdict(inputs[index]), sort_keys=True) if inputs[index] else None) for index, bar in enumerate(bars)))
                db.executemany("INSERT OR IGNORE INTO qualifiers VALUES(?,?)", ((bars[index].start.isoformat(), asset_id) for index in qualifiers))
            db.execute("INSERT INTO prepared_batches(batch) VALUES(?)", (batch,))
        _write_evidence(run_dir / "preparation_checkpoint.json", {**identity, "status":"PREPARING", "last_completed_batch":batch, "completed_batch_count":db.execute("SELECT count(*) FROM prepared_batches").fetchone()[0], "total_batch_count":len(by_batch)})
    return db


def run(config_path: Path = DEFAULT_CONFIG, dataset: Path = DEFAULT_DATASET, profile_path: Path = DEFAULT_PROFILE) -> Path:
    config = load_replay_configuration(config_path); snapshot = _load_strategy_profile(profile_path, config)
    asset_symbols, universe = load_bound_universe(config, dataset)
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    implementation = _fingerprint({"v3_runner":_sha256(Path(__file__)), "runtime":_sha256(ROOT / "qpx_bot/historical_paper_replay_runner.py")})
    run_id = _fingerprint({"configuration_fingerprint":config.fingerprint, "implementation_fingerprint":implementation})
    run_dir = dataset / "historical_paper_replay_v3" / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    identity = {"run_id":run_id, "configuration_fingerprint":config.fingerprint, "universe_manifest_fingerprint":universe["manifest_fingerprint"], "implementation_fingerprint":implementation}
    _write_evidence(run_dir / "run_manifest.json", {"schema_version":RUN_SCHEMA,"semantic_version":SEMANTIC,"status":"PREPARING","source_commit":source_commit,**identity,"asset_identity":"provider_asset_id","asset_count":len(asset_symbols),"symbol_role":"NON_UNIQUE_LABEL","configuration":config.as_dict(),"authority":config.payload["authority"],"started_at_utc":datetime.now(timezone.utc).isoformat()})
    db = prepare(run_dir, dataset, asset_symbols, snapshot, identity)
    from qpx_bot.historical_paper_replay_runner import _read_runtime_state
    restored = _read_runtime_state(run_dir, config)
    runtime = CandidateV1HistoricalPaperRuntime(config, restored, candidate_snapshot=snapshot, asset_symbols=asset_symbols)
    dividends = _load_dividends(dataset, "QDTE")
    after = runtime.state["last_completed_boundary"]
    after_start = (datetime.fromisoformat(after) - timedelta(minutes=15)).isoformat() if after else None
    query = "SELECT start FROM boundaries" + (" WHERE start>?" if after_start else "") + " ORDER BY start"
    vix=_read_vix_daily_cache(DEFAULT_VIX); days=sorted(vix)
    for (start_text,) in db.execute(query, (after_start,) if after_start else ()):
        start = datetime.fromisoformat(start_text); wanted = set(runtime.state["pending"]) | set(runtime._portfolio.positions) | {runtime.income_asset_id}
        wanted |= {row[0] for row in db.execute("SELECT asset_id FROM qualifiers WHERE start=?", (start_text,))}
        evidence=[]
        for asset_id in wanted:
            row=db.execute("SELECT symbol,o,h,l,c,volume,inputs FROM bars WHERE asset_id=? AND start=?",(asset_id,start_text)).fetchone()
            if not row: continue
            symbol,o,h,l,c,volume,raw=row; inputs=CandidateV1CausalInputs(**json.loads(raw)) if raw else None
            evidence.append(CompletedBarEvidence(symbol,asset_id,IntradayBar(start,o,h,l,c,volume),start+timedelta(minutes=15),inputs))
        completed=start+timedelta(minutes=15)
        runtime.process_boundary(CompletedBoundary(_fingerprint({"kind":"COMPLETED_15M","time":completed.isoformat()}),completed,tuple(evidence),_vix_for(start,vix,days)),dividends)
        _write_runtime_state(run_dir,run_id,config,runtime)
    state = runtime.snapshot(); marks=state["last_marks"]; positions=state["portfolio"]["positions"]
    swing_value=sum(float(marks.get(asset_id,value["entry_price"]))*value["shares"] for asset_id,value in positions.items())
    income_value=float(state["income_shares"])*float(marks.get(runtime.income_asset_id,0.0))
    ending=state["portfolio"]["cash"]+state["portfolio"]["tax_reserve_cash"]+swing_value+income_value
    report={"schema_version":RUN_SCHEMA,"semantic_version":SEMANTIC,"run_id":run_id,"status":"COMPLETE",**identity,
        "asset_identity":"provider_asset_id","symbol_role":"NON_UNIQUE_LABEL","starting_equity":config.payload["starting_account"]["starting_cash"],
        "ending_equity":ending,"net_profit_loss":ending-state["portfolio"]["total_contributions"],"maximum_drawdown":state["maximum_drawdown"],
        "completed_15m_boundaries":state["boundaries"],"candidate_v1_evaluations":state["candidate_evaluations"],"signals":state["signals"],"fills":state["fills"],
        "capacity_arbitration":config.payload["capacity_arbitration"],"capacity_decisions":state["capacity_decisions"],"capacity_deferred":state["capacity_deferred"],
        "closed_trades":len(state["portfolio"]["closed_trades"]),"ending_positions":{asset_id:{**value,"symbol_label":asset_symbols[asset_id]} for asset_id,value in positions.items()},
        "outcome_reconciliation":state["outcome_reconciliation"],
        "authority":config.payload["authority"],"completed_at_utc":datetime.now(timezone.utc).isoformat()}
    _write_evidence(run_dir / "final_report.json",report)
    _write_evidence(run_dir / "exit_status.json", {"run_id":run_id,"status":"COMPLETE","exit_code":0})
    run_manifest=json.loads(read_checksummed_state(run_dir/"run_manifest.json",run_dir/"run_manifest.json.sha256",label="V3 run manifest"))
    run_manifest.update({"status":"COMPLETE","completed_at_utc":report["completed_at_utc"],"final_report_fingerprint":_fingerprint(report)})
    _write_evidence(run_dir/"run_manifest.json",run_manifest)
    return run_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG); parser.add_argument("--dataset",type=Path,default=DEFAULT_DATASET); parser.add_argument("--strategy-profile",type=Path,default=DEFAULT_PROFILE)
    args=parser.parse_args(argv); print(run(args.config.resolve(),args.dataset.resolve(),args.strategy_profile.resolve())); return 0


if __name__ == "__main__": raise SystemExit(main())
