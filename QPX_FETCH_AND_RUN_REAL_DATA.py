#!/usr/bin/env python3
"""Download real market data and run the QPX hybrid backtest."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Sequence

from qpx_bot.report import format_hybrid_report
from qpx_bot.run_real_backtest import (
    DEFAULT_INPUT_DIR,
    DEFAULT_OUTPUT_DIR,
    run_real_data_backtest,
)
from qpx_bot.yahoo_data import download_real_dataset


PROJECT_ROOT = Path(__file__).resolve().parent


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download real daily market data and run the QPX "
            "hybrid dividend-plus-swing backtest."
        )
    )
    parser.add_argument(
        "--symbol",
        default="SPY",
        help="Swing ticker to download. Default: SPY.",
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
        help="Destination for the four real-data CSV files.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Destination for validation and backtest reports.",
    )
    parser.add_argument(
        "--range",
        dest="range_name",
        default="max",
        help="Provider history range. Default: max.",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Download and validate files later without backtesting now.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_directory = (
        PROJECT_ROOT
        / "backups"
        / "qpx_market_data"
        / timestamp
    )

    print("=" * 76)
    print("QPX BOT v1.7 — MARKET DATA ACQUISITION + REAL BACKTEST")
    print("=" * 76)
    print(f"Swing symbol : {args.symbol.strip().upper()}")
    print(f"Input folder : {Path(args.input_dir).resolve()}")
    print(f"Output folder: {Path(args.output_dir).resolve()}")
    print()

    summary = download_real_dataset(
        swing_symbol=args.symbol,
        input_directory=args.input_dir,
        range_name=args.range_name,
        backup_directory=backup_directory,
    )

    print()
    print("Download complete")
    print(f"Provider       : {summary.provider}")
    print(f"Swing rows     : {summary.swing_rows}")
    print(f"QDTE rows      : {summary.income_rows}")
    print(f"VIX rows       : {summary.vix_rows}")
    print(f"Dividend events: {summary.dividend_events}")
    print(
        f"Common period  : {summary.common_first_date} "
        f"to {summary.common_last_date}"
    )
    print(f"Manifest       : {summary.manifest_path}")

    if args.download_only:
        print()
        print("QPX REAL MARKET DATA DOWNLOAD: COMPLETE")
        return 0

    result, validation, artifacts = run_real_data_backtest(
        input_directory=args.input_dir,
        output_directory=args.output_dir,
        swing_symbol=args.symbol,
    )

    print()
    print(validation.format_text())
    print()
    print(format_hybrid_report(result))
    print()
    print("Research artifacts:")
    for name, path in artifacts.items():
        print(f"  {name:<10} {path}")

    print()
    print("=" * 76)
    print("QPX FIRST REAL HYBRID BACKTEST: COMPLETE")
    print("=" * 76)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
