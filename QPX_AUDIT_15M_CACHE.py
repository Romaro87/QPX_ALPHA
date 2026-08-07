#!/usr/bin/env python3
"""Audit and import existing QPX 15-minute aggregate caches."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_DATA_ROOT,
    INCOME_SYMBOL,
    SWING_SYMBOLS,
    WARMUP_DAYS,
    _aggregate_cache_path,
    _read_cached_bars,
    _seed_aggregate_checkpoint,
    subtract_years,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    latest_completed_session,
)


def main() -> int:
    end_session, _ = latest_completed_session(
        datetime.now(tz=NEW_YORK)
    )
    requested_start = subtract_years(
        end_session,
        2,
    )
    warmup_start = (
        requested_start
        - timedelta(days=WARMUP_DAYS)
    )
    data_root = (
        Path(DEFAULT_DATA_ROOT)
        .expanduser()
        .resolve()
    )
    data_root.mkdir(
        parents=True,
        exist_ok=True,
    )
    excluded = (
        data_root
        / "__CACHE_AUDIT_DO_NOT_USE__"
    )
    symbols = (
        *SWING_SYMBOLS,
        INCOME_SYMBOL,
    )
    reusable = 0
    resumable = 0
    missing = 0

    print("=" * 78)
    print(
        "QPX 15-MINUTE AGGREGATE CACHE AUDIT"
    )
    print("=" * 78)

    for symbol in symbols:
        seeded = _seed_aggregate_checkpoint(
            data_root=data_root,
            logical_symbol=symbol,
            provider_symbol=symbol,
            start=warmup_start,
            end=end_session,
            exclude_directory=excluded,
        )
        stable = _aggregate_cache_path(
            symbol
        )

        if seeded is None:
            missing += 1
            print(
                f"{symbol:<5} : MISSING — "
                "will download with chunk checkpoints"
            )
            continue

        bars, path = seeded
        first = bars[0].start.date()
        last = bars[-1].start.date()

        if (
            len(bars) >= 12_000
            and first
            <= warmup_start + timedelta(days=10)
            and (
                end_session - last
            ).days <= 4
        ):
            reusable += 1
            state = "REUSABLE COMPLETE"
        else:
            resumable += 1
            state = "RESUMABLE PARTIAL"

        print(
            f"{symbol:<5} : {state} — "
            f"{len(bars)} bars, "
            f"{first} to {last}, "
            f"stable={stable}"
        )

    print("-" * 78)
    print(f"Reusable complete : {reusable}")
    print(f"Resumable partial : {resumable}")
    print(f"Missing           : {missing}")
    print(
        "Network requests  : NONE"
    )
    print("=" * 78)
    print(
        "QPX 15-MINUTE AGGREGATE CACHE AUDIT: COMPLETE"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
