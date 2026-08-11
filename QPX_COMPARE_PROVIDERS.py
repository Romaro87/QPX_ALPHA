from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path


START = date(2024, 8, 8)
END = date(2026, 8, 5)

ROOT = Path(__file__).resolve().parent

MASSIVE = (
    ROOT
    / "research_data"
    / "qpx_actual_two_year_15m_six"
    / "shared"
    / "aggregate_15m"
)

ALPACA = (
    ROOT
    / "research_data"
    / "qpx_alpaca_sip"
    / "shared"
    / "aggregate_15m"
)

SYMBOLS = ("XLE", "QDTE")


def load(path: Path):
    bars = {}

    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            try:
                timestamp = datetime.fromisoformat(
                    row["TimestampMarket"]
                )

                if not (
                    START
                    <= timestamp.date()
                    <= END
                ):
                    continue

                bars[timestamp.isoformat()] = {
                    "time": timestamp,
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(
                        float(row["Volume"])
                    ),
                }

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

    return bars


def pct_delta(a, b):
    if a == 0:
        return 0.0

    return abs(b - a) / abs(a)


print("=" * 88)
print("QPX PROVIDER AUDIT — MASSIVE vs ALPACA SIP")
print("=" * 88)
print(f"Fixed comparison window : {START} -> {END}")
print("Adjustment comparison   : current cached provider outputs")
print("Synthetic data          : NONE")
print("=" * 88)

for symbol in SYMBOLS:
    massive_path = MASSIVE / f"{symbol}_15M.csv"
    alpaca_path = ALPACA / f"{symbol}_15M.csv"

    if not massive_path.exists():
        raise SystemExit(
            f"Missing Massive cache: {massive_path}"
        )

    if not alpaca_path.exists():
        raise SystemExit(
            f"Missing Alpaca cache: {alpaca_path}"
        )

    massive = load(massive_path)
    alpaca = load(alpaca_path)

    massive_times = set(massive)
    alpaca_times = set(alpaca)

    common = sorted(
        massive_times & alpaca_times
    )

    only_massive = sorted(
        massive_times - alpaca_times
    )

    only_alpaca = sorted(
        alpaca_times - massive_times
    )

    price_differences = 0
    volume_differences = 0

    max_open = 0.0
    max_high = 0.0
    max_low = 0.0
    max_close = 0.0
    max_volume_pct = 0.0

    total_close_pct = 0.0
    total_volume_pct = 0.0

    exact_ohlc = 0
    exact_volume = 0

    large_price = []
    large_volume = []

    for timestamp in common:
        m = massive[timestamp]
        a = alpaca[timestamp]

        deltas = {
            "open": pct_delta(
                m["open"],
                a["open"],
            ),
            "high": pct_delta(
                m["high"],
                a["high"],
            ),
            "low": pct_delta(
                m["low"],
                a["low"],
            ),
            "close": pct_delta(
                m["close"],
                a["close"],
            ),
        }

        volume_pct = pct_delta(
            m["volume"],
            a["volume"],
        )

        if all(
            abs(
                m[field]
                - a[field]
            ) < 1e-10
            for field in (
                "open",
                "high",
                "low",
                "close",
            )
        ):
            exact_ohlc += 1
        else:
            price_differences += 1

        if m["volume"] == a["volume"]:
            exact_volume += 1
        else:
            volume_differences += 1

        max_open = max(
            max_open,
            deltas["open"],
        )
        max_high = max(
            max_high,
            deltas["high"],
        )
        max_low = max(
            max_low,
            deltas["low"],
        )
        max_close = max(
            max_close,
            deltas["close"],
        )
        max_volume_pct = max(
            max_volume_pct,
            volume_pct,
        )

        total_close_pct += (
            deltas["close"]
        )

        total_volume_pct += (
            volume_pct
        )

        if deltas["close"] >= 0.001:
            large_price.append(
                (
                    deltas["close"],
                    timestamp,
                    m["close"],
                    a["close"],
                )
            )

        if volume_pct >= 0.10:
            large_volume.append(
                (
                    volume_pct,
                    timestamp,
                    m["volume"],
                    a["volume"],
                )
            )

    missing_alpaca_days = Counter(
        alpaca[t]["time"].date()
        for t in only_alpaca
    )

    missing_massive_days = Counter(
        massive[t]["time"].date()
        for t in only_massive
    )

    print()
    print("-" * 88)
    print(f"SYMBOL: {symbol}")
    print("-" * 88)

    print(
        f"Massive bars            : "
        f"{len(massive):,}"
    )

    print(
        f"Alpaca SIP bars         : "
        f"{len(alpaca):,}"
    )

    print(
        f"Common timestamps       : "
        f"{len(common):,}"
    )

    print(
        f"Only in Massive         : "
        f"{len(only_massive):,}"
    )

    print(
        f"Only in Alpaca SIP      : "
        f"{len(only_alpaca):,}"
    )

    if common:
        print(
            f"Exact OHLC matches      : "
            f"{exact_ohlc:,} "
            f"({exact_ohlc / len(common):.2%})"
        )

        print(
            f"Different OHLC bars     : "
            f"{price_differences:,}"
        )

        print(
            f"Exact volume matches    : "
            f"{exact_volume:,} "
            f"({exact_volume / len(common):.2%})"
        )

        print(
            f"Different volume bars   : "
            f"{volume_differences:,}"
        )

        print(
            f"Mean close difference   : "
            f"{total_close_pct / len(common):.5%}"
        )

        print(
            f"Max close difference    : "
            f"{max_close:.5%}"
        )

        print(
            f"Max open difference     : "
            f"{max_open:.5%}"
        )

        print(
            f"Max high difference     : "
            f"{max_high:.5%}"
        )

        print(
            f"Max low difference      : "
            f"{max_low:.5%}"
        )

        print(
            f"Mean volume difference  : "
            f"{total_volume_pct / len(common):.2%}"
        )

        print(
            f"Max volume difference   : "
            f"{max_volume_pct:.2%}"
        )

    print()
    print(
        "First timestamps present in "
        "Alpaca but absent from Massive:"
    )

    for timestamp in only_alpaca[:12]:
        print(f"  {timestamp}")

    if not only_alpaca:
        print("  none")

    print()
    print(
        "First timestamps present in "
        "Massive but absent from Alpaca:"
    )

    for timestamp in only_massive[:12]:
        print(f"  {timestamp}")

    if not only_massive:
        print("  none")

    if missing_alpaca_days:
        print()
        print(
            "Top dates where Alpaca has "
            "bars Massive lacks:"
        )

        for day, count in (
            missing_alpaca_days
            .most_common(10)
        ):
            print(
                f"  {day}: {count} bars"
            )

    if missing_massive_days:
        print()
        print(
            "Top dates where Massive has "
            "bars Alpaca lacks:"
        )

        for day, count in (
            missing_massive_days
            .most_common(10)
        ):
            print(
                f"  {day}: {count} bars"
            )

    if large_price:
        print()
        print(
            "Largest close-price differences:"
        )

        for (
            delta,
            timestamp,
            massive_close,
            alpaca_close,
        ) in sorted(
            large_price,
            reverse=True,
        )[:10]:
            print(
                f"  {timestamp} | "
                f"{delta:.4%} | "
                f"Massive={massive_close:.4f} | "
                f"Alpaca={alpaca_close:.4f}"
            )

    if large_volume:
        print()
        print(
            "Largest volume differences:"
        )

        for (
            delta,
            timestamp,
            massive_volume,
            alpaca_volume,
        ) in sorted(
            large_volume,
            reverse=True,
        )[:10]:
            print(
                f"  {timestamp} | "
                f"{delta:.2%} | "
                f"Massive={massive_volume:,} | "
                f"Alpaca={alpaca_volume:,}"
            )

print()
print("=" * 88)
print("AUDIT COMPLETE")
print("=" * 88)
