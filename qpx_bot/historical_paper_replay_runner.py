"""Durable causal replay of the current Candidate V1 paper policy.

The archive driver owns complete historical collections.  The paper runtime is
given one detached completed-bar boundary at a time and has no archive handle.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import subprocess
from enum import Enum
from typing import Any, Iterable, Iterator, Mapping, Sequence

from qpx_bot.actual_two_year_15m_six import (
    _position_size_rejection_diagnostic,
    _read_vix_daily_cache,
    _reconcile_net_realized_tax_reserve,
)
from qpx_bot.allocation import rebalance_income_allocation
from qpx_bot.candidate_v1_causal import CandidateV1CausalInputs
from qpx_bot.candidate_v1_config import CandidateV1ConfigSnapshot, disabled_kelly_trade_history, load_candidate_v1_config
from qpx_bot.causal_dividends import CausalDividendEvent, IncompleteDividendMetadata
from qpx_bot.accelerators.capacity_arbitration import (
    CapacityArbitrationConfig, CapacityArbitrationContext, CapacityArbitrationV1,
    CapacityCandidate, tie_identity,
)
from qpx_bot.accelerators.base import DynamicSizingContext
from qpx_bot.accelerators.profit_recycling import (
    ProfitRecyclingContext, ProfitRecyclingRuntime, ProfitSource,
)
from qpx_bot.accelerators.pyramiding import PyramidingContext
from qpx_bot.accelerators.regime_allocation import RegimeAllocationContext
from qpx_bot.data_loader import Candle
from qpx_bot.historical_paper_replay import (
    CandidateV1ReplayPort,
    ReplayConfigurationError,
    ReplayExperimentConfiguration,
    canonical_replay_configuration,
    load_replay_configuration,
)
from qpx_bot.indicators import calculate_indicators
from qpx_bot.historical_replay_accelerators import (
    HistoricalReplayAccelerators, load_historical_replay_accelerators,
    restore_profit_runtime,
)
from qpx_bot.intraday_six_paper import IntradayBar, choose_without_ranking, load_policy
from qpx_bot.ml_historical_calendar_repair import AUDITED_FALSE_OPEN_DATES
from qpx_bot.ml_experimental_causal_baseline import build_input_snapshot
from qpx_bot.paper_state import read_checksummed_state, write_checksummed_state
from qpx_bot.portfolio import ClosedTrade, Portfolio, Position, contribution_allocation
from qpx_bot.risk import PositionSize, buy_fill, calculate_position_size
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(child) for child in value]
    return value


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
    previous_session_vix_observed_at: datetime | None = None


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
                previous_session_vix_observed_at=(
                    datetime.combine(prior_day, time(16, 0), tzinfo=start.tzinfo)
                    if prior_vix is not None else None
                ),
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


def _account_valuation_from_state(
    state: Mapping[str, Any], config: ReplayExperimentConfiguration,
) -> dict[str, Any]:
    """Recompute checkpoint valuation evidence without archive access."""
    portfolio = state["portfolio"]
    marks = state["last_marks"]
    swing_market_value = sum(
        float(marks.get(asset_id, position["entry_price"]))
        * float(position["shares"])
        for asset_id, position in portfolio["positions"].items()
    )
    income_ids = [
        asset_id for asset_id, symbol in state["asset_symbols"].items()
        if symbol == "QDTE"
    ]
    if len(income_ids) != 1:
        raise ReplayConfigurationError(
            "Checkpoint valuation lacks one exact income asset identity."
        )
    income_market_value = (
        float(state["income_shares"])
        * float(marks.get(income_ids[0], 0.0))
    )
    cash = float(portfolio["cash"])
    tax_reserve = float(portfolio["tax_reserve_cash"])
    current_marked_equity = (
        cash + tax_reserve + swing_market_value + income_market_value
    )
    deployable_cash = cash
    accelerator_state = state.get("accelerators")
    if accelerator_state is not None:
        accelerators = load_historical_replay_accelerators(
            config.payload, root=ROOT, sha256=_sha256,
        )
        if accelerators is None:
            raise ReplayConfigurationError(
                "Checkpoint valuation accelerator evidence is missing."
            )
        profit_state = accelerator_state["profit_recycling"]
        profit_runtime = restore_profit_runtime(
            accelerators.profit_recycling_config,
            float(config.payload["starting_account"]["starting_cash"]),
            profit_state["ledger"],
        )
        deployable_cash = profit_runtime.ledger.available_swing_cash(
            cash, int(profit_state["event_sequence"]) + 1,
        )
    return {
        "valuation_boundary": state["last_completed_boundary"],
        "current_marked_equity": current_marked_equity,
        "net_profit_loss": (
            current_marked_equity - float(portfolio["total_contributions"])
        ),
        "deployable_cash": deployable_cash,
        "tax_reserve": tax_reserve,
        "swing_market_value": swing_market_value,
        "income_sleeve_market_value": income_market_value,
    }


class CandidateV1HistoricalPaperRuntime:
    """Current Candidate V1 paper/account logic with no archive capability."""

    __slots__ = (
        "config", "candidate", "policy", "state", "_portfolio", "_arbitration",
        "asset_symbols", "candidate_asset_ids", "income_asset_id", "rank_by_asset",
        "_split_events_by_date", "_split_contract_identity", "_accelerators",
    )

    def __init__(
        self, config: ReplayExperimentConfiguration, state: Mapping[str, Any] | None = None,
        *, candidate_snapshot: CandidateV1ConfigSnapshot | None = None,
        asset_symbols: Mapping[str, str] | None = None,
        split_contract: Mapping[str, Any] | None = None,
        accelerators: HistoricalReplayAccelerators | None = None,
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
        self._accelerators = accelerators or load_historical_replay_accelerators(
            config.payload, root=ROOT, sha256=_sha256,
        )
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
        self._split_contract_identity, self._split_events_by_date = self._validate_split_contract(
            split_contract
        )
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
                "last_marks": {}, "last_atr": {},
                "peak_equity": starting, "maximum_drawdown": 0.0,
                "annual": {}, "signals": 0, "fills": 0, "gap_rejections": 0,
                "risk_rejections": 0, "capacity_deferred": 0, "capacity_decisions": [],
                "capacity_rejections": 0, "entry_outcomes": {},
                "outcome_reconciliation": {},
                "split_contract_identity": self._split_contract_identity,
                "applied_split_event_ids": [], "applied_splits": [],
            }
            if self._accelerators is not None:
                profit_runtime = ProfitRecyclingRuntime(
                    self._accelerators.profit_recycling_config, starting,
                )
                self.state["accelerators"] = {
                    "configuration_fingerprints": self._accelerators.fingerprints,
                    "profit_recycling": {
                        "event_sequence": 0, "ledger": profit_runtime.ledger.as_dict(),
                        "decisions": [],
                    },
                    "dynamic_sizing": {
                        "decisions": [], "opportunities": 0, "reductions": 0,
                        "unchanged": 0, "blocked": 0,
                    },
                    "pyramiding": {
                        "event_sequence": 0, "decisions": [], "opportunities": 0,
                        "additions": 0, "shares_added": 0,
                        "notional_added": 0.0, "positions": {},
                    },
                    "regime_allocation": {
                        "decisions": [], "opportunities": 0, "transitions": 0,
                        "current_regime": None,
                        "current_target_qdte_weight": 0.125,
                    },
                    "observed": {
                        "peak_concurrent_positions": 0,
                        "maximum_active_portfolio_risk_dollars": 0.0,
                        "maximum_active_portfolio_risk": 0.0,
                        "maximum_position_notional_dollars": 0.0,
                        "maximum_position_notional_fraction": 0.0,
                        "maximum_capital_utilization": 0.0,
                    },
                }
        else:
            self.state = json.loads(json.dumps(state))
            self.state.setdefault("last_atr", {})
            if (
                self.state.get("identity_key") != "provider_asset_id"
                or self.state.get("universe_manifest_fingerprint") != config.payload["universe"]["manifest_fingerprint"]
                or self.state.get("asset_symbols") != self.asset_symbols
            ):
                raise ReplayConfigurationError("Replay checkpoint provider-asset identity differs from the selected universe.")
            checkpoint_split_identity = self.state.get("split_contract_identity")
            if checkpoint_split_identity is None and not any(self._split_events_by_date.values()):
                self.state["split_contract_identity"] = self._split_contract_identity
                self.state.setdefault("applied_split_event_ids", [])
                self.state.setdefault("applied_splits", [])
            elif checkpoint_split_identity != self._split_contract_identity:
                raise ReplayConfigurationError(
                    "Replay checkpoint corporate-action evidence differs from the selected split contract."
                )
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
            if self._accelerators is not None:
                accelerator_state = self.state.get("accelerators")
                if (
                    not isinstance(accelerator_state, Mapping)
                    or accelerator_state.get("configuration_fingerprints")
                    != self._accelerators.fingerprints
                ):
                    raise ReplayConfigurationError(
                        "Replay checkpoint accelerator identity differs from configuration."
                    )
                restore_profit_runtime(
                    self._accelerators.profit_recycling_config,
                    float(config.payload["starting_account"]["starting_cash"]),
                    accelerator_state["profit_recycling"]["ledger"],
                )
                if set(accelerator_state["pyramiding"]["positions"]) != set(self._portfolio.positions):
                    raise ReplayConfigurationError(
                        "Replay checkpoint pyramid identity differs from open positions."
                    )
            elif self.state.get("accelerators") is not None:
                raise ReplayConfigurationError(
                    "Replay checkpoint contains accelerators absent from configuration."
                )

    def _validate_split_contract(
        self, contract: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any] | None, dict[date, tuple[dict[str, Any], ...]]]:
        if contract is None:
            return None, {}
        required_fingerprints = (
            "manifest_fingerprint", "corporate_action_ratio_artifact_fingerprint",
            "derived_identity_resolution_fingerprint",
            "derived_asset_id_universe_fingerprint",
            "source_corporate_action_artifact_fingerprint",
            "source_identity_resolution_fingerprint",
            "split_accounting_semantic_version",
        )
        identity = {key: contract.get(key) for key in required_fingerprints}
        if any(not isinstance(value, str) or not value for value in identity.values()):
            raise ReplayConfigurationError("Split contract fingerprints are incomplete.")
        events = contract.get("split_events")
        if not isinstance(events, list):
            raise ReplayConfigurationError("Split contract events are malformed.")
        by_date: dict[date, list[dict[str, Any]]] = {}
        seen: set[str] = set()
        candidate_ids = set(self.candidate_asset_ids)
        for raw in events:
            if not isinstance(raw, Mapping):
                raise ReplayConfigurationError("Split contract event is malformed.")
            event = dict(raw)
            event_id = event.get("provider_event_id")
            asset_id = event.get("affected_provider_asset_id")
            if not isinstance(event_id, str) or not event_id or event_id in seen:
                raise ReplayConfigurationError("Split contract event identity is duplicate or invalid.")
            if asset_id not in candidate_ids:
                raise ReplayConfigurationError("Split contract event targets an unselected provider asset.")
            try:
                effective = date.fromisoformat(str(event["effective_date"]))
                share_multiplier = float(event["share_multiplier"])
                price_multiplier = float(event["price_multiplier"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ReplayConfigurationError("Split contract ratio or date is invalid.") from exc
            if (
                not math.isfinite(share_multiplier) or share_multiplier <= 0
                or not math.isfinite(price_multiplier) or price_multiplier <= 0
                or not math.isclose(
                    share_multiplier * price_multiplier, 1.0,
                    rel_tol=1e-12, abs_tol=1e-12,
                )
                or event.get("ratio_convention")
                != "NEW_SHARES_PER_OLD_SHARES_EQUALS_NEW_RATE_DIVIDED_BY_OLD_RATE"
            ):
                raise ReplayConfigurationError("Split contract ratio convention is invalid.")
            seen.add(event_id)
            by_date.setdefault(effective, []).append(event)
        if len(events) != int(contract.get("split_event_count", -1)):
            raise ReplayConfigurationError("Split contract event count does not reconcile.")
        return identity, {
            day: tuple(sorted(values, key=lambda item: item["provider_event_id"]))
            for day, values in by_date.items()
        }

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

    def _profit_runtime(self) -> ProfitRecyclingRuntime:
        if self._accelerators is None:
            raise ReplayConfigurationError("Profit Recycling is not configured.")
        state = self.state["accelerators"]["profit_recycling"]
        return restore_profit_runtime(
            self._accelerators.profit_recycling_config,
            float(self.config.payload["starting_account"]["starting_cash"]),
            state["ledger"],
        )

    def _deployable_cash(self) -> float:
        if self._accelerators is None:
            return self._portfolio.cash
        state = self.state["accelerators"]["profit_recycling"]
        runtime = self._profit_runtime()
        return runtime.ledger.available_swing_cash(
            self._portfolio.cash, int(state["event_sequence"]) + 1,
        )

    def _consume_recycled_cash(self, cost: float) -> float:
        if self._accelerators is None or cost <= 0:
            return 0.0
        state = self.state["accelerators"]["profit_recycling"]
        runtime = self._profit_runtime()
        available = runtime.ledger.available_swing_cash(
            self._portfolio.cash + cost, int(state["event_sequence"]) + 1,
        )
        if cost > available + 1e-9:
            raise ReplayConfigurationError(
                "Accelerator entry consumed more than governed deployable cash."
            )
        used = min(cost, runtime.ledger.recycled_profit_balance)
        if used:
            runtime.ledger.consume(
                used, int(state["event_sequence"]) + 1, self._portfolio.cash + cost,
            )
        state["ledger"] = runtime.ledger.as_dict()
        return used

    def _current_equity(self) -> float:
        marks = {
            asset_id: float(self.state["last_marks"].get(asset_id, position.entry_price))
            for asset_id, position in self._portfolio.positions.items()
        }
        income_price = float(self.state["last_marks"].get(self.income_asset_id, 0.0))
        return self._portfolio.equity(marks) + self.state["income_shares"] * income_price

    def account_valuation(self) -> dict[str, Any]:
        """Return directly persisted marked-account evidence for this boundary."""
        swing_market_value = sum(
            float(self.state["last_marks"].get(asset_id, position.entry_price))
            * position.shares
            for asset_id, position in self._portfolio.positions.items()
        )
        income_market_value = (
            float(self.state["income_shares"])
            * float(self.state["last_marks"].get(self.income_asset_id, 0.0))
        )
        current_marked_equity = (
            self._portfolio.cash + self._portfolio.tax_reserve_cash
            + swing_market_value + income_market_value
        )
        return {
            "valuation_boundary": self.state["last_completed_boundary"],
            "current_marked_equity": current_marked_equity,
            "net_profit_loss": (
                current_marked_equity - self._portfolio.total_contributions
            ),
            "deployable_cash": self._deployable_cash(),
            "tax_reserve": self._portfolio.tax_reserve_cash,
            "swing_market_value": swing_market_value,
            "income_sleeve_market_value": income_market_value,
        }

    def _experiment_position_size(
        self, *, account_equity: float, available_cash: float,
        entry_price: float, atr: float, active_risk: float,
    ) -> PositionSize:
        risk = self.config.payload.get("experiment_risk")
        if risk is None:
            return calculate_position_size(
                account_equity=account_equity, available_cash=available_cash,
                entry_price=entry_price, atr=atr, active_risk=active_risk,
                config=self.candidate._snapshot.bot_config,
                trade_results_r=disabled_kelly_trade_history(self.candidate._snapshot),
            )
        if risk["per_position_risk_cap_enabled"] is not False:
            raise ReplayConfigurationError(
                "Experiment per-position risk cap is not disabled."
            )
        config = self.candidate._snapshot.bot_config
        entry_fill = buy_fill(entry_price, config.slippage_rate)
        stop_fraction = float(risk["initial_stop_fraction"])
        risk_per_share = entry_fill * stop_fraction
        remaining_active_risk = max(
            0.0,
            account_equity * config.maximum_active_portfolio_risk - active_risk,
        )
        exposure_cap = (
            account_equity
            * float(risk["maximum_provider_asset_exposure_fraction"])
        )
        shares = max(0, min(
            math.floor(available_cash / entry_fill),
            math.floor(exposure_cap / entry_fill),
            math.floor(remaining_active_risk / risk_per_share),
        ))
        blocked = None if shares > 0 else (
            "Cash, provider-asset exposure, or active-risk capacity is below one share."
        )
        return PositionSize(
            shares=shares,
            entry_fill=entry_fill,
            stop_price=entry_fill * (1.0 - stop_fraction),
            target_price=entry_fill + atr * config.target_atr_multiple,
            risk_per_share=risk_per_share,
            planned_risk=shares * risk_per_share,
            risk_fraction=0.0,
            blocked_reason=blocked,
        )

    def _close_position(
        self, *, asset_id: str, exit_price: float, exit_date: date,
        reason: str, decision_timestamp: datetime,
    ) -> ClosedTrade:
        trade = self._portfolio.close_position(
            symbol=asset_id, exit_price=exit_price, exit_date=exit_date,
            reason=reason, config=self.candidate._snapshot.bot_config,
        )
        if self._accelerators is not None:
            pyramid = self.state["accelerators"]["pyramiding"]
            meta = pyramid["positions"].pop(asset_id)
            correction = sum(
                (float(meta["original_entry_price"]) - float(item["fill_price"]))
                * float(item["shares_added"])
                for item in meta["additions"]
            )
            if correction:
                actual_pnl = trade.pnl + correction
                actual_tax = max(0.0, actual_pnl) * self.candidate._snapshot.bot_config.annual_tax_reserve_rate
                self._portfolio.realized_pnl += correction
                self._portfolio.tax_reserve_cash += actual_tax - trade.tax_reserved
                self._portfolio.cash -= actual_tax - trade.tax_reserved
                initial_risk = trade.shares * float(meta["initial_risk_per_share"])
                trade = replace(
                    trade, pnl=actual_pnl, tax_reserved=actual_tax,
                    result_r=(actual_pnl / initial_risk if initial_risk > 0 else 0.0),
                )
                self._portfolio.closed_trades[-1] = trade
        _reconcile_net_realized_tax_reserve(
            portfolio=self._portfolio, config=self.candidate._snapshot.bot_config,
        )
        if self._accelerators is not None:
            state = self.state["accelerators"]["profit_recycling"]
            state["event_sequence"] += 1
            runtime = self._profit_runtime()
            source = (
                ProfitSource.SWING_REALIZED_PROFIT
                if trade.pnl > 0 else ProfitSource.SWING_REALIZED_LOSS
            )
            event_id = _fingerprint({
                "kind": "SWING_CLOSE", "asset_id": asset_id,
                "entry_date": trade.entry_date.isoformat(),
                "exit_date": trade.exit_date.isoformat(),
                "closed_trade_count": len(self._portfolio.closed_trades),
                "pnl": trade.pnl,
            })
            decision = runtime.decide(ProfitRecyclingContext(
                decision_timestamp=decision_timestamp,
                realized_event_id=event_id,
                event_sequence=int(state["event_sequence"]),
                realized_event_source=source,
                gross_realized_pnl=trade.pnl,
                tax_reserved=trade.tax_reserved,
                ordinary_investable_cash=self._portfolio.cash,
                recycled_profit_balance=runtime.ledger.recycled_profit_balance,
                current_portfolio_equity=self._current_equity(),
            ))
            state["ledger"] = runtime.ledger.as_dict()
            state["decisions"].append(_json_safe(asdict(decision)))
        return trade

    def _register_position_for_pyramiding(self, asset_id: str, position: Position) -> None:
        if self._accelerators is None:
            return
        self.state["accelerators"]["pyramiding"]["positions"][asset_id] = {
            "original_entry_shares": float(position.shares),
            "original_entry_price": position.entry_price,
            "original_entry_atr": position.entry_atr,
            "initial_risk_per_share": position.initial_risk_per_share(
                self.candidate._snapshot.bot_config
            ),
            "anchor_price": position.entry_price,
            "additions": [],
        }

    def _apply_dynamic_sizing(
        self, *, asset_id: str, decision_timestamp: datetime, equity: float,
        deployable_cash: float, active_risk: float, risk_budget_shares: int,
        sizing: Any,
    ) -> Any:
        if self._accelerators is None or not sizing.is_tradeable:
            return sizing
        exposure = sum(
            float(self.state["last_marks"].get(key, position.entry_price)) * position.shares
            for key, position in self._portfolio.positions.items()
        )
        decision = self._accelerators.dynamic_sizing.decide(DynamicSizingContext(
            decision_timestamp=decision_timestamp,
            symbol=asset_id,
            risk_budget_requested_shares=risk_budget_shares,
            base_requested_shares=sizing.shares,
            entry_price=sizing.entry_fill,
            decision_time_total_equity=equity,
            available_swing_cash=deployable_cash,
            decision_time_active_portfolio_risk=active_risk,
            maximum_active_portfolio_risk=(
                equity * self.candidate._snapshot.bot_config.maximum_active_portfolio_risk
            ),
            risk_per_share=sizing.risk_per_share,
            existing_open_position_count=len(self._portfolio.positions),
            maximum_open_positions=self.candidate._snapshot.bot_config.maximum_swing_positions,
            existing_portfolio_exposure=(exposure / equity if equity > 0 else 0.0),
        ))
        state = self.state["accelerators"]["dynamic_sizing"]
        state["opportunities"] += 1
        state["decisions"].append(_json_safe(asdict(decision)))
        if decision.final_requested_shares < sizing.shares:
            state["reductions"] += 1
        else:
            state["unchanged"] += 1
        if decision.final_requested_shares < 1:
            state["blocked"] += 1
            return replace(
                sizing, shares=0, planned_risk=0.0,
                blocked_reason="Dynamic Sizing adjusted below one share.",
            )
        return replace(
            sizing, shares=decision.final_requested_shares,
            planned_risk=decision.final_requested_shares * sizing.risk_per_share,
        )

    def _apply_pyramids_open(
        self, start: datetime, current_candidates: Mapping[str, CompletedBarEvidence],
    ) -> None:
        if self._accelerators is None:
            return
        state = self.state["accelerators"]["pyramiding"]
        for asset_id, position in tuple(sorted(self._portfolio.positions.items())):
            evidence = current_candidates.get(asset_id)
            previous_close = self.state["last_marks"].get(asset_id)
            previous_atr = self.state["last_atr"].get(asset_id)
            meta = state["positions"].get(asset_id)
            if evidence is None or previous_close is None or previous_atr is None or meta is None:
                continue
            equity = self._current_equity()
            deployable = self._deployable_cash()
            state["event_sequence"] += 1
            event_id = _fingerprint({
                "kind": "PYRAMID_OPEN_OPPORTUNITY", "boundary": start.isoformat(),
                "asset_id": asset_id, "sequence": state["event_sequence"],
            })
            decision = self._accelerators.pyramiding.decide(PyramidingContext(
                decision_timestamp=start, event_id=event_id,
                event_sequence=int(state["event_sequence"]), symbol=asset_id,
                current_price=float(previous_close),
                execution_price=buy_fill(
                    evidence.bar.open, self.candidate._snapshot.bot_config.slippage_rate,
                ),
                current_atr=float(previous_atr),
                original_entry_price=float(meta["original_entry_price"]),
                original_entry_shares=float(meta["original_entry_shares"]),
                current_shares=float(position.shares),
                additions_count=len(meta["additions"]),
                pyramid_anchor_price=float(meta["anchor_price"]),
                decision_time_total_equity=equity,
                available_cash=deployable,
                active_portfolio_risk=self._portfolio.active_risk(),
                maximum_active_portfolio_risk=(
                    equity * self.candidate._snapshot.bot_config.maximum_active_portfolio_risk
                ),
                current_position_active_risk=position.active_risk,
                hard_notional_cap=float(
                    self.config.payload.get("experiment_risk", {}).get(
                        "maximum_provider_asset_exposure_fraction",
                        self.candidate._snapshot.maximum_position_notional_fraction,
                    )
                ),
            ))
            state["opportunities"] += 1
            state["decisions"].append(_json_safe(asdict(decision)))
            if not decision.accepted:
                continue
            cost = decision.accepted_notional
            if cost > deployable + 1e-9 or cost > self._portfolio.cash + 1e-9:
                raise ReplayConfigurationError("Accepted pyramid addition exceeded governed cash.")
            position.shares += decision.accepted_shares
            self._portfolio.cash -= cost
            addition = {
                "event_id": event_id, "event_sequence": state["event_sequence"],
                "timestamp": start.isoformat(), "fill_price": decision.execution_price,
                "shares_added": decision.accepted_shares,
                "atr_used": previous_atr,
                "configuration_fingerprint": self._accelerators.pyramiding_config.fingerprint,
                "decision_id": decision.decision_id,
            }
            meta["anchor_price"] = decision.execution_price
            meta["additions"].append(addition)
            state["additions"] += 1
            state["shares_added"] += decision.accepted_shares
            state["notional_added"] += cost
            self._consume_recycled_cash(cost)

    def _record_accelerator_observations(self, equity: float) -> None:
        if self._accelerators is None or equity <= 0:
            return
        observed = self.state["accelerators"]["observed"]
        observed["peak_concurrent_positions"] = max(
            observed["peak_concurrent_positions"], len(self._portfolio.positions),
        )
        active_risk = self._portfolio.active_risk()
        observed["maximum_active_portfolio_risk_dollars"] = max(
            observed["maximum_active_portfolio_risk_dollars"], active_risk,
        )
        observed["maximum_active_portfolio_risk"] = max(
            observed["maximum_active_portfolio_risk"], active_risk / equity,
        )
        notional_dollars = [
            float(self.state["last_marks"].get(asset_id, position.entry_price))
            * position.shares
            for asset_id, position in self._portfolio.positions.items()
        ]
        notionals = [value / equity for value in notional_dollars]
        observed["maximum_position_notional_dollars"] = max(
            observed["maximum_position_notional_dollars"],
            max(notional_dollars, default=0.0),
        )
        observed["maximum_position_notional_fraction"] = max(
            observed["maximum_position_notional_fraction"], max(notionals, default=0.0),
        )
        income_price = float(self.state["last_marks"].get(self.income_asset_id, 0.0))
        invested = sum(notional_dollars) + self.state["income_shares"] * income_price
        observed["maximum_capital_utilization"] = max(
            observed["maximum_capital_utilization"], invested / equity,
        )

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

        # OPEN phase: corporate actions transform all affected state at the
        # effective market open before exits, settlements, rebalancing, gap
        # validation, sizing, fills, marking, or risk calculations.
        self._apply_splits_open(start)
        # Dividend entitlements and settlements are effective before account
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
                self._close_position(
                    asset_id=asset_id, exit_price=float(outcome.exit_price),
                    exit_date=start.date(), reason=outcome.reason or "OPEN_EXIT",
                    decision_timestamp=start,
                )

        self._rebalance_income_open(
            start, bars, boundary.previous_session_vix,
            boundary.previous_session_vix_observed_at,
        )
        self._apply_pyramids_open(start, current_candidates)

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
            if len(self._portfolio.positions) >= self.candidate._snapshot.bot_config.maximum_swing_positions:
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
            active_risk = self._portfolio.active_risk()
            deployable_cash = self._deployable_cash()
            sizing = self._experiment_position_size(
                account_equity=equity, available_cash=deployable_cash,
                entry_price=evidence.bar.open, atr=signal.signal_atr,
                active_risk=active_risk,
            )
            risk_budget_shares = sizing.shares
            maximum_notional = equity * self.candidate._snapshot.maximum_position_notional_fraction
            if sizing.is_tradeable and sizing.entry_fill * sizing.shares > maximum_notional:
                shares = int(maximum_notional // sizing.entry_fill)
                sizing = replace(sizing, shares=shares, planned_risk=sizing.risk_per_share * shares,
                                 blocked_reason=None if shares > 0 else "Position notional cap blocked the trade.")
            sizing = self._apply_dynamic_sizing(
                asset_id=signal.provider_asset_id, decision_timestamp=start,
                equity=equity, deployable_cash=deployable_cash,
                active_risk=active_risk, risk_budget_shares=risk_budget_shares,
                sizing=sizing,
            )
            if not sizing.is_tradeable:
                self.state["risk_rejections"] += 1
                rejection_reason = (
                    sizing.blocked_reason
                    if self.config.payload.get("experiment_risk") is not None
                    else _position_size_rejection_diagnostic(
                        account_equity=equity,
                        available_cash=deployable_cash,
                        active_risk=active_risk,
                        sizing=sizing,
                        config=self.candidate._snapshot.bot_config,
                    )
                )
                self._finish_entry(
                    signal.signal_id, "REJECTED", rejection_reason,
                )
                continue
            position = self._portfolio.open_position(
                symbol=signal.provider_asset_id, sizing=sizing, entry_date=start.date(),
                entry_atr=signal.signal_atr, config=self.candidate._snapshot.bot_config,
            )
            experiment_risk = self.config.payload.get("experiment_risk")
            if experiment_risk is not None:
                position.entry_semantic_snapshot = {
                    "sizing_semantic_version": experiment_risk["sizing_semantic_version"],
                    "initial_stop_mode": "ENTRY_PRICE_FRACTION",
                    "initial_stop_fraction": experiment_risk["initial_stop_fraction"],
                    "maximum_provider_asset_exposure_fraction": experiment_risk[
                        "maximum_provider_asset_exposure_fraction"
                    ],
                    "per_position_risk_cap_enabled": False,
                }
            self._register_position_for_pyramiding(signal.provider_asset_id, position)
            self._consume_recycled_cash(sizing.entry_fill * sizing.shares)
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
                self._close_position(
                    asset_id=asset_id, exit_price=float(outcome.exit_price),
                    exit_date=start.date(), reason=outcome.reason or "EXIT",
                    decision_timestamp=boundary.completed_at,
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
        slots = max(
            0,
            self.candidate._snapshot.bot_config.maximum_swing_positions
            - len(self._portfolio.positions) - len(self.state["pending"]),
        )
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
            if evidence.candidate_inputs is not None:
                self.state["last_atr"][asset_id] = evidence.candidate_inputs.current_atr
        self._reconcile_outcomes()
        marks = {symbol: float(self.state["last_marks"].get(symbol, position.entry_price))
                 for symbol, position in self._portfolio.positions.items()}
        income_price = float(self.state["last_marks"].get(self.income_asset_id, 0.0))
        equity = self._portfolio.equity(marks) + self.state["income_shares"] * income_price
        self._record_accelerator_observations(equity)
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

    def _apply_splits_open(self, start: datetime) -> None:
        due = self._split_events_by_date.get(start.date(), ())
        if not due:
            return
        applied = set(self.state["applied_split_event_ids"])
        unapplied = [event for event in due if event["provider_event_id"] not in applied]
        if not unapplied:
            return
        if start.hour != 9 or start.minute != 30:
            raise ReplayConfigurationError(
                "A split event was not delivered at its effective market-open boundary."
            )
        for event in unapplied:
            event_id = str(event["provider_event_id"])
            asset_id = str(event["affected_provider_asset_id"])
            share_multiplier = float(event["share_multiplier"])
            price_multiplier = float(event["price_multiplier"])
            cash_before = self._portfolio.cash
            reserve_before = self._portfolio.tax_reserve_cash
            realized_before = self._portfolio.realized_pnl
            position_reconciliation = None
            if asset_id in self._portfolio.positions:
                position_reconciliation = self._portfolio.apply_split(
                    symbol=asset_id, share_multiplier=share_multiplier,
                )
            pending_reconciliation = None
            pending = self.state["pending"].get(asset_id)
            if pending is not None:
                before = {
                    "signal_atr": float(pending["signal_atr"]),
                    "prior_close": float(pending["prior_close"]),
                }
                pending["signal_atr"] = before["signal_atr"] * price_multiplier
                pending["prior_close"] = before["prior_close"] * price_multiplier
                pending_reconciliation = {
                    "pre_signal_atr": before["signal_atr"],
                    "post_signal_atr": pending["signal_atr"],
                    "pre_prior_close": before["prior_close"],
                    "post_prior_close": pending["prior_close"],
                    "expected_entry_price": None,
                    "precomputed_share_count": None,
                }
            mark_reconciliation = None
            if asset_id in self.state["last_marks"]:
                before_mark = float(self.state["last_marks"][asset_id])
                self.state["last_marks"][asset_id] = before_mark * price_multiplier
                mark_reconciliation = {
                    "pre_last_mark": before_mark,
                    "post_last_mark": self.state["last_marks"][asset_id],
                }
            if asset_id in self.state["last_atr"]:
                self.state["last_atr"][asset_id] = (
                    float(self.state["last_atr"][asset_id]) * price_multiplier
                )
            pyramid_reconciliation = None
            if self._accelerators is not None:
                meta = self.state["accelerators"]["pyramiding"]["positions"].get(asset_id)
                if meta is not None:
                    before_meta = json.loads(json.dumps(meta))
                    meta["original_entry_shares"] *= share_multiplier
                    meta["original_entry_price"] *= price_multiplier
                    meta["original_entry_atr"] *= price_multiplier
                    meta["initial_risk_per_share"] *= price_multiplier
                    meta["anchor_price"] *= price_multiplier
                    for addition in meta["additions"]:
                        addition["shares_added"] *= share_multiplier
                        addition["fill_price"] *= price_multiplier
                        addition["atr_used"] *= price_multiplier
                    pyramid_reconciliation = {
                        "before": before_meta,
                        "after": json.loads(json.dumps(meta)),
                    }
            if (
                self._portfolio.cash != cash_before
                or self._portfolio.tax_reserve_cash != reserve_before
                or self._portfolio.realized_pnl != realized_before
            ):
                raise ReplayConfigurationError("Split transformation changed cash or realized accounting.")
            reconciliation = {
                "provider_event_id": event_id,
                "affected_provider_asset_id": asset_id,
                "effective_boundary": start.isoformat(),
                "action_type": event["action_type"],
                "old_rate": event["old_rate"], "new_rate": event["new_rate"],
                "share_multiplier": share_multiplier,
                "price_multiplier": price_multiplier,
                "split_record_fingerprint": event["split_record_fingerprint"],
                "position_reconciliation": position_reconciliation,
                "pending_reconciliation": pending_reconciliation,
                "mark_reconciliation": mark_reconciliation,
                "pyramid_reconciliation": pyramid_reconciliation,
                "cash_before": cash_before, "cash_after": self._portfolio.cash,
                "tax_reserve_before": reserve_before,
                "tax_reserve_after": self._portfolio.tax_reserve_cash,
                "realized_pnl_before": realized_before,
                "realized_pnl_after": self._portfolio.realized_pnl,
            }
            self.state["applied_splits"].append(reconciliation)
            applied.add(event_id)
        self.state["applied_split_event_ids"] = sorted(applied)

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
        previous_session_vix: float | None,
        previous_session_vix_observed_at: datetime | None,
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
        regime_decision = None
        if self._accelerators is not None:
            if previous_session_vix is None or previous_session_vix_observed_at is None:
                raise ReplayConfigurationError(
                    "Scheduled Regime Allocation lacks previous-session VIX evidence."
                )
            regime_state = self.state["accelerators"]["regime_allocation"]
            swing_value = self._portfolio.market_value(position_marks)
            income_value = self.state["income_shares"] * income_bar.bar.open
            investable = income_value + swing_value + self._portfolio.cash
            regime_decision = self._accelerators.regime_allocation.decide(
                RegimeAllocationContext(
                    decision_timestamp=start,
                    vix_observation_timestamp=previous_session_vix_observed_at,
                    previous_completed_session_vix_close=previous_session_vix,
                    current_qdte_target=float(regime_state["current_target_qdte_weight"]),
                    current_actual_qdte_weight=(income_value / investable if investable > 0 else 0.0),
                    swing_cash=self._portfolio.cash,
                    swing_market_value=swing_value,
                    investable_equity=investable,
                )
            )
            if (
                regime_state["current_regime"] is not None
                and regime_state["current_regime"] != regime_decision.regime_identity
            ):
                regime_state["transitions"] += 1
            regime_state["current_regime"] = regime_decision.regime_identity
            regime_state["current_target_qdte_weight"] = regime_decision.proposed_target_qdte_weight
            regime_state["opportunities"] += 1
            target = regime_decision.proposed_target_qdte_weight

            profit_state = self.state["accelerators"]["profit_recycling"]
            profit_state["event_sequence"] += 1
            profit_runtime = self._profit_runtime()
            profit_runtime.ledger.on_sleeve_rebalance(
                self._portfolio.cash, int(profit_state["event_sequence"]),
            )
            profit_state["ledger"] = profit_runtime.ledger.as_dict()
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
        if regime_decision is not None:
            evidence = _json_safe(asdict(regime_decision))
            evidence["qdte_market_value_traded"] = result.market_value_traded
            total_after = result.after_investable_value
            evidence["resulting_actual_qdte_weight"] = (
                result.after_income_value / total_after if total_after > 0 else 0.0
            )
            evidence["rebalance_action"] = result.action
            self.state["accelerators"]["regime_allocation"]["decisions"].append(evidence)


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
    if payload.get("accelerators") != config.payload.get("accelerators"):
        raise ReplayConfigurationError("Historical replay checkpoint accelerator configuration mismatch.")
    state = payload.get("paper_state")
    if not isinstance(state, Mapping) or payload.get("paper_state_fingerprint") != _fingerprint(state):
        raise ReplayConfigurationError("Historical replay paper-state fingerprint mismatch.")
    valuation = payload.get("account_valuation")
    if valuation is not None:
        recomputed = _account_valuation_from_state(state, config)
        if (
            not isinstance(valuation, Mapping)
            or payload.get("account_valuation_fingerprint") != _fingerprint(valuation)
            or valuation.get("valuation_boundary") != state.get("last_completed_boundary")
            or _fingerprint(valuation) != _fingerprint(recomputed)
        ):
            raise ReplayConfigurationError(
                "Historical replay checkpoint account valuation is invalid."
            )
    elif config.payload.get("experiment_risk") is not None:
        raise ReplayConfigurationError(
            "Historical replay checkpoint lacks required account valuation."
        )
    return state


def _write_runtime_state(run_dir: Path, run_id: str, config: ReplayExperimentConfiguration, runtime: CandidateV1HistoricalPaperRuntime) -> str:
    state = runtime.snapshot()
    valuation = runtime.account_valuation()
    core = {
        "schema_version": RUN_SCHEMA, "semantic_version": RUN_SEMANTIC,
        "run_id": run_id, "configuration_fingerprint": config.fingerprint,
        "capacity_arbitration": config.payload["capacity_arbitration"],
        "accelerators": config.payload.get("accelerators"),
        "last_completed_boundary": state["last_completed_boundary"],
        "account_valuation": valuation,
        "account_valuation_fingerprint": _fingerprint(valuation),
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
    if config.payload.get("accelerators") is not None:
        expected_fingerprints = {
            name: item["configuration_fingerprint"]
            for name, item in config.payload["accelerators"].items()
        }
        if contract.get("accelerator_configuration_fingerprints") != expected_fingerprints:
            raise ReplayConfigurationError(
                "Selected strategy profile accelerator fingerprints differ from experiment."
            )
        expected_risk = (
            snapshot.bot_config.maximum_swing_positions,
            snapshot.bot_config.risk_per_trade,
            snapshot.bot_config.maximum_active_portfolio_risk,
        )
        profile_risk = (
            contract.get("maximum_positions"), contract.get("risk_per_trade"),
            contract.get("maximum_active_portfolio_risk"),
        )
        if profile_risk != expected_risk:
            raise ReplayConfigurationError(
                "Selected strategy profile risk limits differ from Candidate configuration."
            )
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
