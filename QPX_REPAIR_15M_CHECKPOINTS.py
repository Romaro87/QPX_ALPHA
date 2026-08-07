#!/usr/bin/env python3
"""Repair stale aggregate manifests without downloading market data."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from qpx_bot.actual_two_year_15m_six import (
    DEFAULT_DATA_ROOT,
    INCOME_SYMBOL,
    SWING_SYMBOLS,
    WARMUP_DAYS,
    _aggregate_cache_path,
    _aggregate_manifest_path,
    _atomic_json,
    _common_times,
    _read_cached_bars,
    _validated_completed_chunks,
    chunk_ranges,
    subtract_years,
)
from qpx_bot.market_calendar import (
    NEW_YORK,
    latest_completed_session,
)


def main() -> int:
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
    symbols = (
        *SWING_SYMBOLS,
        INCOME_SYMBOL,
    )
    histories = {}
    invalidated_total = 0

    print("=" * 78)
    print(
        "QPX STALE 15-MINUTE CHECKPOINT REPAIR"
    )
    print("=" * 78)
    print(f"expected end session : {end_session}")
    print(f"session status       : {end_status}")
    print(f"warmup start         : {warmup_start}")
    print("network requests     : NONE")
    print("-" * 78)

    for symbol in symbols:
        cache_path = _aggregate_cache_path(
            symbol
        )
        manifest_path = (
            _aggregate_manifest_path(
                cache_path
            )
        )

        if not cache_path.exists():
            print(
                f"{symbol:<5} : MISSING CACHE"
            )
            continue

        bars = _read_cached_bars(
            cache_path
        )
        histories[symbol] = bars
        first = (
            bars[0].start.isoformat()
            if bars
            else "NO_BARS"
        )
        last = (
            bars[-1].start.isoformat()
            if bars
            else "NO_BARS"
        )
        payload = {}

        if manifest_path.exists():
            try:
                payload = json.loads(
                    manifest_path.read_text(
                        encoding="utf-8"
                    )
                )
            except (
                OSError,
                ValueError,
                TypeError,
            ):
                payload = {}

        valid, invalid = (
            _validated_completed_chunks(
                manifest_payload=payload,
                bars=bars,
                start=warmup_start,
                end=end_session,
            )
        )
        invalidated_total += len(invalid)
        all_chunks = {
            (
                f"{chunk_start.isoformat()}_"
                f"{chunk_end.isoformat()}"
            )
            for chunk_start, chunk_end
            in chunk_ranges(
                warmup_start,
                end_session,
            )
        }
        missing = all_chunks - valid

        _atomic_json(
            manifest_path,
            {
                "schema_version": 2,
                "provider_symbol": symbol,
                "interval_minutes": 15,
                "requested_start": (
                    warmup_start.isoformat()
                ),
                "requested_end": (
                    end_session.isoformat()
                ),
                "completed_chunks": sorted(
                    valid
                ),
                "invalidated_chunks": sorted(
                    invalid
                ),
                "missing_or_incomplete_chunks": sorted(
                    missing
                ),
                "bar_count": len(bars),
                "first_bar": first,
                "latest_bar": last,
                "repaired_without_network": True,
                "placeholder_data": False,
                "synthetic_data": False,
            },
        )
        print(
            f"{symbol:<5} : bars={len(bars):>6} "
            f"first={first} last={last} "
            f"valid_chunks={len(valid)} "
            f"invalidated={len(invalid)} "
            f"remaining={len(missing)}"
        )

    print("-" * 78)

    if all(
        symbol in histories
        for symbol in symbols
    ):
        all_common = _common_times(
            histories
        )
        swing_common = _common_times(
            {
                symbol: histories[symbol]
                for symbol in SWING_SYMBOLS
            }
        )
        print(
            "latest all-symbol common : "
            + (
                all_common[-1].isoformat()
                if all_common
                else "NONE"
            )
        )
        print(
            "latest swing-only common : "
            + (
                swing_common[-1].isoformat()
                if swing_common
                else "NONE"
            )
        )

    print(f"invalidated chunks    : {invalidated_total}")
    print("=" * 78)
    print(
        "QPX STALE 15-MINUTE CHECKPOINT REPAIR: COMPLETE"
    )
    print(
        "The next backtest will request only chunks "
        "that are missing or fail end-coverage validation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
