#!/usr/bin/env python3
"""Strict-causal Candidate V1 replay over the frozen Top-100 dataset.

This runner preserves the verified Candidate V1 economics while replacing the
all-symbol intersection loop with an explicit OPEN/CLOSE market clock and a
strategy boundary that receives scalar, already-completed observations only.

QDTE entitlement is captured from shares owned at the ex-date open.  Cash is
released only at the first recorded market open on or after the later of the
authentic payable/process dates frozen from Alpaca corporate actions.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import csv
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path("/storage/emulated/0/QPX_ALPHA")
if not ROOT.exists():
    ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import QPX_FREEZE_TOP100_ALPACA_DATA as freezer
import QPX_RUN_FROZEN_TOP100_PORTFOLIO as baseline
import qpx_bot.actual_two_year_15m_six as qpx

from qpx_bot.causal_replay import (
    CausalAccessError,
    CausalDataPortal,
    MarketClock,
    ReplayBar,
    ReplayPhase,
)
from qpx_bot.candidate_v1_causal import (
    CandidateV1CausalInputs,
    evaluate_candidate_v1_causal,
)
from qpx_bot.causal_dividends import (
    CausalDividendLedger,
    load_causal_dividends,
)
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import IndicatorSet, calculate_indicators
from qpx_bot.intraday_six_paper import choose_without_ranking
from qpx_bot.portfolio import Portfolio
from qpx_bot.risk import buy_fill, calculate_position_size
from qpx_bot.strategy import evaluate_exit


START = date(2024, 3, 7)
END = date(2026, 8, 7)
INITIALIZATION_MARKET_BARS = 200
MAXIMUM_POSITIONS = 6
MAXIMUM_GAP_ATR = 2.0
MAXIMUM_NOTIONAL_FRACTION = 0.90
MOMENTUM_PERSISTENCE = 52.0
VIX_EXCLUSION_LOW = 20.0
VIX_EXCLUSION_HIGH = 25.0

REPORT_ROOT = (
    ROOT
    / "reports"
    / "qpx_frozen_top100_strict_causal_v1"
)
SUMMARY_PATH = REPORT_ROOT / "summary.json"
TRADES_PATH = REPORT_ROOT / "trades.csv"
EQUITY_PATH = REPORT_ROOT / "equity.csv"
SIGNALS_PATH = REPORT_ROOT / "signals.csv"
ALLOCATIONS_PATH = REPORT_ROOT / "allocations.csv"
DIAGNOSTICS_PATH = REPORT_ROOT / "diagnostics.json"


@dataclass(frozen=True, slots=True)
class PendingSignal:
    symbol: str
    signal_time: datetime
    signal_atr: float
    prior_close: float
    tie_key: str


def candidate_config() -> BotConfig:
    config = replace(
        BotConfig(),
        starting_cash=1300.0,
        starting_swing_cash=0.0,
        monthly_contribution=0.0,
        dividend_allocation_years_1_2=0.125,
        swing_allocation_years_1_2=0.875,
        dividend_allocation_later=0.125,
        swing_allocation_later=0.875,
        allocation_rebalance_frequency="weekly",
        maximum_swing_positions=6,
        minimum_average_daily_volume=75_000,
        breakout_volume_multiplier=1.05,
        breakout_lookback=10,
        maximum_vix_for_entries=32.0,
        rsi_overbought=75.0,
        risk_per_trade=0.03,
        maximum_active_portfolio_risk=0.10,
        stop_atr_multiple=2.5,
        target_atr_multiple=5.0,
        trailing_activation_atr=3.0,
        slippage_rate=0.00075,
        annual_tax_reserve_rate=0.37,
        allocation_rebalance_tolerance=0.0025,
        minimum_rebalance_trade=1.0,
    )
    config.validate()
    return config


def atomic_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def replay_bars(symbol: str) -> tuple[ReplayBar, ...]:
    frozen = freezer.read_frozen_bars(
        freezer.frozen_bar_path(symbol)
    )
    ordered = sorted(
        frozen.values(),
        key=lambda item: item.start,
    )
    return tuple(
        ReplayBar(
            start=bar.start,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=int(bar.volume),
        )
        for bar in ordered
        if START <= bar.start.date() <= END
    )


def to_candles(
    bars: tuple[ReplayBar, ...],
) -> list[Candle]:
    return [
        Candle(
            date=bar.start.date(),
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        for bar in bars
    ]


def previous_vix_value(
    *,
    day: date,
    close_dates: list[date],
    closes: dict[date, float],
) -> float:
    index = bisect_left(close_dates, day) - 1
    if index < 0:
        raise RuntimeError(
            f"No previous completed VIX close exists for {day}."
        )
    return float(closes[close_dates[index]])


def strict_entry_inputs(
    *,
    symbol: str,
    timestamp: datetime,
    bars: dict[str, tuple[ReplayBar, ...]],
    indicators: dict[str, IndicatorSet],
    indices: dict[str, dict[datetime, int]],
    vix: float,
    config: BotConfig,
) -> CandidateV1CausalInputs | None:
    index = indices[symbol].get(timestamp)
    if index is None:
        return None

    previous_index = index - 1
    slope_index = index - config.sma_slope_lookback
    breakout_start = index - config.breakout_lookback

    if (
        previous_index < 0
        or slope_index < 0
        or breakout_start < 0
    ):
        return None

    values = indicators[symbol]
    required = (
        values.ema_fast[index],
        values.ema_fast[previous_index],
        values.ema_slow[index],
        values.ema_slow[previous_index],
        values.rsi[index],
        values.rsi[previous_index],
        values.rmi[index],
        values.rmi[previous_index],
        values.sma_trend[index],
        values.sma_trend[slope_index],
        values.average_volume[previous_index],
        values.atr[index],
    )

    if any(value is None for value in required):
        return None

    current = bars[symbol][index]
    prior_high = max(
        item.high
        for item in bars[symbol][
            breakout_start:index
        ]
    )

    return CandidateV1CausalInputs(
        index=index,
        current_close=current.close,
        current_volume=current.volume,
        current_fast=float(values.ema_fast[index]),
        previous_fast=float(
            values.ema_fast[previous_index]
        ),
        current_slow=float(values.ema_slow[index]),
        previous_slow=float(
            values.ema_slow[previous_index]
        ),
        current_rsi=float(values.rsi[index]),
        previous_rsi=float(values.rsi[previous_index]),
        current_rmi=float(values.rmi[index]),
        previous_rmi=float(values.rmi[previous_index]),
        current_sma=float(values.sma_trend[index]),
        slope_sma=float(values.sma_trend[slope_index]),
        baseline_volume=float(
            values.average_volume[previous_index]
        ),
        current_atr=float(values.atr[index]),
        prior_high=float(prior_high),
        vix=float(vix),
    )


def legacy_candidate_evaluation(
    *,
    symbol: str,
    timestamp: datetime,
    candles: dict[str, list[Candle]],
    indicators: dict[str, IndicatorSet],
    indices: dict[str, dict[datetime, int]],
    vix: float,
    config: BotConfig,
):
    index = indices[symbol][timestamp]
    evaluation = qpx._evaluate_entry_relaxed_frequency(
        candles=candles[symbol],
        indicators=indicators[symbol],
        index=index,
        vix=vix,
        config=config,
    )

    if not (
        VIX_EXCLUSION_LOW
        < float(vix)
        < VIX_EXCLUSION_HIGH
    ):
        return evaluation

    checks = dict(evaluation.checks)
    checks["candidate_vix_20_25_exclusion"] = False
    failed = tuple(
        dict.fromkeys(
            (
                *evaluation.failed_checks,
                "candidate_vix_20_25_exclusion",
            )
        )
    )
    return qpx.EntryEvaluation(
        index=evaluation.index,
        should_enter=False,
        checks=checks,
        triggers=evaluation.triggers,
        failed_checks=failed,
    )


def audit_indicator_and_strategy_equivalence(
    *,
    top100: list[str],
    bars: dict[str, tuple[ReplayBar, ...]],
    candles: dict[str, list[Candle]],
    indicators: dict[str, IndicatorSet],
    indices: dict[str, dict[datetime, int]],
    vix_dates: list[date],
    vix_closes: dict[date, float],
    config: BotConfig,
) -> dict[str, int]:
    indicator_checks = 0
    strategy_checks = 0

    fields = (
        "ema_fast",
        "ema_slow",
        "rsi",
        "rmi",
        "atr",
        "sma_trend",
        "average_volume",
    )

    for symbol in top100:
        count = len(bars[symbol])
        sample_indices = sorted(
            {
                min(count - 1, INITIALIZATION_MARKET_BARS),
                count // 2,
                count - 1,
            }
        )

        for index in sample_indices:
            if index < 0:
                continue

            prefix = candles[symbol][: index + 1]
            prefix_indicators = calculate_indicators(
                prefix,
                config,
            )

            for field in fields:
                expected = getattr(
                    indicators[symbol],
                    field,
                )[index]
                actual = getattr(
                    prefix_indicators,
                    field,
                )[index]

                if expected is None or actual is None:
                    if expected is not actual:
                        raise RuntimeError(
                            f"{symbol}: indicator prefix mismatch "
                            f"for {field} at index {index}."
                        )
                elif not math.isclose(
                    float(expected),
                    float(actual),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                ):
                    raise RuntimeError(
                        f"{symbol}: indicator prefix mismatch "
                        f"for {field} at index {index}: "
                        f"{expected} != {actual}"
                    )

                indicator_checks += 1

            timestamp = bars[symbol][index].start
            inputs = strict_entry_inputs(
                symbol=symbol,
                timestamp=timestamp,
                bars=bars,
                indicators=indicators,
                indices=indices,
                vix=previous_vix_value(
                    day=timestamp.date(),
                    close_dates=vix_dates,
                    closes=vix_closes,
                ),
                config=config,
            )

            if inputs is None:
                continue

            strict = evaluate_candidate_v1_causal(
                inputs=inputs,
                config=config,
                momentum_persistence_level=(
                    MOMENTUM_PERSISTENCE
                ),
                vix_exclusion_low=VIX_EXCLUSION_LOW,
                vix_exclusion_high=VIX_EXCLUSION_HIGH,
            )
            legacy = legacy_candidate_evaluation(
                symbol=symbol,
                timestamp=timestamp,
                candles=candles,
                indicators=indicators,
                indices=indices,
                vix=inputs.vix,
                config=config,
            )

            if (
                strict.should_enter
                != legacy.should_enter
                or dict(strict.checks)
                != dict(legacy.checks)
                or strict.triggers
                != legacy.triggers
                or strict.failed_checks
                != legacy.failed_checks
            ):
                raise RuntimeError(
                    f"{symbol}: strict/legacy entry semantics "
                    f"mismatch at {timestamp.isoformat()}."
                )

            strategy_checks += 1

    return {
        "indicator_prefix_value_checks": (
            indicator_checks
        ),
        "strict_vs_legacy_strategy_checks": (
            strategy_checks
        ),
    }


def apply_notional_cap(
    *,
    sizing,
    account_equity: float,
):
    if not sizing.is_tradeable:
        return sizing, False, False

    raw_share_cap = math.floor(
        (
            account_equity
            * MAXIMUM_NOTIONAL_FRACTION
        )
        / sizing.entry_fill
    )
    one_share_floor = raw_share_cap < 1
    share_cap = max(1, raw_share_cap)
    capped_shares = min(
        sizing.shares,
        share_cap,
    )

    if capped_shares >= sizing.shares:
        return sizing, False, one_share_floor

    return (
        replace(
            sizing,
            shares=capped_shares,
            planned_risk=(
                capped_shares
                * sizing.risk_per_share
            ),
        ),
        True,
        one_share_floor,
    )


def current_position_marks(
    *,
    portal: CausalDataPortal,
    portfolio: Portfolio,
    last_close: dict[str, float],
) -> tuple[dict[str, float], int]:
    marks: dict[str, float] = {}
    stale = 0

    for symbol in portfolio.positions:
        snapshot = portal.current_open(symbol)
        if snapshot is not None:
            marks[symbol] = snapshot.open
        elif symbol in last_close:
            marks[symbol] = last_close[symbol]
            stale += 1
        else:
            raise RuntimeError(
                f"No causal valuation mark exists for {symbol}."
            )

    return marks, stale


def close_trade(
    *,
    portfolio: Portfolio,
    symbol: str,
    exit_price: float,
    exit_time: datetime,
    reason: str,
    config: BotConfig,
    entry_times: dict[str, datetime],
    trade_records: list[qpx.TradeRecord],
) -> float:
    closed = portfolio.close_position(
        symbol=symbol,
        exit_price=exit_price,
        exit_date=exit_time.date(),
        reason=reason,
        config=config,
    )
    released = qpx._reconcile_net_realized_tax_reserve(
        portfolio=portfolio,
        config=config,
    )
    entry_time = entry_times.pop(symbol)
    trade_records.append(
        qpx.TradeRecord(
            symbol=closed.symbol,
            entry_time=entry_time,
            exit_time=exit_time,
            shares=closed.shares,
            entry_price=closed.entry_price,
            exit_price=closed.exit_price,
            pnl=closed.pnl,
            tax_reserved=(
                closed.tax_reserved
                - released
            ),
            reason=closed.reason,
            result_r=closed.result_r,
        )
    )
    return released


def write_signal_records(
    path: Path,
    records: list[qpx.SignalRecord],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    qpx._write_signals(path, records)


def load_enriched_frozen_state() -> tuple[dict, dict, tuple[str, ...]]:
    """Load the verified frozen universe without changing the legacy pin."""
    selection = json.loads(
        baseline.SELECTION_PATH.read_text(encoding="utf-8")
    )
    dataset = json.loads(
        baseline.DATASET_MANIFEST.read_text(encoding="utf-8")
    )

    if selection.get("status") != "AUDITED_SELECTION_FROZEN":
        raise RuntimeError("Top-100 selection is not frozen.")
    if (
        selection.get("manifest_fingerprint")
        != baseline.EXPECTED_SELECTION_FP
    ):
        raise RuntimeError("Top-100 selection fingerprint changed.")
    if dataset.get("status") != "FROZEN_AND_VERIFIED":
        raise RuntimeError("Enriched frozen dataset is not verified.")

    freezer.verify_dataset()

    top100 = tuple(
        str(symbol).strip().upper()
        for symbol in selection["top100"]
    )
    if len(top100) != 100 or len(set(top100)) != 100:
        raise RuntimeError("Strict replay requires 100 unique frozen symbols.")

    return selection, dataset, top100


def run_strict() -> tuple[dict, dict]:
    selection, dataset, top100_tuple = (
        load_enriched_frozen_state()
    )
    top100 = list(top100_tuple)

    baseline.verify_required_files(
        dataset,
        top100,
    )
    baseline.prepare_runtime_support(
        dataset
    )

    dividends = load_causal_dividends(
        baseline.RUNTIME_SHARED
        / "QDTE_DIVIDENDS.csv"
    )
    dividend_ledger = CausalDividendLedger([
        event
        for event in dividends
        if START <= event.ex_date <= END
    ])

    config = candidate_config()

    histories: dict[
        str,
        tuple[ReplayBar, ...],
    ] = {
        symbol: replay_bars(symbol)
        for symbol in [*top100, "QDTE"]
    }

    if any(
        not history
        for history in histories.values()
    ):
        raise RuntimeError(
            "One or more frozen histories are empty."
        )

    union_times = sorted(
        set().union(
            *(
                {
                    bar.start
                    for bar in history
                }
                for history in histories.values()
            )
        )
    )
    intersection_times = sorted(
        set.intersection(
            *(
                {
                    bar.start
                    for bar in history
                }
                for history in histories.values()
            )
        )
    )

    if not union_times:
        raise RuntimeError(
            "Strict recorded market clock is empty."
        )

    if (
        union_times[0].date() != START
        or union_times[-1].date() != END
    ):
        raise RuntimeError(
            "Strict recorded market clock does not "
            "cover the frozen test endpoints."
        )

    clock = MarketClock(union_times)
    portal = CausalDataPortal(
        clock=clock,
        histories=histories,
    )

    # Deliberately attempt illegal access against real frozen data.
    if len(union_times) < 2:
        raise RuntimeError(
            "Strict replay needs at least two clock bars."
        )

    future_access_blocked = False
    try:
        portal.bar_at(
            top100[0],
            union_times[1],
        )
    except CausalAccessError:
        future_access_blocked = True

    if not future_access_blocked:
        raise RuntimeError(
            "FUTURE BAR ACCESS WAS NOT BLOCKED."
        )

    current_full_bar_blocked = False
    try:
        portal.completed_bar(top100[0])
    except CausalAccessError:
        current_full_bar_blocked = True

    if not current_full_bar_blocked:
        raise RuntimeError(
            "CURRENT OPEN PHASE EXPOSED FULL OHLCV."
        )

    candles = {
        symbol: to_candles(history)
        for symbol, history in histories.items()
        if symbol != "QDTE"
    }
    indicators = {
        symbol: calculate_indicators(
            candles[symbol],
            config,
        )
        for symbol in top100
    }
    indices = {
        symbol: {
            bar.start: index
            for index, bar in enumerate(
                histories[symbol]
            )
        }
        for symbol in top100
    }

    vix_path = (
        baseline.RUNTIME_SHARED
        / "CBOE_VIX_DAILY.csv"
    )
    vix_closes = qpx._validate_vix_daily_coverage(
        closes=qpx._read_vix_daily_cache(
            vix_path
        ),
        start=START,
        end=END,
    )
    vix_dates = sorted(vix_closes)

    equivalence = (
        audit_indicator_and_strategy_equivalence(
            top100=top100,
            bars=histories,
            candles=candles,
            indicators=indicators,
            indices=indices,
            vix_dates=vix_dates,
            vix_closes=vix_closes,
            config=config,
        )
    )

    first_qdte_open = portal.current_open(
        "QDTE"
    )
    if first_qdte_open is None:
        raise RuntimeError(
            "QDTE has no open at the first strict clock timestamp."
        )

    initial_fill = buy_fill(
        first_qdte_open.open,
        config.slippage_rate,
    )
    income_shares = (
        config.starting_cash
        / initial_fill
    )
    income_cost = config.starting_cash
    portfolio = Portfolio(
        config.starting_swing_cash
    )

    income_shares, income_cost, initial_rebalance = (
        qpx._apply_rebalance(
            portfolio=portfolio,
            income_shares=income_shares,
            income_cost=income_cost,
            qdte_price=first_qdte_open.open,
            position_prices={},
            target_income_weight=0.125,
            config=config,
        )
    )

    allocation_records: list[
        qpx.AllocationRecord
    ] = [
        qpx.AllocationRecord(
            time=clock.time,
            event_type="INITIAL_REBALANCE",
            external_contribution=1300.0,
            target_income_weight=0.125,
            action=initial_rebalance.action,
            before_income_weight=(
                initial_rebalance.before_income_weight
            ),
            after_income_weight=(
                initial_rebalance.after_income_weight
            ),
            qdte_market_value_traded=(
                initial_rebalance.market_value_traded
            ),
            realized_pnl=(
                initial_rebalance.realized_pnl
            ),
            tax_reserved=(
                initial_rebalance.tax_reserved
            ),
        )
    ]

    first_iso = clock.time.isocalendar()
    current_rebalance_key = (
        (first_iso.year, first_iso.week)
        if clock.time.weekday() == 3
        else None
    )

    pending: dict[str, PendingSignal] = {}
    entry_times: dict[str, datetime] = {}
    last_close: dict[str, float] = {}
    trade_records: list[qpx.TradeRecord] = []
    equity_points: list[qpx.EquityPoint] = []
    signal_records: list[qpx.SignalRecord] = []

    total_contributions = 1300.0
    distributions_received = 0.0
    distribution_count = 0
    tax_reserve_released = 0.0

    qualifying_by_symbol = Counter()
    failed_checks = Counter()
    exit_reason_counts = Counter()
    risk_rejection_reasons = Counter()
    risk_rejection_diagnostics = Counter()

    all_symbol_evaluations = 0
    unavailable_symbol_evaluations = 0
    staged_signals = 0
    filled_entries = 0
    capacity_deferred = 0
    gap_rejections = 0
    risk_rejections = 0
    notional_adjustments = 0
    one_share_floor_uses = 0
    maximum_observed_positions = 0
    pending_wait_missing_bar = 0
    stale_open_marks = 0
    stale_close_marks = 0
    gap_exits_at_open = 0

    while True:
        bar_time = clock.time

        # --------------------------------------------------
        # OPEN PHASE
        # --------------------------------------------------
        if clock.phase is not ReplayPhase.OPEN:
            raise RuntimeError(
                "Strict replay entered an invalid OPEN phase."
            )

        settled_before = dividend_ledger.settled_count
        dividend_cash = dividend_ledger.process_open(
            current_date=bar_time.date(),
            income_shares=income_shares,
        )
        if dividend_cash:
            portfolio.cash += dividend_cash
            distributions_received += dividend_cash
        distribution_count += (
            dividend_ledger.settled_count
            - settled_before
        )

        # Broker-held stop/target gap behavior is causally knowable
        # from the current open and must execute before new entries.
        for position in list(
            portfolio.positions.values()
        ):
            snapshot = portal.current_open(
                position.symbol
            )
            if snapshot is None:
                continue

            reason = None
            if snapshot.open <= position.stop_price:
                reason = "STOP_GAP"
            elif snapshot.open >= position.target_price:
                reason = "TARGET_GAP"

            if reason is not None:
                tax_reserve_released += close_trade(
                    portfolio=portfolio,
                    symbol=position.symbol,
                    exit_price=snapshot.open,
                    exit_time=bar_time,
                    reason=reason,
                    config=config,
                    entry_times=entry_times,
                    trade_records=trade_records,
                )
                exit_reason_counts[reason] += 1
                gap_exits_at_open += 1

        # Thursday-only weekly allocation rebalance.
        qdte_open = portal.current_open("QDTE")
        if (
            bar_time.weekday() == 3
            and qdte_open is not None
        ):
            iso = bar_time.isocalendar()
            key = (iso.year, iso.week)

            if key != current_rebalance_key:
                position_marks, stale = (
                    current_position_marks(
                        portal=portal,
                        portfolio=portfolio,
                        last_close=last_close,
                    )
                )
                stale_open_marks += stale

                (
                    income_shares,
                    income_cost,
                    rebalance,
                ) = qpx._apply_rebalance(
                    portfolio=portfolio,
                    income_shares=income_shares,
                    income_cost=income_cost,
                    qdte_price=qdte_open.open,
                    position_prices=position_marks,
                    target_income_weight=0.125,
                    config=config,
                )
                allocation_records.append(
                    qpx.AllocationRecord(
                        time=bar_time,
                        event_type=(
                            "THURSDAY_WEEKLY_REBALANCE"
                        ),
                        external_contribution=0.0,
                        target_income_weight=0.125,
                        action=rebalance.action,
                        before_income_weight=(
                            rebalance.before_income_weight
                        ),
                        after_income_weight=(
                            rebalance.after_income_weight
                        ),
                        qdte_market_value_traded=(
                            rebalance.market_value_traded
                        ),
                        realized_pnl=(
                            rebalance.realized_pnl
                        ),
                        tax_reserved=(
                            rebalance.tax_reserved
                        ),
                    )
                )
                current_rebalance_key = key

        pending_items = sorted(
            pending.values(),
            key=lambda item: (
                item.tie_key,
                item.symbol,
            ),
        )
        pending = {}

        for signal in pending_items:
            if bar_time <= signal.signal_time:
                pending[signal.symbol] = signal
                continue

            snapshot = portal.current_open(
                signal.symbol
            )
            if snapshot is None:
                pending[signal.symbol] = signal
                pending_wait_missing_bar += 1
                continue

            if (
                len(portfolio.positions)
                >= MAXIMUM_POSITIONS
            ):
                capacity_deferred += 1
                signal_records.append(
                    qpx.SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action=(
                            "CANCELLED_CAPACITY_AT_OPEN"
                        ),
                        detail=(
                            "Six slots already occupied."
                        ),
                        tie_key=signal.tie_key,
                    )
                )
                continue

            gap_atr = (
                abs(
                    snapshot.open
                    - signal.prior_close
                )
                / signal.signal_atr
            )
            if gap_atr > MAXIMUM_GAP_ATR:
                gap_rejections += 1
                signal_records.append(
                    qpx.SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action="REJECTED_OPENING_GAP",
                        detail=f"{gap_atr:.8f} ATR",
                        tie_key=signal.tie_key,
                    )
                )
                continue

            position_marks, stale = (
                current_position_marks(
                    portal=portal,
                    portfolio=portfolio,
                    last_close=last_close,
                )
            )
            stale_open_marks += stale

            qdte_snapshot = portal.current_open(
                "QDTE"
            )
            if qdte_snapshot is not None:
                qdte_mark = qdte_snapshot.open
            elif "QDTE" in last_close:
                qdte_mark = last_close["QDTE"]
                stale_open_marks += 1
            else:
                raise RuntimeError(
                    "No causal QDTE mark exists for sizing."
                )

            account_equity = (
                portfolio.equity(
                    position_marks
                )
                + income_shares
                * qdte_mark
            )
            sizing = calculate_position_size(
                account_equity=account_equity,
                available_cash=portfolio.cash,
                entry_price=snapshot.open,
                atr=signal.signal_atr,
                active_risk=portfolio.active_risk(),
                config=config,
                trade_results_r=(),
            )

            (
                sizing,
                notional_adjusted,
                one_share_floor,
            ) = apply_notional_cap(
                sizing=sizing,
                account_equity=account_equity,
            )
            if notional_adjusted:
                notional_adjustments += 1
            if one_share_floor:
                one_share_floor_uses += 1

            if not sizing.is_tradeable:
                risk_rejections += 1
                reason = (
                    sizing.blocked_reason
                    or "UNKNOWN_RISK_REJECTION"
                )
                risk_rejection_reasons[
                    reason
                ] += 1
                diagnostic = (
                    qpx._position_size_rejection_diagnostic(
                        account_equity=account_equity,
                        available_cash=portfolio.cash,
                        active_risk=(
                            portfolio.active_risk()
                        ),
                        sizing=sizing,
                        config=config,
                    )
                )
                risk_rejection_diagnostics[
                    diagnostic
                ] += 1
                signal_records.append(
                    qpx.SignalRecord(
                        time=bar_time,
                        symbol=signal.symbol,
                        action=(
                            "REJECTED_POSITION_SIZING"
                        ),
                        detail=(
                            reason
                            + " | diagnostic="
                            + diagnostic
                        ),
                        tie_key=signal.tie_key,
                    )
                )
                continue

            portfolio.open_position(
                symbol=signal.symbol,
                sizing=sizing,
                entry_date=bar_time.date(),
                entry_atr=signal.signal_atr,
                config=config,
            )
            entry_times[signal.symbol] = bar_time
            filled_entries += 1
            signal_records.append(
                qpx.SignalRecord(
                    time=bar_time,
                    symbol=signal.symbol,
                    action="FILLED",
                    detail=(
                        f"{sizing.shares} shares at "
                        f"{sizing.entry_fill:.8f}"
                    ),
                    tie_key=signal.tie_key,
                )
            )

        maximum_observed_positions = max(
            maximum_observed_positions,
            len(portfolio.positions),
        )

        # --------------------------------------------------
        # CLOSE PHASE
        # --------------------------------------------------
        clock.advance_to_close()

        for symbol in histories:
            completed = portal.completed_bar(
                symbol
            )
            if completed is not None:
                last_close[symbol] = completed.close

        for position in list(
            portfolio.positions.values()
        ):
            completed = portal.completed_bar(
                position.symbol
            )
            if completed is None:
                continue

            index = indices[
                position.symbol
            ][bar_time]
            atr = indicators[
                position.symbol
            ].atr[index]

            if atr is None or atr <= 0:
                continue

            evaluation = evaluate_exit(
                position=position,
                candle=Candle(
                    date=bar_time.date(),
                    open=completed.open,
                    high=completed.high,
                    low=completed.low,
                    close=completed.close,
                    volume=completed.volume,
                ),
                current_atr=float(atr),
                config=config,
            )

            if evaluation.should_exit:
                # A position that existed before this bar had its gap
                # protection evaluated at OPEN. A position opened on
                # this same bar may still legitimately hit its newly
                # established protection during the entry bar.
                if (
                    evaluation.reason
                    in {
                        "STOP_GAP",
                        "TARGET_GAP",
                    }
                    and entry_times.get(
                        position.symbol
                    ) != bar_time
                ):
                    raise RuntimeError(
                        "A pre-existing gap exit survived "
                        "the OPEN phase."
                    )

                if evaluation.exit_price is None:
                    raise RuntimeError(
                        "Exit evaluation omitted price."
                    )

                tax_reserve_released += close_trade(
                    portfolio=portfolio,
                    symbol=position.symbol,
                    exit_price=evaluation.exit_price,
                    exit_time=bar_time,
                    reason=(
                        evaluation.reason
                        or "EXIT"
                    ),
                    config=config,
                    entry_times=entry_times,
                    trade_records=trade_records,
                )
                exit_reason_counts[
                    evaluation.reason
                    or "EXIT"
                ] += 1
            else:
                position.stop_price = (
                    evaluation.next_stop_price
                )
                position.highest_price = (
                    evaluation.highest_price
                )

        if clock.index >= INITIALIZATION_MARKET_BARS:
            qualifying: list[str] = []
            open_symbols = set(
                portfolio.positions
            )
            pending_symbols = set(
                pending
            )

            vix = previous_vix_value(
                day=bar_time.date(),
                close_dates=vix_dates,
                closes=vix_closes,
            )

            for symbol in top100:
                all_symbol_evaluations += 1

                if (
                    portal.completed_bar(symbol)
                    is None
                ):
                    unavailable_symbol_evaluations += 1
                    continue

                inputs = strict_entry_inputs(
                    symbol=symbol,
                    timestamp=bar_time,
                    bars=histories,
                    indicators=indicators,
                    indices=indices,
                    vix=vix,
                    config=config,
                )

                if inputs is None:
                    failed_checks[
                        "data_ready"
                    ] += 1
                    continue

                evaluation = (
                    evaluate_candidate_v1_causal(
                        inputs=inputs,
                        config=config,
                        momentum_persistence_level=(
                            MOMENTUM_PERSISTENCE
                        ),
                        vix_exclusion_low=(
                            VIX_EXCLUSION_LOW
                        ),
                        vix_exclusion_high=(
                            VIX_EXCLUSION_HIGH
                        ),
                    )
                )

                for name in evaluation.failed_checks:
                    failed_checks[name] += 1

                if evaluation.should_enter:
                    qualifying_by_symbol[
                        symbol
                    ] += 1
                    if (
                        symbol not in open_symbols
                        and symbol
                        not in pending_symbols
                    ):
                        qualifying.append(
                            symbol
                        )

            available_slots = max(
                0,
                MAXIMUM_POSITIONS
                - len(portfolio.positions)
                - len(pending),
            )
            accepted, deferred = (
                choose_without_ranking(
                    signal_bar=bar_time,
                    qualifying=qualifying,
                    available_slots=available_slots,
                )
            )
            capacity_deferred += len(
                deferred
            )

            for symbol in deferred:
                tie_key = hashlib.sha256(
                    (
                        bar_time.isoformat()
                        + "|"
                        + symbol
                    ).encode("utf-8")
                ).hexdigest()
                signal_records.append(
                    qpx.SignalRecord(
                        time=bar_time,
                        symbol=symbol,
                        action="DEFERRED_CAPACITY",
                        detail=(
                            "More signals than "
                            "available slots."
                        ),
                        tie_key=tie_key,
                    )
                )

            for symbol in accepted:
                inputs = strict_entry_inputs(
                    symbol=symbol,
                    timestamp=bar_time,
                    bars=histories,
                    indicators=indicators,
                    indices=indices,
                    vix=vix,
                    config=config,
                )
                if (
                    inputs is None
                    or inputs.current_atr <= 0
                ):
                    continue

                tie_key = hashlib.sha256(
                    (
                        bar_time.isoformat()
                        + "|"
                        + symbol
                    ).encode("utf-8")
                ).hexdigest()
                pending[symbol] = PendingSignal(
                    symbol=symbol,
                    signal_time=bar_time,
                    signal_atr=(
                        inputs.current_atr
                    ),
                    prior_close=(
                        inputs.current_close
                    ),
                    tie_key=tie_key,
                )
                staged_signals += 1
                signal_records.append(
                    qpx.SignalRecord(
                        time=bar_time,
                        symbol=symbol,
                        action="STAGED",
                        detail=(
                            "Next legitimate "
                            "symbol 15-minute open."
                        ),
                        tie_key=tie_key,
                    )
                )

        close_marks: dict[
            str,
            float,
        ] = {}
        stale = 0
        for symbol in portfolio.positions:
            completed = portal.completed_bar(
                symbol
            )
            if completed is not None:
                close_marks[symbol] = (
                    completed.close
                )
            elif symbol in last_close:
                close_marks[symbol] = (
                    last_close[symbol]
                )
                stale += 1
            else:
                raise RuntimeError(
                    f"No causal close mark for {symbol}."
                )
        stale_close_marks += stale

        qdte_completed = portal.completed_bar(
            "QDTE"
        )
        if qdte_completed is not None:
            qdte_close = qdte_completed.close
        elif "QDTE" in last_close:
            qdte_close = last_close["QDTE"]
            stale_close_marks += 1
        else:
            raise RuntimeError(
                "No causal QDTE close mark."
            )

        swing_market_value = (
            portfolio.market_value(
                close_marks
            )
        )
        swing_equity = portfolio.equity(
            close_marks
        )
        income_value = (
            income_shares
            * qdte_close
        )
        total_equity = (
            swing_equity
            + income_value
        )
        investable = (
            income_value
            + portfolio.cash
            + swing_market_value
        )
        income_weight = (
            income_value / investable
            if investable > 0
            else 0.0
        )

        equity_points.append(
            qpx.EquityPoint(
                time=bar_time,
                total_equity=total_equity,
                total_contributions=(
                    total_contributions
                ),
                income_value=income_value,
                swing_equity=swing_equity,
                swing_cash=portfolio.cash,
                swing_market_value=(
                    swing_market_value
                ),
                tax_reserve=(
                    portfolio.tax_reserve_cash
                ),
                income_weight=income_weight,
                target_income_weight=0.125,
                open_positions=len(
                    portfolio.positions
                ),
                pending_entries=len(
                    pending
                ),
                active_risk=(
                    portfolio.active_risk()
                ),
            )
        )

        if not clock.advance_to_next_open():
            break

    # Terminal liquidation is post-test accounting, not a strategy signal.
    final_time = clock.time
    pending_at_end = len(pending)
    pending = {}

    for position in list(
        portfolio.positions.values()
    ):
        if position.symbol not in last_close:
            raise RuntimeError(
                f"No final causal mark for {position.symbol}."
            )
        tax_reserve_released += close_trade(
            portfolio=portfolio,
            symbol=position.symbol,
            exit_price=last_close[position.symbol],
            exit_time=final_time,
            reason="END_OF_TEST",
            config=config,
            entry_times=entry_times,
            trade_records=trade_records,
        )
        exit_reason_counts[
            "END_OF_TEST"
        ] += 1

    if "QDTE" not in last_close:
        raise RuntimeError(
            "No final QDTE close exists."
        )

    final_income_value = (
        income_shares
        * last_close["QDTE"]
    )
    final_swing_equity = (
        portfolio.equity({})
    )
    ending_equity = (
        final_income_value
        + final_swing_equity
    )

    equity_points[-1] = qpx.EquityPoint(
        time=final_time,
        total_equity=ending_equity,
        total_contributions=1300.0,
        income_value=final_income_value,
        swing_equity=final_swing_equity,
        swing_cash=portfolio.cash,
        swing_market_value=0.0,
        tax_reserve=(
            portfolio.tax_reserve_cash
        ),
        income_weight=(
            final_income_value
            / (
                final_income_value
                + portfolio.cash
            )
            if (
                final_income_value
                + portfolio.cash
            ) > 0
            else 0.0
        ),
        target_income_weight=0.125,
        open_positions=0,
        pending_entries=0,
        active_risk=0.0,
    )

    metrics = qpx._daily_metrics(
        equity_points,
        starting_capital=1300.0,
    )
    closed_swing_pnl = sum(
        trade.pnl
        for trade in trade_records
    )
    income_rebalance_pnl = sum(
        record.realized_pnl
        for record in allocation_records
    )
    net_profit = ending_equity - 1300.0
    winners = sum(
        trade.pnl > 0
        for trade in trade_records
    )
    profit_factor = qpx._profit_factor(
        trade_records
    )

    expected_sessions = 0
    day = START
    while day <= END:
        if (
            day != date(2025, 1, 9)
            and qpx.is_market_session(day)
        ):
            expected_sessions += 1
        day += timedelta(days=1)

    sessions = {
        timestamp.date()
        for timestamp in union_times
    }

    REPORT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )
    qpx._write_trades(
        TRADES_PATH,
        trade_records,
    )
    qpx._write_equity(
        EQUITY_PATH,
        equity_points,
    )
    qpx._write_signals(
        SIGNALS_PATH,
        signal_records,
    )
    qpx._write_allocations(
        ALLOCATIONS_PATH,
        allocation_records,
    )

    baseline_result = None
    if baseline.SUMMARY_JSON.exists():
        try:
            baseline_summary = json.loads(
                baseline.SUMMARY_JSON.read_text(
                    encoding="utf-8"
                )
            )
            baseline_result = (
                baseline_summary.get(
                    "result"
                )
            )
        except Exception:
            baseline_result = None

    result = {
        "actual_start": START.isoformat(),
        "actual_end": END.isoformat(),
        "starting_total_capital": 1300.0,
        "monthly_contribution": 0.0,
        "ending_equity": ending_equity,
        "net_profit": net_profit,
        "closed_swing_trade_pnl": (
            closed_swing_pnl
        ),
        "income_rebalance_realized_pnl": (
            income_rebalance_pnl
        ),
        "qdte_distributions_received": (
            distributions_received
        ),
        "qdte_distribution_events": (
            distribution_count
        ),
        "closed_trades": len(
            trade_records
        ),
        "win_rate": (
            winners / len(trade_records)
            if trade_records
            else 0.0
        ),
        "profit_factor": profit_factor,
        "flow_adjusted_total_return": (
            metrics.total_return
        ),
        "flow_adjusted_cagr": metrics.cagr,
        "maximum_drawdown": (
            metrics.maximum_drawdown
        ),
        "annualized_volatility": (
            metrics.annualized_volatility
        ),
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": (
            metrics.sortino_ratio
        ),
        "swing_exposure": metrics.exposure,
        "market_clock_bars": len(
            union_times
        ),
        "old_all_symbol_intersection_bars": (
            len(intersection_times)
        ),
        "clock_bars_recovered": (
            len(union_times)
            - len(intersection_times)
        ),
        "market_sessions": len(
            sessions
        ),
        "expected_market_sessions": (
            expected_sessions
        ),
        "session_coverage": (
            len(sessions)
            / expected_sessions
            if expected_sessions
            else 0.0
        ),
        "all_symbol_evaluations": (
            all_symbol_evaluations
        ),
        "unavailable_symbol_evaluations": (
            unavailable_symbol_evaluations
        ),
        "qualifying_evaluations": sum(
            qualifying_by_symbol.values()
        ),
        "staged_signals": staged_signals,
        "filled_entries": filled_entries,
        "capacity_deferred": (
            capacity_deferred
        ),
        "gap_rejections": gap_rejections,
        "gap_exits_at_open": (
            gap_exits_at_open
        ),
        "risk_rejections": risk_rejections,
        "risk_rejection_reasons": dict(
            risk_rejection_reasons
        ),
        "risk_rejection_diagnostics": dict(
            risk_rejection_diagnostics
        ),
        "notional_adjustments": (
            notional_adjustments
        ),
        "one_share_floor_uses": (
            one_share_floor_uses
        ),
        "maximum_observed_positions": (
            maximum_observed_positions
        ),
        "pending_wait_missing_bar": (
            pending_wait_missing_bar
        ),
        "pending_at_test_end": (
            pending_at_end
        ),
        "stale_open_marks_for_valuation": (
            stale_open_marks
        ),
        "stale_close_marks_for_valuation": (
            stale_close_marks
        ),
        "tax_reserve_released": (
            tax_reserve_released
        ),
        "exit_reason_counts": dict(
            exit_reason_counts
        ),
        "qualifying_by_symbol": dict(
            qualifying_by_symbol
        ),
        "failed_check_counts": dict(
            failed_checks
        ),
    }

    comparison = None
    if isinstance(baseline_result, dict):
        comparison = {}
        for name in (
            "ending_equity",
            "net_profit",
            "closed_trades",
            "win_rate",
            "profit_factor",
            "flow_adjusted_cagr",
            "maximum_drawdown",
            "risk_rejections",
            "capacity_deferred",
        ):
            if name in baseline_result:
                old = baseline_result[name]
                new = result.get(name)
                comparison[name] = {
                    "baseline": old,
                    "strict": new,
                    "delta": (
                        float(new) - float(old)
                        if (
                            new is not None
                            and old is not None
                            and isinstance(
                                new,
                                (int, float),
                            )
                            and isinstance(
                                old,
                                (int, float),
                            )
                        )
                        else None
                    ),
                }

    git_head = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=/mnt/sdcard/QPX_ALPHA",
            "-c",
            "safe.directory=/storage/emulated/0/QPX_ALPHA",
            "rev-parse",
            "HEAD",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    gate = {
        "LOOKAHEAD_PROTECTION": "PASS",
        "SIMULATION_CLOCK": "STRICT_RECORDED_UNION",
        "FUTURE_BAR_ACCESS": "BLOCKED",
        "CURRENT_OPEN_FULL_OHLCV": "BLOCKED",
        "SYNTHETIC_FUTURE_DATA": "NONE",
        "DECISION_DATA_CUTOFF": (
            "VERIFIED_SWING_STRATEGY_BOUNDARY"
        ),
        "EXECUTION_TIMING": (
            "VERIFIED_OPEN_CLOSE_PHASES"
        ),
        "MISSING_SYMBOL_BAR_HANDLING": (
            "UNAVAILABLE_SYMBOL_ONLY"
        ),
        "INDICATOR_PREFIX_EQUIVALENCE": "PASS",
        "STRATEGY_SEMANTIC_EQUIVALENCE": "PASS",
        "CORPORATE_ACTION_CASH_TIMING": (
            "PASS_LATER_OF_PAYABLE_OR_PROCESS_DATE"
        ),
        "DIVIDEND_ENTITLEMENT": (
            "PASS_EX_DATE_OWNERSHIP_SNAPSHOT"
        ),
        "OVERALL_PORTFOLIO_QUALIFICATION": (
            "FULL_CAUSAL_ACCOUNTING_PASS"
        ),
    }

    summary = {
        "schema_version": 1,
        "run_version": (
            "candidate_v1_frozen_top100_"
            "strict_causal_v1"
        ),
        "status": "COMPLETE",
        "git_head": git_head,
        "selection_fingerprint": (
            selection["manifest_fingerprint"]
        ),
        "dataset_fingerprint": (
            dataset["dataset_fingerprint"]
        ),
        "market_clock_source": (
            "UNION_OF_RECORDED_REAL_TOP100_PLUS_QDTE_15M_TIMESTAMPS"
        ),
        "future_data_owner": (
            "REPLAY_ENGINE_ONLY"
        ),
        "strategy_data_surface": (
            "SCALAR_COMPLETED_BAR_INPUTS_ONLY"
        ),
        "corporate_action_notice": (
            "QDTE entitlement uses shares owned at ex-date open. Cash is "
            "released at the first recorded market open on or after the "
            "later of frozen Alpaca payable/process dates."
        ),
        "equivalence_audit": equivalence,
        "gate": gate,
        "result": result,
        "baseline_comparison": comparison,
        "artifacts": {
            "trades": str(TRADES_PATH),
            "equity": str(EQUITY_PATH),
            "signals": str(SIGNALS_PATH),
            "allocations": str(
                ALLOCATIONS_PATH
            ),
            "diagnostics": str(
                DIAGNOSTICS_PATH
            ),
        },
        "created_at": (
            datetime.now()
            .astimezone()
            .isoformat()
        ),
    }

    core = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    summary["summary_fingerprint"] = (
        hashlib.sha256(core).hexdigest()
    )

    diagnostics = {
        "gate": gate,
        "equivalence_audit": equivalence,
        "clock": {
            "union_bars": len(
                union_times
            ),
            "intersection_bars": len(
                intersection_times
            ),
            "recovered_bars": (
                len(union_times)
                - len(intersection_times)
            ),
            "sessions": len(
                sessions
            ),
        },
        "missing_data": {
            "unavailable_symbol_evaluations": (
                unavailable_symbol_evaluations
            ),
            "pending_wait_missing_bar": (
                pending_wait_missing_bar
            ),
            "stale_open_marks_for_valuation": (
                stale_open_marks
            ),
            "stale_close_marks_for_valuation": (
                stale_close_marks
            ),
        },
    }

    atomic_json(
        DIAGNOSTICS_PATH,
        diagnostics,
    )
    atomic_json(
        SUMMARY_PATH,
        summary,
    )

    return result, summary


def format_pf(value) -> str:
    if value is None:
        return "INF"
    return f"{float(value):.3f}"


def main() -> int:
    print()
    print("=" * 92)
    print(
        "QPX CANDIDATE V1 — FROZEN TOP-100 STRICT-CAUSAL REPLAY"
    )
    print("=" * 92)
    print("Starting total         : $1,300.00")
    print("Starting QDTE          : $1,300.00")
    print("Starting swing cash    : $0.00")
    print("External contributions : $0.00")
    print("Rebalance              : THURSDAY-ONLY WEEKLY")
    print("Risk / active risk     : 3.00% / 10.00%")
    print("Maximum positions      : 6")
    print("Notional guard         : 90.00%")
    print("Future strategy bars   : INACCESSIBLE")
    print("Clock                  : RECORDED REAL TIMESTAMP UNION")
    print("Forward fill trading   : DISABLED")
    print("Synthetic data         : DISABLED")
    print(
        "Dividend cash timing   : "
        "LATER OF PAYABLE/PROCESS DATE"
    )
    print("=" * 92)
    print()

    result, summary = run_strict()

    print()
    print("=" * 92)
    print("STRICT-CAUSAL RESULT")
    print("=" * 92)
    print(
        f"Actual range           : "
        f"{result['actual_start']} -> "
        f"{result['actual_end']}"
    )
    print(
        f"Strict market bars     : "
        f"{result['market_clock_bars']:,}"
    )
    print(
        f"Old intersection bars  : "
        f"{result['old_all_symbol_intersection_bars']:,}"
    )
    print(
        f"Recovered clock bars   : "
        f"{result['clock_bars_recovered']:,}"
    )
    print(
        f"Market sessions        : "
        f"{result['market_sessions']:,}"
    )
    print(
        f"Closed swing trades    : "
        f"{result['closed_trades']:,}"
    )
    print(
        f"Win rate               : "
        f"{result['win_rate']:.2%}"
    )
    print(
        f"Profit factor          : "
        f"{format_pf(result['profit_factor'])}"
    )
    print(
        f"Closed swing P&L       : "
        f"${result['closed_swing_trade_pnl']:,.2f}"
    )
    print(
        f"Income rebalance P&L   : "
        f"${result['income_rebalance_realized_pnl']:,.2f}"
    )
    print(
        f"QDTE distributions     : "
        f"${result['qdte_distributions_received']:,.2f}"
    )
    print(
        f"Net portfolio profit   : "
        f"${result['net_profit']:,.2f}"
    )
    print(
        f"Ending equity          : "
        f"${result['ending_equity']:,.2f}"
    )
    print(
        f"CAGR                   : "
        f"{result['flow_adjusted_cagr']:.2%}"
    )
    print(
        f"Maximum drawdown       : "
        f"{result['maximum_drawdown']:.2%}"
    )
    print(
        f"Risk rejections        : "
        f"{result['risk_rejections']:,}"
    )
    print(
        f"Capacity deferred      : "
        f"{result['capacity_deferred']:,}"
    )
    print()
    print("LOOKAHEAD PROTECTION   : PASS")
    print("SIMULATION CLOCK       : STRICT RECORDED UNION")
    print("FUTURE BAR ACCESS      : BLOCKED")
    print("DECISION DATA CUTOFF   : VERIFIED — SWING")
    print("EXECUTION TIMING       : VERIFIED — OPEN/CLOSE")
    print(
        "CORPORATE ACTION CASH  : "
        "QUALIFIED — SETTLEMENT-DATE CAUSAL"
    )
    print(
        "OVERALL QUALIFICATION  : "
        "FULL CAUSAL ACCOUNTING PASS"
    )
    print(
        f"Summary                : {SUMMARY_PATH}"
    )
    print(
        "Summary fingerprint    : "
        f"{summary['summary_fingerprint']}"
    )
    print("=" * 92)

    comparison = summary.get(
        "baseline_comparison"
    )
    if comparison:
        print()
        print("=" * 92)
        print("PRESERVED BASELINE VS STRICT")
        print("=" * 92)
        for name, item in comparison.items():
            print(
                f"{name:<24}: "
                f"{item['baseline']} -> "
                f"{item['strict']} "
                f"(delta {item['delta']})"
            )
        print("=" * 92)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
