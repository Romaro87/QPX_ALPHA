"""Run a reproducible QPX hybrid backtest from real CSV files."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.dividends import load_dividend_csv
from qpx_bot.hybrid import HybridBacktestResult, run_hybrid_backtest
from qpx_bot.real_data import (
    align_vix_to_candles,
    load_market_csv,
    load_vix_csv,
    sha256_file,
    trim_market_history,
)
from qpx_bot.report import (
    format_hybrid_report,
    write_hybrid_equity_curve,
    write_trade_log,
)
from qpx_bot.validation import RealDataValidation, validate_real_data


PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
DEFAULT_INPUT_DIR = PACKAGE_DIR / "data_inputs"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports" / "qpx_real_backtest"

EXPECTED_FILES = {
    "swing": "SWING.csv",
    "income": "QDTE.csv",
    "dividends": "QDTE_DIVIDENDS.csv",
    "vix": "VIX.csv",
}


class RealDataNotReady(RuntimeError):
    pass


def required_input_paths(
    input_directory: str | Path,
) -> dict[str, Path]:
    directory = Path(input_directory).expanduser().resolve()
    return {
        name: directory / filename
        for name, filename in EXPECTED_FILES.items()
    }


def missing_input_files(
    input_directory: str | Path,
) -> list[Path]:
    return [
        path
        for path in required_input_paths(input_directory).values()
        if not path.exists()
    ]


def run_real_data_backtest(
    *,
    input_directory: str | Path,
    output_directory: str | Path,
    swing_symbol: str,
    config: BotConfig | None = None,
    forced_entry_indices: set[int] | None = None,
) -> tuple[
    HybridBacktestResult,
    RealDataValidation,
    dict[str, Path],
]:
    config = config or BotConfig()
    config.validate()

    paths = required_input_paths(input_directory)
    missing = [path for path in paths.values() if not path.exists()]

    if missing:
        raise FileNotFoundError(
            "Missing required real-data files:\n"
            + "\n".join(str(path) for path in missing)
        )

    swing_candles = load_market_csv(paths["swing"])
    income_candles = load_market_csv(paths["income"])
    vix_points = load_vix_csv(paths["vix"])
    dividends = load_dividend_csv(paths["dividends"])

    validation = validate_real_data(
        swing_candles=swing_candles,
        income_candles=income_candles,
        vix_points=vix_points,
        dividends=dividends,
        config=config,
    )

    output = Path(output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    validation.write_json(output / "validation.json")
    (output / "validation.txt").write_text(
        validation.format_text() + "\n",
        encoding="utf-8",
    )

    if not validation.ready:
        raise RealDataNotReady(validation.format_text())

    assert validation.common_start is not None
    assert validation.common_end is not None

    swing_candles = trim_market_history(
        swing_candles,
        start_date=validation.common_start,
        end_date=validation.common_end,
    )
    income_candles = [
        candle
        for candle in income_candles
        if candle.date <= validation.common_end
    ]
    vix_values = align_vix_to_candles(
        swing_candles,
        vix_points,
        maximum_gap_days=7,
    )

    result = run_hybrid_backtest(
        swing_candles=swing_candles,
        income_candles=income_candles,
        dividends=dividends,
        swing_symbol=swing_symbol,
        config=config,
        vix=vix_values,
        forced_entry_indices=forced_entry_indices,
    )

    report_path = output / "backtest_report.txt"
    trade_path = output / "trades.csv"
    equity_path = output / "equity_curve.csv"
    manifest_path = output / "run_manifest.json"

    report_path.write_text(
        format_hybrid_report(result) + "\n",
        encoding="utf-8",
    )
    write_trade_log(result, trade_path)
    write_hybrid_equity_curve(result, equity_path)

    manifest = {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "qpx_version": "1.8.0",
        "swing_symbol": swing_symbol.strip().upper(),
        "common_start": validation.common_start.isoformat(),
        "common_end": validation.common_end.isoformat(),
        "configuration": asdict(config),
        "inputs": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for name, path in paths.items()
        },
        "outputs": {
            "report": str(report_path),
            "trades": str(trade_path),
            "equity_curve": str(equity_path),
            "validation": str(output / "validation.json"),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    artifacts = {
        "report": report_path,
        "trades": trade_path,
        "equity": equity_path,
        "validation": output / "validation.json",
        "manifest": manifest_path,
    }
    return result, validation, artifacts


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run QPX Bot against real daily OHLCV, dividend, "
            "and VIX CSV files."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Folder containing SWING.csv, QDTE.csv, "
        "QDTE_DIVIDENDS.csv, and VIX.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Folder for reports and reproducibility files.",
    )
    parser.add_argument(
        "--symbol",
        default="SWING",
        help="Ticker represented by SWING.csv.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Show required input files without running a backtest.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    paths = required_input_paths(args.input_dir)
    missing = [path for path in paths.values() if not path.exists()]

    print("=" * 74)
    print("QPX BOT v1.8 — REAL HISTORICAL DATA RUNNER")
    print("=" * 74)
    print(f"Input folder : {Path(args.input_dir).resolve()}")
    print(f"Output folder: {Path(args.output_dir).resolve()}")
    print()

    for name, path in paths.items():
        status = "FOUND" if path.exists() else "MISSING"
        print(f"{name:<10}: {status:<7} {path.name}")

    if args.check_only:
        return 0

    if missing:
        print()
        print("Place the four required CSV files in the input folder.")
        return 2

    try:
        result, validation, artifacts = run_real_data_backtest(
            input_directory=args.input_dir,
            output_directory=args.output_dir,
            swing_symbol=args.symbol,
        )
    except RealDataNotReady as exc:
        print()
        print(exc)
        return 3

    print()
    print(validation.format_text())
    print()
    print(format_hybrid_report(result))
    print()
    print("Artifacts:")
    for name, path in artifacts.items():
        print(f"  {name:<10} {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
