#!/usr/bin/env python3
"""Post-run diagnostics for the fixed V16 swing-only research control.

This tool does not rerun or modify the strategy. It reconstructs the
actual V16 trade paths from the same validated local 15-minute caches
and produces exit/expectancy diagnostics.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_NOTIONAL_CAP_REPORT_ROOT,
    DEFAULT_VIX_CACHE,
    FIXED_MINIMUM_COMMON_BARS,
    FIXED_WINDOW_END,
    FIXED_WINDOW_START,
    INCOME_SYMBOL,
    NET_REALIZED_TAX_RESERVE_PROFILE,
    NOTIONAL_CAP_16PCT_PROFILE,
    RELAXED_ENTRY_PROFILE,
    SWING_SYMBOLS,
    VIX_PROVIDER_SYMBOL,
    _aggregate_cache_path,
    _common_times,
    _evaluate_entry_relaxed_frequency,
    _read_cached_bars,
    _read_vix_daily_cache,
    _to_candles,
    _validate_vix_daily_coverage,
    expand_previous_session_vix,
)
from qpx_bot.config import BotConfig
from qpx_bot.indicators import calculate_indicators


DIAGNOSTIC_SCHEMA_VERSION = 1
DIAGNOSTIC_LABEL = "V16_EXIT_DIAGNOSTIC_STUDY_V17"


@dataclass(frozen=True, slots=True)
class TradeDiagnostic:
    symbol: str
    entry_time: datetime
    exit_time: datetime
    shares: int
    entry_price: float
    exit_price: float
    pnl: float
    result_r: float
    exit_reason: str
    signal_time: datetime
    entry_atr: float
    entry_vix: float
    vix_regime: str
    triggers: tuple[str, ...]
    trigger_combo: str
    holding_bars: int
    holding_sessions: int
    conservative_mfe_r: float
    conservative_mae_r: float
    pre_exit_mfe_r: float
    profitable_before_exit_bar: bool
    reached_1r: bool
    reached_2r: bool
    reached_3r: bool


def _atomic_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )
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


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0

    ordered = sorted(float(value) for value in values)
    middle = len(ordered) // 2

    if len(ordered) % 2:
        return ordered[middle]

    return (
        ordered[middle - 1]
        + ordered[middle]
    ) / 2.0


def _profit_factor(
    values: Iterable[float],
) -> float | None:
    items = list(values)
    gross_profit = sum(
        value
        for value in items
        if value > 0
    )
    gross_loss = -sum(
        value
        for value in items
        if value < 0
    )

    if gross_loss <= 0:
        return None if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def _format_pf(value: float | None) -> str:
    return "∞" if value is None else f"{value:.3f}"


def _vix_regime(value: float) -> str:
    if value < 20.0:
        return "LOW_LT_20"
    if value < 24.0:
        return "MODERATE_20_TO_24"
    if value <= 28.0:
        return "ELEVATED_24_TO_28"
    return "HIGH_ALLOWED_GT_28"


def _summary(
    rows: Sequence[TradeDiagnostic],
) -> dict[str, Any]:
    count = len(rows)
    winners = sum(
        row.pnl > 0
        for row in rows
    )
    pnl_values = [
        row.pnl
        for row in rows
    ]
    result_r_values = [
        row.result_r
        for row in rows
    ]
    mfe_values = [
        row.conservative_mfe_r
        for row in rows
    ]
    mae_values = [
        row.conservative_mae_r
        for row in rows
    ]
    hold_values = [
        float(row.holding_bars)
        for row in rows
    ]

    return {
        "trades": count,
        "wins": winners,
        "losses": (
            sum(row.pnl < 0 for row in rows)
        ),
        "win_rate": (
            winners / count
            if count
            else 0.0
        ),
        "net_pnl": sum(pnl_values),
        "profit_factor": _profit_factor(
            pnl_values
        ),
        "average_result_r": (
            sum(result_r_values) / count
            if count
            else 0.0
        ),
        "median_result_r": (
            _median(result_r_values)
        ),
        "average_mfe_r": (
            sum(mfe_values) / count
            if count
            else 0.0
        ),
        "median_mfe_r": (
            _median(mfe_values)
        ),
        "average_mae_r": (
            sum(mae_values) / count
            if count
            else 0.0
        ),
        "median_mae_r": (
            _median(mae_values)
        ),
        "average_holding_bars": (
            sum(hold_values) / count
            if count
            else 0.0
        ),
        "median_holding_bars": (
            _median(hold_values)
        ),
    }


def _group_summary(
    rows: Sequence[TradeDiagnostic],
    key,
) -> dict[str, dict[str, Any]]:
    grouped: dict[
        str,
        list[TradeDiagnostic],
    ] = defaultdict(list)

    for row in rows:
        grouped[str(key(row))].append(row)

    return {
        name: _summary(group)
        for name, group
        in sorted(grouped.items())
    }


def _trigger_summary(
    rows: Sequence[TradeDiagnostic],
) -> dict[str, dict[str, Any]]:
    grouped: dict[
        str,
        list[TradeDiagnostic],
    ] = defaultdict(list)

    for row in rows:
        for trigger in row.triggers:
            grouped[trigger].append(row)

    return {
        name: _summary(group)
        for name, group
        in sorted(grouped.items())
    }


def _latest_v16_run(
    report_root: Path,
) -> tuple[Path, Mapping[str, Any]]:
    if not report_root.exists():
        raise RuntimeError(
            f"V16 report root is missing: {report_root}"
        )

    candidates: list[
        tuple[str, Path, Mapping[str, Any]]
    ] = []

    for directory in report_root.iterdir():
        if not directory.is_dir():
            continue

        result_path = (
            directory
            / "swing_only_control_result.json"
        )
        trades_path = (
            directory
            / "swing_only_control_trades.csv"
        )

        if (
            not result_path.exists()
            or not trades_path.exists()
        ):
            continue

        payload = json.loads(
            result_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            payload.get("notional_profile")
            != NOTIONAL_CAP_16PCT_PROFILE
            or payload.get("entry_profile")
            != RELAXED_ENTRY_PROFILE
            or payload.get("tax_reserve_profile")
            != NET_REALIZED_TAX_RESERVE_PROFILE
            or bool(payload.get("kelly_enabled"))
        ):
            continue

        candidates.append(
            (
                directory.name,
                directory,
                payload,
            )
        )

    if not candidates:
        raise RuntimeError(
            "No completed V16 16%-notional run "
            "was found under the expected report root."
        )

    _, directory, payload = max(
        candidates,
        key=lambda item: item[0],
    )
    return directory, payload


def _read_trades(
    path: Path,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    with path.open(
        "r",
        newline="",
        encoding="utf-8",
    ) as file:
        reader = csv.DictReader(file)

        for raw in reader:
            rows.append(
                {
                    "symbol": raw["Symbol"],
                    "entry_time": (
                        datetime.fromisoformat(
                            raw[
                                "EntryTimestampMarket"
                            ]
                        )
                    ),
                    "exit_time": (
                        datetime.fromisoformat(
                            raw[
                                "ExitTimestampMarket"
                            ]
                        )
                    ),
                    "shares": int(
                        raw["Shares"]
                    ),
                    "entry_price": float(
                        raw["EntryPrice"]
                    ),
                    "exit_price": float(
                        raw["ExitPrice"]
                    ),
                    "pnl": float(
                        raw["PnL"]
                    ),
                    "result_r": float(
                        raw["ResultR"]
                    ),
                    "exit_reason": raw[
                        "ExitReason"
                    ],
                }
            )

    return rows


def _load_reconstruction_context(
    result: Mapping[str, Any],
):
    start = date.fromisoformat(
        str(result["actual_start"])
    )
    end = date.fromisoformat(
        str(result["actual_end"])
    )

    if (
        start != FIXED_WINDOW_START
        or end != FIXED_WINDOW_END
    ):
        raise RuntimeError(
            "The located run does not use the "
            "fixed V16 historical window."
        )

    histories = {}

    for symbol in (
        *SWING_SYMBOLS,
        INCOME_SYMBOL,
    ):
        cache_path = (
            _aggregate_cache_path(symbol)
        )

        if not cache_path.exists():
            raise RuntimeError(
                f"Missing local aggregate cache: {cache_path}"
            )

        bars = [
            bar
            for bar in _read_cached_bars(
                cache_path
            )
            if start
            <= bar.start.date()
            <= end
        ]

        if not bars:
            raise RuntimeError(
                f"No fixed-window bars for {symbol}."
            )

        histories[symbol] = bars

    closes = _validate_vix_daily_coverage(
        closes=_read_vix_daily_cache(
            DEFAULT_VIX_CACHE
        ),
        start=start,
        end=end,
    )
    histories["^VIX"] = (
        expand_previous_session_vix(
            reference_bars=histories["SPY"],
            closes=closes,
            minimum_bars=(
                FIXED_MINIMUM_COMMON_BARS
            ),
        )
    )

    test_times = [
        value
        for value in _common_times(
            histories
        )
        if start
        <= value.date()
        <= end
    ]

    expected_bars = int(
        result["common_test_bars"]
    )
    expected_sessions = int(
        result["test_sessions"]
    )
    sessions = {
        value.date()
        for value in test_times
    }

    if len(test_times) != expected_bars:
        raise RuntimeError(
            "Reconstructed common-bar count differs "
            f"from V16: {len(test_times)} != {expected_bars}."
        )

    if len(sessions) != expected_sessions:
        raise RuntimeError(
            "Reconstructed session count differs "
            f"from V16: {len(sessions)} != {expected_sessions}."
        )

    maps = {
        symbol: {
            bar.start: bar
            for bar in bars
        }
        for symbol, bars
        in histories.items()
    }
    candles = {
        symbol: _to_candles(
            histories[symbol]
        )
        for symbol in SWING_SYMBOLS
    }
    config = BotConfig()
    config = __import__(
        "dataclasses"
    ).replace(
        config,
        minimum_average_daily_volume=75_000,
        breakout_volume_multiplier=1.05,
        breakout_lookback=10,
        maximum_vix_for_entries=32.0,
        rsi_overbought=75.0,
    )
    config.validate()
    indicators = {
        symbol: calculate_indicators(
            candles[symbol],
            config,
        )
        for symbol in SWING_SYMBOLS
    }
    indices = {
        symbol: {
            bar.start: index
            for index, bar
            in enumerate(
                histories[symbol]
            )
        }
        for symbol in SWING_SYMBOLS
    }
    time_index = {
        value: index
        for index, value
        in enumerate(test_times)
    }

    return (
        config,
        histories,
        maps,
        indicators,
        indices,
        test_times,
        time_index,
    )


def _diagnose_trade(
    raw: Mapping[str, Any],
    *,
    config: BotConfig,
    maps,
    indicators,
    indices,
    test_times,
    time_index,
) -> TradeDiagnostic:
    symbol = str(raw["symbol"])
    entry_time = raw["entry_time"]
    exit_time = raw["exit_time"]

    if entry_time not in time_index:
        raise RuntimeError(
            f"Entry time is not common: {entry_time}"
        )

    if exit_time not in time_index:
        raise RuntimeError(
            f"Exit time is not common: {exit_time}"
        )

    entry_common_index = (
        time_index[entry_time]
    )
    exit_common_index = (
        time_index[exit_time]
    )

    if entry_common_index < 1:
        raise RuntimeError(
            "Trade entry has no preceding signal bar."
        )

    if exit_common_index < entry_common_index:
        raise RuntimeError(
            "Trade exit precedes entry."
        )

    signal_time = test_times[
        entry_common_index - 1
    ]
    signal_symbol_index = (
        indices[symbol][signal_time]
    )
    entry_atr = indicators[
        symbol
    ].atr[signal_symbol_index]

    if entry_atr is None or entry_atr <= 0:
        raise RuntimeError(
            f"Missing signal ATR for {symbol} "
            f"at {signal_time}."
        )

    entry_vix = maps[
        "^VIX"
    ][signal_time].close
    evaluation = (
        _evaluate_entry_relaxed_frequency(
            candles=_to_candles(
                [
                    maps[symbol][time]
                    for time in sorted(
                        maps[symbol]
                    )
                ]
            ),
            indicators=indicators[symbol],
            index=signal_symbol_index,
            vix=entry_vix,
            config=config,
        )
    )

    if not evaluation.should_enter:
        raise RuntimeError(
            "Entry reconstruction mismatch for "
            f"{symbol} at {signal_time}."
        )

    risk_per_share = (
        float(entry_atr)
        * config.stop_atr_multiple
    )
    entry_price = float(
        raw["entry_price"]
    )
    exit_price = float(
        raw["exit_price"]
    )
    exit_reason = str(
        raw["exit_reason"]
    )

    path_times = test_times[
        entry_common_index:
        exit_common_index + 1
    ]
    prior_times = path_times[:-1]

    favorable_price = entry_price
    adverse_price = entry_price
    pre_exit_favorable_price = (
        entry_price
    )

    for value in prior_times:
        bar = maps[symbol][value]
        favorable_price = max(
            favorable_price,
            bar.high,
        )
        adverse_price = min(
            adverse_price,
            bar.low,
        )
        pre_exit_favorable_price = max(
            pre_exit_favorable_price,
            bar.high,
        )

    exit_bar = maps[symbol][exit_time]

    if exit_reason == "END_OF_TEST":
        favorable_price = max(
            favorable_price,
            exit_bar.high,
        )
        adverse_price = min(
            adverse_price,
            exit_bar.low,
        )
    elif exit_reason == "ATR_TARGET":
        favorable_price = max(
            favorable_price,
            entry_price
            + (
                float(entry_atr)
                * config.target_atr_multiple
            ),
        )
    elif exit_reason == "TARGET_GAP":
        favorable_price = max(
            favorable_price,
            exit_bar.open,
        )
    elif exit_reason == "STOP_GAP":
        adverse_price = min(
            adverse_price,
            exit_bar.open,
        )
    elif exit_reason == "ATR_STOP":
        if config.slippage_rate >= 1:
            raise RuntimeError(
                "Invalid slippage rate."
            )
        stop_trigger = (
            exit_price
            / (
                1.0
                - config.slippage_rate
            )
        )
        adverse_price = min(
            adverse_price,
            stop_trigger,
        )
    else:
        # Unknown exit reasons use only the observed fill endpoint,
        # not the full exit-bar high/low, to avoid post-exit lookahead.
        favorable_price = max(
            favorable_price,
            exit_price,
        )
        adverse_price = min(
            adverse_price,
            exit_price,
        )

    conservative_mfe_r = max(
        0.0,
        (
            favorable_price
            - entry_price
        )
        / risk_per_share,
    )
    conservative_mae_r = max(
        0.0,
        (
            entry_price
            - adverse_price
        )
        / risk_per_share,
    )
    pre_exit_mfe_r = max(
        0.0,
        (
            pre_exit_favorable_price
            - entry_price
        )
        / risk_per_share,
    )

    # A prior bar is counted as actually profitable only if a sell at
    # that high could clear the configured sell-side slippage.
    break_even_market_price = (
        entry_price
        / (
            1.0
            - config.slippage_rate
        )
    )
    profitable_before_exit_bar = (
        float(raw["pnl"]) < 0
        and pre_exit_favorable_price
        >= break_even_market_price
    )

    holding_sessions = len(
        {
            value.date()
            for value in path_times
        }
    )
    triggers = tuple(
        evaluation.triggers
    )
    trigger_combo = (
        "+".join(sorted(triggers))
        if triggers
        else "NONE"
    )

    return TradeDiagnostic(
        symbol=symbol,
        entry_time=entry_time,
        exit_time=exit_time,
        shares=int(raw["shares"]),
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=float(raw["pnl"]),
        result_r=float(raw["result_r"]),
        exit_reason=exit_reason,
        signal_time=signal_time,
        entry_atr=float(entry_atr),
        entry_vix=float(entry_vix),
        vix_regime=_vix_regime(
            float(entry_vix)
        ),
        triggers=triggers,
        trigger_combo=trigger_combo,
        holding_bars=len(path_times),
        holding_sessions=holding_sessions,
        conservative_mfe_r=(
            conservative_mfe_r
        ),
        conservative_mae_r=(
            conservative_mae_r
        ),
        pre_exit_mfe_r=pre_exit_mfe_r,
        profitable_before_exit_bar=(
            profitable_before_exit_bar
        ),
        reached_1r=(
            conservative_mfe_r >= 1.0
        ),
        reached_2r=(
            conservative_mfe_r >= 2.0
        ),
        reached_3r=(
            conservative_mfe_r >= 3.0
        ),
    )


def _write_detail_csv(
    path: Path,
    rows: Sequence[TradeDiagnostic],
) -> None:
    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Symbol",
                "SignalTimestampMarket",
                "EntryTimestampMarket",
                "ExitTimestampMarket",
                "Shares",
                "EntryPrice",
                "ExitPrice",
                "PnL",
                "ResultR",
                "ExitReason",
                "EntryATR",
                "EntryVIX",
                "VIXRegime",
                "Triggers",
                "TriggerCombo",
                "HoldingBars",
                "HoldingSessions",
                "ConservativeMFER",
                "ConservativeMAER",
                "PreExitMFER",
                "ProfitableBeforeExitBar",
                "Reached1R",
                "Reached2R",
                "Reached3R",
            )
        )

        for row in rows:
            writer.writerow(
                (
                    row.symbol,
                    row.signal_time.isoformat(),
                    row.entry_time.isoformat(),
                    row.exit_time.isoformat(),
                    row.shares,
                    f"{row.entry_price:.8f}",
                    f"{row.exit_price:.8f}",
                    f"{row.pnl:.8f}",
                    f"{row.result_r:.8f}",
                    row.exit_reason,
                    f"{row.entry_atr:.8f}",
                    f"{row.entry_vix:.8f}",
                    row.vix_regime,
                    "|".join(row.triggers),
                    row.trigger_combo,
                    row.holding_bars,
                    row.holding_sessions,
                    f"{row.conservative_mfe_r:.8f}",
                    f"{row.conservative_mae_r:.8f}",
                    f"{row.pre_exit_mfe_r:.8f}",
                    int(
                        row.profitable_before_exit_bar
                    ),
                    int(row.reached_1r),
                    int(row.reached_2r),
                    int(row.reached_3r),
                )
            )


def _format_group(
    title: str,
    groups: Mapping[
        str,
        Mapping[str, Any],
    ],
) -> list[str]:
    lines = [title]

    for name, summary in groups.items():
        lines.append(
            "  "
            f"{name:<32} "
            f"n={summary['trades']:>4} "
            f"win={summary['win_rate']:.1%} "
            f"PF={_format_pf(summary['profit_factor']):>6} "
            f"net=${summary['net_pnl']:>9,.2f} "
            f"avgR={summary['average_result_r']:>7.3f} "
            f"MFE={summary['average_mfe_r']:>6.3f}R "
            f"MAE={summary['average_mae_r']:>6.3f}R "
            f"hold={summary['average_holding_bars']:>6.1f} bars"
        )

    return lines


def _build_report(
    *,
    source_directory: Path,
    result: Mapping[str, Any],
    rows: Sequence[TradeDiagnostic],
    payload: Mapping[str, Any],
) -> str:
    winners = [
        row
        for row in rows
        if row.pnl > 0
    ]
    losers = [
        row
        for row in rows
        if row.pnl < 0
    ]
    profitable_losers = [
        row
        for row in losers
        if row.profitable_before_exit_bar
    ]

    lines = [
        "=" * 100,
        (
            "QPX V17 — V16 EXIT / EXPECTANCY DIAGNOSTIC STUDY "
            "(NO STRATEGY CHANGES)"
        ),
        "=" * 100,
        f"Source V16 run             : {source_directory}",
        (
            "Historical window          : "
            f"{result['actual_start']} to {result['actual_end']}"
        ),
        (
            "Common bars / sessions     : "
            f"{result['common_test_bars']} / "
            f"{result['test_sessions']}"
        ),
        (
            "Entry / risk / notional    : "
            f"{result['entry_profile']} / "
            f"{result['risk_profile']} / "
            f"{result['notional_profile']}"
        ),
        "Strategy rerun               : NO",
        "Entry/exit rule changes      : NONE",
        "Market-data download         : NONE",
        "",
        "OVERALL",
        (
            f"  Closed trades             : {len(rows)}"
        ),
        (
            f"  Winners / losers          : "
            f"{len(winners)} / {len(losers)}"
        ),
        (
            "  Win rate                  : "
            f"{payload['overall']['win_rate']:.2%}"
        ),
        (
            "  Net realized P&L          : "
            f"${payload['overall']['net_pnl']:,.2f}"
        ),
        (
            "  Profit factor             : "
            f"{_format_pf(payload['overall']['profit_factor'])}"
        ),
        (
            "  Average / median R        : "
            f"{payload['overall']['average_result_r']:.3f} / "
            f"{payload['overall']['median_result_r']:.3f}"
        ),
        (
            "  Avg / median conservative MFE : "
            f"{payload['overall']['average_mfe_r']:.3f}R / "
            f"{payload['overall']['median_mfe_r']:.3f}R"
        ),
        (
            "  Avg / median conservative MAE : "
            f"{payload['overall']['average_mae_r']:.3f}R / "
            f"{payload['overall']['median_mae_r']:.3f}R"
        ),
        (
            "  Avg / median holding bars : "
            f"{payload['overall']['average_holding_bars']:.1f} / "
            f"{payload['overall']['median_holding_bars']:.1f}"
        ),
        "",
        "EXCURSION / REVERSAL",
        (
            "  All trades reaching +1R   : "
            f"{payload['all_reached_1r']} "
            f"({payload['all_reached_1r'] / len(rows):.2%})"
        ),
        (
            "  All trades reaching +2R   : "
            f"{payload['all_reached_2r']} "
            f"({payload['all_reached_2r'] / len(rows):.2%})"
        ),
        (
            "  All trades reaching +3R   : "
            f"{payload['all_reached_3r']} "
            f"({payload['all_reached_3r'] / len(rows):.2%})"
        ),
        (
            "  Winners reaching +1R      : "
            f"{payload['winner_reached_1r']} / {len(winners)} "
            f"({(payload['winner_reached_1r'] / len(winners)) if winners else 0.0:.2%})"
        ),
        (
            "  Winners reaching +2R      : "
            f"{payload['winner_reached_2r']} / {len(winners)} "
            f"({(payload['winner_reached_2r'] / len(winners)) if winners else 0.0:.2%})"
        ),
        (
            "  Winners reaching +3R      : "
            f"{payload['winner_reached_3r']} / {len(winners)} "
            f"({(payload['winner_reached_3r'] / len(winners)) if winners else 0.0:.2%})"
        ),
        (
            "  Losing trades profitable before exit bar: "
            f"{len(profitable_losers)} / {len(losers)} "
            f"({(len(profitable_losers) / len(losers)) if losers else 0.0:.2%})"
        ),
        (
            "  Losers that had reached +1R: "
            f"{payload['loser_reached_1r']} / {len(losers)} "
            f"({(payload['loser_reached_1r'] / len(losers)) if losers else 0.0:.2%})"
        ),
        "",
        (
            "MFE/MAE methodology: conservative. Full OHLC is used only "
            "for bars completed before the exit bar. On stop/target exit "
            "bars, the known trigger/open is used rather than the full "
            "post-exit high/low, avoiding post-exit lookahead."
        ),
        (
            "Profitable-before-exit-bar requires a prior completed bar "
            "high high enough to clear configured sell-side slippage."
        ),
        "",
    ]
    lines.extend(
        _format_group(
            "BY EXIT REASON",
            payload["by_exit_reason"],
        )
    )
    lines.append("")
    lines.extend(
        _format_group(
            "BY SYMBOL",
            payload["by_symbol"],
        )
    )
    lines.append("")
    lines.extend(
        _format_group(
            "BY ENTRY VIX REGIME",
            payload["by_vix_regime"],
        )
    )
    lines.append("")
    lines.extend(
        _format_group(
            "BY ENTRY TRIGGER (COUNTS OVERLAP)",
            payload["by_trigger"],
        )
    )
    lines.append("")
    lines.extend(
        _format_group(
            "BY TRIGGER COMBINATION",
            payload["by_trigger_combo"],
        )
    )
    lines.extend(
        (
            "",
            "INTERPRETATION GUARDRAILS",
            (
                "  This is an in-sample diagnostic of the already-tested "
                "V16 window, not independent validation."
            ),
            (
                "  No stop, target, trailing, entry, sizing, allocation, "
                "or market-data rule was changed by V17."
            ),
            (
                "  Use these diagnostics to choose a small number of "
                "explicit exit hypotheses, then validate those hypotheses "
                "on a separate/frozen period."
            ),
            "=" * 100,
        )
    )
    return "\n".join(lines)


def run_diagnostics(
    *,
    report_root: str | Path = (
        DEFAULT_NOTIONAL_CAP_REPORT_ROOT
    ),
) -> tuple[
    Path,
    Path,
    Path,
]:
    report_root_path = (
        Path(report_root)
        .expanduser()
        .resolve()
    )
    source_directory, result = (
        _latest_v16_run(
            report_root_path
        )
    )
    trades_path = (
        source_directory
        / "swing_only_control_trades.csv"
    )
    raw_trades = _read_trades(
        trades_path
    )

    if len(raw_trades) != int(
        result["closed_trades"]
    ):
        raise RuntimeError(
            "V16 trade CSV count differs from result JSON."
        )

    (
        config,
        histories,
        maps,
        indicators,
        indices,
        test_times,
        time_index,
    ) = _load_reconstruction_context(
        result
    )

    rows = [
        _diagnose_trade(
            raw,
            config=config,
            maps=maps,
            indicators=indicators,
            indices=indices,
            test_times=test_times,
            time_index=time_index,
        )
        for raw in raw_trades
    ]

    if len(rows) != len(raw_trades):
        raise RuntimeError(
            "Diagnostic row count mismatch."
        )

    overall = _summary(rows)
    winners = [
        row
        for row in rows
        if row.pnl > 0
    ]
    losers = [
        row
        for row in rows
        if row.pnl < 0
    ]

    payload = {
        "schema_version": (
            DIAGNOSTIC_SCHEMA_VERSION
        ),
        "diagnostic_label": (
            DIAGNOSTIC_LABEL
        ),
        "source_v16_directory": str(
            source_directory
        ),
        "source_result": dict(result),
        "strategy_rerun": False,
        "strategy_rule_changes": False,
        "market_data_download": False,
        "conservative_exit_bar_method": True,
        "overall": overall,
        "all_reached_1r": sum(
            row.reached_1r
            for row in rows
        ),
        "all_reached_2r": sum(
            row.reached_2r
            for row in rows
        ),
        "all_reached_3r": sum(
            row.reached_3r
            for row in rows
        ),
        "winner_reached_1r": sum(
            row.reached_1r
            for row in winners
        ),
        "winner_reached_2r": sum(
            row.reached_2r
            for row in winners
        ),
        "winner_reached_3r": sum(
            row.reached_3r
            for row in winners
        ),
        "loser_reached_1r": sum(
            row.reached_1r
            for row in losers
        ),
        "losers_profitable_before_exit_bar": (
            sum(
                row.profitable_before_exit_bar
                for row in losers
            )
        ),
        "by_exit_reason": _group_summary(
            rows,
            lambda row: row.exit_reason,
        ),
        "by_symbol": _group_summary(
            rows,
            lambda row: row.symbol,
        ),
        "by_vix_regime": _group_summary(
            rows,
            lambda row: row.vix_regime,
        ),
        "by_trigger": _trigger_summary(
            rows
        ),
        "by_trigger_combo": _group_summary(
            rows,
            lambda row: row.trigger_combo,
        ),
        "exit_reason_counts": dict(
            Counter(
                row.exit_reason
                for row in rows
            )
        ),
        "vix_regime_counts": dict(
            Counter(
                row.vix_regime
                for row in rows
            )
        ),
        "trigger_combo_counts": dict(
            Counter(
                row.trigger_combo
                for row in rows
            )
        ),
    }

    text = _build_report(
        source_directory=source_directory,
        result=result,
        rows=rows,
        payload=payload,
    )

    text_path = (
        source_directory
        / "v17_exit_diagnostics_report.txt"
    )
    json_path = (
        source_directory
        / "v17_exit_diagnostics.json"
    )
    csv_path = (
        source_directory
        / "v17_exit_diagnostics_trades.csv"
    )

    text_path.write_text(
        text + "\n",
        encoding="utf-8",
    )
    _atomic_json(
        json_path,
        payload,
    )
    _write_detail_csv(
        csv_path,
        rows,
    )

    print(text)
    print("-" * 100)
    print("Diagnostic artifacts:")
    print(f"  report : {text_path}")
    print(f"  json   : {json_path}")
    print(f"  trades : {csv_path}")
    print()
    print(
        "QPX V16 EXIT DIAGNOSTIC STUDY V17: COMPLETE"
    )
    return (
        text_path,
        json_path,
        csv_path,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze the latest completed V16 16%-notional "
            "swing-control run without rerunning the strategy."
        )
    )
    parser.add_argument(
        "--report-root",
        default=str(
            DEFAULT_NOTIONAL_CAP_REPORT_ROOT
        ),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    run_diagnostics(
        report_root=args.report_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
