#!/usr/bin/env python3
"""Install, test, push, and run the actual five-year QPX backtest."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (
            start,
            *start.parents,
        ):
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
STAMP = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
BACKUP = (
    ROOT
    / "backups"
    / "qpx_actual_five_year_backtest"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.16.0"\n',
    "qpx_bot/actual_five_year.py": '"""Actual-market five-year orchestration using the existing QPX engine."""\n\nfrom __future__ import annotations\n\nimport csv\nimport json\nimport math\nimport re\nfrom dataclasses import asdict, dataclass\nfrom datetime import date, datetime, timedelta, timezone\nfrom pathlib import Path\nfrom typing import Any, Mapping, Sequence\n\nfrom qpx_bot.backtest import BacktestResult, run_backtest\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.market_calendar import NEW_YORK, latest_completed_session\nfrom qpx_bot.paper_state import StateStore\nfrom qpx_bot.performance import (\n    BenchmarkResult,\n    load_adjusted_bars,\n    run_buy_and_hold_benchmark,\n)\nfrom qpx_bot.real_data import (\n    align_vix_to_candles,\n    load_market_csv,\n    load_vix_csv,\n    sha256_file,\n)\nfrom qpx_bot.report import (\n    format_backtest_report,\n    format_hybrid_report,\n    write_equity_curve,\n    write_trade_log,\n)\nfrom qpx_bot.run_real_backtest import run_real_data_backtest\nfrom qpx_bot.yahoo_data import download_real_dataset\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_SELECTION_RUNTIME = PACKAGE_DIR / "selection_runtime"\nDEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_DATA_ROOT = (\n    PROJECT_ROOT / "research_data" / "qpx_actual_five_year"\n)\nDEFAULT_REPORT_ROOT = (\n    PROJECT_ROOT / "reports" / "qpx_actual_five_year"\n)\nTICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,15}$")\nMINIMUM_FIVE_YEAR_BARS = 1_200\nMAXIMUM_START_DELAY_DAYS = 10\n\n\n@dataclass(frozen=True, slots=True)\nclass SymbolResolution:\n    symbol: str\n    source: str\n\n\n@dataclass(frozen=True, slots=True)\nclass Window:\n    requested_start: date\n    actual_start: date\n    actual_end: date\n    bars: int\n    calendar_days: int\n\n\n@dataclass(frozen=True, slots=True)\nclass FiveYearRun:\n    symbol: str\n    symbol_source: str\n    provider: str\n    generated_at_utc: str\n    requested_start: str\n    actual_start: str\n    actual_end: str\n    bars: int\n    strategy_ending_equity: float\n    strategy_total_contributions: float\n    strategy_net_profit: float\n    strategy_return_on_contributed_capital: float\n    strategy_trades: int\n    strategy_win_rate: float\n    strategy_profit_factor: float | None\n    strategy_maximum_drawdown: float\n    strategy_signal_count: int\n    strategy_rejected_entries: int\n    benchmark_ending_equity: float\n    benchmark_total_contributions: float\n    benchmark_total_return: float\n    benchmark_cagr: float\n    benchmark_maximum_drawdown: float\n    benchmark_uses_adjusted_close: bool\n    ending_equity_difference: float\n    hybrid_actual_start: str\n    hybrid_actual_end: str\n    hybrid_actual_bars: int\n    hybrid_ending_equity: float\n    hybrid_total_contributions: float\n    hybrid_net_profit: float\n    hybrid_return_on_contributed_capital: float\n    forced_entry_indices: None\n    live_broker_enabled: bool\n\n\ndef _load_json(path: Path) -> Mapping[str, Any]:\n    if not path.exists():\n        return {}\n\n    payload = json.loads(path.read_text(encoding="utf-8"))\n\n    if not isinstance(payload, Mapping):\n        raise RuntimeError(\n            f"JSON root must be an object: {path}"\n        )\n\n    return payload\n\n\ndef normalize_symbol(value: str) -> str:\n    symbol = value.strip().upper()\n\n    if not TICKER_PATTERN.fullmatch(symbol):\n        raise ValueError(\n            "Ticker contains unsupported characters."\n        )\n\n    return symbol\n\n\ndef resolve_symbol(\n    *,\n    explicit_symbol: str | None,\n    selection_runtime: str | Path = DEFAULT_SELECTION_RUNTIME,\n    paper_runtime: str | Path = DEFAULT_PAPER_RUNTIME,\n) -> SymbolResolution:\n    if explicit_symbol:\n        return SymbolResolution(\n            symbol=normalize_symbol(explicit_symbol),\n            source="EXPLICIT_CLI",\n        )\n\n    selection_path = (\n        Path(selection_runtime).expanduser().resolve()\n        / "selection_decision.json"\n    )\n    selection = _load_json(selection_path)\n    selected = str(\n        selection.get("selected_symbol", "")\n    ).strip()\n\n    if selected:\n        return SymbolResolution(\n            symbol=normalize_symbol(selected),\n            source="CURRENT_SELECTION_DECISION",\n        )\n\n    store = StateStore(paper_runtime)\n\n    if store.exists():\n        state = store.load()\n        return SymbolResolution(\n            symbol=normalize_symbol(state.swing_symbol),\n            source="PERSISTENT_PAPER_STATE",\n        )\n\n    raise RuntimeError(\n        "No current swing symbol was found. Pass --symbol "\n        "explicitly; no default ticker is substituted."\n    )\n\n\ndef subtract_years(day: date, years: int) -> date:\n    if years < 1:\n        raise ValueError("Years must be positive.")\n\n    try:\n        return day.replace(year=day.year - years)\n    except ValueError:\n        return day.replace(\n            year=day.year - years,\n            month=2,\n            day=28,\n        )\n\n\ndef completed_session(\n    current: datetime | None = None,\n) -> date:\n    moment = current or datetime.now(tz=NEW_YORK)\n\n    if moment.tzinfo is None:\n        moment = moment.replace(tzinfo=NEW_YORK)\n\n    session, _ = latest_completed_session(\n        moment.astimezone(NEW_YORK)\n    )\n    return session\n\n\ndef exact_five_year_candles(\n    candles,\n    *,\n    end_session: date,\n) -> tuple[list[Any], Window]:\n    requested_start = subtract_years(\n        end_session,\n        5,\n    )\n    selected = [\n        candle\n        for candle in candles\n        if requested_start\n        <= candle.date\n        <= end_session\n    ]\n\n    if not selected:\n        raise RuntimeError(\n            "No actual market bars exist in the requested "\n            "five-year window."\n        )\n\n    if selected[-1].date != end_session:\n        raise RuntimeError(\n            "Actual market data is stale. Expected the latest "\n            f"completed session {end_session}, but received "\n            f"{selected[-1].date}."\n        )\n\n    start_delay = (\n        selected[0].date - requested_start\n    ).days\n\n    if start_delay > MAXIMUM_START_DELAY_DAYS:\n        raise RuntimeError(\n            "Actual history does not reach the requested "\n            f"five-year boundary. First bar: {selected[0].date}; "\n            f"target: {requested_start}."\n        )\n\n    if len(selected) < MINIMUM_FIVE_YEAR_BARS:\n        raise RuntimeError(\n            "Too few actual daily bars for a five-year "\n            f"backtest: {len(selected)}; "\n            f"{MINIMUM_FIVE_YEAR_BARS} required."\n        )\n\n    window = Window(\n        requested_start=requested_start,\n        actual_start=selected[0].date,\n        actual_end=selected[-1].date,\n        bars=len(selected),\n        calendar_days=(\n            selected[-1].date\n            - selected[0].date\n        ).days,\n    )\n    return selected, window\n\n\ndef _finite_or_none(value: float) -> float | None:\n    return value if math.isfinite(value) else None\n\n\ndef _write_json(\n    path: Path,\n    payload: Mapping[str, Any],\n) -> None:\n    path.parent.mkdir(parents=True, exist_ok=True)\n    temporary = path.with_suffix(\n        path.suffix + ".tmp"\n    )\n    temporary.write_text(\n        json.dumps(\n            payload,\n            indent=2,\n            sort_keys=True,\n            allow_nan=False,\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    temporary.replace(path)\n\n\ndef _write_benchmark_curve(\n    benchmark: BenchmarkResult,\n    path: Path,\n) -> Path:\n    path.parent.mkdir(parents=True, exist_ok=True)\n\n    with path.open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            (\n                "Date",\n                "Equity",\n                "TotalContributions",\n            )\n        )\n\n        for point in benchmark.points:\n            writer.writerow(\n                (\n                    point.date.isoformat(),\n                    f"{point.equity:.6f}",\n                    f"{point.total_contributions:.6f}",\n                )\n            )\n\n    return path\n\n\ndef _benchmark_text(\n    benchmark: BenchmarkResult,\n) -> str:\n    metrics = benchmark.metrics\n    return "\\n".join(\n        (\n            "=" * 72,\n            "MATCHED ADJUSTED-CLOSE BUY-AND-HOLD",\n            "=" * 72,\n            f"Symbol                    : {benchmark.symbol}",\n            (\n                "Adjusted close used       : "\n                f"{benchmark.uses_adjusted_close}"\n            ),\n            (\n                "Total contributed capital : "\n                f"${benchmark.total_contributions:,.2f}"\n            ),\n            (\n                "Ending equity             : "\n                f"${benchmark.ending_equity:,.2f}"\n            ),\n            (\n                "Flow-adjusted total return: "\n                f"{metrics.total_return:.2%}"\n            ),\n            (\n                "Flow-adjusted CAGR        : "\n                f"{metrics.cagr:.2%}"\n            ),\n            (\n                "Annualized volatility     : "\n                f"{metrics.annualized_volatility:.2%}"\n            ),\n            (\n                "Sharpe ratio              : "\n                f"{metrics.sharpe_ratio:,.3f}"\n            ),\n            (\n                "Sortino ratio             : "\n                f"{metrics.sortino_ratio:,.3f}"\n            ),\n            (\n                "Maximum drawdown          : "\n                f"{metrics.maximum_drawdown:.2%}"\n            ),\n            "=" * 72,\n        )\n    )\n\n\ndef _actual_hybrid_text(result) -> str:\n    return format_hybrid_report(result).replace(\n        (\n            "Synthetic demo data is execution proof, "\n            "not performance evidence."\n        ),\n        (\n            "Actual downloaded daily OHLCV, dividend, "\n            "and VIX data; period is limited by QDTE\'s "\n            "real available history."\n        ),\n    )\n\n\ndef _run_payload(\n    *,\n    resolution: SymbolResolution,\n    window: Window,\n    result: BacktestResult,\n    benchmark: BenchmarkResult,\n    hybrid_result,\n    provider: str,\n) -> FiveYearRun:\n    return FiveYearRun(\n        symbol=resolution.symbol,\n        symbol_source=resolution.source,\n        provider=provider,\n        generated_at_utc=datetime.now(\n            timezone.utc\n        ).isoformat(),\n        requested_start=(\n            window.requested_start.isoformat()\n        ),\n        actual_start=window.actual_start.isoformat(),\n        actual_end=window.actual_end.isoformat(),\n        bars=window.bars,\n        strategy_ending_equity=result.ending_equity,\n        strategy_total_contributions=(\n            result.total_contributions\n        ),\n        strategy_net_profit=result.net_profit,\n        strategy_return_on_contributed_capital=(\n            result.return_on_contributed_capital\n        ),\n        strategy_trades=len(result.trades),\n        strategy_win_rate=result.win_rate,\n        strategy_profit_factor=_finite_or_none(\n            result.profit_factor\n        ),\n        strategy_maximum_drawdown=(\n            result.maximum_drawdown\n        ),\n        strategy_signal_count=result.signal_count,\n        strategy_rejected_entries=(\n            result.rejected_entries\n        ),\n        benchmark_ending_equity=(\n            benchmark.ending_equity\n        ),\n        benchmark_total_contributions=(\n            benchmark.total_contributions\n        ),\n        benchmark_total_return=(\n            benchmark.metrics.total_return\n        ),\n        benchmark_cagr=benchmark.metrics.cagr,\n        benchmark_maximum_drawdown=(\n            benchmark.metrics.maximum_drawdown\n        ),\n        benchmark_uses_adjusted_close=(\n            benchmark.uses_adjusted_close\n        ),\n        ending_equity_difference=(\n            result.ending_equity\n            - benchmark.ending_equity\n        ),\n        hybrid_actual_start=(\n            hybrid_result.start_date.isoformat()\n        ),\n        hybrid_actual_end=(\n            hybrid_result.end_date.isoformat()\n        ),\n        hybrid_actual_bars=len(\n            hybrid_result.equity_curve\n        ),\n        hybrid_ending_equity=(\n            hybrid_result.ending_equity\n        ),\n        hybrid_total_contributions=(\n            hybrid_result.total_contributions\n        ),\n        hybrid_net_profit=hybrid_result.net_profit,\n        hybrid_return_on_contributed_capital=(\n            hybrid_result.return_on_contributed_capital\n        ),\n        forced_entry_indices=None,\n        live_broker_enabled=False,\n    )\n\n\ndef run_actual_five_year_backtest(\n    *,\n    symbol: str | None = None,\n    data_root: str | Path = DEFAULT_DATA_ROOT,\n    report_root: str | Path = DEFAULT_REPORT_ROOT,\n    selection_runtime: str | Path = DEFAULT_SELECTION_RUNTIME,\n    paper_runtime: str | Path = DEFAULT_PAPER_RUNTIME,\n    current: datetime | None = None,\n) -> tuple[FiveYearRun, dict[str, Path]]:\n    resolution = resolve_symbol(\n        explicit_symbol=symbol,\n        selection_runtime=selection_runtime,\n        paper_runtime=paper_runtime,\n    )\n    normalized = resolution.symbol\n    data_directory = (\n        Path(data_root).expanduser().resolve()\n        / normalized\n        / "inputs"\n    )\n    output = (\n        Path(report_root).expanduser().resolve()\n        / normalized\n    )\n    output.mkdir(parents=True, exist_ok=True)\n    backup_directory = (\n        Path(data_root).expanduser().resolve()\n        / normalized\n        / "previous_inputs"\n        / datetime.now().strftime(\n            "%Y%m%d_%H%M%S"\n        )\n    )\n\n    # Six years are requested only to provide a real-data boundary\n    # buffer. The existing engine receives exactly five completed years.\n    download = download_real_dataset(\n        swing_symbol=normalized,\n        input_directory=data_directory,\n        range_name="6y",\n        backup_directory=backup_directory,\n    )\n    source_manifest_path = (\n        data_directory / "DOWNLOAD_MANIFEST.json"\n    )\n    source_manifest = _load_json(\n        source_manifest_path\n    )\n\n    if (\n        source_manifest.get("provider")\n        != "Yahoo Finance chart endpoint"\n    ):\n        raise RuntimeError(\n            "Unexpected market-data provider."\n        )\n\n    if source_manifest.get("interval") != "1d":\n        raise RuntimeError(\n            "Actual backtest requires daily bars."\n        )\n\n    swing_path = data_directory / "SWING.csv"\n    vix_path = data_directory / "VIX.csv"\n    swing_all = load_market_csv(swing_path)\n    vix_points = load_vix_csv(vix_path)\n    end_session = completed_session(current)\n    swing, window = exact_five_year_candles(\n        swing_all,\n        end_session=end_session,\n    )\n    vix_values = align_vix_to_candles(\n        swing,\n        vix_points,\n        maximum_gap_days=7,\n    )\n\n    config = BotConfig()\n\n    # Existing engine, real inputs, production strategy rules.\n    result = run_backtest(\n        candles=swing,\n        symbol=normalized,\n        config=config,\n        vix=vix_values,\n        forced_entry_indices=None,\n    )\n\n    adjusted_bars, uses_adjusted = (\n        load_adjusted_bars(swing_path)\n    )\n    adjusted_window = [\n        bar\n        for bar in adjusted_bars\n        if (\n            window.requested_start\n            <= bar.date\n            <= window.actual_end\n        )\n    ]\n\n    if (\n        not adjusted_window\n        or adjusted_window[-1].date\n        != window.actual_end\n    ):\n        raise RuntimeError(\n            "Adjusted benchmark data does not match "\n            "the five-year strategy window."\n        )\n\n    benchmark = run_buy_and_hold_benchmark(\n        bars=adjusted_window,\n        symbol=normalized,\n        config=config,\n        uses_adjusted_close=uses_adjusted,\n    )\n\n    hybrid_directory = (\n        output / "hybrid_actual_available_history"\n    )\n    (\n        hybrid_result,\n        hybrid_validation,\n        hybrid_artifacts,\n    ) = run_real_data_backtest(\n        input_directory=data_directory,\n        output_directory=hybrid_directory,\n        swing_symbol=normalized,\n        config=config,\n        forced_entry_indices=None,\n    )\n    hybrid_report = (\n        hybrid_directory / "backtest_report.txt"\n    )\n    hybrid_report.write_text(\n        _actual_hybrid_text(hybrid_result) + "\\n",\n        encoding="utf-8",\n    )\n\n    strategy_report_path = (\n        output / "actual_five_year_report.txt"\n    )\n    trades_path = (\n        output / "actual_five_year_trades.csv"\n    )\n    equity_path = (\n        output / "actual_five_year_equity.csv"\n    )\n    benchmark_path = (\n        output / "actual_five_year_benchmark.csv"\n    )\n    result_path = (\n        output / "actual_five_year_result.json"\n    )\n    provenance_path = (\n        output / "actual_five_year_provenance.json"\n    )\n\n    write_trade_log(result, trades_path)\n    write_equity_curve(result, equity_path)\n    _write_benchmark_curve(\n        benchmark,\n        benchmark_path,\n    )\n\n    run = _run_payload(\n        resolution=resolution,\n        window=window,\n        result=result,\n        benchmark=benchmark,\n        hybrid_result=hybrid_result,\n        provider=download.provider,\n    )\n\n    report = "\\n\\n".join(\n        (\n            "\\n".join(\n                (\n                    "=" * 78,\n                    "QPX BOT v1.16 — ACTUAL FIVE-YEAR BACKTEST",\n                    "=" * 78,\n                    f"Data provider             : {download.provider}",\n                    (\n                        "Selected symbol source    : "\n                        f"{resolution.source}"\n                    ),\n                    f"Selected symbol           : {normalized}",\n                    (\n                        "Requested completed period: "\n                        f"{window.requested_start} to "\n                        f"{window.actual_end}"\n                    ),\n                    (\n                        "Actual daily-bar period   : "\n                        f"{window.actual_start} to "\n                        f"{window.actual_end}"\n                    ),\n                    f"Actual daily bars         : {window.bars}",\n                    (\n                        "Existing engine           : "\n                        "qpx_bot.backtest.run_backtest"\n                    ),\n                    "Forced entries             : DISABLED",\n                    "Live brokerage             : DISABLED",\n                    (\n                        "Five-year scope           : "\n                        "swing strategy sleeve"\n                    ),\n                    (\n                        "Hybrid scope              : "\n                        f"{hybrid_result.start_date} to "\n                        f"{hybrid_result.end_date}; limited "\n                        "by actual QDTE history"\n                    ),\n                    "=" * 78,\n                )\n            ),\n            format_backtest_report(result),\n            _benchmark_text(benchmark),\n            "\\n".join(\n                (\n                    "=" * 72,\n                    "FIVE-YEAR STRATEGY VS MATCHED BENCHMARK",\n                    "=" * 72,\n                    (\n                        "Strategy ending equity    : "\n                        f"${result.ending_equity:,.2f}"\n                    ),\n                    (\n                        "Benchmark ending equity   : "\n                        f"${benchmark.ending_equity:,.2f}"\n                    ),\n                    (\n                        "Ending equity difference  : "\n                        f"${run.ending_equity_difference:,.2f}"\n                    ),\n                    "=" * 72,\n                )\n            ),\n            _actual_hybrid_text(hybrid_result),\n        )\n    )\n    strategy_report_path.write_text(\n        report + "\\n",\n        encoding="utf-8",\n    )\n    _write_json(\n        result_path,\n        asdict(run),\n    )\n\n    input_paths = {\n        "swing": swing_path,\n        "income": data_directory / "QDTE.csv",\n        "dividends": (\n            data_directory / "QDTE_DIVIDENDS.csv"\n        ),\n        "vix": vix_path,\n        "download_manifest": source_manifest_path,\n    }\n    provenance = {\n        "schema_version": 1,\n        "generated_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "actual_data": True,\n        "data_provider": download.provider,\n        "download_requested_range": "6y",\n        "backtest_requested_years": 5,\n        "completed_session_end": (\n            window.actual_end.isoformat()\n        ),\n        "symbol": normalized,\n        "symbol_source": resolution.source,\n        "engine": "qpx_bot.backtest.run_backtest",\n        "engine_modified": False,\n        "forced_entry_indices": None,\n        "configuration": asdict(config),\n        "inputs": {\n            name: {\n                "path": str(path),\n                "sha256": sha256_file(path),\n            }\n            for name, path in input_paths.items()\n        },\n        "source_manifest": dict(source_manifest),\n        "five_year_window": asdict(window),\n        "hybrid_actual_window": {\n            "start": (\n                hybrid_validation.common_start.isoformat()\n                if hybrid_validation.common_start\n                else None\n            ),\n            "end": (\n                hybrid_validation.common_end.isoformat()\n                if hybrid_validation.common_end\n                else None\n            ),\n            "note": (\n                "The full hybrid period is constrained by "\n                "QDTE\'s actual available trading history. "\n                "No pre-inception QDTE data was fabricated."\n            ),\n        },\n        "outputs": {\n            "report": str(strategy_report_path),\n            "result": str(result_path),\n            "trades": str(trades_path),\n            "equity": str(equity_path),\n            "benchmark": str(benchmark_path),\n            "hybrid": {\n                name: str(path)\n                for name, path in hybrid_artifacts.items()\n            },\n        },\n        "live_broker_enabled": False,\n    }\n    provenance["five_year_window"] = {\n        "requested_start": (\n            window.requested_start.isoformat()\n        ),\n        "actual_start": (\n            window.actual_start.isoformat()\n        ),\n        "actual_end": (\n            window.actual_end.isoformat()\n        ),\n        "bars": window.bars,\n        "calendar_days": window.calendar_days,\n    }\n    _write_json(\n        provenance_path,\n        provenance,\n    )\n\n    artifacts = {\n        "report": strategy_report_path,\n        "result": result_path,\n        "trades": trades_path,\n        "equity": equity_path,\n        "benchmark": benchmark_path,\n        "provenance": provenance_path,\n        "source_manifest": source_manifest_path,\n        "hybrid_report": hybrid_report,\n    }\n    return run, artifacts\n\n\ndef format_run_summary(\n    run: FiveYearRun,\n    artifacts: Mapping[str, Path],\n) -> str:\n    profit_factor = (\n        "∞"\n        if run.strategy_profit_factor is None\n        else f"{run.strategy_profit_factor:,.3f}"\n    )\n    lines = [\n        "=" * 78,\n        "QPX ACTUAL FIVE-YEAR BACKTEST: COMPLETE",\n        "=" * 78,\n        f"Symbol                   : {run.symbol}",\n        f"Symbol source            : {run.symbol_source}",\n        f"Actual provider          : {run.provider}",\n        (\n            "Actual period            : "\n            f"{run.actual_start} to {run.actual_end}"\n        ),\n        f"Actual daily bars        : {run.bars}",\n        (\n            "Strategy ending equity   : "\n            f"${run.strategy_ending_equity:,.2f}"\n        ),\n        (\n            "Strategy net profit      : "\n            f"${run.strategy_net_profit:,.2f}"\n        ),\n        (\n            "Return on contributions  : "\n            f"{run.strategy_return_on_contributed_capital:.2%}"\n        ),\n        f"Closed trades            : {run.strategy_trades}",\n        f"Win rate                 : {run.strategy_win_rate:.2%}",\n        f"Profit factor            : {profit_factor}",\n        (\n            "Maximum drawdown         : "\n            f"{run.strategy_maximum_drawdown:.2%}"\n        ),\n        (\n            "Benchmark ending equity  : "\n            f"${run.benchmark_ending_equity:,.2f}"\n        ),\n        (\n            "Benchmark flow CAGR      : "\n            f"{run.benchmark_cagr:.2%}"\n        ),\n        (\n            "Ending equity difference : "\n            f"${run.ending_equity_difference:,.2f}"\n        ),\n        (\n            "Actual hybrid period     : "\n            f"{run.hybrid_actual_start} to "\n            f"{run.hybrid_actual_end}"\n        ),\n        (\n            "Actual hybrid equity     : "\n            f"${run.hybrid_ending_equity:,.2f}"\n        ),\n        "Forced entries            : DISABLED",\n        "Live brokerage            : DISABLED",\n        "-" * 78,\n        "Artifacts:",\n    ]\n\n    for name, path in artifacts.items():\n        lines.append(f"  {name:<16} {path}")\n\n    lines.extend(\n        (\n            "=" * 78,\n            (\n                "Research simulation using downloaded actual "\n                "market data. Results do not guarantee future "\n                "performance."\n            ),\n        )\n    )\n    return "\\n".join(lines)\n',
    "QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py": '#!/usr/bin/env python3\n"""Download actual data and run the existing QPX engine for five years."""\n\nfrom __future__ import annotations\n\nimport argparse\nfrom typing import Sequence\n\nfrom qpx_bot.actual_five_year import (\n    format_run_summary,\n    run_actual_five_year_backtest,\n)\n\n\ndef _parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Download actual Yahoo daily data and execute the "\n            "existing QPX strategy engine over five completed years."\n        )\n    )\n    parser.add_argument(\n        "--symbol",\n        default=None,\n        help=(\n            "Optional explicit ticker. Without this argument, "\n            "the current data-driven selection is used. No "\n            "fallback ticker is substituted."\n        ),\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _parser().parse_args(argv)\n    run, artifacts = run_actual_five_year_backtest(\n        symbol=args.symbol,\n    )\n    print(format_run_summary(run, artifacts))\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_actual_five_year.py": 'import json\nfrom datetime import date\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.actual_five_year import (\n    normalize_symbol,\n    resolve_symbol,\n    subtract_years,\n)\n\n\nassert normalize_symbol("xlk") == "XLK"\nassert normalize_symbol("^vix") == "^VIX"\nassert subtract_years(\n    date(2024, 2, 29),\n    5,\n) == date(2019, 2, 28)\n\ntry:\n    normalize_symbol("not a ticker")\nexcept ValueError:\n    pass\nelse:\n    raise AssertionError(\n        "Invalid ticker text was accepted."\n    )\n\nwith TemporaryDirectory() as temporary_directory:\n    root = Path(temporary_directory)\n    selection = root / "selection"\n    selection.mkdir(parents=True)\n    (\n        selection / "selection_decision.json"\n    ).write_text(\n        json.dumps(\n            {\n                "selected_symbol": "XLK",\n                "symbol_bonus_policy": "none",\n            }\n        )\n        + "\\n",\n        encoding="utf-8",\n    )\n    resolution = resolve_symbol(\n        explicit_symbol=None,\n        selection_runtime=selection,\n        paper_runtime=root / "paper",\n    )\n    assert resolution.symbol == "XLK"\n    assert (\n        resolution.source\n        == "CURRENT_SELECTION_DECISION"\n    )\n\n    explicit = resolve_symbol(\n        explicit_symbol="IWM",\n        selection_runtime=selection,\n        paper_runtime=root / "paper",\n    )\n    assert explicit.symbol == "IWM"\n    assert explicit.source == "EXPLICIT_CLI"\n\nsource = (\n    Path(__file__).resolve().parents[1]\n    / "qpx_bot"\n    / "actual_five_year.py"\n).read_text(encoding="utf-8")\n\nassert "run_backtest(" in source\nassert "forced_entry_indices=None" in source\nassert \'range_name="6y"\' in source\nassert "download_real_dataset(" in source\nassert "MINIMUM_FIVE_YEAR_BARS = 1_200" in source\nassert "No pre-inception QDTE data was fabricated." in source\nassert "forced_entry_indices={" not in source\n\nprint("QPX Bot Actual Five-Year Backtest Runner PASS")\n',
    "qpx_bot/ACTUAL_FIVE_YEAR_BACKTEST_README.txt": 'QPX ACTUAL FIVE-YEAR BACKTEST\n=============================\n\nThis runner uses the existing QPX backtest engine. It does not replace\nor reimplement strategy execution.\n\nCommand\n-------\n\npython QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py\n\nThe current data-driven selection is used. To research another ticker\nexplicitly:\n\npython QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py --symbol XLK\n\nNo default or fallback ticker is substituted.\n\nActual-data rules\n-----------------\n\n- Data is downloaded from the Yahoo Finance chart endpoint.\n- Daily OHLCV and adjusted closes are retained.\n- Actual VIX closes are aligned to the swing bars.\n- Actual QDTE distributions are downloaded.\n- Six years are requested as a boundary buffer.\n- The existing swing engine receives exactly five completed market\n  years, ending at the latest completed session.\n- At least 1,200 actual daily bars are required.\n- Stale data is rejected.\n- forced_entry_indices is always None.\n- The current BotConfig is used without a backtest-only optimization.\n- The live paper data folder is not modified.\n- Input hashes and the provider manifest are preserved.\n\nTwo honest results are produced\n-------------------------------\n\n1. ACTUAL FIVE-YEAR SWING STRATEGY\n\nThe existing qpx_bot.backtest.run_backtest engine executes the current\nswing rules for five completed years using the selected ticker and real\nVIX values. A matched adjusted-close buy-and-hold benchmark receives\nthe same starting cash and monthly contributions.\n\n2. ACTUAL HYBRID AVAILABLE HISTORY\n\nThe existing hybrid engine uses real QDTE prices and distributions.\nQDTE began trading in 2024, so a genuine five-year hybrid history does\nnot exist. The hybrid report is limited to actual overlapping history.\nNo QDTE prices, distributions, or options returns are synthesized\nbefore inception.\n\nOutputs\n-------\n\nreports/qpx_actual_five_year/<SYMBOL>/\n    actual_five_year_report.txt\n    actual_five_year_result.json\n    actual_five_year_trades.csv\n    actual_five_year_equity.csv\n    actual_five_year_benchmark.csv\n    actual_five_year_provenance.json\n    hybrid_actual_available_history/\n\nActual source files are stored separately from live paper inputs:\n\nresearch_data/qpx_actual_five_year/<SYMBOL>/inputs/\n\nThis is historical research, not a guarantee of future results. No\nbrokerage connection or live order path is enabled.\n',
}

GITIGNORE_APPEND = '# QPX actual five-year research data and reports\nresearch_data/qpx_actual_five_year/\nreports/qpx_actual_five_year/\n'
TARGETS = [*FILES, ".gitignore"]
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


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative,
            ],
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

        if (
            worktree.returncode != 0
            or staged.returncode != 0
        ):
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
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
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            path,
            backup_path,
        )


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(
                content
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        if path.name.startswith("QPX_RUN_"):
            path.chmod(0o700)

        print(f"Installed: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(
        encoding="utf-8"
    )
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print(
        "Restoring previous target files..."
    )

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

    run([
        "git",
        "add",
        "--",
        *paths,
    ])

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print(
            "Actual five-year runner is already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Add actual five-year QPX "
            "backtest runner"
        ),
    ])

    branch = subprocess.check_output(
        [
            "git",
            "branch",
            "--show-current",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run([
        "git",
        "push",
        "origin",
        branch,
    ])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — ACTUAL FIVE-YEAR "
        "BACKTEST INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    install_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            "tests.test_qpx_bot_actual_five_year",
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
    print(
        "Downloading actual market data and running "
        "the existing QPX engine..."
    )
    print()

    result = run(
        [
            sys.executable,
            "QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py",
        ],
        check=False,
    )

    if result.returncode != 0:
        print()
        print("=" * 78)
        print(
            "QPX ACTUAL FIVE-YEAR RUNNER: "
            "INSTALLED AND PUSHED"
        )
        print(
            "ACTUAL DATA RUN: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py"
        )
        return result.returncode

    print()
    print("=" * 78)
    print(
        "QPX ACTUAL FIVE-YEAR BACKTEST: COMPLETE"
    )
    print("=" * 78)
    print(
        "Actual provider data, existing QPX engine, "
        "no forced entries, and no live brokerage."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
