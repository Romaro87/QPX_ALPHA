from __future__ import annotations

import argparse
from datetime import date

from qpx_bot.alpaca_provider import sync
from qpx_bot.scenario_config import (
    DEFAULT_SCENARIO,
    load_scenario,
)


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--scenario",
        default=str(DEFAULT_SCENARIO),
    )

    parser.add_argument(
        "--start",
        default="2024-08-08",
    )

    parser.add_argument(
        "--end",
        default="2026-08-07",
    )

    args = parser.parse_args()

    scenario = load_scenario(args.scenario)

    symbols: list[str] = []

    for symbol in (
        *scenario.symbols["candidate_symbols"],
        scenario.symbols["income_symbol"],
    ):
        symbol = str(symbol).strip().upper()

        if symbol and symbol not in symbols:
            symbols.append(symbol)

    print("=" * 72)
    print("QPX ALPACA SIP BULK SYNC")
    print("=" * 72)
    print(
        "Symbols : "
        + ", ".join(symbols)
    )
    print(
        f"Range   : {args.start} -> {args.end}"
    )
    print("Feed    : SIP")
    print("Bars    : 15 MINUTE")
    print("Mode    : CACHE + RESUME")
    print("Live    : DISABLED")
    print("=" * 72)

    sync(
        symbols=symbols,
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
