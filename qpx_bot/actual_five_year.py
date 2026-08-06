"""Actual-market five-year orchestration using the existing QPX engine."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from qpx_bot.backtest import BacktestResult, run_backtest
from qpx_bot.config import BotConfig
from qpx_bot.market_calendar import NEW_YORK, latest_completed_session
from qpx_bot.paper_state import StateStore
from qpx_bot.performance import (
    BenchmarkResult,
    load_adjusted_bars,
    run_buy_and_hold_benchmark,
)
from qpx_bot.real_data import (
    align_vix_to_candles,
    load_market_csv,
    load_vix_csv,
    sha256_file,
)
from qpx_bot.report import (
    format_backtest_report,
    format_hybrid_report,
    write_equity_curve,
    write_trade_log,
)
from qpx_bot.run_real_backtest import run_real_data_backtest
from qpx_bot.yahoo_data import download_real_dataset


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_SELECTION_RUNTIME = PACKAGE_DIR / "selection_runtime"
DEFAULT_PAPER_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_DATA_ROOT = (
    PROJECT_ROOT / "research_data" / "qpx_actual_five_year"
)
DEFAULT_REPORT_ROOT = (
    PROJECT_ROOT / "reports" / "qpx_actual_five_year"
)
TICKER_PATTERN = re.compile(r"^[A-Z0-9.^-]{1,15}$")
MINIMUM_FIVE_YEAR_BARS = 1_200
MAXIMUM_START_DELAY_DAYS = 10


@dataclass(frozen=True, slots=True)
class SymbolResolution:
    symbol: str
    source: str


@dataclass(frozen=True, slots=True)
class Window:
    requested_start: date
    actual_start: date
    actual_end: date
    bars: int
    calendar_days: int


@dataclass(frozen=True, slots=True)
class FiveYearRun:
    symbol: str
    symbol_source: str
    provider: str
    generated_at_utc: str
    requested_start: str
    actual_start: str
    actual_end: str
    bars: int
    strategy_ending_equity: float
    strategy_total_contributions: float
    strategy_net_profit: float
    strategy_return_on_contributed_capital: float
    strategy_trades: int
    strategy_win_rate: float
    strategy_profit_factor: float | None
    strategy_maximum_drawdown: float
    strategy_signal_count: int
    strategy_rejected_entries: int
    benchmark_ending_equity: float
    benchmark_total_contributions: float
    benchmark_total_return: float
    benchmark_cagr: float
    benchmark_maximum_drawdown: float
    benchmark_uses_adjusted_close: bool
    ending_equity_difference: float
    hybrid_actual_start: str
    hybrid_actual_end: str
    hybrid_actual_bars: int
    hybrid_ending_equity: float
    hybrid_total_contributions: float
    hybrid_net_profit: float
    hybrid_return_on_contributed_capital: float
    forced_entry_indices: None
    live_broker_enabled: bool


def _load_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        return {}

    payload = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(payload, Mapping):
        raise RuntimeError(
            f"JSON root must be an object: {path}"
        )

    return payload


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper()

    if not TICKER_PATTERN.fullmatch(symbol):
        raise ValueError(
            "Ticker contains unsupported characters."
        )

    return symbol


def resolve_symbol(
    *,
    explicit_symbol: str | None,
    selection_runtime: str | Path = DEFAULT_SELECTION_RUNTIME,
    paper_runtime: str | Path = DEFAULT_PAPER_RUNTIME,
) -> SymbolResolution:
    if explicit_symbol:
        return SymbolResolution(
            symbol=normalize_symbol(explicit_symbol),
            source="EXPLICIT_CLI",
        )

    selection_path = (
        Path(selection_runtime).expanduser().resolve()
        / "selection_decision.json"
    )
    selection = _load_json(selection_path)
    selected = str(
        selection.get("selected_symbol", "")
    ).strip()

    if selected:
        return SymbolResolution(
            symbol=normalize_symbol(selected),
            source="CURRENT_SELECTION_DECISION",
        )

    store = StateStore(paper_runtime)

    if store.exists():
        state = store.load()
        return SymbolResolution(
            symbol=normalize_symbol(state.swing_symbol),
            source="PERSISTENT_PAPER_STATE",
        )

    raise RuntimeError(
        "No current swing symbol was found. Pass --symbol "
        "explicitly; no default ticker is substituted."
    )


def subtract_years(day: date, years: int) -> date:
    if years < 1:
        raise ValueError("Years must be positive.")

    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(
            year=day.year - years,
            month=2,
            day=28,
        )


def completed_session(
    current: datetime | None = None,
) -> date:
    moment = current or datetime.now(tz=NEW_YORK)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=NEW_YORK)

    session, _ = latest_completed_session(
        moment.astimezone(NEW_YORK)
    )
    return session


def exact_five_year_candles(
    candles,
    *,
    end_session: date,
) -> tuple[list[Any], Window]:
    requested_start = subtract_years(
        end_session,
        5,
    )
    selected = [
        candle
        for candle in candles
        if requested_start
        <= candle.date
        <= end_session
    ]

    if not selected:
        raise RuntimeError(
            "No actual market bars exist in the requested "
            "five-year window."
        )

    if selected[-1].date != end_session:
        raise RuntimeError(
            "Actual market data is stale. Expected the latest "
            f"completed session {end_session}, but received "
            f"{selected[-1].date}."
        )

    start_delay = (
        selected[0].date - requested_start
    ).days

    if start_delay > MAXIMUM_START_DELAY_DAYS:
        raise RuntimeError(
            "Actual history does not reach the requested "
            f"five-year boundary. First bar: {selected[0].date}; "
            f"target: {requested_start}."
        )

    if len(selected) < MINIMUM_FIVE_YEAR_BARS:
        raise RuntimeError(
            "Too few actual daily bars for a five-year "
            f"backtest: {len(selected)}; "
            f"{MINIMUM_FIVE_YEAR_BARS} required."
        )

    window = Window(
        requested_start=requested_start,
        actual_start=selected[0].date,
        actual_end=selected[-1].date,
        bars=len(selected),
        calendar_days=(
            selected[-1].date
            - selected[0].date
        ).days,
    )
    return selected, window


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _write_json(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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


def _write_benchmark_curve(
    benchmark: BenchmarkResult,
    path: Path,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(
            (
                "Date",
                "Equity",
                "TotalContributions",
            )
        )

        for point in benchmark.points:
            writer.writerow(
                (
                    point.date.isoformat(),
                    f"{point.equity:.6f}",
                    f"{point.total_contributions:.6f}",
                )
            )

    return path


def _benchmark_text(
    benchmark: BenchmarkResult,
) -> str:
    metrics = benchmark.metrics
    return "\n".join(
        (
            "=" * 72,
            "MATCHED ADJUSTED-CLOSE BUY-AND-HOLD",
            "=" * 72,
            f"Symbol                    : {benchmark.symbol}",
            (
                "Adjusted close used       : "
                f"{benchmark.uses_adjusted_close}"
            ),
            (
                "Total contributed capital : "
                f"${benchmark.total_contributions:,.2f}"
            ),
            (
                "Ending equity             : "
                f"${benchmark.ending_equity:,.2f}"
            ),
            (
                "Flow-adjusted total return: "
                f"{metrics.total_return:.2%}"
            ),
            (
                "Flow-adjusted CAGR        : "
                f"{metrics.cagr:.2%}"
            ),
            (
                "Annualized volatility     : "
                f"{metrics.annualized_volatility:.2%}"
            ),
            (
                "Sharpe ratio              : "
                f"{metrics.sharpe_ratio:,.3f}"
            ),
            (
                "Sortino ratio             : "
                f"{metrics.sortino_ratio:,.3f}"
            ),
            (
                "Maximum drawdown          : "
                f"{metrics.maximum_drawdown:.2%}"
            ),
            "=" * 72,
        )
    )


def _actual_hybrid_text(result) -> str:
    return format_hybrid_report(result).replace(
        (
            "Synthetic demo data is execution proof, "
            "not performance evidence."
        ),
        (
            "Actual downloaded daily OHLCV, dividend, "
            "and VIX data; period is limited by QDTE's "
            "real available history."
        ),
    )


def _run_payload(
    *,
    resolution: SymbolResolution,
    window: Window,
    result: BacktestResult,
    benchmark: BenchmarkResult,
    hybrid_result,
    provider: str,
) -> FiveYearRun:
    return FiveYearRun(
        symbol=resolution.symbol,
        symbol_source=resolution.source,
        provider=provider,
        generated_at_utc=datetime.now(
            timezone.utc
        ).isoformat(),
        requested_start=(
            window.requested_start.isoformat()
        ),
        actual_start=window.actual_start.isoformat(),
        actual_end=window.actual_end.isoformat(),
        bars=window.bars,
        strategy_ending_equity=result.ending_equity,
        strategy_total_contributions=(
            result.total_contributions
        ),
        strategy_net_profit=result.net_profit,
        strategy_return_on_contributed_capital=(
            result.return_on_contributed_capital
        ),
        strategy_trades=len(result.trades),
        strategy_win_rate=result.win_rate,
        strategy_profit_factor=_finite_or_none(
            result.profit_factor
        ),
        strategy_maximum_drawdown=(
            result.maximum_drawdown
        ),
        strategy_signal_count=result.signal_count,
        strategy_rejected_entries=(
            result.rejected_entries
        ),
        benchmark_ending_equity=(
            benchmark.ending_equity
        ),
        benchmark_total_contributions=(
            benchmark.total_contributions
        ),
        benchmark_total_return=(
            benchmark.metrics.total_return
        ),
        benchmark_cagr=benchmark.metrics.cagr,
        benchmark_maximum_drawdown=(
            benchmark.metrics.maximum_drawdown
        ),
        benchmark_uses_adjusted_close=(
            benchmark.uses_adjusted_close
        ),
        ending_equity_difference=(
            result.ending_equity
            - benchmark.ending_equity
        ),
        hybrid_actual_start=(
            hybrid_result.start_date.isoformat()
        ),
        hybrid_actual_end=(
            hybrid_result.end_date.isoformat()
        ),
        hybrid_actual_bars=len(
            hybrid_result.equity_curve
        ),
        hybrid_ending_equity=(
            hybrid_result.ending_equity
        ),
        hybrid_total_contributions=(
            hybrid_result.total_contributions
        ),
        hybrid_net_profit=hybrid_result.net_profit,
        hybrid_return_on_contributed_capital=(
            hybrid_result.return_on_contributed_capital
        ),
        forced_entry_indices=None,
        live_broker_enabled=False,
    )


def run_actual_five_year_backtest(
    *,
    symbol: str | None = None,
    data_root: str | Path = DEFAULT_DATA_ROOT,
    report_root: str | Path = DEFAULT_REPORT_ROOT,
    selection_runtime: str | Path = DEFAULT_SELECTION_RUNTIME,
    paper_runtime: str | Path = DEFAULT_PAPER_RUNTIME,
    current: datetime | None = None,
) -> tuple[FiveYearRun, dict[str, Path]]:
    resolution = resolve_symbol(
        explicit_symbol=symbol,
        selection_runtime=selection_runtime,
        paper_runtime=paper_runtime,
    )
    normalized = resolution.symbol
    data_directory = (
        Path(data_root).expanduser().resolve()
        / normalized
        / "inputs"
    )
    output = (
        Path(report_root).expanduser().resolve()
        / normalized
    )
    output.mkdir(parents=True, exist_ok=True)
    backup_directory = (
        Path(data_root).expanduser().resolve()
        / normalized
        / "previous_inputs"
        / datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
    )

    # Six years are requested only to provide a real-data boundary
    # buffer. The existing engine receives exactly five completed years.
    download = download_real_dataset(
        swing_symbol=normalized,
        input_directory=data_directory,
        range_name="6y",
        backup_directory=backup_directory,
    )
    source_manifest_path = (
        data_directory / "DOWNLOAD_MANIFEST.json"
    )
    source_manifest = _load_json(
        source_manifest_path
    )

    if (
        source_manifest.get("provider")
        != "Yahoo Finance chart endpoint"
    ):
        raise RuntimeError(
            "Unexpected market-data provider."
        )

    if source_manifest.get("interval") != "1d":
        raise RuntimeError(
            "Actual backtest requires daily bars."
        )

    swing_path = data_directory / "SWING.csv"
    vix_path = data_directory / "VIX.csv"
    swing_all = load_market_csv(swing_path)
    vix_points = load_vix_csv(vix_path)
    end_session = completed_session(current)
    swing, window = exact_five_year_candles(
        swing_all,
        end_session=end_session,
    )
    vix_values = align_vix_to_candles(
        swing,
        vix_points,
        maximum_gap_days=7,
    )

    config = BotConfig()

    # Existing engine, real inputs, production strategy rules.
    result = run_backtest(
        candles=swing,
        symbol=normalized,
        config=config,
        vix=vix_values,
        forced_entry_indices=None,
    )

    adjusted_bars, uses_adjusted = (
        load_adjusted_bars(swing_path)
    )
    adjusted_window = [
        bar
        for bar in adjusted_bars
        if (
            window.requested_start
            <= bar.date
            <= window.actual_end
        )
    ]

    if (
        not adjusted_window
        or adjusted_window[-1].date
        != window.actual_end
    ):
        raise RuntimeError(
            "Adjusted benchmark data does not match "
            "the five-year strategy window."
        )

    benchmark = run_buy_and_hold_benchmark(
        bars=adjusted_window,
        symbol=normalized,
        config=config,
        uses_adjusted_close=uses_adjusted,
    )

    hybrid_directory = (
        output / "hybrid_actual_available_history"
    )
    (
        hybrid_result,
        hybrid_validation,
        hybrid_artifacts,
    ) = run_real_data_backtest(
        input_directory=data_directory,
        output_directory=hybrid_directory,
        swing_symbol=normalized,
        config=config,
        forced_entry_indices=None,
    )
    hybrid_report = (
        hybrid_directory / "backtest_report.txt"
    )
    hybrid_report.write_text(
        _actual_hybrid_text(hybrid_result) + "\n",
        encoding="utf-8",
    )

    strategy_report_path = (
        output / "actual_five_year_report.txt"
    )
    trades_path = (
        output / "actual_five_year_trades.csv"
    )
    equity_path = (
        output / "actual_five_year_equity.csv"
    )
    benchmark_path = (
        output / "actual_five_year_benchmark.csv"
    )
    result_path = (
        output / "actual_five_year_result.json"
    )
    provenance_path = (
        output / "actual_five_year_provenance.json"
    )

    write_trade_log(result, trades_path)
    write_equity_curve(result, equity_path)
    _write_benchmark_curve(
        benchmark,
        benchmark_path,
    )

    run = _run_payload(
        resolution=resolution,
        window=window,
        result=result,
        benchmark=benchmark,
        hybrid_result=hybrid_result,
        provider=download.provider,
    )

    report = "\n\n".join(
        (
            "\n".join(
                (
                    "=" * 78,
                    "QPX BOT v1.16 — ACTUAL FIVE-YEAR BACKTEST",
                    "=" * 78,
                    f"Data provider             : {download.provider}",
                    (
                        "Selected symbol source    : "
                        f"{resolution.source}"
                    ),
                    f"Selected symbol           : {normalized}",
                    (
                        "Requested completed period: "
                        f"{window.requested_start} to "
                        f"{window.actual_end}"
                    ),
                    (
                        "Actual daily-bar period   : "
                        f"{window.actual_start} to "
                        f"{window.actual_end}"
                    ),
                    f"Actual daily bars         : {window.bars}",
                    (
                        "Existing engine           : "
                        "qpx_bot.backtest.run_backtest"
                    ),
                    "Forced entries             : DISABLED",
                    "Live brokerage             : DISABLED",
                    (
                        "Five-year scope           : "
                        "swing strategy sleeve"
                    ),
                    (
                        "Hybrid scope              : "
                        f"{hybrid_result.start_date} to "
                        f"{hybrid_result.end_date}; limited "
                        "by actual QDTE history"
                    ),
                    "=" * 78,
                )
            ),
            format_backtest_report(result),
            _benchmark_text(benchmark),
            "\n".join(
                (
                    "=" * 72,
                    "FIVE-YEAR STRATEGY VS MATCHED BENCHMARK",
                    "=" * 72,
                    (
                        "Strategy ending equity    : "
                        f"${result.ending_equity:,.2f}"
                    ),
                    (
                        "Benchmark ending equity   : "
                        f"${benchmark.ending_equity:,.2f}"
                    ),
                    (
                        "Ending equity difference  : "
                        f"${run.ending_equity_difference:,.2f}"
                    ),
                    "=" * 72,
                )
            ),
            _actual_hybrid_text(hybrid_result),
        )
    )
    strategy_report_path.write_text(
        report + "\n",
        encoding="utf-8",
    )
    _write_json(
        result_path,
        asdict(run),
    )

    input_paths = {
        "swing": swing_path,
        "income": data_directory / "QDTE.csv",
        "dividends": (
            data_directory / "QDTE_DIVIDENDS.csv"
        ),
        "vix": vix_path,
        "download_manifest": source_manifest_path,
    }
    provenance = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "actual_data": True,
        "data_provider": download.provider,
        "download_requested_range": "6y",
        "backtest_requested_years": 5,
        "completed_session_end": (
            window.actual_end.isoformat()
        ),
        "symbol": normalized,
        "symbol_source": resolution.source,
        "engine": "qpx_bot.backtest.run_backtest",
        "engine_modified": False,
        "forced_entry_indices": None,
        "configuration": asdict(config),
        "inputs": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for name, path in input_paths.items()
        },
        "source_manifest": dict(source_manifest),
        "five_year_window": asdict(window),
        "hybrid_actual_window": {
            "start": (
                hybrid_validation.common_start.isoformat()
                if hybrid_validation.common_start
                else None
            ),
            "end": (
                hybrid_validation.common_end.isoformat()
                if hybrid_validation.common_end
                else None
            ),
            "note": (
                "The full hybrid period is constrained by "
                "QDTE's actual available trading history. "
                "No pre-inception QDTE data was fabricated."
            ),
        },
        "outputs": {
            "report": str(strategy_report_path),
            "result": str(result_path),
            "trades": str(trades_path),
            "equity": str(equity_path),
            "benchmark": str(benchmark_path),
            "hybrid": {
                name: str(path)
                for name, path in hybrid_artifacts.items()
            },
        },
        "live_broker_enabled": False,
    }
    provenance["five_year_window"] = {
        "requested_start": (
            window.requested_start.isoformat()
        ),
        "actual_start": (
            window.actual_start.isoformat()
        ),
        "actual_end": (
            window.actual_end.isoformat()
        ),
        "bars": window.bars,
        "calendar_days": window.calendar_days,
    }
    _write_json(
        provenance_path,
        provenance,
    )

    artifacts = {
        "report": strategy_report_path,
        "result": result_path,
        "trades": trades_path,
        "equity": equity_path,
        "benchmark": benchmark_path,
        "provenance": provenance_path,
        "source_manifest": source_manifest_path,
        "hybrid_report": hybrid_report,
    }
    return run, artifacts


def format_run_summary(
    run: FiveYearRun,
    artifacts: Mapping[str, Path],
) -> str:
    profit_factor = (
        "∞"
        if run.strategy_profit_factor is None
        else f"{run.strategy_profit_factor:,.3f}"
    )
    lines = [
        "=" * 78,
        "QPX ACTUAL FIVE-YEAR BACKTEST: COMPLETE",
        "=" * 78,
        f"Symbol                   : {run.symbol}",
        f"Symbol source            : {run.symbol_source}",
        f"Actual provider          : {run.provider}",
        (
            "Actual period            : "
            f"{run.actual_start} to {run.actual_end}"
        ),
        f"Actual daily bars        : {run.bars}",
        (
            "Strategy ending equity   : "
            f"${run.strategy_ending_equity:,.2f}"
        ),
        (
            "Strategy net profit      : "
            f"${run.strategy_net_profit:,.2f}"
        ),
        (
            "Return on contributions  : "
            f"{run.strategy_return_on_contributed_capital:.2%}"
        ),
        f"Closed trades            : {run.strategy_trades}",
        f"Win rate                 : {run.strategy_win_rate:.2%}",
        f"Profit factor            : {profit_factor}",
        (
            "Maximum drawdown         : "
            f"{run.strategy_maximum_drawdown:.2%}"
        ),
        (
            "Benchmark ending equity  : "
            f"${run.benchmark_ending_equity:,.2f}"
        ),
        (
            "Benchmark flow CAGR      : "
            f"{run.benchmark_cagr:.2%}"
        ),
        (
            "Ending equity difference : "
            f"${run.ending_equity_difference:,.2f}"
        ),
        (
            "Actual hybrid period     : "
            f"{run.hybrid_actual_start} to "
            f"{run.hybrid_actual_end}"
        ),
        (
            "Actual hybrid equity     : "
            f"${run.hybrid_ending_equity:,.2f}"
        ),
        "Forced entries            : DISABLED",
        "Live brokerage            : DISABLED",
        "-" * 78,
        "Artifacts:",
    ]

    for name, path in artifacts.items():
        lines.append(f"  {name:<16} {path}")

    lines.extend(
        (
            "=" * 78,
            (
                "Research simulation using downloaded actual "
                "market data. Results do not guarantee future "
                "performance."
            ),
        )
    )
    return "\n".join(lines)
