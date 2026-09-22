"""Resumable asset-ID keyed V3 reservoir replay."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import asdict
from datetime import datetime, time, timedelta, timezone
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
from qpx_bot.historical_paper_replay_v3_evidence import (
    EVIDENCE_SEMANTIC_VERSION,
    V3EvidenceArchive,
    initial_archive_state,
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
DEFAULT_CHECKPOINT_INTERVAL_BOUNDARIES = 32


def _validate_checkpoint_interval_boundaries(value: int) -> int:
    if type(value) is not int or value < 1:
        raise ReplayConfigurationError(
            "V3 checkpoint interval boundaries must be a positive integer."
        )
    return value


def _pending_boundary_rows(
    db: sqlite3.Connection, last_completed_boundary: str | None,
) -> Iterable[tuple[str]]:
    if last_completed_boundary is None:
        return db.execute("SELECT start FROM boundaries ORDER BY start")
    last_durable_start = (
        datetime.fromisoformat(last_completed_boundary) - timedelta(minutes=15)
    ).isoformat()
    return db.execute(
        "SELECT start FROM boundaries WHERE start>? ORDER BY start",
        (last_durable_start,),
    )


def _checkpoint_replay_state(
    run_dir: Path,
    run_id: str,
    config: Any,
    runtime: CandidateV1HistoricalPaperRuntime,
    boundaries_since_checkpoint: int,
    checkpoint_interval_boundaries: int,
    evidence_archive: V3EvidenceArchive | None = None,
) -> int:
    if boundaries_since_checkpoint >= checkpoint_interval_boundaries:
        _write_checkpoint_transaction(
            run_dir, run_id, config, runtime, evidence_archive,
        )
        return 0
    return boundaries_since_checkpoint


def _checkpoint_final_replay_state(
    run_dir: Path,
    run_id: str,
    config: Any,
    runtime: CandidateV1HistoricalPaperRuntime,
    boundaries_since_checkpoint: int,
    evidence_archive: V3EvidenceArchive | None = None,
) -> None:
    if boundaries_since_checkpoint > 0 or not (run_dir / "checkpoint.json").exists():
        _write_checkpoint_transaction(
            run_dir, run_id, config, runtime, evidence_archive,
        )


def _write_checkpoint_transaction(
    run_dir: Path, run_id: str, config: Any,
    runtime: CandidateV1HistoricalPaperRuntime,
    evidence_archive: V3EvidenceArchive | None,
) -> None:
    if evidence_archive is None:
        _write_runtime_state(run_dir, run_id, config, runtime)
        return
    flush = evidence_archive.prepare_flush(runtime)
    evidence_archive.persist_and_verify_batch(flush)
    _write_runtime_state(
        run_dir, run_id, config, runtime, paper_state=flush.compact_state,
    )
    evidence_archive.commit_flush(runtime, flush)
    evidence_archive.write_progress_report(runtime)


def _account_report_fields(valuation: Mapping[str, Any]) -> dict[str, Any]:
    """Bind final-report account fields to the checkpoint valuation contract."""
    return {
        "valuation_boundary": valuation["valuation_boundary"],
        "current_marked_equity": valuation["current_marked_equity"],
        "deployable_cash": valuation["deployable_cash"],
        "tax_reserve": valuation["tax_reserve"],
        "swing_market_value": valuation["swing_market_value"],
        "income_sleeve_market_value": valuation["income_sleeve_market_value"],
    }


def load_bound_universe(config: Any, dataset: Path) -> tuple[dict[str, str], Mapping[str, Any]]:
    universe = config.payload["universe"]
    path = (ROOT / str(universe["manifest_reference"])).resolve()
    checksum_path = path.with_suffix(path.suffix + ".sha256")
    if checksum_path.exists() and _sha256(path) != checksum_path.read_text(encoding="utf-8").strip():
        raise ReplayConfigurationError("V3 universe manifest file checksum mismatch.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    claimed = manifest.pop("manifest_fingerprint", None)
    actual = _fingerprint(manifest)
    manifest["manifest_fingerprint"] = claimed
    if actual != claimed or claimed != universe["manifest_fingerprint"]:
        raise ReplayConfigurationError("V3 universe manifest fingerprint mismatch.")
    members = manifest.get("members")
    selected_count = manifest.get("selected_count")
    if (
        not isinstance(members, list) or type(selected_count) is not int
        or selected_count < 1 or len(members) != selected_count
    ):
        raise ReplayConfigurationError("V3 universe manifest count does not reconcile.")
    asset_symbols = {
        str(item["provider_asset_id"]): str(
            item.get("canonical_symbol", item.get("symbol_label", ""))
        ).upper()
        for item in members
    }
    if len(asset_symbols) != selected_count or any(not value for value in asset_symbols.values()):
        raise ReplayConfigurationError("V3 universe provider asset identities are not unique.")
    income = manifest.get("income_asset")
    if income is not None:
        if not isinstance(income, Mapping):
            raise ReplayConfigurationError("V3 universe income asset is malformed.")
        income_id = str(income.get("provider_asset_id", ""))
        income_label = str(income.get("symbol_label", "")).upper()
        if not income_id or not income_label or income_id in asset_symbols:
            raise ReplayConfigurationError("V3 universe income identity is invalid.")
        asset_symbols[income_id] = income_label
    split_policy = manifest.get("split_policy", "EXCLUDE_SELECTED_SPLIT_ASSETS")
    if split_policy == "EXCLUDE_SELECTED_SPLIT_ASSETS":
        excluded_count = manifest.get("split_excluded_count")
        if type(excluded_count) is not int or excluded_count < 1:
            raise ReplayConfigurationError("V3 split-exclusion count is invalid.")
        if set(asset_symbols) & split_excluded_asset_ids(dataset):
            raise ReplayConfigurationError("V3 universe contains a split-excluded provider asset.")
    elif split_policy == "CAUSAL_APPLY_AT_EFFECTIVE_OPEN":
        if manifest.get("split_excluded_count") != 0:
            raise ReplayConfigurationError("Causal-split universe cannot declare split exclusions.")
        if manifest.get("split_event_count") != len(manifest.get("split_events", ())):
            raise ReplayConfigurationError("Causal-split universe event count does not reconcile.")
    else:
        raise ReplayConfigurationError("V3 universe split policy is unsupported.")
    return asset_symbols, manifest


def _vix_for(start: datetime, vix: Mapping[Any, float], days: list[Any]) -> float | None:
    index = bisect_left(days, start.date()) - 1
    day = days[index] if index >= 0 else None
    return vix[day] if day is not None and (start.date() - day).days <= 7 else None


def _vix_observation_for(
    start: datetime, vix: Mapping[Any, float], days: list[Any],
) -> tuple[float | None, datetime | None]:
    index = bisect_left(days, start.date()) - 1
    day = days[index] if index >= 0 else None
    if day is None or (start.date() - day).days > 7:
        return None, None
    return vix[day], datetime.combine(day, time(16, 0), tzinfo=start.tzinfo)


def _inputs_from_indicators(
    bars: list[IntradayBar], candles: list[Candle], indicators: Any, config: Any,
    result: list[CandidateV1CausalInputs | None], start_index: int, end_index: int,
) -> None:
    for index in range(start_index, end_index):
        bar = bars[index]
        previous = index - 1; slope = index - config.sma_slope_lookback
        if previous < 0 or slope < 0 or index < config.breakout_lookback:
            result[index] = None; continue
        needed = (indicators.ema_fast[index], indicators.ema_slow[index], indicators.rsi[index], indicators.rmi[index], indicators.atr[index], indicators.sma_trend[index], indicators.average_volume[previous])
        if any(x is None for x in needed) or indicators.ema_fast[previous] is None or indicators.ema_slow[previous] is None or indicators.rsi[previous] is None or indicators.rmi[previous] is None or indicators.sma_trend[slope] is None:
            result[index] = None; continue
        result[index] = CandidateV1CausalInputs(
            index=index, current_close=bar.close, current_volume=bar.volume,
            current_fast=float(indicators.ema_fast[index]), previous_fast=float(indicators.ema_fast[previous]),
            current_slow=float(indicators.ema_slow[index]), previous_slow=float(indicators.ema_slow[previous]),
            current_rsi=float(indicators.rsi[index]), previous_rsi=float(indicators.rsi[previous]),
            current_rmi=float(indicators.rmi[index]), previous_rmi=float(indicators.rmi[previous]),
            current_sma=float(indicators.sma_trend[index]), slope_sma=float(indicators.sma_trend[slope]),
            baseline_volume=float(indicators.average_volume[previous]), current_atr=float(indicators.atr[index]),
            prior_high=max(c.high for c in candles[index-config.breakout_lookback:index]), vix=0.0,
        )


def _inputs(
    bars: list[IntradayBar], config: Any,
    split_events: Sequence[Mapping[str, Any]] = (),
) -> list[CandidateV1CausalInputs | None]:
    """Compute causal inputs, rescaling accumulated history only when a split is effective."""
    candles = [
        Candle(
            date=b.start.date(), open=b.open, high=b.high, low=b.low,
            close=b.close, volume=b.volume,
        )
        for b in bars
    ]
    result: list[CandidateV1CausalInputs | None] = [None] * len(bars)
    events_by_index: dict[int, list[Mapping[str, Any]]] = {}
    starts = [bar.start.date() for bar in bars]
    seen: set[str] = set()
    for event in sorted(
        split_events,
        key=lambda item: (str(item["effective_date"]), str(item["provider_event_id"])),
    ):
        event_id = str(event["provider_event_id"])
        if event_id in seen:
            raise ReplayConfigurationError("Duplicate split event in causal indicator input.")
        seen.add(event_id)
        effective = datetime.fromisoformat(str(event["effective_date"])).date()
        index = bisect_left(starts, effective)
        if index < len(bars):
            events_by_index.setdefault(index, []).append(event)
    segment_start = 0
    for index, events in sorted(events_by_index.items()):
        indicators = calculate_indicators(candles, config)
        _inputs_from_indicators(
            bars, candles, indicators, config, result, segment_start, index,
        )
        for event in events:
            share_multiplier = float(event["share_multiplier"])
            price_multiplier = float(event["price_multiplier"])
            if share_multiplier <= 0 or price_multiplier <= 0:
                raise ReplayConfigurationError("Causal indicator split ratio is invalid.")
            for prior in range(index):
                candle = candles[prior]
                candles[prior] = Candle(
                    date=candle.date,
                    open=candle.open * price_multiplier,
                    high=candle.high * price_multiplier,
                    low=candle.low * price_multiplier,
                    close=candle.close * price_multiplier,
                    volume=candle.volume * share_multiplier,
                )
        segment_start = index
    indicators = calculate_indicators(candles, config)
    _inputs_from_indicators(
        bars, candles, indicators, config, result, segment_start, len(bars),
    )
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


def prepare(
    run_dir: Path, dataset: Path, asset_symbols: Mapping[str, str], snapshot: Any,
    identity: Mapping[str, str], split_events: Sequence[Mapping[str, Any]] = (),
) -> sqlite3.Connection:
    state_path = dataset / "acquisition_state/state.json"
    state = json.loads(read_checksummed_state(state_path, state_path.with_suffix(".sha256"), label="Historical acquisition state"))
    db = _database(run_dir / "v3_replay_cache.sqlite3", identity)
    completed = {row[0] for row in db.execute("SELECT batch FROM prepared_batches")}
    vix = _read_vix_daily_cache(DEFAULT_VIX); vix_days = sorted(vix); port = CandidateV1ReplayPort(snapshot)
    by_batch: dict[int, list[Mapping[str, Any]]] = {}
    selected_asset_ids = set(asset_symbols)
    partition_asset_ids: set[str] = set()
    for part in state["partitions"]:
        part_asset_ids = {str(item) for item in part["asset_ids"]}
        partition_asset_ids.update(part_asset_ids & selected_asset_ids)
        if part_asset_ids & selected_asset_ids:
            by_batch.setdefault(int(part["batch"]), []).append(part)
    missing = selected_asset_ids - partition_asset_ids
    if missing:
        raise ReplayConfigurationError(
            f"Selected provider assets are absent from reservoir partitions: {sorted(missing)}"
        )
    income_ids = {asset_id for asset_id, symbol in asset_symbols.items() if symbol == "QDTE"}
    split_events_by_asset: dict[str, list[Mapping[str, Any]]] = {}
    for event in split_events:
        split_events_by_asset.setdefault(
            str(event["affected_provider_asset_id"]), []
        ).append(event)
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
                inputs = _inputs(
                    bars, snapshot.bot_config, split_events_by_asset.get(asset_id, ()),
                )
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


def run(
    config_path: Path = DEFAULT_CONFIG,
    dataset: Path = DEFAULT_DATASET,
    profile_path: Path = DEFAULT_PROFILE,
    checkpoint_interval_boundaries: int = DEFAULT_CHECKPOINT_INTERVAL_BOUNDARIES,
) -> Path:
    checkpoint_interval_boundaries = _validate_checkpoint_interval_boundaries(
        checkpoint_interval_boundaries
    )
    config = load_replay_configuration(config_path); snapshot = _load_strategy_profile(profile_path, config)
    asset_symbols, universe = load_bound_universe(config, dataset)
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    implementation = _fingerprint({
        "v3_runner": _sha256(Path(__file__)),
        "bounded_evidence": _sha256(
            ROOT / "qpx_bot/historical_paper_replay_v3_evidence.py"
        ),
        "replay_configuration": _sha256(ROOT / "qpx_bot/historical_paper_replay.py"),
        "runtime": _sha256(ROOT / "qpx_bot/historical_paper_replay_runner.py"),
        "portfolio": _sha256(ROOT / "qpx_bot/portfolio.py"),
        "top100_evidence_builder": _sha256(ROOT / "qpx_bot/top100_split_evidence.py"),
        "historical_replay_accelerators": _sha256(ROOT / "qpx_bot/historical_replay_accelerators.py"),
        "dynamic_sizing": _sha256(ROOT / "qpx_bot/accelerators/dynamic_sizing.py"),
        "profit_recycling": _sha256(ROOT / "qpx_bot/accelerators/profit_recycling.py"),
        "pyramiding": _sha256(ROOT / "qpx_bot/accelerators/pyramiding.py"),
        "regime_allocation": _sha256(ROOT / "qpx_bot/accelerators/regime_allocation.py"),
    })
    run_identity = {
        "configuration_fingerprint": config.fingerprint,
        "implementation_fingerprint": implementation,
        "universe_manifest_fingerprint": universe["manifest_fingerprint"],
        "derived_asset_id_universe_fingerprint": universe.get(
            "derived_asset_id_universe_fingerprint", universe["manifest_fingerprint"]
        ),
        "dataset_fingerprint": config.payload["dataset"]["snapshot_fingerprint"],
        "frozen_selection_fingerprint": universe.get("frozen_selection_fingerprint"),
        "corporate_action_artifact_fingerprint": universe.get(
            "corporate_action_ratio_artifact_fingerprint",
            universe.get("source_corporate_action_fingerprint"),
        ),
        "identity_resolution_fingerprint": universe.get(
            "derived_identity_resolution_fingerprint",
            universe.get("source_identity_resolution_fingerprint"),
        ),
        "split_accounting_semantic_version": universe.get(
            "split_accounting_semantic_version", "SPLIT_EXCLUDED"
        ),
        "accelerator_bundle_fingerprint": (
            _fingerprint(config.payload["accelerators"])
            if config.payload.get("accelerators") is not None else None
        ),
    }
    run_id = _fingerprint(run_identity)
    run_dir = dataset / "historical_paper_replay_v3" / run_id; run_dir.mkdir(parents=True, exist_ok=True)
    identity = {
        "run_id": run_id,
        **{key: value for key, value in run_identity.items() if value is not None},
    }
    _write_evidence(run_dir / "run_manifest.json", {
        "schema_version": RUN_SCHEMA, "semantic_version": SEMANTIC,
        "status": "PREPARING", "source_commit": source_commit, **identity,
        "asset_identity": "provider_asset_id",
        "swing_asset_count": universe["selected_count"],
        "total_asset_count_including_income": len(asset_symbols),
        "symbol_role": "NON_UNIQUE_LABEL",
        "selection_bias_label": universe.get("selection_bias_label"),
        "split_policy": universe.get("split_policy", "EXCLUDE_SELECTED_SPLIT_ASSETS"),
        "split_event_count": universe.get("split_event_count", 0),
        "fractional_share_policy": universe.get("fractional_share_policy"),
        "entry_share_policy": universe.get("entry_share_policy", "INTEGER_ONLY"),
        "checkpoint_interval_boundaries": checkpoint_interval_boundaries,
        "evidence_batch_semantic_version": EVIDENCE_SEMANTIC_VERSION,
        "accelerators": config.payload.get("accelerators"),
        "experiment_risk": config.payload.get("experiment_risk"),
        "configuration": config.as_dict(), "authority": config.payload["authority"],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
    })
    split_contract = (
        universe if universe.get("split_policy") == "CAUSAL_APPLY_AT_EFFECTIVE_OPEN"
        else None
    )
    db = prepare(
        run_dir, dataset, asset_symbols, snapshot, identity,
        universe.get("split_events", ()),
    )
    for event in universe.get("split_events", ()):
        effective = str(event["effective_date"])
        exists = db.execute(
            "SELECT 1 FROM boundaries WHERE start LIKE ? LIMIT 1",
            (effective + "T09:30:%",),
        ).fetchone()
        if exists is None:
            raise ReplayConfigurationError(
                f"Split event lacks an effective market-open boundary: {event['provider_event_id']}"
            )
    from qpx_bot.historical_paper_replay_runner import _read_runtime_state
    restored = _read_runtime_state(run_dir, config)
    runtime = CandidateV1HistoricalPaperRuntime(
        config, restored, candidate_snapshot=snapshot, asset_symbols=asset_symbols,
        split_contract=split_contract,
    )
    if restored is None:
        runtime.state["evidence_archive"] = initial_archive_state()
    elif "evidence_archive" not in runtime.state:
        raise ReplayConfigurationError(
            "V3 checkpoint predates bounded evidence and cannot be reused under this implementation."
        )
    evidence_archive = V3EvidenceArchive(run_dir, identity, runtime)
    dividends = _load_dividends(dataset, "QDTE")
    after = runtime.state["last_completed_boundary"]
    boundaries_since_checkpoint = 0
    vix=_read_vix_daily_cache(DEFAULT_VIX); days=sorted(vix)
    for (start_text,) in _pending_boundary_rows(db, after):
        start = datetime.fromisoformat(start_text); wanted = set(runtime.state["pending"]) | set(runtime._portfolio.positions) | {runtime.income_asset_id}
        wanted |= {row[0] for row in db.execute("SELECT asset_id FROM qualifiers WHERE start=?", (start_text,))}
        evidence=[]
        for asset_id in wanted:
            row=db.execute("SELECT symbol,o,h,l,c,volume,inputs FROM bars WHERE asset_id=? AND start=?",(asset_id,start_text)).fetchone()
            if not row: continue
            symbol,o,h,l,c,volume,raw=row; inputs=CandidateV1CausalInputs(**json.loads(raw)) if raw else None
            evidence.append(CompletedBarEvidence(symbol,asset_id,IntradayBar(start,o,h,l,c,volume),start+timedelta(minutes=15),inputs))
        completed=start+timedelta(minutes=15)
        prior_vix, prior_vix_at = _vix_observation_for(start, vix, days)
        runtime.process_boundary(CompletedBoundary(
            _fingerprint({"kind":"COMPLETED_15M","time":completed.isoformat()}),
            completed, tuple(evidence), prior_vix, prior_vix_at,
        ),dividends)
        boundaries_since_checkpoint += 1
        boundaries_since_checkpoint = _checkpoint_replay_state(
            run_dir, run_id, config, runtime, boundaries_since_checkpoint,
            checkpoint_interval_boundaries, evidence_archive,
        )
    _checkpoint_final_replay_state(
        run_dir, run_id, config, runtime, boundaries_since_checkpoint,
        evidence_archive,
    )
    state = runtime.persistence_state(); positions=state["portfolio"]["positions"]
    archived_evidence = evidence_archive.report_evidence(state)
    valuation = runtime.account_valuation()
    swing_value = valuation["swing_market_value"]
    income_value = valuation["income_sleeve_market_value"]
    ending = valuation["current_marked_equity"]
    closed = state["portfolio"]["closed_trades"]
    gross_profit = sum(float(item["pnl"]) for item in closed if float(item["pnl"]) > 0)
    gross_loss = -sum(float(item["pnl"]) for item in closed if float(item["pnl"]) < 0)
    report={"schema_version":RUN_SCHEMA,"semantic_version":SEMANTIC,"run_id":run_id,"status":"COMPLETE",**identity,
        "asset_identity":"provider_asset_id","symbol_role":"NON_UNIQUE_LABEL","starting_equity":config.payload["starting_account"]["starting_cash"],
        "ending_equity":ending,"net_profit_loss":ending-state["portfolio"]["total_contributions"],"maximum_drawdown":state["maximum_drawdown"],
        **_account_report_fields(valuation),
        "completed_15m_boundaries":state["boundaries"],"candidate_v1_evaluations":state["candidate_evaluations"],"signals":state["signals"],"fills":state["fills"],
        "capacity_arbitration":config.payload["capacity_arbitration"],"capacity_decisions":archived_evidence["capacity_decisions"],"capacity_deferred":state["capacity_deferred"],
        "experiment_risk": config.payload.get("experiment_risk"),
        "closed_trades":len(closed),
        "wins":sum(1 for item in closed if float(item["pnl"]) > 0),
        "losses":sum(1 for item in closed if float(item["pnl"]) < 0),
        "win_rate":(sum(1 for item in closed if float(item["pnl"]) > 0) / len(closed) if closed else 0.0),
        "profit_factor":(gross_profit / gross_loss if gross_loss else None),
        "ending_cash":state["portfolio"]["cash"],
        "ending_tax_reserve":state["portfolio"]["tax_reserve_cash"],
        "ending_positions":{asset_id:{**value,"symbol_label":asset_symbols[asset_id]} for asset_id,value in positions.items()},
        "outcome_reconciliation":state["outcome_reconciliation"],
        "selection_bias_label":universe.get("selection_bias_label"),
        "frozen_selection_fingerprint":universe.get("frozen_selection_fingerprint"),
        "derived_asset_id_universe_fingerprint":universe.get("derived_asset_id_universe_fingerprint"),
        "corporate_action_ratio_artifact_fingerprint":universe.get("corporate_action_ratio_artifact_fingerprint"),
        "derived_identity_resolution_fingerprint":universe.get("derived_identity_resolution_fingerprint"),
        "split_accounting_semantic_version":universe.get("split_accounting_semantic_version"),
        "applied_split_count":len(state.get("applied_splits", ())),
        "applied_splits":state.get("applied_splits", []),
        "authority":config.payload["authority"],"completed_at_utc":datetime.now(timezone.utc).isoformat()}
    if state.get("accelerators") is not None:
        accelerator_state = state["accelerators"]
        profit = accelerator_state["profit_recycling"]
        archived_profit = archived_evidence["profit_recycling"]
        ledger = profit["ledger"]
        dynamic = accelerator_state["dynamic_sizing"]
        archived_dynamic = archived_evidence["dynamic_sizing"]
        pyramid = accelerator_state["pyramiding"]
        archived_pyramid = archived_evidence["pyramiding"]
        regime = accelerator_state["regime_allocation"]
        archived_regime = archived_evidence["regime_allocation"]
        report["accelerators"] = {
            "configuration": config.payload["accelerators"],
            "configuration_fingerprints": accelerator_state["configuration_fingerprints"],
            "profit_recycling": {
                "decision_count": archived_profit["decision_count"],
                "decision_ids": archived_profit["decision_ids"],
                "dollars_made_available": archived_profit["dollars_made_available"],
                "dollars_deployed": ledger["already_recycled_amount"],
                "unused_recycled_dollars": ledger["recycled_profit_balance"],
                "released_at_sleeve_rebalance": ledger["released_at_sleeve_rebalance"],
                "ledger": ledger,
            },
            "dynamic_sizing": {
                "decision_count": archived_dynamic["decision_count"],
                "opportunity_count": dynamic["opportunities"],
                "increases": 0, "reductions": dynamic["reductions"],
                "unchanged": dynamic["unchanged"], "blocked": dynamic["blocked"],
                "decision_ids": archived_dynamic["decision_ids"],
                "multiplier_counts": archived_dynamic["multiplier_counts"],
            },
            "pyramiding": {
                "decision_count": archived_pyramid["decision_count"],
                "opportunity_count": pyramid["opportunities"],
                "addition_count": pyramid["additions"],
                "shares_added": pyramid["shares_added"],
                "notional_added": pyramid["notional_added"],
                "affected_provider_asset_ids": archived_pyramid["affected_provider_asset_ids"],
                "accepted_additions": archived_pyramid["accepted_additions"],
            },
            "regime_allocation": {
                "decision_count": archived_regime["decision_count"],
                "opportunity_count": regime["opportunities"],
                "transition_count": regime["transitions"],
                "decisions": archived_regime["decisions"],
            },
            "observed": accelerator_state["observed"],
        }
    report["experiment_report_fingerprint"] = _fingerprint(report)
    _write_evidence(run_dir / "final_report.json",report)
    _write_evidence(run_dir / "exit_status.json", {"run_id":run_id,"status":"COMPLETE","exit_code":0})
    run_manifest=json.loads(read_checksummed_state(run_dir/"run_manifest.json",run_dir/"run_manifest.json.sha256",label="V3 run manifest"))
    run_manifest.update({"status":"COMPLETE","completed_at_utc":report["completed_at_utc"],"final_report_fingerprint":_fingerprint(report)})
    _write_evidence(run_dir/"run_manifest.json",run_manifest)
    evidence_archive.write_progress_report(runtime, status="COMPLETE")
    return run_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--config",type=Path,default=DEFAULT_CONFIG); parser.add_argument("--dataset",type=Path,default=DEFAULT_DATASET); parser.add_argument("--strategy-profile",type=Path,default=DEFAULT_PROFILE)
    parser.add_argument(
        "--checkpoint-interval-boundaries", type=int,
        default=DEFAULT_CHECKPOINT_INTERVAL_BOUNDARIES,
    )
    args=parser.parse_args(argv); print(run(args.config.resolve(),args.dataset.resolve(),args.strategy_profile.resolve(),args.checkpoint_interval_boundaries)); return 0


if __name__ == "__main__": raise SystemExit(main())
