from __future__ import annotations

import argparse
import json
import time

from datetime import date, timedelta
from pathlib import Path

import QPX_FIND_BEST_ALPACA_SWING as sweep

from qpx_bot.alpaca_provider import (
    _request as alpaca_request,
    read_cache,
)


VERSION = "daily_session_prefilter_v1"

MINIMUM_SESSION_OVERLAP = 0.95

BATCH_SIZE = 100

CHECKPOINT = (
    sweep.REPORT_ROOT
    / "daily_eligibility_v1.json"
)


def qdte_master_sessions() -> set[date]:
    bars = read_cache(
        "QDTE"
    )

    sessions = {
        bar.start.date()
        for bar in bars.values()
        if (
            sweep.START
            <= bar.start.date()
            <= sweep.END
        )
    }

    if not sessions:
        raise RuntimeError(
            "QDTE master cache is empty."
        )

    first = min(
        sessions
    )

    last = max(
        sessions
    )

    if first != sweep.START:
        raise RuntimeError(
            "QDTE master sessions do not "
            "reach the requested start."
        )

    if last != sweep.END:
        raise RuntimeError(
            "QDTE master sessions do not "
            "reach the requested end."
        )

    return sessions


def fetch_daily_days(
    symbols: list[str],
) -> dict[str, set[date]]:
    stores = {
        symbol: set()
        for symbol in symbols
    }

    params = {
        "symbols": ",".join(
            symbols
        ),
        "timeframe": "1Day",
        "start": (
            sweep.START.isoformat()
            + "T00:00:00Z"
        ),
        "end": (
            (
                sweep.END
                + timedelta(days=1)
            ).isoformat()
            + "T00:00:00Z"
        ),
        "limit": "10000",
        "feed": "sip",
        "adjustment": "split",
        "sort": "asc",
    }

    while True:
        payload = alpaca_request(
            params
        )

        payload_bars = payload.get(
            "bars",
            {},
        )

        if not isinstance(
            payload_bars,
            dict,
        ):
            raise RuntimeError(
                "Alpaca daily response "
                "has malformed bars."
            )

        for raw_symbol, rows in (
            payload_bars.items()
        ):
            symbol = str(
                raw_symbol
            ).strip().upper()

            if symbol not in stores:
                continue

            if not isinstance(
                rows,
                list,
            ):
                continue

            for raw in rows:
                if not isinstance(
                    raw,
                    dict,
                ):
                    continue

                timestamp = str(
                    raw.get(
                        "t",
                        "",
                    )
                )

                if len(timestamp) < 10:
                    continue

                try:
                    day = (
                        date.fromisoformat(
                            timestamp[:10]
                        )
                    )
                except ValueError:
                    continue

                if (
                    sweep.START
                    <= day
                    <= sweep.END
                ):
                    stores[
                        symbol
                    ].add(
                        day
                    )

        token = payload.get(
            "next_page_token"
        )

        if not token:
            break

        params[
            "page_token"
        ] = str(
            token
        )

    return stores


def evaluate(
    symbol: str,
    days: set[date],
    master: set[date],
) -> dict:
    common = (
        days
        & master
    )

    ratio = (
        len(common)
        / len(master)
        if master
        else 0.0
    )

    first = (
        min(common)
        if common
        else None
    )

    last = (
        max(common)
        if common
        else None
    )

    eligible = True
    reason = ""

    if not common:
        eligible = False
        reason = (
            "no real daily overlap "
            "with QDTE master sessions"
        )

    elif first != sweep.START:
        eligible = False
        reason = (
            "daily history does not "
            "reach test start; "
            f"first common date={first}"
        )

    elif last != sweep.END:
        eligible = False
        reason = (
            "daily history does not "
            "reach test end; "
            f"last common date={last}"
        )

    elif (
        ratio
        < MINIMUM_SESSION_OVERLAP
    ):
        eligible = False
        reason = (
            "daily session coverage "
            f"{len(common)}/"
            f"{len(master)} "
            f"({ratio:.2%}) "
            "is below 95%"
        )

    return {
        "symbol": symbol,
        "eligible": eligible,
        "daily_sessions": len(
            days
        ),
        "common_sessions": len(
            common
        ),
        "master_sessions": len(
            master
        ),
        "session_overlap_pct": (
            ratio
        ),
        "first_common": (
            first.isoformat()
            if first
            else None
        ),
        "last_common": (
            last.isoformat()
            if last
            else None
        ),
        "reason": reason,
    }


def load_checkpoint() -> dict:
    if not CHECKPOINT.exists():
        return {}

    payload = json.loads(
        CHECKPOINT.read_text(
            encoding="utf-8"
        )
    )

    if (
        payload.get("version")
        != VERSION
        or payload.get("start")
        != sweep.START.isoformat()
        or payload.get("end")
        != sweep.END.isoformat()
        or float(
            payload.get(
                "minimum_session_overlap",
                -1,
            )
        )
        != MINIMUM_SESSION_OVERLAP
    ):
        raise RuntimeError(
            "Existing daily eligibility "
            "checkpoint is incompatible."
        )

    records = payload.get(
        "records",
        {},
    )

    if not isinstance(
        records,
        dict,
    ):
        raise RuntimeError(
            "Daily eligibility checkpoint "
            "is malformed."
        )

    return records


def save_checkpoint(
    records: dict,
) -> None:
    CHECKPOINT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    payload = {
        "version": VERSION,
        "start": (
            sweep.START.isoformat()
        ),
        "end": (
            sweep.END.isoformat()
        ),
        "minimum_session_overlap": (
            MINIMUM_SESSION_OVERLAP
        ),
        "record_count": len(
            records
        ),
        "records": records,
    }

    temporary = (
        CHECKPOINT.with_suffix(
            ".tmp"
        )
    )

    temporary.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    temporary.replace(
        CHECKPOINT
    )


def failure_row(
    record: dict,
) -> dict:
    symbol = str(
        record["symbol"]
    )

    return {
        "symbol": symbol,
        "status": "FAILED",
        "failure_stage": (
            "DAILY_ELIGIBILITY"
        ),
        "qdte_volume_exception": (
            symbol == "QDTE"
        ),
        "daily_sessions": (
            record[
                "daily_sessions"
            ]
        ),
        "daily_common_sessions": (
            record[
                "common_sessions"
            ]
        ),
        "daily_session_overlap_pct": (
            record[
                "session_overlap_pct"
            ]
        ),
        "error": (
            "DAILY_PREFILTER: "
            + str(
                record[
                    "reason"
                ]
            )
        ),
    }


def control_test(
    master: set[date],
) -> None:
    controls = [
        "XLE",
        "QDTE",
        "AMD",
    ]

    days = fetch_daily_days(
        controls
    )

    print(
        "DAILY PREFILTER CONTROLS"
    )

    for symbol in controls:
        record = evaluate(
            symbol,
            days[symbol],
            master,
        )

        if not record[
            "eligible"
        ]:
            raise RuntimeError(
                f"{symbol} control failed: "
                f"{record['reason']}"
            )

        print(
            f"{symbol:<6} PASS | "
            f"{record['common_sessions']}/"
            f"{record['master_sessions']} "
            f"sessions | "
            f"{record['session_overlap_pct']:.2%}"
        )

    print(
        "CONTROL TEST PASSED"
    )


def run_prefilter() -> int:
    universe = (
        sweep.alpaca_universe()
    )

    rows = (
        sweep.load_progress()
    )

    master = (
        qdte_master_sessions()
    )

    control_test(
        master
    )

    records = (
        load_checkpoint()
    )

    recovered = 0

    for symbol, record in (
        records.items()
    ):
        if symbol in rows:
            continue

        if (
            record.get(
                "eligible"
            )
            is False
        ):
            row = failure_row(
                record
            )

            rows[symbol] = row

            sweep.append_progress(
                row
            )

            recovered += 1

    pending = [
        symbol
        for symbol in universe
        if (
            symbol not in rows
            and symbol not in records
        )
    ]

    existing_passes = sum(
        1
        for symbol, record
        in records.items()
        if (
            record.get(
                "eligible"
            )
            is True
            and symbol not in rows
        )
    )

    print()
    print(
        "=" * 80
    )
    print(
        "QPX FAST DAILY ELIGIBILITY PREFILTER"
    )
    print(
        "=" * 80
    )
    print(
        f"Universe              : "
        f"{len(universe):,}"
    )
    print(
        f"Existing results      : "
        f"{len(rows):,}"
    )
    print(
        f"Saved eligible        : "
        f"{existing_passes:,}"
    )
    print(
        f"Recovered rejections  : "
        f"{recovered:,}"
    )
    print(
        f"Need daily check      : "
        f"{len(pending):,}"
    )
    print(
        "Minimum session match : 95%"
    )
    print(
        "Synthetic data        : NONE"
    )
    print(
        "Profitability filter  : NONE"
    )
    print(
        "=" * 80
    )
    print()

    if not pending:
        sweep.write_summary(
            rows,
            universe,
        )

        print(
            "DAILY PREFILTER ALREADY COMPLETE"
        )

        return 0

    started = (
        time.monotonic()
    )

    new_passes = 0
    new_rejections = 0

    for offset in range(
        0,
        len(pending),
        BATCH_SIZE,
    ):
        batch = pending[
            offset:
            offset + BATCH_SIZE
        ]

        daily = fetch_daily_days(
            batch
        )

        for symbol in batch:
            record = evaluate(
                symbol,
                daily[symbol],
                master,
            )

            records[
                symbol
            ] = record

            if record[
                "eligible"
            ]:
                new_passes += 1

            else:
                new_rejections += 1

                row = failure_row(
                    record
                )

                rows[
                    symbol
                ] = row

                sweep.append_progress(
                    row
                )

        save_checkpoint(
            records
        )

        processed = min(
            offset
            + len(batch),
            len(pending),
        )

        elapsed = (
            time.monotonic()
            - started
        )

        rate = (
            processed
            / elapsed
            if elapsed > 0
            else 0.0
        )

        remaining = (
            len(pending)
            - processed
        )

        eta_minutes = (
            remaining
            / rate
            / 60.0
            if rate > 0
            else 0.0
        )

        print(
            f"DAILY [{processed:,}/"
            f"{len(pending):,}] | "
            f"PASS {new_passes:,} | "
            f"REJECT {new_rejections:,} | "
            f"{rate:.2f} symbols/sec | "
            f"ETA {eta_minutes:.1f} min",
            flush=True,
        )

    sweep.write_summary(
        rows,
        universe,
    )

    eligible_total = sum(
        1
        for record
        in records.values()
        if record.get(
            "eligible"
        )
        is True
    )

    rejected_total = sum(
        1
        for record
        in records.values()
        if record.get(
            "eligible"
        )
        is False
    )

    print()
    print(
        "=" * 80
    )
    print(
        "DAILY PREFILTER COMPLETE"
    )
    print(
        f"Eligible for full test : "
        f"{eligible_total:,}"
    )
    print(
        f"Rejected cheaply       : "
        f"{rejected_total:,}"
    )
    print(
        f"Checkpoint             : "
        f"{CHECKPOINT}"
    )
    print(
        "=" * 80
    )

    return 0


def main() -> int:
    parser = (
        argparse.ArgumentParser()
    )

    parser.add_argument(
        "--controls-only",
        action="store_true",
    )

    args = parser.parse_args()

    master = (
        qdte_master_sessions()
    )

    if args.controls_only:
        control_test(
            master
        )

        return 0

    return run_prefilter()


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
