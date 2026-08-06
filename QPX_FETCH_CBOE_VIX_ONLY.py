#!/usr/bin/env python3
"""Download and validate only the official Cboe VIX cache."""

from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Sequence

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_VIX_CACHE,
    WARMUP_DAYS,
    prepare_cboe_vix_cache,
    subtract_years,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    latest_completed_session,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            block = file.read(1024 * 1024)

            if not block:
                break

            digest.update(block)

    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare only the official Cboe VIX "
            "daily cache used by the two-year "
            "15-minute QPX backtest."
        )
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Force a new official Cboe download "
            "instead of reusing a valid local cache."
        ),
    )
    parser.add_argument(
        "--cache",
        default=str(DEFAULT_VIX_CACHE),
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    end_session, end_status = (
        latest_completed_session(
            datetime.now(tz=NEW_YORK)
        )
    )
    requested_start = subtract_years(
        end_session,
        2,
    )
    warmup_start = (
        requested_start
        - timedelta(days=WARMUP_DAYS)
    )
    closes, source, path = (
        prepare_cboe_vix_cache(
            start=warmup_start,
            end=end_session,
            cache_path=args.cache,
            refresh=args.refresh,
        )
    )
    ordered = sorted(closes)

    print("=" * 78)
    print(
        "QPX OFFICIAL CBOE VIX PREFLIGHT: COMPLETE"
    )
    print("=" * 78)
    print(f"source              : {source}")
    print(f"provider end status : {end_status}")
    print(f"coverage start      : {ordered[0]}")
    print(f"coverage end        : {ordered[-1]}")
    print(f"daily observations  : {len(ordered)}")
    print(f"cache path          : {path}")
    print(f"sha256              : {_sha256(path)}")
    print(
        "observation policy  : "
        "PREVIOUS_COMPLETED_SESSION_DAILY_CLOSE"
    )
    print("placeholder data    : DISABLED")
    print("synthetic data      : DISABLED")
    print("=" * 78)
    print(
        "The VIX preflight is complete. The long "
        "Massive/Polygon download has not been started."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
