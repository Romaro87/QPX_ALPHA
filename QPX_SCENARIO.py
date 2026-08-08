from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from qpx_bot.scenario_config import (
    DEFAULT_SCENARIO,
    load_scenario,
    validate_scenario,
)


def show(path: Path) -> None:
    scenario = load_scenario(path)
    p = scenario.payload

    print("=" * 72)
    print("QPX SCENARIO")
    print("=" * 72)
    print(f"Name                  : {scenario.name}")
    print(
        "Candidates            : "
        + ", ".join(p["symbols"]["candidate_symbols"])
    )
    print(
        "Tradable              : "
        + ", ".join(p["symbols"]["tradable_symbols"])
    )
    print(
        f"Income                : "
        f"{p['symbols']['income_symbol']}"
    )
    print(
        f"Volatility            : "
        f"{p['symbols']['volatility_symbol']}"
    )
    print(
        f"Monthly contribution  : "
        f"${p['capital']['monthly_contribution']:,.2f}"
    )
    print(
        f"Income / swing        : "
        f"{p['allocation']['income_weight_years_1_2']:.1%} / "
        f"{p['allocation']['swing_weight_years_1_2']:.1%}"
    )
    print(
        f"Rebalance             : "
        f"{p['allocation']['rebalance_frequency'].upper()}"
    )
    print(
        f"Risk / trade          : "
        f"{p['risk']['risk_per_trade']:.2%}"
    )
    print(
        f"Active risk max       : "
        f"{p['risk']['maximum_active_portfolio_risk']:.2%}"
    )
    print(
        f"Position notional max : "
        f"{p['risk']['maximum_position_notional']:.2%}"
    )
    print(
        f"Maximum positions     : "
        f"{p['risk']['maximum_positions']}"
    )
    print(
        f"Kelly                 : "
        f"{'ON' if p['risk']['kelly_enabled'] else 'OFF'}"
    )
    print(
        f"VIX exclusion         : "
        f"{p['entry']['vix_exclusion_low']} < VIX < "
        f"{p['entry']['vix_exclusion_high']}"
    )
    print(
        f"Gap ceiling           : "
        f"{p['entry']['maximum_gap_atr_multiple']} ATR"
    )
    print(
        f"ATR stop / target     : "
        f"{p['exit']['stop_atr_multiple']} / "
        f"{p['exit']['target_atr_multiple']}"
    )
    print("Live broker           : DISABLED")
    print("=" * 72)
    print(f"File                  : {scenario.path}")


def clone(source: Path, destination: Path, name: str | None) -> None:
    scenario = load_scenario(source)
    payload = scenario.clone_payload()

    if name:
        payload["name"] = name

    validate_scenario(payload)

    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Created scenario: {destination}")


def set_value(path: Path, key: str, raw_value: str) -> None:
    scenario = load_scenario(path)
    payload = scenario.clone_payload()

    parts = key.split(".")
    target = payload

    for part in parts[:-1]:
        if part not in target or not isinstance(target[part], dict):
            raise KeyError(f"Unknown configuration path: {key}")
        target = target[part]

    leaf = parts[-1]

    if leaf not in target:
        raise KeyError(f"Unknown configuration path: {key}")

    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        value = raw_value

    target[leaf] = value

    validate_scenario(payload)

    path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"Updated {key} = {value!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        default=str(DEFAULT_SCENARIO),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser("show")

    clone_parser = sub.add_parser("clone")
    clone_parser.add_argument("destination")
    clone_parser.add_argument("--name")

    set_parser = sub.add_parser("set")
    set_parser.add_argument("key")
    set_parser.add_argument("value")

    args = parser.parse_args()

    path = Path(args.scenario)

    if args.command == "show":
        show(path)

    elif args.command == "clone":
        clone(
            path,
            Path(args.destination),
            args.name,
        )

    elif args.command == "set":
        set_value(
            path,
            args.key,
            args.value,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
