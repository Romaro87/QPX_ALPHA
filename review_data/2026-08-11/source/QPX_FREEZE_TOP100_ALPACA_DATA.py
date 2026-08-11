from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess

from datetime import date, datetime
from pathlib import Path

import qpx_bot.actual_two_year_15m_six as research

from qpx_bot.alpaca_dividends import (
    dividend_path,
    manifest_path as dividend_manifest_path,
    sync_dividends,
)

from qpx_bot.alpaca_provider import (
    Bar,
    _qpx_original_sync as raw_alpaca_sync,
    cache_path,
    manifest_path as provider_manifest_path,
    read_cache,
)


ROOT = Path(__file__).resolve().parent

SELECTION = (
    ROOT
    / "qpx_bot"
    / "research_universes"
    / "alpaca_top100_qdte1300_thursday_v1.json"
)

FROZEN_ROOT = (
    ROOT
    / "research_data"
    / "qpx_frozen_alpaca_top100_v1"
)

BARS_ROOT = FROZEN_ROOT / "bars"
SYMBOL_META_ROOT = FROZEN_ROOT / "symbol_manifests"
SUPPORT_ROOT = FROZEN_ROOT / "support"
CLOCK_ROOT = FROZEN_ROOT / "clocks"

STATE_PATH = FROZEN_ROOT / "freeze_state.json"
DATASET_MANIFEST = FROZEN_ROOT / "dataset_manifest.json"

START = date(2024, 3, 7)
END = date(2026, 8, 7)

MINIMUM_BAR_OVERLAP = 0.95
MINIMUM_SESSION_OVERLAP = 0.95

EXPECTED_SELECTION_FINGERPRINT = (
    "5e271e4a9e0d4a20b6f4d0cecc08e8b"
    "f9efe1d2123a64832d09ba1c1eb9ffd23"
)

EXPECTED_QDTE_BARS = 15165
EXPECTED_QDTE_SESSIONS = 607

FREEZE_VERSION = "alpaca_top100_frozen_data_v1"


def safe_symbol(symbol: str) -> str:
    return (
        symbol.strip().upper()
        .replace("^", "")
        .replace(":", "_")
        .replace("/", "_")
    )


def frozen_bar_path(symbol: str) -> Path:
    return (
        BARS_ROOT
        / f"{safe_symbol(symbol)}_15M.csv"
    )


def frozen_meta_path(symbol: str) -> Path:
    return (
        SYMBOL_META_ROOT
        / f"{safe_symbol(symbol)}.json"
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def atomic_json(
    path: Path,
    payload,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

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


def atomic_copy(
    source: Path,
    target: Path,
) -> None:
    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = target.with_suffix(
        target.suffix + ".tmp"
    )

    shutil.copyfile(
        source,
        temporary,
    )

    temporary.replace(target)


def load_selection():
    if not SELECTION.exists():
        raise RuntimeError(
            f"Frozen selection manifest missing: {SELECTION}"
        )

    payload = json.loads(
        SELECTION.read_text(
            encoding="utf-8"
        )
    )

    if (
        payload.get("status")
        != "AUDITED_SELECTION_FROZEN"
    ):
        raise RuntimeError(
            "Top-100 selection is not audited/frozen."
        )

    if (
        payload.get("manifest_fingerprint")
        != EXPECTED_SELECTION_FINGERPRINT
    ):
        raise RuntimeError(
            "Top-100 selection fingerprint changed."
        )

    symbols = [
        str(value).strip().upper()
        for value in payload[
            "frozen_research_symbols"
        ]
    ]

    if len(symbols) != 102:
        raise RuntimeError(
            f"Expected 102 frozen symbols, got {len(symbols)}."
        )

    if len(set(symbols)) != 102:
        raise RuntimeError(
            "Frozen symbol list contains duplicates."
        )

    for required in (
        "QDTE",
        "XLE",
        "AMD",
        "TSLA",
    ):
        if required not in symbols:
            raise RuntimeError(
                f"Required control missing: {required}"
            )

    return payload, symbols


def filtered_source_bars(
    symbol: str,
) -> dict[str, Bar]:
    result = {}

    for key, bar in read_cache(
        symbol
    ).items():
        if (
            START
            <= bar.start.date()
            <= END
        ):
            result[key] = bar

    return result


def sanity_check_bar(
    symbol: str,
    bar: Bar,
) -> None:
    values = (
        bar.open,
        bar.high,
        bar.low,
        bar.close,
    )

    if any(
        value <= 0
        for value in values
    ):
        raise RuntimeError(
            f"{symbol}: non-positive OHLC value."
        )

    if (
        bar.high
        < max(
            bar.open,
            bar.low,
            bar.close,
        )
    ):
        raise RuntimeError(
            f"{symbol}: invalid high price."
        )

    if (
        bar.low
        > min(
            bar.open,
            bar.high,
            bar.close,
        )
    ):
        raise RuntimeError(
            f"{symbol}: invalid low price."
        )

    if bar.volume < 0:
        raise RuntimeError(
            f"{symbol}: negative volume."
        )


def validate_bars(
    symbol: str,
    bars: dict[str, Bar],
    *,
    qdte_times=None,
    qdte_sessions=None,
):
    if not bars:
        raise RuntimeError(
            f"{symbol}: frozen history is empty."
        )

    ordered = sorted(
        bars.values(),
        key=lambda item: item.start,
    )

    for bar in ordered:
        sanity_check_bar(
            symbol,
            bar,
        )

    times = {
        bar.start
        for bar in ordered
    }

    if len(times) != len(ordered):
        raise RuntimeError(
            f"{symbol}: duplicate frozen timestamps."
        )

    first_day = min(times).date()
    last_day = max(times).date()

    if first_day != START:
        raise RuntimeError(
            f"{symbol}: first date is {first_day}, "
            f"expected {START}."
        )

    if last_day != END:
        raise RuntimeError(
            f"{symbol}: last date is {last_day}, "
            f"expected {END}."
        )

    sessions = {
        timestamp.date()
        for timestamp in times
    }

    if symbol == "QDTE":
        if len(times) != EXPECTED_QDTE_BARS:
            raise RuntimeError(
                f"QDTE bar count changed: "
                f"{len(times)} != {EXPECTED_QDTE_BARS}"
            )

        if len(sessions) != EXPECTED_QDTE_SESSIONS:
            raise RuntimeError(
                f"QDTE session count changed: "
                f"{len(sessions)} != "
                f"{EXPECTED_QDTE_SESSIONS}"
            )

        return {
            "times": times,
            "sessions_set": sessions,
            "bars": len(times),
            "sessions": len(sessions),
            "common_bars": len(times),
            "bar_overlap_pct": 1.0,
            "common_sessions": len(sessions),
            "session_overlap_pct": 1.0,
            "missing_qdte_timestamps": 0,
        }

    if (
        qdte_times is None
        or qdte_sessions is None
    ):
        raise RuntimeError(
            "QDTE master clock was not supplied."
        )

    common = (
        times
        & qdte_times
    )

    if not common:
        raise RuntimeError(
            f"{symbol}: no common timestamps with QDTE."
        )

    common_sessions = {
        timestamp.date()
        for timestamp in common
    }

    bar_ratio = (
        len(common)
        / len(qdte_times)
    )

    session_ratio = (
        len(common_sessions)
        / len(qdte_sessions)
    )

    if min(common).date() != START:
        raise RuntimeError(
            f"{symbol}: common clock does not reach start."
        )

    if max(common).date() != END:
        raise RuntimeError(
            f"{symbol}: common clock does not reach end."
        )

    if (
        bar_ratio
        < MINIMUM_BAR_OVERLAP
    ):
        raise RuntimeError(
            f"{symbol}: bar overlap dropped to "
            f"{bar_ratio:.2%}."
        )

    if (
        session_ratio
        < MINIMUM_SESSION_OVERLAP
    ):
        raise RuntimeError(
            f"{symbol}: session overlap dropped to "
            f"{session_ratio:.2%}."
        )

    return {
        "times": times,
        "sessions_set": sessions,
        "bars": len(times),
        "sessions": len(sessions),
        "common_bars": len(common),
        "bar_overlap_pct": bar_ratio,
        "common_sessions": len(
            common_sessions
        ),
        "session_overlap_pct": (
            session_ratio
        ),
        "missing_qdte_timestamps": (
            len(qdte_times)
            - len(common)
        ),
    }


def write_frozen_bars(
    path: Path,
    bars: dict[str, Bar],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.writer(
            handle
        )

        writer.writerow(
            (
                "TimestampMarket",
                "Open",
                "High",
                "Low",
                "Close",
                "Volume",
            )
        )

        for bar in sorted(
            bars.values(),
            key=lambda item: item.start,
        ):
            writer.writerow(
                (
                    bar.start.isoformat(),
                    bar.open,
                    bar.high,
                    bar.low,
                    bar.close,
                    bar.volume,
                )
            )

    temporary.replace(path)


def read_frozen_bars(
    path: Path,
) -> dict[str, Bar]:
    bars = {}

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as handle:
        reader = csv.DictReader(
            handle
        )

        required = {
            "TimestampMarket",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        }

        if not required.issubset(
            set(reader.fieldnames or [])
        ):
            raise RuntimeError(
                f"Invalid frozen columns: {path}"
            )

        for row in reader:
            timestamp = datetime.fromisoformat(
                row["TimestampMarket"]
            )

            bar = Bar(
                start=timestamp,
                open=float(
                    row["Open"]
                ),
                high=float(
                    row["High"]
                ),
                low=float(
                    row["Low"]
                ),
                close=float(
                    row["Close"]
                ),
                volume=int(
                    float(
                        row["Volume"]
                    )
                ),
            )

            key = timestamp.isoformat()

            if key in bars:
                raise RuntimeError(
                    f"Duplicate timestamp in {path}"
                )

            bars[key] = bar

    return bars


def refresh_source(
    symbol: str,
) -> dict[str, Bar]:
    source = cache_path(
        symbol
    )

    source_manifest = (
        provider_manifest_path(
            symbol
        )
    )

    if (
        not source.exists()
        and source_manifest.exists()
    ):
        source_manifest.unlink(
            missing_ok=True
        )

    last_error = None

    for attempt in (
        1,
        2,
    ):
        try:
            raw_alpaca_sync(
                symbols=[symbol],
                start=START,
                end=END,
            )

            bars = (
                filtered_source_bars(
                    symbol
                )
            )

            if not bars:
                raise RuntimeError(
                    f"{symbol}: provider cache empty."
                )

            return bars

        except Exception as exc:
            last_error = exc

            if attempt == 1:
                source.unlink(
                    missing_ok=True
                )

                source_manifest.unlink(
                    missing_ok=True
                )

                print(
                    f"{symbol:<8} SOURCE RETRY | "
                    f"{exc}"
                )

    raise RuntimeError(
        f"{symbol}: source refresh failed: "
        f"{last_error}"
    )


def load_existing_frozen(
    symbol: str,
    *,
    qdte_times=None,
    qdte_sessions=None,
):
    data_path = frozen_bar_path(
        symbol
    )

    meta_path = frozen_meta_path(
        symbol
    )

    if (
        not data_path.exists()
        or not meta_path.exists()
    ):
        return None

    try:
        metadata = json.loads(
            meta_path.read_text(
                encoding="utf-8"
            )
        )

        if (
            metadata.get(
                "freeze_version"
            )
            != FREEZE_VERSION
        ):
            return None

        if (
            metadata.get("sha256")
            != sha256(data_path)
        ):
            return None

        bars = read_frozen_bars(
            data_path
        )

        validation = validate_bars(
            symbol,
            bars,
            qdte_times=qdte_times,
            qdte_sessions=qdte_sessions,
        )

        if (
            validation["bars"]
            != metadata.get(
                "bar_count"
            )
        ):
            return None

        return (
            bars,
            validation,
            metadata,
        )

    except Exception:
        return None


def freeze_symbol(
    symbol: str,
    *,
    qdte_times=None,
    qdte_sessions=None,
):
    existing = load_existing_frozen(
        symbol,
        qdte_times=qdte_times,
        qdte_sessions=qdte_sessions,
    )

    if existing is not None:
        return (
            *existing,
            "VERIFIED",
        )

    data_path = frozen_bar_path(
        symbol
    )

    meta_path = frozen_meta_path(
        symbol
    )

    data_path.unlink(
        missing_ok=True
    )

    meta_path.unlink(
        missing_ok=True
    )

    source_bars = (
        refresh_source(
            symbol
        )
    )

    try:
        validation = validate_bars(
            symbol,
            source_bars,
            qdte_times=qdte_times,
            qdte_sessions=qdte_sessions,
        )

    except Exception:
        cache_path(
            symbol
        ).unlink(
            missing_ok=True
        )

        provider_manifest_path(
            symbol
        ).unlink(
            missing_ok=True
        )

        source_bars = (
            refresh_source(
                symbol
            )
        )

        validation = validate_bars(
            symbol,
            source_bars,
            qdte_times=qdte_times,
            qdte_sessions=qdte_sessions,
        )

    write_frozen_bars(
        data_path,
        source_bars,
    )

    frozen_hash = sha256(
        data_path
    )

    source = cache_path(
        symbol
    )

    metadata = {
        "schema_version": 1,
        "freeze_version": (
            FREEZE_VERSION
        ),
        "provider": "alpaca",
        "feed": "sip",
        "adjustment": "split",
        "interval": "15Min",
        "symbol": symbol,
        "window_start": START.isoformat(),
        "window_end": END.isoformat(),
        "bar_count": (
            validation["bars"]
        ),
        "session_count": (
            validation["sessions"]
        ),
        "common_qdte_bars": (
            validation[
                "common_bars"
            ]
        ),
        "bar_overlap_pct": (
            validation[
                "bar_overlap_pct"
            ]
        ),
        "common_qdte_sessions": (
            validation[
                "common_sessions"
            ]
        ),
        "session_overlap_pct": (
            validation[
                "session_overlap_pct"
            ]
        ),
        "missing_qdte_timestamps": (
            validation[
                "missing_qdte_timestamps"
            ]
        ),
        "first_bar": (
            min(
                validation["times"]
            ).isoformat()
        ),
        "last_bar": (
            max(
                validation["times"]
            ).isoformat()
        ),
        "sha256": frozen_hash,
        "source_cache_sha256": (
            sha256(source)
            if source.exists()
            else None
        ),
        "synthetic_data": False,
        "forward_fill": False,
        "timestamp_substitution": False,
    }

    atomic_json(
        meta_path,
        metadata,
    )

    return (
        source_bars,
        validation,
        metadata,
        "FROZEN",
    )


def freeze_support_files():
    vix_source = (
        ROOT
        / "research_data"
        / "qpx_alpaca_sip"
        / "shared"
        / "CBOE_VIX_DAILY.csv"
    )

    if not vix_source.exists():
        raise RuntimeError(
            "Validated CBOE VIX cache is missing."
        )

    closes = (
        research._read_vix_daily_cache(
            vix_source
        )
    )

    validated_vix = (
        research._validate_vix_daily_coverage(
            closes=closes,
            start=START,
            end=END,
        )
    )

    if not validated_vix:
        raise RuntimeError(
            "CBOE VIX validation returned no observations."
        )

    dividends_source = (
        sync_dividends(
            symbol="QDTE",
            start=START,
            end=END,
        )
    )

    if not dividends_source.exists():
        raise RuntimeError(
            "QDTE dividend cache is missing."
        )

    vix_target = (
        SUPPORT_ROOT
        / "CBOE_VIX_DAILY.csv"
    )

    dividend_target = (
        SUPPORT_ROOT
        / "QDTE_DIVIDENDS.csv"
    )

    dividend_manifest_source = (
        dividend_manifest_path(
            "QDTE"
        )
    )

    dividend_manifest_target = (
        SUPPORT_ROOT
        / "QDTE_DIVIDENDS.csv.manifest.json"
    )

    if not vix_target.exists():
        atomic_copy(
            vix_source,
            vix_target,
        )

    if (
        not dividend_target.exists()
        or sha256(dividend_target)
        != sha256(dividends_source)
    ):
        atomic_copy(
            dividends_source,
            dividend_target,
        )

    if (
        dividend_manifest_source.exists()
        and (
            not dividend_manifest_target.exists()
            or sha256(dividend_manifest_target)
            != sha256(dividend_manifest_source)
        )
    ):
        atomic_copy(
            dividend_manifest_source,
            dividend_manifest_target,
        )

    return {
        "cboe_vix": {
            "path": str(
                vix_target.relative_to(
                    FROZEN_ROOT
                )
            ),
            "sha256": sha256(
                vix_target
            ),
            "validated_observations": (
                len(validated_vix)
            ),
        },
        "qdte_dividends": {
            "path": str(
                dividend_target.relative_to(
                    FROZEN_ROOT
                )
            ),
            "sha256": sha256(
                dividend_target
            ),
        },
    }


def write_clock(
    timestamps,
):
    path = (
        CLOCK_ROOT
        / "all102_real_intersection_v1.csv"
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary = path.with_suffix(
        path.suffix + ".tmp"
    )

    with temporary.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as handle:
        writer = csv.writer(
            handle
        )

        writer.writerow(
            ("TimestampMarket",)
        )

        for timestamp in sorted(
            timestamps
        ):
            writer.writerow(
                (
                    timestamp.isoformat(),
                )
            )

    temporary.replace(path)

    return path


def data_fingerprint(
    *,
    selection_fingerprint,
    symbol_metadata,
    support,
    clock_hash,
):
    payload = {
        "freeze_version": (
            FREEZE_VERSION
        ),
        "selection_fingerprint": (
            selection_fingerprint
        ),
        "window_start": (
            START.isoformat()
        ),
        "window_end": (
            END.isoformat()
        ),
        "symbols": {
            symbol: {
                "sha256": (
                    metadata["sha256"]
                ),
                "bars": (
                    metadata[
                        "bar_count"
                    ]
                ),
            }
            for symbol, metadata
            in sorted(
                symbol_metadata.items()
            )
        },
        "support": {
            key: value["sha256"]
            for key, value
            in sorted(
                support.items()
            )
        },
        "all102_clock_sha256": (
            clock_hash
        ),
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(
        encoded
    ).hexdigest()


def verify_dataset():
    if not DATASET_MANIFEST.exists():
        raise RuntimeError(
            "Dataset manifest does not exist."
        )

    manifest = json.loads(
        DATASET_MANIFEST.read_text(
            encoding="utf-8"
        )
    )

    symbols = manifest[
        "symbols"
    ]

    if len(symbols) != 102:
        raise RuntimeError(
            "Dataset manifest does not contain 102 symbols."
        )

    for symbol, metadata in symbols.items():
        path = frozen_bar_path(
            symbol
        )

        if not path.exists():
            raise RuntimeError(
                f"{symbol}: frozen file missing."
            )

        if sha256(path) != metadata[
            "sha256"
        ]:
            raise RuntimeError(
                f"{symbol}: frozen hash mismatch."
            )

    for item in manifest[
        "support"
    ].values():
        path = (
            FROZEN_ROOT
            / item["path"]
        )

        if not path.exists():
            raise RuntimeError(
                f"Support file missing: {path}"
            )

        if sha256(path) != item[
            "sha256"
        ]:
            raise RuntimeError(
                f"Support hash mismatch: {path}"
            )

    clock_path = (
        FROZEN_ROOT
        / manifest[
            "all102_common_clock"
        ][
            "path"
        ]
    )

    if (
        sha256(clock_path)
        != manifest[
            "all102_common_clock"
        ][
            "sha256"
        ]
    ):
        raise RuntimeError(
            "All-102 clock hash mismatch."
        )

    recalculated = data_fingerprint(
        selection_fingerprint=(
            manifest[
                "selection_fingerprint"
            ]
        ),
        symbol_metadata=symbols,
        support=manifest["support"],
        clock_hash=(
            manifest[
                "all102_common_clock"
            ][
                "sha256"
            ]
        ),
    )

    if (
        recalculated
        != manifest[
            "dataset_fingerprint"
        ]
    ):
        raise RuntimeError(
            "Dataset fingerprint mismatch."
        )

    print(
        "DATASET VERIFY         : PASSED"
    )
    print(
        "SYMBOLS VERIFIED       :",
        len(symbols),
    )
    print(
        "DATASET FINGERPRINT    :",
        manifest[
            "dataset_fingerprint"
        ],
    )


def freeze_dataset():
    selection, symbols = (
        load_selection()
    )

    FROZEN_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    if DATASET_MANIFEST.exists():
        verify_dataset()
        return

    ordered_symbols = [
        "QDTE"
    ]

    ordered_symbols.extend(
        symbol
        for symbol in symbols
        if symbol != "QDTE"
    )

    symbol_metadata = {}

    qdte_times = None
    qdte_sessions = None
    all102_clock = None

    minimum_overlap = (
        1.0,
        "QDTE",
    )

    for index, symbol in enumerate(
        ordered_symbols,
        start=1,
    ):
        (
            bars,
            validation,
            metadata,
            action,
        ) = freeze_symbol(
            symbol,
            qdte_times=qdte_times,
            qdte_sessions=qdte_sessions,
        )

        if symbol == "QDTE":
            qdte_times = set(
                validation["times"]
            )

            qdte_sessions = set(
                validation[
                    "sessions_set"
                ]
            )

            all102_clock = set(
                qdte_times
            )

        else:
            assert all102_clock is not None

            all102_clock.intersection_update(
                validation["times"]
            )

        symbol_metadata[
            symbol
        ] = metadata

        overlap = float(
            metadata[
                "bar_overlap_pct"
            ]
        )

        if overlap < minimum_overlap[0]:
            minimum_overlap = (
                overlap,
                symbol,
            )

        atomic_json(
            STATE_PATH,
            {
                "schema_version": 1,
                "freeze_version": (
                    FREEZE_VERSION
                ),
                "status": "IN_PROGRESS",
                "completed": index,
                "total": len(
                    ordered_symbols
                ),
                "last_symbol": symbol,
            },
        )

        print(
            f"[{index:03d}/"
            f"{len(ordered_symbols):03d}] "
            f"{symbol:<8} {action:<8} | "
            f"{metadata['bar_count']:,} bars | "
            f"{overlap:.2%} QDTE overlap"
        )

    assert qdte_times is not None
    assert qdte_sessions is not None
    assert all102_clock is not None

    if not all102_clock:
        raise RuntimeError(
            "All-102 common clock is empty."
        )

    common_sessions = {
        timestamp.date()
        for timestamp in all102_clock
    }

    clock_ratio = (
        len(all102_clock)
        / len(qdte_times)
    )

    clock_path = write_clock(
        all102_clock
    )

    clock_hash = sha256(
        clock_path
    )

    if (
        min(all102_clock).date()
        == START
        and max(all102_clock).date()
        == END
        and clock_ratio
        >= MINIMUM_BAR_OVERLAP
    ):
        clock_status = (
            "ACCEPTABLE_ALL102_COMMON_CLOCK"
        )
    else:
        clock_status = (
            "REFERENCE_ONLY_FINALIST_CLOCK_REQUIRED"
        )

    support = (
        freeze_support_files()
    )

    commit = subprocess.check_output(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        text=True,
    ).strip()

    fingerprint = data_fingerprint(
        selection_fingerprint=(
            selection[
                "manifest_fingerprint"
            ]
        ),
        symbol_metadata=(
            symbol_metadata
        ),
        support=support,
        clock_hash=clock_hash,
    )

    manifest = {
        "schema_version": 1,
        "freeze_version": (
            FREEZE_VERSION
        ),
        "status": "FROZEN_AND_VERIFIED",
        "provider": "ALPACA_SIP",
        "adjustment": "split",
        "interval": "15Min",
        "window_start": (
            START.isoformat()
        ),
        "window_end": (
            END.isoformat()
        ),
        "selection_fingerprint": (
            selection[
                "manifest_fingerprint"
            ]
        ),
        "source_selection": str(
            SELECTION.relative_to(
                ROOT
            )
        ),
        "created_from_commit": (
            commit
        ),
        "qdte_master": {
            "bars": len(
                qdte_times
            ),
            "sessions": len(
                qdte_sessions
            ),
        },
        "minimum_symbol_overlap": {
            "symbol": (
                minimum_overlap[1]
            ),
            "bar_overlap_pct": (
                minimum_overlap[0]
            ),
        },
        "all102_common_clock": {
            "path": str(
                clock_path.relative_to(
                    FROZEN_ROOT
                )
            ),
            "sha256": (
                clock_hash
            ),
            "bars": len(
                all102_clock
            ),
            "sessions": len(
                common_sessions
            ),
            "qdte_bar_coverage": (
                clock_ratio
            ),
            "first_timestamp": (
                min(
                    all102_clock
                ).isoformat()
            ),
            "last_timestamp": (
                max(
                    all102_clock
                ).isoformat()
            ),
            "status": (
                clock_status
            ),
        },
        "symbols": (
            symbol_metadata
        ),
        "support": support,
        "synthetic_data": False,
        "forward_fill": False,
        "timestamp_substitution": False,
        "finalist_clock_status": (
            "PENDING_IDENTICAL_CLOCK_FINALIST_ROUND"
        ),
        "dataset_fingerprint": (
            fingerprint
        ),
    }

    atomic_json(
        DATASET_MANIFEST,
        manifest,
    )

    atomic_json(
        STATE_PATH,
        {
            "schema_version": 1,
            "freeze_version": (
                FREEZE_VERSION
            ),
            "status": (
                "FROZEN_AND_VERIFIED"
            ),
            "completed": 102,
            "total": 102,
            "dataset_fingerprint": (
                fingerprint
            ),
        },
    )

    verify_dataset()

    print()
    print(
        "DATA FREEZE STATUS     : COMPLETE"
    )
    print(
        "FROZEN SYMBOLS         : 102"
    )
    print(
        "QDTE MASTER BARS       :",
        len(qdte_times),
    )
    print(
        "QDTE MASTER SESSIONS   :",
        len(qdte_sessions),
    )
    print(
        "MIN SYMBOL OVERLAP     :",
        f"{minimum_overlap[0]:.2%}",
        minimum_overlap[1],
    )
    print(
        "ALL102 COMMON BARS     :",
        len(all102_clock),
    )
    print(
        "ALL102 CLOCK COVERAGE  :",
        f"{clock_ratio:.2%}",
    )
    print(
        "ALL102 CLOCK STATUS    :",
        clock_status,
    )
    print(
        "DATASET FINGERPRINT    :",
        fingerprint,
    )
    print(
        "DATASET MANIFEST       :",
        DATASET_MANIFEST,
    )


def plan():
    selection, symbols = (
        load_selection()
    )

    print(
        "FREEZE PLAN            : PASSED"
    )
    print(
        "SELECTION STATUS       :",
        selection["status"],
    )
    print(
        "SELECTION FINGERPRINT  :",
        selection[
            "manifest_fingerprint"
        ],
    )
    print(
        "SYMBOLS                :",
        len(symbols),
    )
    print(
        "WINDOW                 :",
        START,
        "->",
        END,
    )
    print(
        "MIN BAR OVERLAP        :",
        f"{MINIMUM_BAR_OVERLAP:.0%}",
    )
    print(
        "SYNTHETIC DATA         : DISABLED"
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--plan",
        action="store_true",
    )

    parser.add_argument(
        "--verify-only",
        action="store_true",
    )

    args = parser.parse_args()

    if args.plan:
        plan()
        return

    if args.verify_only:
        verify_dataset()
        return

    freeze_dataset()


if __name__ == "__main__":
    main()
