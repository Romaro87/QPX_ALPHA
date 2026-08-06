#!/usr/bin/env python3
"""Run QPX walk-forward validation from the real-data folder."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.dividends import load_dividend_csv
from qpx_bot.performance import load_adjusted_bars
from qpx_bot.real_data import (
    align_vix_to_candles,
    load_market_csv,
    load_vix_csv,
    sha256_file,
    trim_market_history,
)
from qpx_bot.run_real_backtest import (
    DEFAULT_INPUT_DIR,
    required_input_paths,
)
from qpx_bot.validation import validate_real_data
from qpx_bot.walk_forward import (
    format_walk_forward_report,
    run_walk_forward,
    write_walk_forward_json,
    write_walk_forward_windows,
)


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "reports" / "qpx_walk_forward"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run rolling QPX training/testing windows and compare "
            "unseen results with adjusted-close SPY buy-and-hold."
        )
    )
    parser.add_argument(
        "--input-dir",
        default=str(DEFAULT_INPUT_DIR),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
    )
    parser.add_argument("--symbol", default="SPY")
    parser.add_argument("--train-bars", type=int, default=252)
    parser.add_argument("--test-bars", type=int, default=63)
    parser.add_argument("--step-bars", type=int, default=63)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = BotConfig()
    paths = required_input_paths(args.input_dir)
    missing = [path for path in paths.values() if not path.exists()]

    print("=" * 78)
    print("QPX BOT v1.8 — WALK-FORWARD + SPY BENCHMARK RUNNER")
    print("=" * 78)

    if missing:
        print("Missing real-data inputs:")
        for path in missing:
            print(f"  {path}")
        return 2

    swing = load_market_csv(paths["swing"])
    income = load_market_csv(paths["income"])
    vix_points = load_vix_csv(paths["vix"])
    dividends = load_dividend_csv(paths["dividends"])
    adjusted_bars, uses_adjusted = load_adjusted_bars(
        paths["swing"]
    )

    validation = validate_real_data(
        swing_candles=swing,
        income_candles=income,
        vix_points=vix_points,
        dividends=dividends,
        config=config,
    )

    if not validation.ready:
        print(validation.format_text())
        return 3

    assert validation.common_start is not None
    assert validation.common_end is not None

    swing = trim_market_history(
        swing,
        start_date=validation.common_start,
        end_date=validation.common_end,
    )
    income = [
        candle
        for candle in income
        if candle.date <= validation.common_end
    ]
    adjusted_bars = [
        bar
        for bar in adjusted_bars
        if (
            validation.common_start
            <= bar.date
            <= validation.common_end
        )
    ]
    vix_values = align_vix_to_candles(
        swing,
        vix_points,
        maximum_gap_days=7,
    )

    result = run_walk_forward(
        swing_candles=swing,
        income_candles=income,
        dividends=dividends,
        vix_values=vix_values,
        adjusted_bars=adjusted_bars,
        symbol=args.symbol,
        config=config,
        train_bars=args.train_bars,
        test_bars=args.test_bars,
        step_bars=args.step_bars,
        benchmark_uses_adjusted_close=uses_adjusted,
    )

    output = Path(args.output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    report_path = output / "walk_forward_report.txt"
    windows_path = output / "walk_forward_windows.csv"
    result_path = output / "walk_forward_result.json"
    manifest_path = output / "walk_forward_manifest.json"

    report = format_walk_forward_report(result)
    report_path.write_text(report + "\n", encoding="utf-8")
    write_walk_forward_windows(result, windows_path)
    write_walk_forward_json(result, result_path)

    manifest = {
        "generated_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "qpx_version": "1.8.0",
        "symbol": args.symbol.strip().upper(),
        "train_bars": args.train_bars,
        "test_bars": args.test_bars,
        "step_bars": args.step_bars,
        "benchmark_adjusted_close": uses_adjusted,
        "inputs": {
            name: {
                "path": str(path),
                "sha256": sha256_file(path),
            }
            for name, path in paths.items()
        },
        "outputs": {
            "report": str(report_path),
            "windows": str(windows_path),
            "result": str(result_path),
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    print(report)
    print()
    print("Artifacts:")
    for path in (
        report_path,
        windows_path,
        result_path,
        manifest_path,
    ):
        print(f"  {path}")

    print()
    print("=" * 78)
    print("QPX WALK-FORWARD VALIDATION: COMPLETE")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
