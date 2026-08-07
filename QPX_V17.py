#!/usr/bin/env python3
"""Install, test, push, and run the V17 V16 exit-diagnostic study."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


EXPECTED_BASE_COMMIT = (
    "dff1f06e964da8247846f2d931556402ce3ac4d9"
)


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (start, *start.parents):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP = (
    ROOT
    / "backups"
    / "qpx_v16_exit_diagnostics_v17"
    / STAMP
)
FILES = {
    'QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py': '\n#!/usr/bin/env python3\n"""Post-run diagnostics for the fixed V16 swing-only research control.\n\nThis tool does not rerun or modify the strategy. It reconstructs the\nactual V16 trade paths from the same validated local 15-minute caches\nand produces exit/expectancy diagnostics.\n"""\n\nfrom __future__ import annotations\n\nimport argparse\nimport csv\nimport json\nfrom collections import Counter, defaultdict\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime\nfrom pathlib import Path\nfrom typing import Any, Iterable, Mapping, Sequence\n\nfrom qpx_bot.actual_two_year_15m_six import (\n    DEFAULT_NOTIONAL_CAP_REPORT_ROOT,\n    DEFAULT_VIX_CACHE,\n    FIXED_MINIMUM_COMMON_BARS,\n    FIXED_WINDOW_END,\n    FIXED_WINDOW_START,\n    INCOME_SYMBOL,\n    NET_REALIZED_TAX_RESERVE_PROFILE,\n    NOTIONAL_CAP_16PCT_PROFILE,\n    RELAXED_ENTRY_PROFILE,\n    SWING_SYMBOLS,\n    VIX_PROVIDER_SYMBOL,\n    _aggregate_cache_path,\n    _common_times,\n    _evaluate_entry_relaxed_frequency,\n    _read_cached_bars,\n    _read_vix_daily_cache,\n    _to_candles,\n    _validate_vix_daily_coverage,\n    expand_previous_session_vix,\n)\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.indicators import calculate_indicators\n\n\nDIAGNOSTIC_SCHEMA_VERSION = 1\nDIAGNOSTIC_LABEL = "V16_EXIT_DIAGNOSTIC_STUDY_V17"\n\n\n@dataclass(frozen=True, slots=True)\nclass TradeDiagnostic:\n    symbol: str\n    entry_time: datetime\n    exit_time: datetime\n    shares: int\n    entry_price: float\n    exit_price: float\n    pnl: float\n    result_r: float\n    exit_reason: str\n    signal_time: datetime\n    entry_atr: float\n    entry_vix: float\n    vix_regime: str\n    triggers: tuple[str, ...]\n    trigger_combo: str\n    holding_bars: int\n    holding_sessions: int\n    conservative_mfe_r: float\n    conservative_mae_r: float\n    pre_exit_mfe_r: float\n    profitable_before_exit_bar: bool\n    reached_1r: bool\n    reached_2r: bool\n    reached_3r: bool\n\n\ndef _atomic_json(\n    path: Path,\n    payload: Mapping[str, Any],\n) -> None:\n    temporary = path.with_suffix(\n        path.suffix + ".tmp"\n    )\n    temporary.write_text(\n        json.dumps(\n            payload,\n            indent=2,\n            sort_keys=True,\n            allow_nan=False,\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n\n\ndef _median(values: Sequence[float]) -> float:\n    if not values:\n        return 0.0\n\n    ordered = sorted(float(value) for value in values)\n    middle = len(ordered) // 2\n\n    if len(ordered) % 2:\n        return ordered[middle]\n\n    return (\n        ordered[middle - 1]\n        + ordered[middle]\n    ) / 2.0\n\n\ndef _profit_factor(\n    values: Iterable[float],\n) -> float | None:\n    items = list(values)\n    gross_profit = sum(\n        value\n        for value in items\n        if value > 0\n    )\n    gross_loss = -sum(\n        value\n        for value in items\n        if value < 0\n    )\n\n    if gross_loss <= 0:\n        return None if gross_profit > 0 else 0.0\n\n    return gross_profit / gross_loss\n\n\ndef _format_pf(value: float | None) -> str:\n    return "∞" if value is None else f"{value:.3f}"\n\n\ndef _vix_regime(value: float) -> str:\n    if value < 20.0:\n        return "LOW_LT_20"\n    if value < 24.0:\n        return "MODERATE_20_TO_24"\n    if value <= 28.0:\n        return "ELEVATED_24_TO_28"\n    return "HIGH_ALLOWED_GT_28"\n\n\ndef _summary(\n    rows: Sequence[TradeDiagnostic],\n) -> dict[str, Any]:\n    count = len(rows)\n    winners = sum(\n        row.pnl > 0\n        for row in rows\n    )\n    pnl_values = [\n        row.pnl\n        for row in rows\n    ]\n    result_r_values = [\n        row.result_r\n        for row in rows\n    ]\n    mfe_values = [\n        row.conservative_mfe_r\n        for row in rows\n    ]\n    mae_values = [\n        row.conservative_mae_r\n        for row in rows\n    ]\n    hold_values = [\n        float(row.holding_bars)\n        for row in rows\n    ]\n\n    return {\n        "trades": count,\n        "wins": winners,\n        "losses": (\n            sum(row.pnl < 0 for row in rows)\n        ),\n        "win_rate": (\n            winners / count\n            if count\n            else 0.0\n        ),\n        "net_pnl": sum(pnl_values),\n        "profit_factor": _profit_factor(\n            pnl_values\n        ),\n        "average_result_r": (\n            sum(result_r_values) / count\n            if count\n            else 0.0\n        ),\n        "median_result_r": (\n            _median(result_r_values)\n        ),\n        "average_mfe_r": (\n            sum(mfe_values) / count\n            if count\n            else 0.0\n        ),\n        "median_mfe_r": (\n            _median(mfe_values)\n        ),\n        "average_mae_r": (\n            sum(mae_values) / count\n            if count\n            else 0.0\n        ),\n        "median_mae_r": (\n            _median(mae_values)\n        ),\n        "average_holding_bars": (\n            sum(hold_values) / count\n            if count\n            else 0.0\n        ),\n        "median_holding_bars": (\n            _median(hold_values)\n        ),\n    }\n\n\ndef _group_summary(\n    rows: Sequence[TradeDiagnostic],\n    key,\n) -> dict[str, dict[str, Any]]:\n    grouped: dict[\n        str,\n        list[TradeDiagnostic],\n    ] = defaultdict(list)\n\n    for row in rows:\n        grouped[str(key(row))].append(row)\n\n    return {\n        name: _summary(group)\n        for name, group\n        in sorted(grouped.items())\n    }\n\n\ndef _trigger_summary(\n    rows: Sequence[TradeDiagnostic],\n) -> dict[str, dict[str, Any]]:\n    grouped: dict[\n        str,\n        list[TradeDiagnostic],\n    ] = defaultdict(list)\n\n    for row in rows:\n        for trigger in row.triggers:\n            grouped[trigger].append(row)\n\n    return {\n        name: _summary(group)\n        for name, group\n        in sorted(grouped.items())\n    }\n\n\ndef _latest_v16_run(\n    report_root: Path,\n) -> tuple[Path, Mapping[str, Any]]:\n    if not report_root.exists():\n        raise RuntimeError(\n            f"V16 report root is missing: {report_root}"\n        )\n\n    candidates: list[\n        tuple[str, Path, Mapping[str, Any]]\n    ] = []\n\n    for directory in report_root.iterdir():\n        if not directory.is_dir():\n            continue\n\n        result_path = (\n            directory\n            / "swing_only_control_result.json"\n        )\n        trades_path = (\n            directory\n            / "swing_only_control_trades.csv"\n        )\n\n        if (\n            not result_path.exists()\n            or not trades_path.exists()\n        ):\n            continue\n\n        payload = json.loads(\n            result_path.read_text(\n                encoding="utf-8"\n            )\n        )\n\n        if (\n            payload.get("notional_profile")\n            != NOTIONAL_CAP_16PCT_PROFILE\n            or payload.get("entry_profile")\n            != RELAXED_ENTRY_PROFILE\n            or payload.get("tax_reserve_profile")\n            != NET_REALIZED_TAX_RESERVE_PROFILE\n            or bool(payload.get("kelly_enabled"))\n        ):\n            continue\n\n        candidates.append(\n            (\n                directory.name,\n                directory,\n                payload,\n            )\n        )\n\n    if not candidates:\n        raise RuntimeError(\n            "No completed V16 16%-notional run "\n            "was found under the expected report root."\n        )\n\n    _, directory, payload = max(\n        candidates,\n        key=lambda item: item[0],\n    )\n    return directory, payload\n\n\ndef _read_trades(\n    path: Path,\n) -> list[dict[str, Any]]:\n    rows: list[dict[str, Any]] = []\n\n    with path.open(\n        "r",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        reader = csv.DictReader(file)\n\n        for raw in reader:\n            rows.append(\n                {\n                    "symbol": raw["Symbol"],\n                    "entry_time": (\n                        datetime.fromisoformat(\n                            raw[\n                                "EntryTimestampMarket"\n                            ]\n                        )\n                    ),\n                    "exit_time": (\n                        datetime.fromisoformat(\n                            raw[\n                                "ExitTimestampMarket"\n                            ]\n                        )\n                    ),\n                    "shares": int(\n                        raw["Shares"]\n                    ),\n                    "entry_price": float(\n                        raw["EntryPrice"]\n                    ),\n                    "exit_price": float(\n                        raw["ExitPrice"]\n                    ),\n                    "pnl": float(\n                        raw["PnL"]\n                    ),\n                    "result_r": float(\n                        raw["ResultR"]\n                    ),\n                    "exit_reason": raw[\n                        "ExitReason"\n                    ],\n                }\n            )\n\n    return rows\n\n\ndef _load_reconstruction_context(\n    result: Mapping[str, Any],\n):\n    start = date.fromisoformat(\n        str(result["actual_start"])\n    )\n    end = date.fromisoformat(\n        str(result["actual_end"])\n    )\n\n    if (\n        start != FIXED_WINDOW_START\n        or end != FIXED_WINDOW_END\n    ):\n        raise RuntimeError(\n            "The located run does not use the "\n            "fixed V16 historical window."\n        )\n\n    histories = {}\n\n    for symbol in (\n        *SWING_SYMBOLS,\n        INCOME_SYMBOL,\n    ):\n        cache_path = (\n            _aggregate_cache_path(symbol)\n        )\n\n        if not cache_path.exists():\n            raise RuntimeError(\n                f"Missing local aggregate cache: {cache_path}"\n            )\n\n        bars = [\n            bar\n            for bar in _read_cached_bars(\n                cache_path\n            )\n            if start\n            <= bar.start.date()\n            <= end\n        ]\n\n        if not bars:\n            raise RuntimeError(\n                f"No fixed-window bars for {symbol}."\n            )\n\n        histories[symbol] = bars\n\n    closes = _validate_vix_daily_coverage(\n        closes=_read_vix_daily_cache(\n            DEFAULT_VIX_CACHE\n        ),\n        start=start,\n        end=end,\n    )\n    histories["^VIX"] = (\n        expand_previous_session_vix(\n            reference_bars=histories["SPY"],\n            closes=closes,\n            minimum_bars=(\n                FIXED_MINIMUM_COMMON_BARS\n            ),\n        )\n    )\n\n    test_times = [\n        value\n        for value in _common_times(\n            histories\n        )\n        if start\n        <= value.date()\n        <= end\n    ]\n\n    expected_bars = int(\n        result["common_test_bars"]\n    )\n    expected_sessions = int(\n        result["test_sessions"]\n    )\n    sessions = {\n        value.date()\n        for value in test_times\n    }\n\n    if len(test_times) != expected_bars:\n        raise RuntimeError(\n            "Reconstructed common-bar count differs "\n            f"from V16: {len(test_times)} != {expected_bars}."\n        )\n\n    if len(sessions) != expected_sessions:\n        raise RuntimeError(\n            "Reconstructed session count differs "\n            f"from V16: {len(sessions)} != {expected_sessions}."\n        )\n\n    maps = {\n        symbol: {\n            bar.start: bar\n            for bar in bars\n        }\n        for symbol, bars\n        in histories.items()\n    }\n    candles = {\n        symbol: _to_candles(\n            histories[symbol]\n        )\n        for symbol in SWING_SYMBOLS\n    }\n    config = BotConfig()\n    config = __import__(\n        "dataclasses"\n    ).replace(\n        config,\n        minimum_average_daily_volume=75_000,\n        breakout_volume_multiplier=1.05,\n        breakout_lookback=10,\n        maximum_vix_for_entries=32.0,\n        rsi_overbought=75.0,\n    )\n    config.validate()\n    indicators = {\n        symbol: calculate_indicators(\n            candles[symbol],\n            config,\n        )\n        for symbol in SWING_SYMBOLS\n    }\n    indices = {\n        symbol: {\n            bar.start: index\n            for index, bar\n            in enumerate(\n                histories[symbol]\n            )\n        }\n        for symbol in SWING_SYMBOLS\n    }\n    time_index = {\n        value: index\n        for index, value\n        in enumerate(test_times)\n    }\n\n    return (\n        config,\n        histories,\n        maps,\n        indicators,\n        indices,\n        test_times,\n        time_index,\n    )\n\n\ndef _diagnose_trade(\n    raw: Mapping[str, Any],\n    *,\n    config: BotConfig,\n    maps,\n    indicators,\n    indices,\n    test_times,\n    time_index,\n) -> TradeDiagnostic:\n    symbol = str(raw["symbol"])\n    entry_time = raw["entry_time"]\n    exit_time = raw["exit_time"]\n\n    if entry_time not in time_index:\n        raise RuntimeError(\n            f"Entry time is not common: {entry_time}"\n        )\n\n    if exit_time not in time_index:\n        raise RuntimeError(\n            f"Exit time is not common: {exit_time}"\n        )\n\n    entry_common_index = (\n        time_index[entry_time]\n    )\n    exit_common_index = (\n        time_index[exit_time]\n    )\n\n    if entry_common_index < 1:\n        raise RuntimeError(\n            "Trade entry has no preceding signal bar."\n        )\n\n    if exit_common_index < entry_common_index:\n        raise RuntimeError(\n            "Trade exit precedes entry."\n        )\n\n    signal_time = test_times[\n        entry_common_index - 1\n    ]\n    signal_symbol_index = (\n        indices[symbol][signal_time]\n    )\n    entry_atr = indicators[\n        symbol\n    ].atr[signal_symbol_index]\n\n    if entry_atr is None or entry_atr <= 0:\n        raise RuntimeError(\n            f"Missing signal ATR for {symbol} "\n            f"at {signal_time}."\n        )\n\n    entry_vix = maps[\n        "^VIX"\n    ][signal_time].close\n    evaluation = (\n        _evaluate_entry_relaxed_frequency(\n            candles=_to_candles(\n                [\n                    maps[symbol][time]\n                    for time in sorted(\n                        maps[symbol]\n                    )\n                ]\n            ),\n            indicators=indicators[symbol],\n            index=signal_symbol_index,\n            vix=entry_vix,\n            config=config,\n        )\n    )\n\n    if not evaluation.should_enter:\n        raise RuntimeError(\n            "Entry reconstruction mismatch for "\n            f"{symbol} at {signal_time}."\n        )\n\n    risk_per_share = (\n        float(entry_atr)\n        * config.stop_atr_multiple\n    )\n    entry_price = float(\n        raw["entry_price"]\n    )\n    exit_price = float(\n        raw["exit_price"]\n    )\n    exit_reason = str(\n        raw["exit_reason"]\n    )\n\n    path_times = test_times[\n        entry_common_index:\n        exit_common_index + 1\n    ]\n    prior_times = path_times[:-1]\n\n    favorable_price = entry_price\n    adverse_price = entry_price\n    pre_exit_favorable_price = (\n        entry_price\n    )\n\n    for value in prior_times:\n        bar = maps[symbol][value]\n        favorable_price = max(\n            favorable_price,\n            bar.high,\n        )\n        adverse_price = min(\n            adverse_price,\n            bar.low,\n        )\n        pre_exit_favorable_price = max(\n            pre_exit_favorable_price,\n            bar.high,\n        )\n\n    exit_bar = maps[symbol][exit_time]\n\n    if exit_reason == "END_OF_TEST":\n        favorable_price = max(\n            favorable_price,\n            exit_bar.high,\n        )\n        adverse_price = min(\n            adverse_price,\n            exit_bar.low,\n        )\n    elif exit_reason == "ATR_TARGET":\n        favorable_price = max(\n            favorable_price,\n            entry_price\n            + (\n                float(entry_atr)\n                * config.target_atr_multiple\n            ),\n        )\n    elif exit_reason == "TARGET_GAP":\n        favorable_price = max(\n            favorable_price,\n            exit_bar.open,\n        )\n    elif exit_reason == "STOP_GAP":\n        adverse_price = min(\n            adverse_price,\n            exit_bar.open,\n        )\n    elif exit_reason == "ATR_STOP":\n        if config.slippage_rate >= 1:\n            raise RuntimeError(\n                "Invalid slippage rate."\n            )\n        stop_trigger = (\n            exit_price\n            / (\n                1.0\n                - config.slippage_rate\n            )\n        )\n        adverse_price = min(\n            adverse_price,\n            stop_trigger,\n        )\n    else:\n        # Unknown exit reasons use only the observed fill endpoint,\n        # not the full exit-bar high/low, to avoid post-exit lookahead.\n        favorable_price = max(\n            favorable_price,\n            exit_price,\n        )\n        adverse_price = min(\n            adverse_price,\n            exit_price,\n        )\n\n    conservative_mfe_r = max(\n        0.0,\n        (\n            favorable_price\n            - entry_price\n        )\n        / risk_per_share,\n    )\n    conservative_mae_r = max(\n        0.0,\n        (\n            entry_price\n            - adverse_price\n        )\n        / risk_per_share,\n    )\n    pre_exit_mfe_r = max(\n        0.0,\n        (\n            pre_exit_favorable_price\n            - entry_price\n        )\n        / risk_per_share,\n    )\n\n    # A prior bar is counted as actually profitable only if a sell at\n    # that high could clear the configured sell-side slippage.\n    break_even_market_price = (\n        entry_price\n        / (\n            1.0\n            - config.slippage_rate\n        )\n    )\n    profitable_before_exit_bar = (\n        float(raw["pnl"]) < 0\n        and pre_exit_favorable_price\n        >= break_even_market_price\n    )\n\n    holding_sessions = len(\n        {\n            value.date()\n            for value in path_times\n        }\n    )\n    triggers = tuple(\n        evaluation.triggers\n    )\n    trigger_combo = (\n        "+".join(sorted(triggers))\n        if triggers\n        else "NONE"\n    )\n\n    return TradeDiagnostic(\n        symbol=symbol,\n        entry_time=entry_time,\n        exit_time=exit_time,\n        shares=int(raw["shares"]),\n        entry_price=entry_price,\n        exit_price=exit_price,\n        pnl=float(raw["pnl"]),\n        result_r=float(raw["result_r"]),\n        exit_reason=exit_reason,\n        signal_time=signal_time,\n        entry_atr=float(entry_atr),\n        entry_vix=float(entry_vix),\n        vix_regime=_vix_regime(\n            float(entry_vix)\n        ),\n        triggers=triggers,\n        trigger_combo=trigger_combo,\n        holding_bars=len(path_times),\n        holding_sessions=holding_sessions,\n        conservative_mfe_r=(\n            conservative_mfe_r\n        ),\n        conservative_mae_r=(\n            conservative_mae_r\n        ),\n        pre_exit_mfe_r=pre_exit_mfe_r,\n        profitable_before_exit_bar=(\n            profitable_before_exit_bar\n        ),\n        reached_1r=(\n            conservative_mfe_r >= 1.0\n        ),\n        reached_2r=(\n            conservative_mfe_r >= 2.0\n        ),\n        reached_3r=(\n            conservative_mfe_r >= 3.0\n        ),\n    )\n\n\ndef _write_detail_csv(\n    path: Path,\n    rows: Sequence[TradeDiagnostic],\n) -> None:\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Symbol",\n                "SignalTimestampMarket",\n                "EntryTimestampMarket",\n                "ExitTimestampMarket",\n                "Shares",\n                "EntryPrice",\n                "ExitPrice",\n                "PnL",\n                "ResultR",\n                "ExitReason",\n                "EntryATR",\n                "EntryVIX",\n                "VIXRegime",\n                "Triggers",\n                "TriggerCombo",\n                "HoldingBars",\n                "HoldingSessions",\n                "ConservativeMFER",\n                "ConservativeMAER",\n                "PreExitMFER",\n                "ProfitableBeforeExitBar",\n                "Reached1R",\n                "Reached2R",\n                "Reached3R",\n            )\n        )\n\n        for row in rows:\n            writer.writerow(\n                (\n                    row.symbol,\n                    row.signal_time.isoformat(),\n                    row.entry_time.isoformat(),\n                    row.exit_time.isoformat(),\n                    row.shares,\n                    f"{row.entry_price:.8f}",\n                    f"{row.exit_price:.8f}",\n                    f"{row.pnl:.8f}",\n                    f"{row.result_r:.8f}",\n                    row.exit_reason,\n                    f"{row.entry_atr:.8f}",\n                    f"{row.entry_vix:.8f}",\n                    row.vix_regime,\n                    "|".join(row.triggers),\n                    row.trigger_combo,\n                    row.holding_bars,\n                    row.holding_sessions,\n                    f"{row.conservative_mfe_r:.8f}",\n                    f"{row.conservative_mae_r:.8f}",\n                    f"{row.pre_exit_mfe_r:.8f}",\n                    int(\n                        row.profitable_before_exit_bar\n                    ),\n                    int(row.reached_1r),\n                    int(row.reached_2r),\n                    int(row.reached_3r),\n                )\n            )\n\n\ndef _format_group(\n    title: str,\n    groups: Mapping[\n        str,\n        Mapping[str, Any],\n    ],\n) -> list[str]:\n    lines = [title]\n\n    for name, summary in groups.items():\n        lines.append(\n            "  "\n            f"{name:<32} "\n            f"n={summary[\'trades\']:>4} "\n            f"win={summary[\'win_rate\']:.1%} "\n            f"PF={_format_pf(summary[\'profit_factor\']):>6} "\n            f"net=${summary[\'net_pnl\']:>9,.2f} "\n            f"avgR={summary[\'average_result_r\']:>7.3f} "\n            f"MFE={summary[\'average_mfe_r\']:>6.3f}R "\n            f"MAE={summary[\'average_mae_r\']:>6.3f}R "\n            f"hold={summary[\'average_holding_bars\']:>6.1f} bars"\n        )\n\n    return lines\n\n\ndef _build_report(\n    *,\n    source_directory: Path,\n    result: Mapping[str, Any],\n    rows: Sequence[TradeDiagnostic],\n    payload: Mapping[str, Any],\n) -> str:\n    winners = [\n        row\n        for row in rows\n        if row.pnl > 0\n    ]\n    losers = [\n        row\n        for row in rows\n        if row.pnl < 0\n    ]\n    profitable_losers = [\n        row\n        for row in losers\n        if row.profitable_before_exit_bar\n    ]\n\n    lines = [\n        "=" * 100,\n        (\n            "QPX V17 — V16 EXIT / EXPECTANCY DIAGNOSTIC STUDY "\n            "(NO STRATEGY CHANGES)"\n        ),\n        "=" * 100,\n        f"Source V16 run             : {source_directory}",\n        (\n            "Historical window          : "\n            f"{result[\'actual_start\']} to {result[\'actual_end\']}"\n        ),\n        (\n            "Common bars / sessions     : "\n            f"{result[\'common_test_bars\']} / "\n            f"{result[\'test_sessions\']}"\n        ),\n        (\n            "Entry / risk / notional    : "\n            f"{result[\'entry_profile\']} / "\n            f"{result[\'risk_profile\']} / "\n            f"{result[\'notional_profile\']}"\n        ),\n        "Strategy rerun               : NO",\n        "Entry/exit rule changes      : NONE",\n        "Market-data download         : NONE",\n        "",\n        "OVERALL",\n        (\n            f"  Closed trades             : {len(rows)}"\n        ),\n        (\n            f"  Winners / losers          : "\n            f"{len(winners)} / {len(losers)}"\n        ),\n        (\n            "  Win rate                  : "\n            f"{payload[\'overall\'][\'win_rate\']:.2%}"\n        ),\n        (\n            "  Net realized P&L          : "\n            f"${payload[\'overall\'][\'net_pnl\']:,.2f}"\n        ),\n        (\n            "  Profit factor             : "\n            f"{_format_pf(payload[\'overall\'][\'profit_factor\'])}"\n        ),\n        (\n            "  Average / median R        : "\n            f"{payload[\'overall\'][\'average_result_r\']:.3f} / "\n            f"{payload[\'overall\'][\'median_result_r\']:.3f}"\n        ),\n        (\n            "  Avg / median conservative MFE : "\n            f"{payload[\'overall\'][\'average_mfe_r\']:.3f}R / "\n            f"{payload[\'overall\'][\'median_mfe_r\']:.3f}R"\n        ),\n        (\n            "  Avg / median conservative MAE : "\n            f"{payload[\'overall\'][\'average_mae_r\']:.3f}R / "\n            f"{payload[\'overall\'][\'median_mae_r\']:.3f}R"\n        ),\n        (\n            "  Avg / median holding bars : "\n            f"{payload[\'overall\'][\'average_holding_bars\']:.1f} / "\n            f"{payload[\'overall\'][\'median_holding_bars\']:.1f}"\n        ),\n        "",\n        "EXCURSION / REVERSAL",\n        (\n            "  All trades reaching +1R   : "\n            f"{payload[\'all_reached_1r\']} "\n            f"({payload[\'all_reached_1r\'] / len(rows):.2%})"\n        ),\n        (\n            "  All trades reaching +2R   : "\n            f"{payload[\'all_reached_2r\']} "\n            f"({payload[\'all_reached_2r\'] / len(rows):.2%})"\n        ),\n        (\n            "  All trades reaching +3R   : "\n            f"{payload[\'all_reached_3r\']} "\n            f"({payload[\'all_reached_3r\'] / len(rows):.2%})"\n        ),\n        (\n            "  Winners reaching +1R      : "\n            f"{payload[\'winner_reached_1r\']} / {len(winners)} "\n            f"({(payload[\'winner_reached_1r\'] / len(winners)) if winners else 0.0:.2%})"\n        ),\n        (\n            "  Winners reaching +2R      : "\n            f"{payload[\'winner_reached_2r\']} / {len(winners)} "\n            f"({(payload[\'winner_reached_2r\'] / len(winners)) if winners else 0.0:.2%})"\n        ),\n        (\n            "  Winners reaching +3R      : "\n            f"{payload[\'winner_reached_3r\']} / {len(winners)} "\n            f"({(payload[\'winner_reached_3r\'] / len(winners)) if winners else 0.0:.2%})"\n        ),\n        (\n            "  Losing trades profitable before exit bar: "\n            f"{len(profitable_losers)} / {len(losers)} "\n            f"({(len(profitable_losers) / len(losers)) if losers else 0.0:.2%})"\n        ),\n        (\n            "  Losers that had reached +1R: "\n            f"{payload[\'loser_reached_1r\']} / {len(losers)} "\n            f"({(payload[\'loser_reached_1r\'] / len(losers)) if losers else 0.0:.2%})"\n        ),\n        "",\n        (\n            "MFE/MAE methodology: conservative. Full OHLC is used only "\n            "for bars completed before the exit bar. On stop/target exit "\n            "bars, the known trigger/open is used rather than the full "\n            "post-exit high/low, avoiding post-exit lookahead."\n        ),\n        (\n            "Profitable-before-exit-bar requires a prior completed bar "\n            "high high enough to clear configured sell-side slippage."\n        ),\n        "",\n    ]\n    lines.extend(\n        _format_group(\n            "BY EXIT REASON",\n            payload["by_exit_reason"],\n        )\n    )\n    lines.append("")\n    lines.extend(\n        _format_group(\n            "BY SYMBOL",\n            payload["by_symbol"],\n        )\n    )\n    lines.append("")\n    lines.extend(\n        _format_group(\n            "BY ENTRY VIX REGIME",\n            payload["by_vix_regime"],\n        )\n    )\n    lines.append("")\n    lines.extend(\n        _format_group(\n            "BY ENTRY TRIGGER (COUNTS OVERLAP)",\n            payload["by_trigger"],\n        )\n    )\n    lines.append("")\n    lines.extend(\n        _format_group(\n            "BY TRIGGER COMBINATION",\n            payload["by_trigger_combo"],\n        )\n    )\n    lines.extend(\n        (\n            "",\n            "INTERPRETATION GUARDRAILS",\n            (\n                "  This is an in-sample diagnostic of the already-tested "\n                "V16 window, not independent validation."\n            ),\n            (\n                "  No stop, target, trailing, entry, sizing, allocation, "\n                "or market-data rule was changed by V17."\n            ),\n            (\n                "  Use these diagnostics to choose a small number of "\n                "explicit exit hypotheses, then validate those hypotheses "\n                "on a separate/frozen period."\n            ),\n            "=" * 100,\n        )\n    )\n    return "\\n".join(lines)\n\n\ndef run_diagnostics(\n    *,\n    report_root: str | Path = (\n        DEFAULT_NOTIONAL_CAP_REPORT_ROOT\n    ),\n) -> tuple[\n    Path,\n    Path,\n    Path,\n]:\n    report_root_path = (\n        Path(report_root)\n        .expanduser()\n        .resolve()\n    )\n    source_directory, result = (\n        _latest_v16_run(\n            report_root_path\n        )\n    )\n    trades_path = (\n        source_directory\n        / "swing_only_control_trades.csv"\n    )\n    raw_trades = _read_trades(\n        trades_path\n    )\n\n    if len(raw_trades) != int(\n        result["closed_trades"]\n    ):\n        raise RuntimeError(\n            "V16 trade CSV count differs from result JSON."\n        )\n\n    (\n        config,\n        histories,\n        maps,\n        indicators,\n        indices,\n        test_times,\n        time_index,\n    ) = _load_reconstruction_context(\n        result\n    )\n\n    rows = [\n        _diagnose_trade(\n            raw,\n            config=config,\n            maps=maps,\n            indicators=indicators,\n            indices=indices,\n            test_times=test_times,\n            time_index=time_index,\n        )\n        for raw in raw_trades\n    ]\n\n    if len(rows) != len(raw_trades):\n        raise RuntimeError(\n            "Diagnostic row count mismatch."\n        )\n\n    overall = _summary(rows)\n    winners = [\n        row\n        for row in rows\n        if row.pnl > 0\n    ]\n    losers = [\n        row\n        for row in rows\n        if row.pnl < 0\n    ]\n\n    payload = {\n        "schema_version": (\n            DIAGNOSTIC_SCHEMA_VERSION\n        ),\n        "diagnostic_label": (\n            DIAGNOSTIC_LABEL\n        ),\n        "source_v16_directory": str(\n            source_directory\n        ),\n        "source_result": dict(result),\n        "strategy_rerun": False,\n        "strategy_rule_changes": False,\n        "market_data_download": False,\n        "conservative_exit_bar_method": True,\n        "overall": overall,\n        "all_reached_1r": sum(\n            row.reached_1r\n            for row in rows\n        ),\n        "all_reached_2r": sum(\n            row.reached_2r\n            for row in rows\n        ),\n        "all_reached_3r": sum(\n            row.reached_3r\n            for row in rows\n        ),\n        "winner_reached_1r": sum(\n            row.reached_1r\n            for row in winners\n        ),\n        "winner_reached_2r": sum(\n            row.reached_2r\n            for row in winners\n        ),\n        "winner_reached_3r": sum(\n            row.reached_3r\n            for row in winners\n        ),\n        "loser_reached_1r": sum(\n            row.reached_1r\n            for row in losers\n        ),\n        "losers_profitable_before_exit_bar": (\n            sum(\n                row.profitable_before_exit_bar\n                for row in losers\n            )\n        ),\n        "by_exit_reason": _group_summary(\n            rows,\n            lambda row: row.exit_reason,\n        ),\n        "by_symbol": _group_summary(\n            rows,\n            lambda row: row.symbol,\n        ),\n        "by_vix_regime": _group_summary(\n            rows,\n            lambda row: row.vix_regime,\n        ),\n        "by_trigger": _trigger_summary(\n            rows\n        ),\n        "by_trigger_combo": _group_summary(\n            rows,\n            lambda row: row.trigger_combo,\n        ),\n        "exit_reason_counts": dict(\n            Counter(\n                row.exit_reason\n                for row in rows\n            )\n        ),\n        "vix_regime_counts": dict(\n            Counter(\n                row.vix_regime\n                for row in rows\n            )\n        ),\n        "trigger_combo_counts": dict(\n            Counter(\n                row.trigger_combo\n                for row in rows\n            )\n        ),\n    }\n\n    text = _build_report(\n        source_directory=source_directory,\n        result=result,\n        rows=rows,\n        payload=payload,\n    )\n\n    text_path = (\n        source_directory\n        / "v17_exit_diagnostics_report.txt"\n    )\n    json_path = (\n        source_directory\n        / "v17_exit_diagnostics.json"\n    )\n    csv_path = (\n        source_directory\n        / "v17_exit_diagnostics_trades.csv"\n    )\n\n    text_path.write_text(\n        text + "\\n",\n        encoding="utf-8",\n    )\n    _atomic_json(\n        json_path,\n        payload,\n    )\n    _write_detail_csv(\n        csv_path,\n        rows,\n    )\n\n    print(text)\n    print("-" * 100)\n    print("Diagnostic artifacts:")\n    print(f"  report : {text_path}")\n    print(f"  json   : {json_path}")\n    print(f"  trades : {csv_path}")\n    print()\n    print(\n        "QPX V16 EXIT DIAGNOSTIC STUDY V17: COMPLETE"\n    )\n    return (\n        text_path,\n        json_path,\n        csv_path,\n    )\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Analyze the latest completed V16 16%-notional "\n            "swing-control run without rerunning the strategy."\n        )\n    )\n    parser.add_argument(\n        "--report-root",\n        default=str(\n            DEFAULT_NOTIONAL_CAP_REPORT_ROOT\n        ),\n    )\n    return parser\n\n\ndef main(\n    argv: Sequence[str] | None = None,\n) -> int:\n    args = _parser().parse_args(argv)\n    run_diagnostics(\n        report_root=args.report_root,\n    )\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    'tests/test_qpx_bot_v16_exit_diagnostics.py': '\nfrom pathlib import Path\n\nfrom QPX_ANALYZE_V16_EXIT_DIAGNOSTICS import (\n    DIAGNOSTIC_LABEL,\n    TradeDiagnostic,\n    _format_pf,\n    _median,\n    _profit_factor,\n    _summary,\n    _vix_regime,\n)\n\n\nassert (\n    DIAGNOSTIC_LABEL\n    == "V16_EXIT_DIAGNOSTIC_STUDY_V17"\n)\nassert abs(\n    _median([1.0, 3.0, 2.0]) - 2.0\n) < 1e-9\nassert abs(\n    _median([1.0, 3.0]) - 2.0\n) < 1e-9\nassert abs(\n    _profit_factor(\n        [2.0, -1.0, 1.0, -1.0]\n    )\n    - 1.5\n) < 1e-9\nassert _format_pf(None) == "∞"\nassert _vix_regime(19.99) == "LOW_LT_20"\nassert (\n    _vix_regime(21.0)\n    == "MODERATE_20_TO_24"\n)\nassert (\n    _vix_regime(26.0)\n    == "ELEVATED_24_TO_28"\n)\nassert (\n    _vix_regime(29.0)\n    == "HIGH_ALLOWED_GT_28"\n)\n\nfrom datetime import datetime, timezone\n\nrow = TradeDiagnostic(\n    symbol="SPY",\n    entry_time=datetime(\n        2025, 1, 2, tzinfo=timezone.utc\n    ),\n    exit_time=datetime(\n        2025, 1, 3, tzinfo=timezone.utc\n    ),\n    shares=1,\n    entry_price=100.0,\n    exit_price=102.0,\n    pnl=2.0,\n    result_r=0.4,\n    exit_reason="TEST",\n    signal_time=datetime(\n        2025, 1, 2, tzinfo=timezone.utc\n    ),\n    entry_atr=2.0,\n    entry_vix=18.0,\n    vix_regime="LOW_LT_20",\n    triggers=("MOMENTUM_PERSISTENCE",),\n    trigger_combo="MOMENTUM_PERSISTENCE",\n    holding_bars=2,\n    holding_sessions=2,\n    conservative_mfe_r=1.2,\n    conservative_mae_r=0.4,\n    pre_exit_mfe_r=1.0,\n    profitable_before_exit_bar=False,\n    reached_1r=True,\n    reached_2r=False,\n    reached_3r=False,\n)\nsummary = _summary([row])\nassert summary["trades"] == 1\nassert summary["wins"] == 1\nassert abs(summary["net_pnl"] - 2.0) < 1e-9\n\nroot = Path(__file__).resolve().parents[1]\nsource = (\n    root\n    / "QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py"\n).read_text(encoding="utf-8")\n\nfor marker in (\n    "Strategy rerun               : NO",\n    "Entry/exit rule changes      : NONE",\n    "conservative_exit_bar_method",\n    "profitable_before_exit_bar",\n    "winner_reached_1r",\n    "winner_reached_2r",\n    "winner_reached_3r",\n    "BY EXIT REASON",\n    "BY SYMBOL",\n    "BY ENTRY VIX REGIME",\n    "BY ENTRY TRIGGER (COUNTS OVERLAP)",\n    "BY TRIGGER COMBINATION",\n):\n    assert marker in source, marker\n\nfor prohibited in (\n    "fetch_aggregate_history(",\n    "MASSIVE_API_KEY",\n    "POLYGON_API_KEY",\n    "getpass",\n):\n    assert prohibited not in source, prohibited\n\nprint(\n    "QPX V16 Exit Diagnostics V17 PASS"\n)\n',
    'qpx_bot/ACTUAL_TWO_YEAR_15M_SIX_README.txt': 'QPX ACTUAL TWO-YEAR 15-MINUTE SIX-POSITION BACKTEST — CBOE VIX\n================================================================\n\nThe Massive/Polygon key downloaded the ETF histories but returned HTTP\n403 for I:VIX because the account is not entitled to that index ticker.\n\nThis revision does not fabricate VIX values and does not use an ETF\nproxy. It downloads Cboe\'s official daily VIX closing history.\n\nFor each 15-minute session bar, the VIX gate uses the official close\nfrom the previous completed market session. Monday therefore uses\nFriday\'s official close. Tuesday uses Monday\'s official close.\n\nThis prevents look-ahead. It is real VIX data, but it is deliberately\nlagged daily data rather than unavailable intraday VIX data. The report,\nmanifest, and provenance files disclose that distinction.\n\nDIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV, and QDTE continue to use actual\n15-minute Massive/Polygon bars. The runner reuses validated files from\nthe incomplete download, avoiding repeated rate-limited requests. A\nsymbol is downloaded again only if its cache is missing or incomplete.\n\nActual QDTE dividend records still come from the authenticated provider.\n\nThe runner aborts instead of using synthetic or interpolated ETF bars,\ndaily ETF bars in place of intraday bars, a volatility ETF proxy,\nfabricated VIX values, fake distributions, or forced trades.\n\nRankings remain removed. The six-position cap, risk controls, next-bar\nexecution, ATR exits, contributions, allocation rules, slippage, and tax\nreserves remain unchanged. Live brokerage remains disabled.\n\nResearch simulation only. Historical results do not guarantee future\nperformance.\n\n\nV4 unit-test correction\n-----------------------\n\nProduction still requires 12,000 covered VIX timestamps. The small\nthree-bar deterministic unit fixture passes an explicit three-bar test\nthreshold so it can validate previous-session timing without weakening\nthe real backtest coverage requirement.\n\n\nV5 split execution workflow\n---------------------------\n\nInstallation and Git push are now independent from all slow market-data\nrequests.\n\nThe installer performs only these network-independent code actions:\n\n1. install the revised source;\n2. run the focused and complete test suites;\n3. commit and push the source;\n4. run the small official Cboe VIX-only preflight;\n5. stop.\n\nThe VIX preflight runs before any Massive/Polygon aggregate request and\nwrites a stable local cache:\n\nresearch_data/qpx_actual_two_year_15m_six/shared/CBOE_VIX_DAILY.csv\n\nThe long backtest is launched later with:\n\npython QPX_RUN_ACTUAL_TWO_YEAR_15M_SIX.py\n\nThat run validates or reuses the VIX cache first. Only after VIX passes\ndoes it request or reuse ETF and QDTE data.\n\nMarket-data CSV files remain local and are excluded from Git. Reports\nrecord their paths, provenance, and SHA-256 hashes.\n\n\nV6 resumable aggregate checkpoints\n----------------------------------\n\nThe long provider download now persists each completed 90-day symbol\nchunk immediately in:\n\nresearch_data/qpx_actual_two_year_15m_six/shared/aggregate_15m/\n\nEvery stable symbol CSV has a companion manifest listing completed\nchunks. If Termux is interrupted or a later input fails, the next run\nskips those completed chunks.\n\nBefore any new provider request, QPX recursively scans all earlier\ntimestamped research directories. A complete valid symbol history is\nimported into the stable cache and marked complete.\n\nThe installer runs a no-network cache audit and then the separate Cboe\nVIX preflight. It does not launch the long Massive/Polygon backtest.\n\n\nV7 focused-test correction\n--------------------------\n\nThe V6 focused test searched for one display sentence that Python builds\nfrom two adjacent source strings. The runtime message was valid, but the\ncombined sentence was not a contiguous source substring.\n\nV7 removes that brittle presentation-text check and verifies the actual\ncheckpoint structures instead:\n\n- _mark_all_chunks_complete\n- LOCAL_VALIDATED_MASSIVE_POLYGON_CACHE\n- completed chunk manifests\n- stable aggregate cache import/resume paths\n\nNo strategy, provider, VIX, coverage, risk, or execution rule changed.\n\n\nV8 stale-tail checkpoint repair\n-------------------------------\n\nA completed-chunk manifest must now be supported by actual bars that\nreach the end of that requested chunk within the unchanged freshness\ntolerance.\n\nOlder manifests could mark the final 90-day request complete even when\nthe provider returned a stale tail. That caused every later run to skip\nthe exact request needed to refresh the test endpoint.\n\nV8 validates declared chunks against the local CSV, removes stale or\nincomplete declarations, and saves a chunk as complete only after its\nactual bar coverage reaches the chunk endpoint.\n\nQPX_REPAIR_15M_CHECKPOINTS.py performs this manifest repair and prints\nper-symbol endpoint diagnostics without making a network request. The\nnext backtest downloads only missing or invalidated chunks.\n\n\nV9 focused-test correction\n--------------------------\n\nV8 used two exact English sentence fragments in its static source test.\nThe implementation builds those messages from adjacent source strings,\nso the runtime output was valid while the contiguous source assertions\nwere not.\n\nV9 verifies the stable checkpoint structures instead:\n\n- invalidated_chunks\n- last_attempted_chunk_complete\n- chunk_complete\n- _validated_completed_chunks\n\nThe stale-tail repair behavior and every strategy, coverage, risk,\nprovider, and no-placeholder rule remain unchanged.\n\n\nV10 fixed local near-two-year backtest\n--------------------------------------\n\nThis revision adds a separate, local-only historical validation window:\n\n- fixed start: 2024-08-06;\n- fixed end: 2026-07-28;\n- calendar span: 721 days;\n- real 15-minute DIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV, and QDTE\n  cache files already present on the device;\n- official Cboe daily VIX closes using the previous completed session;\n- actual cached QDTE distribution events;\n- first 200 common 15-minute bars reserved for indicator\n  initialization, with swing entries disabled;\n- minimum 11,500 common bars and 480 sessions;\n- no network requests;\n- no API key;\n- no synthetic, interpolated, placeholder, or forced data.\n\nThis is deliberately labeled a fixed near-two-year study, not an exact\ntwo-year study. It ends nine calendar days before 2026-08-06. Therefore,\nthe exact second-anniversary 40/60 allocation phase is not reached\ninside this window; the 65/35 phase remains active through the end.\n\nThe original rolling provider-backed runner remains available. The\nfixed local runner is:\n\npython QPX_RUN_FIXED_2024_08_06_TO_2026_07_28.py\n\n\nV11 fixed-window observed-session threshold\n-------------------------------------------\n\nThe fixed 2024-08-06 through 2026-07-28 local study keeps the existing\n11,500 common 15-minute bar requirement and now uses a fixed-window-only\nminimum of 450 common market sessions. The rolling exact two-year study\nstill requires 480 sessions.\n\nThe fixed study also reports the expected exchange sessions calculated\nfrom the QPX market calendar and the observed common-session coverage\npercentage. Missing bars are not filled, interpolated, synthesized, or\nreplaced.\n\n\nV12 swing-only fixed-window control\n-----------------------------------\n\nThe swing-only control uses the same fixed 2024-08-06 through 2026-07-28\nwindow, the same 200-common-bar initialization, the same eight swing\nsymbols, the same common timestamp intersection, the same previous-session\nofficial Cboe VIX observation policy, the same entry/exit rules, the same\nsix-slot policy, the same risk sizing, and the same $2,800 initial total\ncapital plus $2,000 monthly contributions.\n\nControl-specific changes:\n- QDTE receives no capital.\n- QDTE distributions are disabled.\n- All initial capital and monthly contributions enter swing cash.\n- QDTE 15-minute bars remain in the common-timestamp intersection solely\n  so the control uses the same timestamp sample as the hybrid study.\n- Allocation rebalancing is disabled.\n- Tax-reserve behavior on profitable swing exits remains active.\n- No market data is downloaded and no provider key is requested.\n\n\nV13 relaxed swing-frequency research control\n--------------------------------------------\n\nThis is a research-only swing-only profile. It does not change the\nlive/paper default strategy.\n\nThe prior swing-only control showed only one opening-gap rejection and\none risk-sizing rejection. Therefore increasing risk-per-trade or the\n6% portfolio-risk ceiling would primarily increase position size, not\ntrade count.\n\nThe relaxed-frequency profile changes only entry-frequency gates:\n- 15-minute average-volume floor: 75,000 shares. The original 2,000,000\n  field is defined as daily volume but was being compared directly to\n  15-minute candle volume. 2,000,000 / 26 is approximately 76,923.\n- breakout-volume multiplier: 1.20x -> 1.05x.\n- breakout lookback: 20 -> 10 completed 15-minute bars.\n- maximum VIX: 28 -> 32.\n- RSI overbought ceiling: 70 -> 75.\n- momentum: exact EMA/RSI/RMI crosses still count, plus an established\n  bullish EMA state with RSI or RMI >= 52.\n- opening-gap rejection: 1.5 ATR -> 2.0 ATR.\n\nUnchanged:\n- 1% base risk per trade.\n- 6% maximum active portfolio risk.\n- 2.5 ATR stop.\n- 5 ATR target.\n- 3 ATR trailing activation.\n- 0.075% slippage.\n- six concurrent slots.\n- no rankings.\n- no synthetic, interpolated, placeholder, or forced entries.\n- live brokerage remains disabled.\n\n\nV14 relaxed-frequency no-Kelly research control\n-----------------------------------------------\n\nV13 successfully increased qualifying signal bars from the sparse\nbaseline to a much larger opportunity set, but the fixed-window run\nstopped at 20 filled trades while recording 1,565 risk-sizing\nrejections.\n\nThe risk engine enables Kelly sizing after 20 completed trades. A\nnon-positive Kelly result becomes a zero risk fraction and blocks the\ntrade.\n\nV14 keeps the V13 relaxed-frequency entry profile but disables adaptive\nKelly only in this fixed local swing-only research control.\n\nUnchanged protections:\n- 1% base risk per trade.\n- 6% aggregate active-risk cap.\n- 2.5 ATR stop.\n- 5 ATR target.\n- 3 ATR trailing activation.\n- 0.075% slippage.\n- six-position maximum.\n- no rankings.\n- no synthetic, interpolated, placeholder, or forced entries.\n- live brokerage disabled.\n\nV14 also records risk-rejection reasons explicitly so subsequent runs\nshow whether any remaining rejections come from cash, active-risk\ncapacity, or another sizing rule.\n\n\nV15 net-realized tax-reserve research control\n---------------------------------------------\n\nV14 produced 486 swing trades with the relaxed-frequency entry profile,\nfixed 1% risk per trade, 6% aggregate active-risk cap, and Kelly\ndisabled. It also accumulated a large tax-reserve balance because the\nshared portfolio logic reserves 37% of every profitable exit\nindependently.\n\nV15 is a research-only cash-management control. It keeps the V14\nstrategy, entries, exits, position risk, aggregate risk, slippage,\nsymbols, dates, and real-data inputs unchanged.\n\nThe only cash-reserve change is:\n- after each closed swing trade, research tax reserve is reconciled to\n  37% of positive cumulative net realized swing P&L;\n- if later realized losses reduce that cumulative net gain, the excess\n  reserve is released back to investable swing cash;\n- if cumulative net realized P&L is zero or negative, the research\n  reserve is zero.\n\nThis is not complete tax accounting and is not tax advice. It is an\nexplicit research control for measuring whether the prior per-winning-\ntrade reserve was unnecessarily constraining investable cash.\n\nV15 also decomposes the risk engine\'s combined "risk budget or cash is\ntoo small for one share" rejection into:\n- CASH_BELOW_ONE_SHARE;\n- BASE_RISK_BUDGET_BELOW_ONE_SHARE;\n- ACTIVE_RISK_CAP_BELOW_ONE_SHARE;\n- combined cash/risk causes when both apply.\n\nLive/paper defaults, qpx_bot/config.py, qpx_bot/risk.py, and\nqpx_bot/portfolio.py are not modified by this workflow.\n\n\nV16 16% position-notional research control\n------------------------------------------\n\nV15 showed that every remaining one-share sizing rejection was caused by\ninsufficient investable cash, not the 1% per-trade risk budget or the\n6% aggregate active-risk ceiling.\n\nV16 keeps the V15 entry, exit, risk, tax-reserve, slippage, symbol,\ndate, and actual-data behavior unchanged. It adds a research-only\nper-position notional target of 16% of account equity after normal\nrisk sizing.\n\nWhole-share practicality:\n- if 16% of account equity is less than the price of one share, V16\n  permits one share rather than automatically excluding a high-priced\n  ETF;\n- this exception is counted separately in the report as a one-share\n  floor use;\n- therefore the 16% value is a target cap with a one-share minimum,\n  not an absolute leverage guarantee for a small whole-share account.\n\nThe objective is to prevent one low-ATR signal from consuming most\navailable cash while preserving the original 1% trade-risk and 6%\naggregate active-risk limits.\n\nLive/paper defaults, qpx_bot/config.py, qpx_bot/risk.py, and\nqpx_bot/portfolio.py are not modified by this workflow.\n\n\nV17 V16 exit / expectancy diagnostic study\n-------------------------------------------\n\nV17 is diagnostic-only. It does not rerun the strategy and does not\nchange entry, exit, sizing, tax-reserve, notional-cap, allocation, or\nmarket-data rules.\n\nIt locates the latest completed V16 16%-notional run and reconstructs\neach closed trade from the same validated local 15-minute caches. It\nverifies the reconstructed common-bar and session counts against the\nsaved V16 result before producing diagnostics.\n\nPer-trade diagnostics include:\n- exit reason;\n- conservative maximum favorable excursion (MFE) in initial-R units;\n- conservative maximum adverse excursion (MAE) in initial-R units;\n- whether +1R, +2R, or +3R was reached before exit;\n- whether a losing trade had been sell-side-slippage-adjusted profitable\n  on a completed bar before its exit bar;\n- holding bars and holding sessions;\n- entry VIX regime;\n- reconstructed relaxed-entry trigger(s).\n\nThe exit-bar excursion method is intentionally conservative: full OHLC\nis used only for completed bars before the exit bar. On stop/target exit\nbars, the known trigger/open is used instead of the full exit-bar high\nor low, avoiding post-exit lookahead.\n\nSummaries are produced overall and by exit reason, symbol, VIX regime,\nindividual entry trigger, and trigger combination. Trigger counts can\noverlap when one entry has multiple triggers.\n\nV17 writes text, JSON, and per-trade CSV diagnostic artifacts into the\nsource V16 report directory. It makes no provider request and needs no\nAPI key.\n\nThese are in-sample diagnostics of an already-examined historical\nwindow. They are intended to formulate a small number of explicit exit\nhypotheses for later frozen validation, not to claim independent\nperformance validation.\n',
}
TARGETS = list(FILES)
originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
    )


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            relative,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_expected_base() -> None:
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()

    if head != EXPECTED_BASE_COMMIT:
        # Permit reruns after V17 itself has already been committed,
        # provided the diagnostic analyzer is tracked.
        if (
            ROOT
            / "QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py"
        ).exists() and is_tracked(
            "QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py"
        ):
            return

        raise RuntimeError(
            "Repository HEAD is not the verified V16 base. "
            f"Expected {EXPECTED_BASE_COMMIT}, found {head}."
        )


def ensure_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )

        if worktree.returncode or staged.returncode:
            changed.append(relative)
        elif path.exists() and not is_tracked(relative):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and "
            "were not overwritten:\n"
            + "\n".join(changed)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup = BACKUP / relative
        backup.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(path, backup)


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(content).strip()
            + "\n",
            encoding="utf-8",
        )

        if path.name.startswith("QPX_"):
            path.chmod(0o700)

        print(f"Installed: {relative}")


def restore() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(
                Path(__file__)
                .resolve()
                .relative_to(ROOT)
            )
        )
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    if subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    ).returncode == 0:
        print(
            "The V17 exit-diagnostic workflow "
            "is already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        "Add V16 exit expectancy diagnostic study",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — V16 EXIT / EXPECTANCY "
        "DIAGNOSTIC INSTALLER V17"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_expected_base()
    ensure_safe()

    try:
        install_files()
        run([
            sys.executable,
            "-m",
            "tests.test_qpx_bot_v16_exit_diagnostics",
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("=" * 78)
    print("CODE INSTALL/TEST/PUSH: COMPLETE")
    print("=" * 78)
    print(
        "Analyzing the latest completed V16 run."
    )
    print(
        "The strategy will NOT be rerun and no "
        "market data will be downloaded."
    )
    print(
        "No entry, exit, sizing, risk, or live/paper "
        "rule is changed by this workflow."
    )
    print()

    result = run(
        [
            sys.executable,
            "QPX_ANALYZE_V16_EXIT_DIAGNOSTICS.py",
        ],
        check=False,
    )

    if result.returncode != 0:
        print()
        print("=" * 78)
        print("CODE PUSH: COMPLETE")
        print("V16 EXIT DIAGNOSTIC STUDY: INCOMPLETE")
        print("=" * 78)
        return result.returncode

    print()
    print("=" * 78)
    print(
        "QPX V16 EXIT / EXPECTANCY "
        "DIAGNOSTIC WORKFLOW V17: COMPLETE"
    )
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
