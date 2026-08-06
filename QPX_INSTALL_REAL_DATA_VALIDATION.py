#!/usr/bin/env python3
"""Install, test, commit, and push QPX real-data validation."""

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
BACKUP = ROOT / "backups" / "qpx_real_data_validation" / STAMP

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nBacktesting bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.6.0"\n',
    "qpx_bot/real_data.py": '"""Flexible real-market CSV ingestion for QPX Bot."""\n\nfrom __future__ import annotations\n\nimport csv\nimport hashlib\nfrom dataclasses import dataclass\nfrom datetime import date, datetime, timezone\nfrom pathlib import Path\nfrom typing import Iterable, Mapping, Sequence\n\nfrom qpx_bot.data_loader import Candle\n\n\nDATE_NAMES = ("date", "time", "datetime", "timestamp")\nOPEN_NAMES = ("open",)\nHIGH_NAMES = ("high",)\nLOW_NAMES = ("low",)\nCLOSE_NAMES = ("close", "adj close", "adjusted close")\nVOLUME_NAMES = ("volume", "vol")\nVIX_NAMES = ("vix", "close", "value")\n\n\n@dataclass(frozen=True, slots=True)\nclass VixPoint:\n    """One daily VIX closing observation."""\n\n    date: date\n    value: float\n\n    def validate(self) -> None:\n        if self.value < 0:\n            raise ValueError("VIX cannot be negative.")\n\n\ndef _normalized_headers(\n    fieldnames: Sequence[str] | None,\n) -> dict[str, str]:\n    if not fieldnames:\n        raise ValueError("CSV file does not contain a header.")\n\n    mapping: dict[str, str] = {}\n\n    for original in fieldnames:\n        normalized = original.strip().lower()\n        if normalized:\n            mapping[normalized] = original\n\n    return mapping\n\n\ndef _find_column(\n    headers: Mapping[str, str],\n    candidates: Sequence[str],\n    label: str,\n) -> str:\n    for candidate in candidates:\n        if candidate in headers:\n            return headers[candidate]\n\n    raise ValueError(\n        f"CSV file does not contain a {label} column. "\n        f"Accepted names: {\', \'.join(candidates)}"\n    )\n\n\ndef _parse_date(raw_value: str) -> date:\n    value = str(raw_value).strip()\n\n    if not value:\n        raise ValueError("Date value is empty.")\n\n    try:\n        numeric = float(value)\n    except ValueError:\n        numeric = None\n\n    if numeric is not None:\n        if numeric > 10_000_000_000:\n            numeric /= 1000.0\n\n        return datetime.fromtimestamp(\n            numeric,\n            tz=timezone.utc,\n        ).date()\n\n    iso_candidate = value.replace("Z", "+00:00")\n\n    try:\n        return datetime.fromisoformat(iso_candidate).date()\n    except ValueError:\n        pass\n\n    for date_format in (\n        "%Y-%m-%d",\n        "%Y/%m/%d",\n        "%m/%d/%Y",\n        "%d/%m/%Y",\n    ):\n        try:\n            return datetime.strptime(value, date_format).date()\n        except ValueError:\n            continue\n\n    raise ValueError(f"Unsupported date/time value: {raw_value!r}")\n\n\ndef _load_rows(path: Path) -> tuple[list[dict[str, str]], dict[str, str]]:\n    if not path.exists():\n        raise FileNotFoundError(f"CSV file was not found: {path}")\n\n    if not path.is_file():\n        raise ValueError(f"CSV path is not a file: {path}")\n\n    with path.open("r", newline="", encoding="utf-8-sig") as file:\n        reader = csv.DictReader(file)\n        headers = _normalized_headers(reader.fieldnames)\n        rows = list(reader)\n\n    if not rows:\n        raise ValueError(f"CSV file contains no data rows: {path}")\n\n    return rows, headers\n\n\ndef load_market_csv(filename: str | Path) -> list[Candle]:\n    """\n    Load daily OHLCV from TradingView or conventional CSV exports.\n\n    Column matching is case-insensitive. The date/time column may be an\n    ISO timestamp, calendar date, Unix seconds, or Unix milliseconds.\n    """\n    path = Path(filename).expanduser().resolve()\n    rows, headers = _load_rows(path)\n\n    date_column = _find_column(headers, DATE_NAMES, "date/time")\n    open_column = _find_column(headers, OPEN_NAMES, "open")\n    high_column = _find_column(headers, HIGH_NAMES, "high")\n    low_column = _find_column(headers, LOW_NAMES, "low")\n    close_column = _find_column(headers, CLOSE_NAMES, "close")\n    volume_column = _find_column(headers, VOLUME_NAMES, "volume")\n\n    candles: list[Candle] = []\n\n    for line_number, row in enumerate(rows, start=2):\n        try:\n            candle = Candle(\n                date=_parse_date(row[date_column]),\n                open=float(row[open_column]),\n                high=float(row[high_column]),\n                low=float(row[low_column]),\n                close=float(row[close_column]),\n                volume=int(float(row[volume_column])),\n            )\n            candle.validate()\n            candles.append(candle)\n        except (TypeError, ValueError, KeyError) as exc:\n            raise ValueError(\n                f"Invalid OHLCV data in {path.name} on line "\n                f"{line_number}: {exc}"\n            ) from exc\n\n    candles.sort(key=lambda candle: candle.date)\n    dates = [candle.date for candle in candles]\n\n    if len(dates) != len(set(dates)):\n        raise ValueError(\n            f"{path.name} contains duplicate calendar dates. "\n            "Export one daily bar per date."\n        )\n\n    return candles\n\n\ndef load_vix_csv(filename: str | Path) -> list[VixPoint]:\n    """\n    Load daily VIX values.\n\n    Supports Date,VIX files and TradingView VIX OHLCV exports, where\n    the daily close is used.\n    """\n    path = Path(filename).expanduser().resolve()\n    rows, headers = _load_rows(path)\n\n    date_column = _find_column(headers, DATE_NAMES, "date/time")\n    value_column = _find_column(headers, VIX_NAMES, "VIX/close")\n\n    points: list[VixPoint] = []\n\n    for line_number, row in enumerate(rows, start=2):\n        try:\n            point = VixPoint(\n                date=_parse_date(row[date_column]),\n                value=float(row[value_column]),\n            )\n            point.validate()\n            points.append(point)\n        except (TypeError, ValueError, KeyError) as exc:\n            raise ValueError(\n                f"Invalid VIX data in {path.name} on line "\n                f"{line_number}: {exc}"\n            ) from exc\n\n    points.sort(key=lambda point: point.date)\n    dates = [point.date for point in points]\n\n    if len(dates) != len(set(dates)):\n        raise ValueError(\n            f"{path.name} contains duplicate VIX dates."\n        )\n\n    return points\n\n\ndef align_vix_to_candles(\n    candles: Sequence[Candle],\n    points: Sequence[VixPoint],\n    *,\n    maximum_gap_days: int = 7,\n) -> list[float]:\n    """\n    Align VIX closes to swing candles using prior-value carry-forward.\n\n    Carry-forward is limited so missing data cannot silently span a\n    large historical gap.\n    """\n    if not candles:\n        raise ValueError("Cannot align VIX to an empty candle series.")\n\n    if not points:\n        raise ValueError("VIX series cannot be empty.")\n\n    if maximum_gap_days < 0:\n        raise ValueError("Maximum VIX gap cannot be negative.")\n\n    values: list[float] = []\n    point_index = 0\n    latest: VixPoint | None = None\n\n    for candle in candles:\n        while (\n            point_index < len(points)\n            and points[point_index].date <= candle.date\n        ):\n            latest = points[point_index]\n            point_index += 1\n\n        if latest is None:\n            raise ValueError(\n                "VIX history begins after the first swing candle."\n            )\n\n        gap = (candle.date - latest.date).days\n\n        if gap > maximum_gap_days:\n            raise ValueError(\n                f"VIX data gap is {gap} days on {candle.date}; "\n                f"maximum allowed is {maximum_gap_days}."\n            )\n\n        values.append(latest.value)\n\n    return values\n\n\ndef trim_market_history(\n    candles: Sequence[Candle],\n    *,\n    start_date: date,\n    end_date: date,\n) -> list[Candle]:\n    if start_date > end_date:\n        raise ValueError("Trim start date is after end date.")\n\n    return [\n        candle\n        for candle in candles\n        if start_date <= candle.date <= end_date\n    ]\n\n\ndef sha256_file(filename: str | Path) -> str:\n    """Return a reproducibility hash for one input file."""\n    path = Path(filename)\n    digest = hashlib.sha256()\n\n    with path.open("rb") as file:\n        for chunk in iter(lambda: file.read(1024 * 1024), b""):\n            digest.update(chunk)\n\n    return digest.hexdigest()\n',
    "qpx_bot/validation.py": '"""Readiness checks for real QPX Bot historical data."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import asdict, dataclass\nfrom datetime import date\nimport json\nfrom pathlib import Path\nfrom typing import Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.data_loader import Candle\nfrom qpx_bot.dividends import DividendEvent\nfrom qpx_bot.real_data import VixPoint\n\n\n@dataclass(frozen=True, slots=True)\nclass ValidationCheck:\n    name: str\n    passed: bool\n    detail: str\n    severity: str = "error"\n\n\n@dataclass(frozen=True, slots=True)\nclass RealDataValidation:\n    ready: bool\n    common_start: date | None\n    common_end: date | None\n    swing_bars: int\n    income_bars: int\n    vix_points: int\n    dividend_events: int\n    checks: tuple[ValidationCheck, ...]\n\n    def format_text(self) -> str:\n        lines = [\n            "=" * 74,\n            "QPX REAL-DATA READINESS REPORT",\n            "=" * 74,\n            f"Ready          : {\'YES\' if self.ready else \'NO\'}",\n            f"Common start   : {self.common_start or \'none\'}",\n            f"Common end     : {self.common_end or \'none\'}",\n            f"Swing bars     : {self.swing_bars}",\n            f"Income bars    : {self.income_bars}",\n            f"VIX points     : {self.vix_points}",\n            f"Dividend events: {self.dividend_events}",\n            "-" * 74,\n        ]\n\n        for check in self.checks:\n            status = "PASS" if check.passed else "FAIL"\n            lines.append(\n                f"{status:<5} {check.name:<28} {check.detail}"\n            )\n\n        lines.append("=" * 74)\n        return "\\n".join(lines)\n\n    def write_json(self, filename: str | Path) -> Path:\n        path = Path(filename)\n        path.parent.mkdir(parents=True, exist_ok=True)\n        payload = asdict(self)\n        payload["common_start"] = (\n            self.common_start.isoformat()\n            if self.common_start\n            else None\n        )\n        payload["common_end"] = (\n            self.common_end.isoformat()\n            if self.common_end\n            else None\n        )\n        path.write_text(\n            json.dumps(payload, indent=2),\n            encoding="utf-8",\n        )\n        return path\n\n\ndef validate_real_data(\n    *,\n    swing_candles: Sequence[Candle],\n    income_candles: Sequence[Candle],\n    vix_points: Sequence[VixPoint],\n    dividends: Sequence[DividendEvent],\n    config: BotConfig,\n) -> RealDataValidation:\n    config.validate()\n    checks: list[ValidationCheck] = []\n\n    common_start: date | None = None\n    common_end: date | None = None\n\n    nonempty = (\n        bool(swing_candles)\n        and bool(income_candles)\n        and bool(vix_points)\n    )\n    checks.append(\n        ValidationCheck(\n            name="required histories",\n            passed=nonempty,\n            detail=(\n                "swing, income, and VIX histories are present"\n                if nonempty\n                else "one or more required histories are empty"\n            ),\n        )\n    )\n\n    if nonempty:\n        common_start = max(\n            swing_candles[0].date,\n            income_candles[0].date,\n            vix_points[0].date,\n        )\n        common_end = min(\n            swing_candles[-1].date,\n            income_candles[-1].date,\n            vix_points[-1].date,\n        )\n\n    overlap_valid = (\n        common_start is not None\n        and common_end is not None\n        and common_start <= common_end\n    )\n    checks.append(\n        ValidationCheck(\n            name="date overlap",\n            passed=overlap_valid,\n            detail=(\n                f"{common_start} through {common_end}"\n                if overlap_valid\n                else "histories do not share a usable date range"\n            ),\n        )\n    )\n\n    required_bars = max(\n        2,\n        config.sma_trend_period\n        + config.sma_slope_lookback\n        + 2,\n    )\n    overlapping_swing_bars = (\n        sum(\n            1\n            for candle in swing_candles\n            if common_start <= candle.date <= common_end\n        )\n        if overlap_valid\n        else 0\n    )\n    checks.append(\n        ValidationCheck(\n            name="strategy warm-up",\n            passed=overlapping_swing_bars >= required_bars,\n            detail=(\n                f"{overlapping_swing_bars} overlapping swing bars; "\n                f"{required_bars} required"\n            ),\n        )\n    )\n\n    vix_covers_start = (\n        bool(vix_points)\n        and bool(swing_candles)\n        and vix_points[0].date <= swing_candles[0].date\n    )\n    checks.append(\n        ValidationCheck(\n            name="VIX start coverage",\n            passed=vix_covers_start or overlap_valid,\n            detail=(\n                "VIX can be aligned after common-date trimming"\n                if overlap_valid\n                else "VIX starts too late"\n            ),\n        )\n    )\n\n    dividend_dates_valid = (\n        not dividends\n        or (\n            bool(income_candles)\n            and all(\n                income_candles[0].date\n                <= event.date\n                <= income_candles[-1].date\n                for event in dividends\n            )\n        )\n    )\n    checks.append(\n        ValidationCheck(\n            name="dividend date range",\n            passed=dividend_dates_valid,\n            detail=(\n                "all dividend events fall inside income history"\n                if dividend_dates_valid\n                else "one or more dividends fall outside income history"\n            ),\n        )\n    )\n\n    positive_prices = all(\n        candle.open > 0\n        and candle.high > 0\n        and candle.low > 0\n        and candle.close > 0\n        for candle in (*swing_candles, *income_candles)\n    )\n    checks.append(\n        ValidationCheck(\n            name="positive prices",\n            passed=positive_prices,\n            detail=(\n                "all OHLC values are positive"\n                if positive_prices\n                else "non-positive OHLC value detected"\n            ),\n        )\n    )\n\n    no_duplicate_dates = (\n        len({candle.date for candle in swing_candles})\n        == len(swing_candles)\n        and len({candle.date for candle in income_candles})\n        == len(income_candles)\n        and len({point.date for point in vix_points})\n        == len(vix_points)\n    )\n    checks.append(\n        ValidationCheck(\n            name="unique daily dates",\n            passed=no_duplicate_dates,\n            detail=(\n                "one bar per date"\n                if no_duplicate_dates\n                else "duplicate daily dates detected"\n            ),\n        )\n    )\n\n    ready = all(\n        check.passed\n        for check in checks\n        if check.severity == "error"\n    )\n\n    return RealDataValidation(\n        ready=ready,\n        common_start=common_start,\n        common_end=common_end,\n        swing_bars=len(swing_candles),\n        income_bars=len(income_candles),\n        vix_points=len(vix_points),\n        dividend_events=len(dividends),\n        checks=tuple(checks),\n    )\n',
    "qpx_bot/run_real_backtest.py": '"""Run a reproducible QPX hybrid backtest from real CSV files."""\n\nfrom __future__ import annotations\n\nimport argparse\nfrom dataclasses import asdict\nfrom datetime import datetime, timezone\nimport json\nfrom pathlib import Path\nfrom typing import Sequence\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.dividends import load_dividend_csv\nfrom qpx_bot.hybrid import HybridBacktestResult, run_hybrid_backtest\nfrom qpx_bot.real_data import (\n    align_vix_to_candles,\n    load_market_csv,\n    load_vix_csv,\n    sha256_file,\n    trim_market_history,\n)\nfrom qpx_bot.report import (\n    format_hybrid_report,\n    write_hybrid_equity_curve,\n    write_trade_log,\n)\nfrom qpx_bot.validation import RealDataValidation, validate_real_data\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nPROJECT_ROOT = PACKAGE_DIR.parent\nDEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"\nDEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "qpx_real_backtest"\n\nEXPECTED_FILES = {\n    "swing": "SWING.csv",\n    "income": "QDTE.csv",\n    "dividends": "QDTE_DIVIDENDS.csv",\n    "vix": "VIX.csv",\n}\n\n\nclass RealDataNotReady(RuntimeError):\n    pass\n\n\ndef required_input_paths(\n    input_directory: str | Path,\n) -> dict[str, Path]:\n    directory = Path(input_directory).expanduser().resolve()\n    return {\n        name: directory / filename\n        for name, filename in EXPECTED_FILES.items()\n    }\n\n\ndef missing_input_files(\n    input_directory: str | Path,\n) -> list[Path]:\n    return [\n        path\n        for path in required_input_paths(input_directory).values()\n        if not path.exists()\n    ]\n\n\ndef run_real_data_backtest(\n    *,\n    input_directory: str | Path,\n    output_directory: str | Path,\n    swing_symbol: str,\n    config: BotConfig | None = None,\n    forced_entry_indices: set[int] | None = None,\n) -> tuple[\n    HybridBacktestResult,\n    RealDataValidation,\n    dict[str, Path],\n]:\n    config = config or BotConfig()\n    config.validate()\n\n    paths = required_input_paths(input_directory)\n    missing = [path for path in paths.values() if not path.exists()]\n\n    if missing:\n        raise FileNotFoundError(\n            "Missing required real-data files:\\n"\n            + "\\n".join(str(path) for path in missing)\n        )\n\n    swing_candles = load_market_csv(paths["swing"])\n    income_candles = load_market_csv(paths["income"])\n    vix_points = load_vix_csv(paths["vix"])\n    dividends = load_dividend_csv(paths["dividends"])\n\n    validation = validate_real_data(\n        swing_candles=swing_candles,\n        income_candles=income_candles,\n        vix_points=vix_points,\n        dividends=dividends,\n        config=config,\n    )\n\n    output = Path(output_directory).expanduser().resolve()\n    output.mkdir(parents=True, exist_ok=True)\n    validation.write_json(output / "validation.json")\n    (output / "validation.txt").write_text(\n        validation.format_text() + "\\n",\n        encoding="utf-8",\n    )\n\n    if not validation.ready:\n        raise RealDataNotReady(validation.format_text())\n\n    assert validation.common_start is not None\n    assert validation.common_end is not None\n\n    swing_candles = trim_market_history(\n        swing_candles,\n        start_date=validation.common_start,\n        end_date=validation.common_end,\n    )\n    income_candles = [\n        candle\n        for candle in income_candles\n        if candle.date <= validation.common_end\n    ]\n    vix_values = align_vix_to_candles(\n        swing_candles,\n        vix_points,\n        maximum_gap_days=7,\n    )\n\n    result = run_hybrid_backtest(\n        swing_candles=swing_candles,\n        income_candles=income_candles,\n        dividends=dividends,\n        swing_symbol=swing_symbol,\n        config=config,\n        vix=vix_values,\n        forced_entry_indices=forced_entry_indices,\n    )\n\n    report_path = output / "backtest_report.txt"\n    trade_path = output / "trades.csv"\n    equity_path = output / "equity_curve.csv"\n    manifest_path = output / "run_manifest.json"\n\n    report_path.write_text(\n        format_hybrid_report(result) + "\\n",\n        encoding="utf-8",\n    )\n    write_trade_log(result, trade_path)\n    write_hybrid_equity_curve(result, equity_path)\n\n    manifest = {\n        "generated_at_utc": datetime.now(\n            timezone.utc\n        ).isoformat(),\n        "qpx_version": "1.6.0",\n        "swing_symbol": swing_symbol.strip().upper(),\n        "common_start": validation.common_start.isoformat(),\n        "common_end": validation.common_end.isoformat(),\n        "configuration": asdict(config),\n        "inputs": {\n            name: {\n                "path": str(path),\n                "sha256": sha256_file(path),\n            }\n            for name, path in paths.items()\n        },\n        "outputs": {\n            "report": str(report_path),\n            "trades": str(trade_path),\n            "equity_curve": str(equity_path),\n            "validation": str(output / "validation.json"),\n        },\n    }\n    manifest_path.write_text(\n        json.dumps(manifest, indent=2),\n        encoding="utf-8",\n    )\n\n    artifacts = {\n        "report": report_path,\n        "trades": trade_path,\n        "equity": equity_path,\n        "validation": output / "validation.json",\n        "manifest": manifest_path,\n    }\n    return result, validation, artifacts\n\n\ndef _build_parser() -> argparse.ArgumentParser:\n    parser = argparse.ArgumentParser(\n        description=(\n            "Run QPX Bot against real daily OHLCV, dividend, "\n            "and VIX CSV files."\n        )\n    )\n    parser.add_argument(\n        "--input-dir",\n        default=str(DEFAULT_INPUT_DIR),\n        help="Folder containing SWING.csv, QDTE.csv, "\n        "QDTE_DIVIDENDS.csv, and VIX.csv.",\n    )\n    parser.add_argument(\n        "--output-dir",\n        default=str(DEFAULT_OUTPUT_DIR),\n        help="Folder for reports and reproducibility files.",\n    )\n    parser.add_argument(\n        "--symbol",\n        default="SWING",\n        help="Ticker represented by SWING.csv.",\n    )\n    parser.add_argument(\n        "--check-only",\n        action="store_true",\n        help="Show required input files without running a backtest.",\n    )\n    return parser\n\n\ndef main(argv: Sequence[str] | None = None) -> int:\n    args = _build_parser().parse_args(argv)\n    paths = required_input_paths(args.input_dir)\n    missing = [path for path in paths.values() if not path.exists()]\n\n    print("=" * 74)\n    print("QPX BOT v1.6 — REAL HISTORICAL DATA RUNNER")\n    print("=" * 74)\n    print(f"Input folder : {Path(args.input_dir).resolve()}")\n    print(f"Output folder: {Path(args.output_dir).resolve()}")\n    print()\n\n    for name, path in paths.items():\n        status = "FOUND" if path.exists() else "MISSING"\n        print(f"{name:<10}: {status:<7} {path.name}")\n\n    if args.check_only:\n        return 0\n\n    if missing:\n        print()\n        print("Place the four required CSV files in the input folder.")\n        return 2\n\n    try:\n        result, validation, artifacts = run_real_data_backtest(\n            input_directory=args.input_dir,\n            output_directory=args.output_dir,\n            swing_symbol=args.symbol,\n        )\n    except RealDataNotReady as exc:\n        print()\n        print(exc)\n        return 3\n\n    print()\n    print(validation.format_text())\n    print()\n    print(format_hybrid_report(result))\n    print()\n    print("Artifacts:")\n    for name, path in artifacts.items():\n        print(f"  {name:<10} {path}")\n\n    return 0\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "QPX_RUN_REAL_BACKTEST.py": '#!/usr/bin/env python3\n"""Simple QPX real-data backtest launcher."""\n\nfrom qpx_bot.run_real_backtest import main\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n',
    "tests/test_qpx_bot_real_data.py": 'import csv\nfrom dataclasses import replace\nfrom datetime import date, datetime, timedelta, timezone\nfrom pathlib import Path\nfrom tempfile import TemporaryDirectory\n\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.run_real_backtest import run_real_data_backtest\n\n\nconfig = replace(\n    BotConfig(),\n    starting_cash=10_000.0,\n    monthly_contribution=500.0,\n    ema_fast_period=2,\n    ema_slow_period=3,\n    rsi_period=3,\n    rmi_period=3,\n    rmi_momentum=2,\n    sma_trend_period=5,\n    sma_slope_lookback=2,\n    atr_period=3,\n    average_volume_period=3,\n    breakout_lookback=3,\n)\n\nwith TemporaryDirectory() as temporary_directory:\n    root = Path(temporary_directory)\n    input_dir = root / "inputs"\n    output_dir = root / "outputs"\n    input_dir.mkdir()\n\n    start = date(2022, 1, 3)\n    rows = []\n\n    for index in range(260):\n        day = start + timedelta(days=index)\n        price = 100.0 + (index * 0.08)\n        rows.append(\n            {\n                "day": day,\n                "open": price,\n                "high": price + (5.0 if index == 25 else 1.0),\n                "low": price - 1.0,\n                "close": price + 0.25,\n                "volume": 3_000_000,\n            }\n        )\n\n    with (input_dir / "SWING.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            ["time", "open", "high", "low", "close", "Volume"]\n        )\n        for row in rows:\n            timestamp = int(\n                datetime(\n                    row["day"].year,\n                    row["day"].month,\n                    row["day"].day,\n                    tzinfo=timezone.utc,\n                ).timestamp()\n            )\n            writer.writerow(\n                [\n                    timestamp,\n                    row["open"],\n                    row["high"],\n                    row["low"],\n                    row["close"],\n                    row["volume"],\n                ]\n            )\n\n    with (input_dir / "QDTE.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(\n            ["Date", "Open", "High", "Low", "Close", "Volume"]\n        )\n        for index, row in enumerate(rows):\n            price = 40.0 + (index * 0.03)\n            writer.writerow(\n                [\n                    row["day"].isoformat(),\n                    price,\n                    price + 0.40,\n                    price - 0.40,\n                    price + 0.10,\n                    1_500_000,\n                ]\n            )\n\n    with (input_dir / "VIX.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(["Date", "VIX"])\n        for row in rows:\n            writer.writerow([row["day"].isoformat(), 20.0])\n\n    with (input_dir / "QDTE_DIVIDENDS.csv").open(\n        "w",\n        newline="",\n        encoding="utf-8",\n    ) as file:\n        writer = csv.writer(file)\n        writer.writerow(["Date", "Dividend"])\n        for index in (20, 60, 120, 200):\n            writer.writerow([rows[index]["day"].isoformat(), 0.20])\n\n    result, validation, artifacts = run_real_data_backtest(\n        input_directory=input_dir,\n        output_directory=output_dir,\n        swing_symbol="TEST",\n        config=config,\n        forced_entry_indices={20},\n    )\n\n    assert validation.ready\n    assert result.swing_symbol == "TEST"\n    assert result.total_dividends > 0\n    assert result.ending_equity > 0\n    assert len(result.trades) == 1\n\n    for path in artifacts.values():\n        assert path.exists()\n\n    manifest = artifacts["manifest"].read_text(encoding="utf-8")\n    assert \'"sha256"\' in manifest\n    assert \'"qpx_version": "1.6.0"\' in manifest\n\nprint("QPX Bot Real Historical Data Pipeline PASS")\n',
    "qpx_bot/data_inputs/README.txt": 'QPX BOT REAL-DATA DROP FOLDER\n================================\n\nPlace these four daily CSV files in this folder:\n\n1. SWING.csv\n   The swing-trading symbol exported from TradingView.\n   Required columns, case-insensitive:\n   Date/time, Open, High, Low, Close, Volume\n\n2. QDTE.csv\n   Daily QDTE OHLCV history.\n   Required columns:\n   Date/time, Open, High, Low, Close, Volume\n\n3. QDTE_DIVIDENDS.csv\n   Actual QDTE cash distributions.\n   Required columns:\n   Date, Dividend\n\n4. VIX.csv\n   Daily VIX history.\n   Accepted formats:\n   Date,VIX\n   or a TradingView OHLCV export, using its Close column.\n\nRun from the QPX_ALPHA project root:\n\npython QPX_RUN_REAL_BACKTEST.py --check-only\n\nAfter all four files show FOUND:\n\npython QPX_RUN_REAL_BACKTEST.py --symbol SPY\n\nReports are written to:\n\nreports/qpx_real_backtest/\n\nImportant:\n- Use daily bars, not intraday bars.\n- Do not invent dividends or extend QDTE before its actual history.\n- The runner trims all sources to their real overlapping date range.\n- Input file SHA-256 hashes are recorded for reproducibility.\n',
    "qpx_bot/data_inputs/templates/MARKET_TEMPLATE.csv": 'Date,Open,High,Low,Close,Volume\n2024-01-02,100,101,99,100.5,2500000\n',
    "qpx_bot/data_inputs/templates/DIVIDEND_TEMPLATE.csv": 'Date,Dividend\n2024-01-05,0.20\n',
    "qpx_bot/data_inputs/templates/VIX_TEMPLATE.csv": 'Date,VIX\n2024-01-02,20.50\n',
}

originals: dict[str, bytes | None] = {}


def run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in FILES:
        worktree = subprocess.run(
            ["git", "diff", "--quiet", "--", relative],
            cwd=ROOT,
        )
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", relative],
            cwd=ROOT,
        )

        if worktree.returncode != 0 or staged.returncode != 0:
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files have uncommitted edits and were "
            "not overwritten:\n" + "\n".join(changed)
        )


def install() -> None:
    for relative, content in FILES.items():
        path = ROOT / relative
        originals[relative] = (
            path.read_bytes()
            if path.exists()
            else None
        )

        if path.exists():
            backup_path = BACKUP / relative
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup_path)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            textwrap.dedent(content).strip() + "\n",
            encoding="utf-8",
        )
        print(f"Installed: {relative}")


def restore() -> None:
    print("Restoring previous target files...")

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(FILES)

    try:
        paths.append(
            str(Path(__file__).resolve().relative_to(ROOT))
        )
    except ValueError:
        pass

    run(["git", "add", "--", *paths])

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print("Real-data validation milestone is already committed.")
        return

    run([
        "git",
        "commit",
        "-m",
        "Implement QPX Bot real historical data validation",
    ])

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError("Cannot push from detached Git state.")

    run(["git", "push", "origin", branch])


def main() -> int:
    print("=" * 74)
    print("QPX BOT — REAL HISTORICAL DATA VALIDATION INSTALLER")
    print("=" * 74)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    install()

    try:
        run([sys.executable, "QPX_RUN_REAL_BACKTEST.py", "--check-only"])
        run([sys.executable, "tests/run_all_tests.py"])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print("=" * 74)
    print("QPX BOT REAL HISTORICAL DATA VALIDATION: COMPLETE")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
