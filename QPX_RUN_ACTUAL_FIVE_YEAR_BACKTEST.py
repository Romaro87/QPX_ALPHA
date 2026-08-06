#!/usr/bin/env python3
"""Download actual data and run the existing QPX engine for five years."""

from __future__ import annotations

import argparse
from typing import Sequence

from qpx_bot.actual_five_year import (
    format_run_summary,
    run_actual_five_year_backtest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Download actual Yahoo daily data and execute the "
            "existing QPX strategy engine over five completed years."
        )
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help=(
            "Optional explicit ticker. Without this argument, "
            "the current data-driven selection is used. No "
            "fallback ticker is substituted."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run, artifacts = run_actual_five_year_backtest(
        symbol=args.symbol,
    )
    print(format_run_summary(run, artifacts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
