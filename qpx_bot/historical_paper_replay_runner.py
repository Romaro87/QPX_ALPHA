"""Durable causal replay of the current Candidate V1 paper policy.

The archive driver owns complete historical collections.  The paper runtime is
given one detached completed-bar boundary at a time and has no archive handle.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import csv
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable, Iterator, Mapping, Sequence

from qpx_bot.actual_two_year_15m_six import _read_vix_daily_cache
from qpx_bot.allocation import rebalance_income_allocation
from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.candidate_v1_config import CandidateV1ConfigSnapshot, disabled_kelly_trade_history, load_candidate_v1_config
from qpx_bot.causal_dividends import CausalDividendEvent, IncompleteDividendMetadata
from qpx_bot.accelerators.capacity_arbitration import (
    CapacityArbitrationConfig, CapacityArbitrationContext, CapacityArbitrationV1,
    CapacityCandidate, tie_identity,
)
from qpx_bot.data_loader import Candle
from qpx_bot.historical_paper_replay import (
    CandidateV1ReplayPort,
    ReplayConfigurationError,
    ReplayExperimentConfiguration,
    canonical_replay_configuration,
    load_replay_configuration,
)
from qpx_bot.indicators import calculate_indicators
from qpx_bot.intraday_six_paper import IntradayBar, choose_without_ranking, load_policy
from qpx_bot.ml_historical_calendar_repair import AUDITED_FALSE_OPEN_DATES
from qpx_bot.ml_experimental_causal_baseline import build_input_snapshot
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state
from qpx_bot.portfolio import ClosedTrade, Portfolio, Position, contribution_allocation
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_exit


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "qpx_bot/replay_configs/candidate_v1_ten_year_sip_primary_v1.json"
DEFAULT_DATASET = ROOT / "research_data/qpx_ml_historical_v1"
DEFAULT_VIX = DEFAULT_DATASET / "historical_paper_replay_inputs/CBOE_VIX_DAILY.csv"
DEFAULT_CANDIDATE_POLICY = ROOT / "qpx_bot/candidate_v1_policy.json"
DEFAULT_SYMBOLS = ROOT / "qpx_bot/symbols.json"
RUN_SCHEMA = 1
RUN_SEMANTIC = "QPX_CANDIDATE_V1_CAUSAL_HISTORICAL_PAPER_REPLAY_V1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_replay_configuration(value)).hexdigest()


def _write_evidence(path: Path, payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    write_checksummed_state(path, path.with_suffix(path.suffix + ".sha256"), encoded)
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CompletedBarEvidence:
    symbol: str
    provider_asset_id: str
    bar: IntradayBar
    completed_at: datetime
    candidate_inputs: CandidateV1CausalInputs | None


@dataclass(frozen=True, slots=True)
class CompletedBoundary:
    boundary_id: str
    completed_at: datetime
    bars: tuple[CompletedBarEvidence, ...]
    previous_session_vix: float | None


class ReservoirArchiveDriver:
    """Archive-owning source; yielded boundaries are detached immutable facts."""

    __slots__ = ("_boundaries", "source_evidence")

    def __init__(self, boundaries: Sequence[CompletedBoundary], source_evidence: Mapping[str, Any]):
        self._boundaries = tuple(boundaries)
        self.source_evidence = json.loads(json.dumps(source_evidence))

    def boundaries_after(self, completed_at: datetime | None) -> Iterator[CompletedBoundary]:
        for boundary in self._boundaries:
            if completed_at is None or boundary.completed_at > completed_at:
                yield boundary

    @classmethod
    def from_reservoir(
        cls,
        *,
        dataset: Path,
        symbols: Sequence[str],
        income_symbol: str,
        vix_path: Path,
        config: ReplayExperimentConfiguration,
        candidate_snapshot: CandidateV1ConfigSnapshot,
    ) -> "ReservoirArchiveDriver":
        configured_dataset = (ROOT / str(config.payload["dataset"]["root_identity"])).resolve()
        if dataset.resolve() != configured_dataset:
            raise ReplayConfigurationError("Opened historical reservoir root differs from config.")
        state_path = dataset / "acquisition_state/state.json"
        state = json.loads(read_checksummed_state(
            state_path,
            state_path.with_suffix(".sha256"),
            label="Historical acquisition state",
        ))
        if state.get("status") != "COMPLETE" or state.get("stage") != "COMPLETE":
            raise ReplayConfigurationError("Historical reservoir acquisition is not complete.")
        if state.get("provider") != "alpaca" or state.get("feed") != "sip":
            raise ReplayConfigurationError("Historical reservoir provider/feed differs from config.")
        if state.get("canonical_resolution") != "15Min" or state.get("adjustment") != "raw":
            raise ReplayConfigurationError("Historical reservoir bar contract differs from config.")
        if config.payload["market_data"]["adjustment_mode"] != "CAUSAL_SPLIT_ADJUSTED":
            raise ReplayConfigurationError("This driver requires causal split-adjusted mode.")
        input_snapshot = build_input_snapshot(dataset)
        if input_snapshot["input_snapshot_fingerprint"] != config.payload["dataset"]["snapshot_fingerprint"]:
            raise ReplayConfigurationError("Historical reservoir snapshot fingerprint differs from config.")

        enrichment = dataset / str(state["corporate_action_identity_enrichment_path"])
        snapshot_path = enrichment.parent.parent / "asset-snapshot-active.json"
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        wanted = {str(symbol).upper() for symbol in (*symbols, income_symbol)}
        asset_ids = {
            str(record.get("symbol", "")).upper(): str(record["provider_asset_id"])
            for record in snapshot["records"]
            if str(record.get("symbol", "")).upper() in wanted
        }
        if set(asset_ids) != wanted:
            raise ReplayConfigurationError(
                f"Provider asset identity is incomplete: missing={sorted(wanted - set(asset_ids))}."
            )

        partitions: dict[tuple[int, str], int] = {}
        for item in state["partitions"]:
            for symbol, provider_id in asset_ids.items():
                if provider_id in item["asset_ids"]:
                    partitions[(int(item["year"]), symbol)] = int(item["batch"])

        rows: dict[str, dict[datetime, IntradayBar]] = {symbol: {} for symbol in wanted}
        used_files: list[dict[str, Any]] = []
        for (year, symbol), batch in sorted(partitions.items()):
            provider_id = asset_ids[symbol]
            base = dataset / f"bars_15m/year={year}/batch={batch:05d}.csv.gz"
            manifest = base.with_suffix(base.suffix + ".manifest.json")
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            if _sha256(base) != manifest_payload.get("sha256"):
                raise ReplayConfigurationError(f"Bar partition checksum mismatch: {base}")
            cls._read_rows(base, provider_id, symbol, rows[symbol], replace=False)
            used_files.append({"path": str(base.relative_to(dataset)), "sha256": _sha256(base)})

            repair_dir = dataset / f"calendar_repairs/year={year}/batch={batch:05d}"
            for repair in sorted(repair_dir.glob("*.csv.gz")):
                repair_manifest = repair.with_suffix("").with_suffix(".manifest.json")
                repair_payload = json.loads(repair_manifest.read_text(encoding="utf-8"))
                if _sha256(repair) != repair_payload.get("accepted_patch_sha256"):
                    raise ReplayConfigurationError(f"Calendar-repair checksum mismatch: {repair}")
                cls._read_rows(repair, provider_id, symbol, rows[symbol], replace=False)
                used_files.append({"path": str(repair.relative_to(dataset)), "sha256": _sha256(repair)})

        for symbol in rows:
            for timestamp in tuple(rows[symbol]):
                if timestamp.date() in AUDITED_FALSE_OPEN_DATES:
                    del rows[symbol][timestamp]
            if symbol in symbols and not rows[symbol]:
                raise ReplayConfigurationError(f"No historical bars exist for Candidate symbol {symbol}.")

        split_count = cls._applicable_split_count(dataset, set(asset_ids.values()))
        if split_count:
            raise ReplayConfigurationError(
                "Causal split adjustment is not implemented for a selected asset with a split event."
            )

        vix = _read_vix_daily_cache(vix_path)
        if _sha256(vix_path) != config.payload["volatility"]["evidence_fingerprint"]:
            raise ReplayConfigurationError("Cboe VIX evidence fingerprint mismatch.")

        histories = {symbol: [row for _, row in sorted(values.items())] for symbol, values in rows.items()}
        candidate_values: dict[tuple[str, datetime], CandidateV1CausalInputs | None] = {}
        bot_config = candidate_snapshot.bot_config
        for symbol in symbols:
            bars = histories[symbol]
            candles = [
                Candle(date=bar.start.date(), open=bar.open, high=bar.high, low=bar.low,
                       close=bar.close, volume=bar.volume)
                for bar in bars
            ]
            indicators = calculate_indicators(candles, bot_config)
            for index, bar in enumerate(bars):
                prior_index = index - 1
                slope_index = index - bot_config.sma_slope_lookback
                if prior_index < 0 or slope_index < 0 or index < bot_config.breakout_lookback:
                    candidate_values[(symbol, bar.start)] = None
                    continue
                needed = (
                    indicators.ema_fast[index], indicators.ema_slow[index],
                    indicators.rsi[index], indicators.rmi[index], indicators.atr[index],
                    indicators.sma_trend[index], indicators.average_volume[prior_index],
                )
                if (
                    any(value is None for value in needed)
                    or indicators.ema_fast[prior_index] is None
                    or indicators.ema_slow[prior_index] is None
                    or indicators.rsi[prior_index] is None
                    or indicators.rmi[prior_index] is None
                    or indicators.sma_trend[slope_index] is None
                ):
                    candidate_values[(symbol, bar.start)] = None
                    continue
                candidate_values[(symbol, bar.start)] = CandidateV1CausalInputs(
                    index=index,
                    current_close=bar.close,
                    current_volume=bar.volume,
                    current_fast=float(indicators.ema_fast[index]),
                    previous_fast=float(indicators.ema_fast[prior_index]),
                    current_slow=float(indicators.ema_slow[index]),
                    previous_slow=float(indicators.ema_slow[prior_index]),
                    current_rsi=float(indicators.rsi[index]),
                    previous_rsi=float(indicators.rsi[prior_index]),
                    current_rmi=float(indicators.rmi[index]),
                    previous_rmi=float(indicators.rmi[prior_index]),
                    current_sma=float(indicators.sma_trend[index]),
                    slope_sma=float(indicators.sma_trend[slope_index]),
                    baseline_volume=float(indicators.average_volume[prior_index]),
                    current_atr=float(indicators.atr[index]),
                    prior_high=max(candle.high for candle in candles[index-bot_config.breakout_lookback:index]),
                    vix=0.0,
                )

        by_start: dict[datetime, list[CompletedBarEvidence]] = {}
        for symbol, bars in histories.items():
            for bar in bars:
                completed = bar.start + timedelta(minutes=15)
                inputs = candidate_values.get((symbol, bar.start))
                by_start.setdefault(bar.start, []).append(
                    CompletedBarEvidence(symbol, asset_ids[symbol], bar, completed, inputs)
                )
        boundaries: list[CompletedBoundary] = []
        ordered_vix_days = sorted(vix)
        for start in sorted(by_start):
            bars = tuple(sorted(by_start[start], key=lambda item: item.symbol))
            completed = start + timedelta(minutes=15)
            prior_index = bisect_left(ordered_vix_days, start.date()) - 1
            prior_day = ordered_vix_days[prior_index] if prior_index >= 0 else None
            prior_vix = (
                vix[prior_day]
                if prior_day is not None and (start.date() - prior_day).days <= 7
                else None
            )
            boundaries.append(CompletedBoundary(
                boundary_id=_fingerprint({"kind": "COMPLETED_15M", "time": completed.isoformat()}),
                completed_at=completed,
                bars=bars,
                previous_session_vix=prior_vix,
            ))
        evidence = {
            "dataset_root": str(dataset.resolve()),
            "dataset_plan_sha256": _sha256(dataset / "manifests/dataset_plan.json"),
            "acquisition_state_sha256": _sha256(state_path),
            "calendar_repair_aggregate_fingerprint": "81e3db3203ecdab2ff9ed347d4419ac1013952b32d881960f7122f9ba7e5f822",
            "corporate_action_artifact_fingerprint": state["corporate_action_artifact_fingerprint"],
            "corporate_action_identity_resolution_fingerprint": state["corporate_action_identity_resolution_fingerprint"],
            "used_source_files_fingerprint": _fingerprint(used_files),
            "used_source_file_count": len(used_files),
            "input_snapshot_fingerprint": input_snapshot["input_snapshot_fingerprint"],
            "partition_inventory_fingerprint": input_snapshot["partition_inventory_fingerprint"],
            "reservoir_partitions": input_snapshot["partitions_total"],
            "reservoir_rows": input_snapshot["rows_15m"],
            "asset_ids": asset_ids,
            "applicable_split_events": split_count,
            "bar_rows": {symbol: len(values) for symbol, values in histories.items()},
            "first_bar_start": min(by_start).isoformat(),
            "last_bar_start": max(by_start).isoformat(),
        }
        return cls(boundaries, evidence)

    @staticmethod
    def _read_rows(
        path: Path, provider_id: str, expected_symbol: str,
        output: dict[datetime, IntradayBar], *, replace: bool,
    ) -> None:
        with gzip.open(path, "rt", newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                if row.get("provider_asset_id") != provider_id:
                    continue
                if str(row.get("observation_symbol", "")).upper() != expected_symbol:
                    raise ReplayConfigurationError("Provider asset/symbol evidence is contradictory.")
                timestamp = datetime.fromisoformat(str(row["market_timestamp"]))
                bar = IntradayBar(
                    start=timestamp, open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]), volume=int(row["volume"]),
                )
                if timestamp in output and output[timestamp] != bar and not replace:
                    raise ReplayConfigurationError("Conflicting duplicate historical bar evidence.")
                output[timestamp] = bar

    @staticmethod
    def _applicable_split_count(dataset: Path, provider_ids: set[str]) -> int:
        state = json.loads((dataset / "acquisition_state/state.json").read_text(encoding="utf-8"))
        resolution = json.loads((dataset / str(state["corporate_action_identity_resolution_path"])).read_text(encoding="utf-8"))
        event_to_asset = {
            str(record["provider_event_id"]): str(record["provider_asset_id"])
            for record in resolution["records"]
            if record.get("outcome") == "RESOLVED_PROVIDER_IDENTITY"
        }
        count = 0
        with gzip.open(dataset / str(state["corporate_action_artifact_path"]), "rt", encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if (
                    record.get("action_type") in {"stock_split", "reverse_split"}
                    and event_to_asset.get(str(record.get("provider_event_id"))) in provider_ids
                ):
                    count += 1
        return count


@dataclass(frozen=True, slots=True)
class PendingEntry:
    signal_id: str
    provider_asset_id: str
    symbol_label: str
    signal_completed_at: str
    signal_atr: float
    prior_close: float
    tie_key: str


def _position_to_dict(position: Position) -> dict[str, Any]:
    payload = asdict(position)
    payload["entry_date"] = position.entry_date.isoformat()
    return payload


def _trade_to_dict(trade: ClosedTrade) -> dict[str, Any]:
    payload = asdict(trade)
    payload["entry_date"] = trade.entry_date.isoformat()
    payload["exit_date"] = trade.exit_date.isoformat()
    return payload


def _position_from_dict(value: Mapping[str, Any]) -> Position:
    payload = dict(value)
    payload["entry_date"] = date.fromisoformat(str(payload["entry_date"]))
    return Position(**payload)


def _trade_from_dict(value: Mapping[str, Any]) -> ClosedTrade:
    payload = dict(value)
    payload["entry_date"] = date.fromisoformat(str(payload["entry_date"]))
    payload["exit_date"] = date.fromisoformat(str(payload["exit_date"]))
    return ClosedTrade(**payload)


class CandidateV1HistoricalPaperRuntime:
    """Current Candidate V1 paper/account logic with no archive capability."""

    __slots__ = (
        "config", "candidate", "policy", "state", "_portfolio", "_arbitration",
        "asset_symbols", "candidate_asset_ids", "income_asset_id", "rank_by_asset",
    )

    def __init__(
        self, config: ReplayExperimentConfiguration, state: Mapping[str, Any] | None = None,
        *, candidate_snapshot: CandidateV1ConfigSnapshot | None = None,
        asset_symbols: Mapping[str, str] | None = None,
    ):
        self.config = config
        snapshot = candidate_snapshot or load_candidate_v1_config()
        if snapshot.fingerprint != config.payload["strategy"]["configuration_fingerprint"]:
            raise ReplayConfigurationError("Candidate V1 configuration fingerprint mismatch.")
        self.candidate = CandidateV1ReplayPort(snapshot)
        arbitration_config = CapacityArbitrationConfig(
            str(config.payload["capacity_arbitration"]["policy"]),
            str(config.payload["capacity_arbitration"]["policy_version"]),
        )
        if arbitration_config.fingerprint != config.payload["capacity_arbitration"]["configuration_fingerprint"]:
            raise ReplayConfigurationError("Capacity arbitration configuration fingerprint mismatch.")
        self._arbitration = CapacityArbitrationV1(arbitration_config)
        self.policy = load_policy(DEFAULT_CANDIDATE_POLICY)
        if self.policy.interval != "15m" or self.policy.rankings_enabled:
            raise ReplayConfigurationError("Candidate V1 current 15-minute unranked policy is not active.")
        if self.policy.signal_evaluation != "all_candidates_each_completed_15m_bar":
            raise ReplayConfigurationError("Candidate V1 decision cadence differs from replay config.")
        if asset_symbols is None:
            asset_symbols = {symbol: symbol for symbol in (*self.policy.candidates, self.policy.income_symbol)}
        self.asset_symbols = {str(asset_id): str(symbol).upper() for asset_id, symbol in asset_symbols.items()}
        if len(self.asset_symbols) != len(asset_symbols):
            raise ReplayConfigurationError("Provider asset identities must be unique.")
        income_matches = [asset_id for asset_id, symbol in self.asset_symbols.items() if symbol == self.policy.income_symbol]
        if len(income_matches) != 1:
            raise ReplayConfigurationError("Replay universe must contain exactly one income asset identity.")
        self.income_asset_id = income_matches[0]
        self.candidate_asset_ids = tuple(asset_id for asset_id in self.asset_symbols if asset_id != self.income_asset_id)
        self.rank_by_asset = {asset_id: rank for rank, asset_id in enumerate(self.candidate_asset_ids, 1)}
        if state is None:
            starting = float(config.payload["starting_account"]["starting_cash"])
            self._portfolio = Portfolio(starting, preserve_identity=True)
            self.state = {
                "identity_key": "provider_asset_id",
                "universe_manifest_fingerprint": config.payload["universe"]["manifest_fingerprint"],
                "asset_symbols": self.asset_symbols,
                "last_completed_boundary": None, "boundaries": 0, "candidate_evaluations": 0,
                "pending": {}, "income_shares": 0.0, "income_cost": 0.0,
                "income_dividends": 0.0, "dividend_entitlements": {},
                "settled_dividends": [], "last_rebalance_week": None,
                "last_marks": {}, "peak_equity": starting, "maximum_drawdown": 0.0,
                "annual": {}, "signals": 0, "fills": 0, "gap_rejections": 0,
                "risk_rejections": 0, "capacity_deferred": 0, "capacity_decisions": [],
                "capacity_rejections": 0, "entry_outcomes": {},
                "outcome_reconciliation": {},
            }
        else:
            self.state = json.loads(json.dumps(state))
            if (
                self.state.get("identity_key") != "provider_asset_id"
                or self.state.get("universe_manifest_fingerprint") != config.payload["universe"]["manifest_fingerprint"]
                or self.state.get("asset_symbols") != self.asset_symbols
            ):
                raise ReplayConfigurationError("Replay checkpoint provider-asset identity differs from the selected universe.")
            p = self.state.pop("portfolio")
            self._portfolio = Portfolio(float(p["starting_cash"]), preserve_identity=True)
            self._portfolio.cash = float(p["cash"])
            self._portfolio.tax_reserve_cash = float(p["tax_reserve_cash"])
            self._portfolio.total_contributions = float(p["total_contributions"])
            self._portfolio.realized_pnl = float(p["realized_pnl"])
            self._portfolio.positions = {k: _position_from_dict(v) for k, v in p["positions"].items()}
            self._portfolio.closed_trades = [_trade_from_dict(v) for v in p["closed_trades"]]
            if any(key != position.symbol for key, position in self._portfolio.positions.items()):
                raise ReplayConfigurationError("Checkpoint position identity differs from its provider-asset key.")

    def snapshot(self) -> dict[str, Any]:
        return {
            **json.loads(json.dumps(self.state)),
            "portfolio": {
                "starting_cash": self._portfolio.starting_cash,
                "cash": self._portfolio.cash,
                "tax_reserve_cash": self._portfolio.tax_reserve_cash,
                "total_contributions": self._portfolio.total_contributions,
                "realized_pnl": self._portfolio.realized_pnl,
                "positions": {k: _position_to_dict(v) for k, v in self._portfolio.positions.items()},
                "closed_trades": [_trade_to_dict(v) for v in self._portfolio.closed_trades],
            },
        }

    def process_boundary(self, boundary: CompletedBoundary, dividends: Mapping[date, Sequence[Mapping[str, Any]]]) -> None:
        last = self.state["last_completed_boundary"]
        if last is not None and boundary.completed_at <= datetime.fromisoformat(last):
            raise ReplayConfigurationError("Replay boundary is duplicate or out of order.")
        bars = {item.provider_asset_id: item for item in boundary.bars}
        if len(bars) != len(boundary.bars):
            raise ReplayConfigurationError("A boundary contains duplicate provider asset identity.")
        starts = {item.bar.start for item in boundary.bars}
        if len(starts) > 1:
            raise ReplayConfigurationError("A completed boundary contains different bar starts.")
        start = next(iter(starts)) if starts else boundary.completed_at - timedelta(minutes=15)
        candidate_assets = self.candidate_asset_ids
        current_candidates = {asset_id: bars[asset_id] for asset_id in candidate_assets if asset_id in bars}

        # OPEN phase: entitlements and settlements are effective before account
        # allocation; exits available at the open release cash before rebalance.
        self._apply_dividends_open(start.date(), dividends)
        for asset_id, position in tuple(self._portfolio.positions.items()):
            evidence = current_candidates.get(asset_id)
            if evidence is None or evidence.candidate_inputs is None:
                continue
            open_only = Candle(
                date=start.date(), open=evidence.bar.open, high=evidence.bar.open,
                low=evidence.bar.open, close=evidence.bar.open, volume=0,
            )
            outcome = evaluate_exit(
                position=position, candle=open_only,
                current_atr=evidence.candidate_inputs.current_atr,
                config=self.candidate._snapshot.bot_config,
            )
            if outcome.should_exit:
                self._portfolio.close_position(
                    symbol=asset_id, exit_price=float(outcome.exit_price), exit_date=start.date(),
                    reason=outcome.reason or "OPEN_EXIT", config=self.candidate._snapshot.bot_config,
                )

        self._rebalance_income_open(start, bars)

        pending_items = sorted(
            (PendingEntry(**value) for value in self.state["pending"].values()),
            key=lambda item: (item.tie_key, item.provider_asset_id),
        )
        self.state["pending"] = {}
        for signal in pending_items:
            evidence = current_candidates.get(signal.provider_asset_id)
            if evidence is None or start < datetime.fromisoformat(signal.signal_completed_at):
                self.state["pending"][signal.provider_asset_id] = asdict(signal)
                continue
            if len(self._portfolio.positions) >= self.policy.maximum_concurrent_positions:
                self.state["capacity_rejections"] += 1
                self._finish_entry(signal.signal_id, "REJECTED", "MAXIMUM_CONCURRENT_POSITIONS")
                continue
            gap = abs(evidence.bar.open - signal.prior_close) / signal.signal_atr
            if gap > self.policy.maximum_gap_atr_multiple:
                self.state["gap_rejections"] += 1
                self._finish_entry(signal.signal_id, "REJECTED", "MAXIMUM_GAP_ATR_MULTIPLE")
                continue
            marks = {symbol: float(self.state["last_marks"].get(symbol, position.entry_price))
                     for symbol, position in self._portfolio.positions.items()}
            income_price = float(self.state["last_marks"].get(self.income_asset_id, 0.0))
            equity = self._portfolio.equity(marks) + self.state["income_shares"] * income_price
            sizing = calculate_position_size(
                account_equity=equity, available_cash=self._portfolio.cash,
                entry_price=evidence.bar.open, atr=signal.signal_atr,
                active_risk=self._portfolio.active_risk(), config=self.candidate._snapshot.bot_config,
                trade_results_r=disabled_kelly_trade_history(self.candidate._snapshot),
            )
            maximum_notional = equity * self.candidate._snapshot.maximum_position_notional_fraction
            if sizing.is_tradeable and sizing.entry_fill * sizing.shares > maximum_notional:
                from dataclasses import replace
                shares = int(maximum_notional // sizing.entry_fill)
                sizing = replace(sizing, shares=shares, planned_risk=sizing.risk_per_share * shares,
                                 blocked_reason=None if shares > 0 else "Position notional cap blocked the trade.")
            if not sizing.is_tradeable:
                self.state["risk_rejections"] += 1
                self._finish_entry(
                    signal.signal_id, "REJECTED",
                    sizing.blocked_reason or "UNSPECIFIED_SIZING_REJECTION",
                )
                continue
            self._portfolio.open_position(
                symbol=signal.provider_asset_id, sizing=sizing, entry_date=start.date(),
                entry_atr=signal.signal_atr, config=self.candidate._snapshot.bot_config,
            )
            self.state["fills"] += 1
            self._finish_entry(signal.signal_id, "FILLED", None)

        # CLOSE phase: the now-completed bar may update trailing state or close
        # positions, and only then may it authorize a later entry.
        for asset_id, position in tuple(self._portfolio.positions.items()):
            evidence = current_candidates.get(asset_id)
            if evidence is None or evidence.candidate_inputs is None:
                continue
            outcome = evaluate_exit(
                position=position,
                candle=Candle(date=start.date(), open=evidence.bar.open, high=evidence.bar.high,
                              low=evidence.bar.low, close=evidence.bar.close, volume=evidence.bar.volume),
                current_atr=evidence.candidate_inputs.current_atr,
                config=self.candidate._snapshot.bot_config,
            )
            if outcome.should_exit:
                self._portfolio.close_position(
                    symbol=asset_id, exit_price=float(outcome.exit_price), exit_date=start.date(),
                    reason=outcome.reason or "EXIT", config=self.candidate._snapshot.bot_config,
                )
            else:
                position.stop_price = outcome.next_stop_price
                position.highest_price = outcome.highest_price

        qualifying: list[tuple[str, CandidateV1CausalInputs]] = []
        if boundary.previous_session_vix is not None:
            for asset_id, evidence in sorted(
                current_candidates.items(), key=lambda item: self.rank_by_asset[item[0]],
            ):
                if evidence.candidate_inputs is None:
                    continue
                raw = evidence.candidate_inputs
                inputs = CandidateV1CausalInputs(**{**asdict(raw), "vix": boundary.previous_session_vix})
                result = self.candidate.evaluate(inputs)
                self.state["candidate_evaluations"] += 1
                if result.should_enter and asset_id not in self._portfolio.positions and asset_id not in self.state["pending"]:
                    qualifying.append((asset_id, raw))
        slots = max(0, self.policy.maximum_concurrent_positions - len(self._portfolio.positions) - len(self.state["pending"]))
        candidates = tuple(
            CapacityCandidate(
                symbol=asset_id, current_close=inputs.current_close, prior_high=inputs.prior_high,
                current_atr=inputs.current_atr, current_fast=inputs.current_fast,
                current_slow=inputs.current_slow, current_volume=inputs.current_volume,
                baseline_volume=inputs.baseline_volume,
                frozen_top100_rank=self.rank_by_asset[asset_id],
                tie_break_identity=tie_identity(start, asset_id),
            )
            for asset_id, inputs in qualifying
        )
        decision = self._arbitration.decide(CapacityArbitrationContext(start, slots, candidates))
        self.state["capacity_deferred"] += len(decision.deferred_candidates)
        if candidates:
            self.state.setdefault("capacity_decisions", []).append({
                "decision_id": decision.decision_id, "policy": decision.policy,
                "policy_version": decision.policy_version,
                "configuration_fingerprint": decision.configuration_fingerprint,
                "available_slots": decision.available_slots,
                "qualifying_asset_ids": decision.qualifying_symbols,
                "selected_asset_ids": decision.selected_candidates,
                "deferred_asset_ids": decision.deferred_candidates,
                "scores": [score.as_dict() for score in decision.scores],
            })
        for asset_id in decision.selected_candidates:
            evidence = current_candidates[asset_id]
            inputs = evidence.candidate_inputs
            assert inputs is not None
            tie = hashlib.sha256((start.isoformat() + "|" + asset_id).encode()).hexdigest()
            signal_id = hashlib.sha256(("entry|" + start.isoformat() + "|" + asset_id).encode()).hexdigest()
            self.state["pending"][asset_id] = asdict(PendingEntry(
                signal_id=signal_id,
                provider_asset_id=asset_id, symbol_label=self.asset_symbols[asset_id],
                signal_completed_at=boundary.completed_at.isoformat(),
                signal_atr=inputs.current_atr, prior_close=evidence.bar.close, tie_key=tie,
            ))
            self.state["entry_outcomes"][signal_id] = {
                "provider_asset_id": asset_id, "symbol_label": self.asset_symbols[asset_id],
                "decision_completed_at": boundary.completed_at.isoformat(),
                "status": "PENDING", "reason": None,
            }
            self.state["signals"] += 1

        for asset_id, evidence in bars.items():
            self.state["last_marks"][asset_id] = evidence.bar.close
        self._reconcile_outcomes()
        marks = {symbol: float(self.state["last_marks"].get(symbol, position.entry_price))
                 for symbol, position in self._portfolio.positions.items()}
        income_price = float(self.state["last_marks"].get(self.income_asset_id, 0.0))
        equity = self._portfolio.equity(marks) + self.state["income_shares"] * income_price
        self.state["peak_equity"] = max(float(self.state["peak_equity"]), equity)
        if self.state["peak_equity"] > 0:
            self.state["maximum_drawdown"] = max(
                float(self.state["maximum_drawdown"]),
                (self.state["peak_equity"] - equity) / self.state["peak_equity"],
            )
        year = str(start.year)
        self.state["annual"][year] = {"ending_equity": equity, "last_boundary": boundary.completed_at.isoformat()}
        self.state["boundaries"] += 1
        self.state["last_completed_boundary"] = boundary.completed_at.isoformat()

    def _finish_entry(self, signal_id: str, status: str, reason: str | None) -> None:
        outcome = self.state["entry_outcomes"].get(signal_id)
        if outcome is None or outcome.get("status") != "PENDING":
            raise ReplayConfigurationError("Pending-entry outcome identity is missing or already terminal.")
        outcome["status"] = status
        outcome["reason"] = reason

    def _reconcile_outcomes(self) -> None:
        qualifying = sum(len(item["qualifying_asset_ids"]) for item in self.state["capacity_decisions"])
        selected = sum(len(item["selected_asset_ids"]) for item in self.state["capacity_decisions"])
        deferred = sum(len(item["deferred_asset_ids"]) for item in self.state["capacity_decisions"])
        statuses: dict[str, int] = {}
        reasons: dict[str, int] = {}
        for item in self.state["entry_outcomes"].values():
            status = str(item["status"])
            statuses[status] = statuses.get(status, 0) + 1
            if status == "REJECTED":
                reason = str(item.get("reason") or "UNSPECIFIED")
                reasons[reason] = reasons.get(reason, 0) + 1
        if qualifying != selected + deferred or selected != sum(statuses.values()):
            raise ReplayConfigurationError("Historical replay entry outcomes do not reconcile.")
        if statuses.get("PENDING", 0) != len(self.state["pending"]):
            raise ReplayConfigurationError("Historical replay pending outcomes do not reconcile.")
        self.state["outcome_reconciliation"] = {
            "qualifying": qualifying, "selected": selected, "deferred": deferred,
            "pending": statuses.get("PENDING", 0), "filled": statuses.get("FILLED", 0),
            "rejected": statuses.get("REJECTED", 0),
            "sizing_rejection_reasons": dict(sorted(reasons.items())),
            "reconciled": True,
        }

    def _apply_dividends_open(
        self, current_date: date,
        dividends: Mapping[date, Sequence[Mapping[str, Any]]],
    ) -> None:
        entitlements = self.state["dividend_entitlements"]
        for raw in dividends.get(current_date, ()):
            event_id = str(raw["provider_event_id"])
            if event_id in entitlements:
                continue
            try:
                event = CausalDividendEvent(
                    event_id=event_id,
                    ex_date=date.fromisoformat(str(raw["ex_or_effective_date"])[:10]),
                    cash_amount=float(raw["rate"]),
                    record_date=(date.fromisoformat(str(raw["record_date"])[:10]) if raw.get("record_date") else None),
                    payable_date=(date.fromisoformat(str(raw["payable_date"])[:10]) if raw.get("payable_date") else None),
                    process_date=(date.fromisoformat(str(raw["process_date"])[:10]) if raw.get("process_date") else None),
                )
                available = event.cash_available_date
            except (KeyError, TypeError, ValueError, IncompleteDividendMetadata) as exc:
                raise ReplayConfigurationError(f"Incomplete causal dividend metadata for {event_id}: {exc}") from exc
            entitlements[event_id] = {
                "ex_date": event.ex_date.isoformat(),
                "entitled_shares": self.state["income_shares"],
                "cash_amount_per_share": event.cash_amount,
                "cash_available_date": available.isoformat(),
            }
        settled = set(self.state["settled_dividends"])
        for event_id, entitlement in sorted(entitlements.items()):
            if event_id in settled or date.fromisoformat(entitlement["cash_available_date"]) > current_date:
                continue
            cash = float(entitlement["entitled_shares"]) * float(entitlement["cash_amount_per_share"])
            self._portfolio.cash += cash
            self.state["income_dividends"] += cash
            settled.add(event_id)
        self.state["settled_dividends"] = sorted(settled)

    def _rebalance_income_open(
        self, start: datetime, bars: Mapping[str, CompletedBarEvidence],
    ) -> None:
        income_bar = bars.get(self.income_asset_id)
        if income_bar is None:
            return
        if start.weekday() != self.candidate._snapshot.rebalance_weekday:
            return
        iso = start.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        if week == self.state["last_rebalance_week"]:
            return
        years = max(0, start.year - 2016)
        target, _ = contribution_allocation(years, self.candidate._snapshot.bot_config)
        position_marks = {
            asset_id: (
                bars[asset_id].bar.open if asset_id in bars
                else float(self.state["last_marks"].get(asset_id, position.entry_price))
            )
            for asset_id, position in self._portfolio.positions.items()
        }
        result = rebalance_income_allocation(
            income_shares=self.state["income_shares"], income_cost=self.state["income_cost"],
            swing_cash=self._portfolio.cash, swing_market_value=self._portfolio.market_value(position_marks),
            income_price=income_bar.bar.open, target_income_weight=target,
            slippage_rate=self.candidate._snapshot.bot_config.slippage_rate,
            tax_reserve_rate=self.candidate._snapshot.bot_config.annual_tax_reserve_rate,
            tolerance=self.candidate._snapshot.bot_config.allocation_rebalance_tolerance,
            minimum_trade=self.candidate._snapshot.bot_config.minimum_rebalance_trade,
        )
        self.state["income_shares"] = result.shares_after
        self.state["income_cost"] = result.income_cost_after
        self._portfolio.cash = result.swing_cash_after
        self._portfolio.tax_reserve_cash += result.tax_reserved
        self._portfolio.realized_pnl += result.realized_pnl
        self.state["last_rebalance_week"] = week


def _load_dividends(dataset: Path, income_symbol: str) -> dict[date, list[Mapping[str, Any]]]:
    state = json.loads((dataset / "acquisition_state/state.json").read_text(encoding="utf-8"))
    result: dict[date, list[Mapping[str, Any]]] = {}
    with gzip.open(dataset / str(state["corporate_action_artifact_path"]), "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if record.get("action_type") != "cash_dividend" or record.get("symbol") != income_symbol:
                continue
            if record.get("rate") is None or record.get("ex_or_effective_date") is None:
                continue
            result.setdefault(date.fromisoformat(record["ex_or_effective_date"]), []).append(record)
    return result


def _read_runtime_state(run_dir: Path, config: ReplayExperimentConfiguration) -> Mapping[str, Any] | None:
    path = run_dir / "checkpoint.json"
    if not path.exists():
        return None
    encoded = read_checksummed_state(path, run_dir / "checkpoint.json.sha256", label="Historical paper replay state")
    payload = json.loads(encoded)
    if payload.get("configuration_fingerprint") != config.fingerprint:
        raise ReplayConfigurationError("Historical replay checkpoint configuration mismatch.")
    if payload.get("capacity_arbitration") != config.payload["capacity_arbitration"]:
        raise ReplayConfigurationError("Historical replay checkpoint capacity arbitration mismatch.")
    state = payload.get("paper_state")
    if not isinstance(state, Mapping) or payload.get("paper_state_fingerprint") != _fingerprint(state):
        raise ReplayConfigurationError("Historical replay paper-state fingerprint mismatch.")
    return state


def _write_runtime_state(run_dir: Path, run_id: str, config: ReplayExperimentConfiguration, runtime: CandidateV1HistoricalPaperRuntime) -> str:
    state = runtime.snapshot()
    core = {
        "schema_version": RUN_SCHEMA, "semantic_version": RUN_SEMANTIC,
        "run_id": run_id, "configuration_fingerprint": config.fingerprint,
        "capacity_arbitration": config.payload["capacity_arbitration"],
        "last_completed_boundary": state["last_completed_boundary"],
        "paper_state_fingerprint": _fingerprint(state), "paper_state": state,
        "authority": config.payload["authority"],
    }
    return _write_evidence(run_dir / "checkpoint.json", core)


def _load_strategy_profile(path: Path | None, config: ReplayExperimentConfiguration) -> CandidateV1ConfigSnapshot:
    if path is None:
        return load_candidate_v1_config()
    profile = json.loads(path.read_text(encoding="utf-8"))
    contract = profile.get("contract")
    if not isinstance(contract, Mapping):
        raise ReplayConfigurationError("Selected strategy profile lacks a contract.")
    candidate_path = (ROOT / str(contract.get("candidate_v1_configuration_path", ""))).resolve()
    snapshot = load_candidate_v1_config(candidate_path)
    expected = config.payload["capacity_arbitration"]
    if snapshot.fingerprint != config.payload["strategy"]["configuration_fingerprint"]:
        raise ReplayConfigurationError("Selected strategy profile Candidate fingerprint differs from experiment.")
    if (
        contract.get("capacity_arbitration_enabled") is not True
        or contract.get("capacity_arbitration_policy") != expected["policy"]
        or contract.get("capacity_arbitration_policy_version") != expected["policy_version"]
        or contract.get("capacity_arbitration_configuration_fingerprint") != expected["configuration_fingerprint"]
    ):
        raise ReplayConfigurationError("Selected strategy profile capacity arbitration differs from experiment.")
    if float(contract.get("maximum_position_notional_fraction", -1)) != snapshot.maximum_position_notional_fraction:
        raise ReplayConfigurationError("Selected strategy profile notional cap differs from Candidate configuration.")
    if float(config.payload["starting_account"]["starting_cash"]) != snapshot.bot_config.total_starting_capital:
        raise ReplayConfigurationError("Selected strategy profile starting account differs from experiment.")
    return snapshot


def run(
    config_path: Path = DEFAULT_CONFIG, dataset: Path = DEFAULT_DATASET,
    strategy_profile_path: Path | None = None,
) -> Path:
    config = load_replay_configuration(config_path)
    candidate_snapshot = _load_strategy_profile(strategy_profile_path, config)
    policy = load_policy(DEFAULT_CANDIDATE_POLICY)
    if candidate_snapshot.fingerprint != config.payload["strategy"]["configuration_fingerprint"]:
        raise ReplayConfigurationError("Frozen strategy configuration differs from current Candidate V1.")
    universe = config.payload["universe"]
    manifest_path = (ROOT / str(universe["manifest_reference"])).resolve()
    if universe["mode"] != "STATIC_FROZEN" or manifest_path != DEFAULT_SYMBOLS.resolve():
        raise ReplayConfigurationError("Primary replay must bind the explicit Candidate V1 symbol manifest.")
    if _sha256(manifest_path) != universe["manifest_fingerprint"]:
        raise ReplayConfigurationError("Frozen Candidate V1 symbol manifest fingerprint mismatch.")
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    run_id = _fingerprint({"configuration_fingerprint": config.fingerprint, "source_commit": source_commit})
    run_dir = dataset / "historical_paper_replay" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    driver = ReservoirArchiveDriver.from_reservoir(
        dataset=dataset, symbols=policy.candidates, income_symbol=policy.income_symbol,
        vix_path=DEFAULT_VIX, config=config, candidate_snapshot=candidate_snapshot,
    )
    manifest = {
        "schema_version": RUN_SCHEMA, "semantic_version": RUN_SEMANTIC,
        "run_id": run_id, "status": "RUNNING", "source_commit": source_commit,
        "runner_sha256": _sha256(Path(__file__)),
        "configuration": config.as_dict(), "configuration_fingerprint": config.fingerprint,
        "strategy_profile_path": str(strategy_profile_path.resolve()) if strategy_profile_path else None,
        "candidate_configuration": candidate_snapshot.as_dict(),
        "candidate_configuration_fingerprint": candidate_snapshot.fingerprint,
        "candidate_v1_policy_sha256": _sha256(DEFAULT_CANDIDATE_POLICY),
        "candidate_v1_symbols_sha256": _sha256(DEFAULT_SYMBOLS),
        "source_evidence": driver.source_evidence,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "authority": config.payload["authority"],
    }
    _write_evidence(run_dir / "run_manifest.json", manifest)
    restored = _read_runtime_state(run_dir, config)
    asset_symbols = {asset_id: symbol for symbol, asset_id in driver.source_evidence["asset_ids"].items()}
    runtime = CandidateV1HistoricalPaperRuntime(
        config, restored, candidate_snapshot=candidate_snapshot, asset_symbols=asset_symbols,
    )
    dividends = _load_dividends(dataset, policy.income_symbol)
    after = datetime.fromisoformat(runtime.state["last_completed_boundary"]) if runtime.state["last_completed_boundary"] else None
    for boundary in driver.boundaries_after(after):
        runtime.process_boundary(boundary, dividends)
        _write_runtime_state(run_dir, run_id, config, runtime)
    state = runtime.snapshot()
    marks = state["last_marks"]
    positions = state["portfolio"]["positions"]
    swing_market_value = sum(float(marks.get(symbol, value["entry_price"])) * value["shares"] for symbol, value in positions.items())
    income_value = float(state["income_shares"]) * float(marks.get(runtime.income_asset_id, 0.0))
    ending_equity = state["portfolio"]["cash"] + state["portfolio"]["tax_reserve_cash"] + swing_market_value + income_value
    report = {
        "schema_version": RUN_SCHEMA, "semantic_version": RUN_SEMANTIC,
        "run_id": run_id, "status": "COMPLETE", "configuration_fingerprint": config.fingerprint,
        "capacity_arbitration": config.payload["capacity_arbitration"],
        "candidate_configuration_fingerprint": candidate_snapshot.fingerprint,
        "source_commit": source_commit, "historical_start": driver.source_evidence["first_bar_start"],
        "historical_end": driver.source_evidence["last_bar_start"],
        "completed_15m_boundaries": state["boundaries"],
        "candidate_v1_evaluations": state["candidate_evaluations"],
        "starting_equity": config.payload["starting_account"]["starting_cash"],
        "ending_equity": ending_equity,
        "net_profit_loss": ending_equity - state["portfolio"]["total_contributions"],
        "maximum_drawdown": state["maximum_drawdown"],
        "signals": state["signals"], "fills": state["fills"],
        "closed_trades": len(state["portfolio"]["closed_trades"]),
        "wins": sum(1 for trade in state["portfolio"]["closed_trades"] if trade["pnl"] > 0),
        "losses": sum(1 for trade in state["portfolio"]["closed_trades"] if trade["pnl"] < 0),
        "income_dividends": state["income_dividends"],
        "gap_rejections": state["gap_rejections"], "risk_rejections": state["risk_rejections"],
        "capacity_deferred": state["capacity_deferred"],
        "capacity_decisions": state["capacity_decisions"],
        "ending_cash": state["portfolio"]["cash"], "ending_tax_reserve": state["portfolio"]["tax_reserve_cash"],
        "ending_income_shares": state["income_shares"], "ending_positions": {
            asset_id: {**value, "symbol_label": runtime.asset_symbols[asset_id]}
            for asset_id, value in positions.items()
        },
        "annual": state["annual"], "causal_integrity_status": "PASS",
        "historical_data_qualification_status": config.payload["dataset"]["qualification_status"],
        "known_evidence_limitations": {"unresolved_unbounded_corporate_actions": 22498},
        "source_evidence": driver.source_evidence, "authority": config.payload["authority"],
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_evidence(run_dir / "final_report.json", report)
    _write_evidence(run_dir / "exit_status.json", {"run_id": run_id, "status": "COMPLETE", "exit_code": 0})
    manifest["status"] = "COMPLETE"
    manifest["completed_at_utc"] = report["completed_at_utc"]
    manifest["final_report_fingerprint"] = _fingerprint(report)
    _write_evidence(run_dir / "run_manifest.json", manifest)
    return run_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--strategy-profile", type=Path)
    args = parser.parse_args(argv)
    run_dir = run(args.config.resolve(), args.dataset.resolve(), args.strategy_profile.resolve() if args.strategy_profile else None)
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
