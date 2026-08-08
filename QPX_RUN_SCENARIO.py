from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path

from qpx_bot.scenario_config import (
    DEFAULT_SCENARIO,
    load_scenario,
)


ROOT = Path(__file__).resolve().parent

REFERENCE_RUNNER = (
    ROOT
    / "qpx_bot"
    / "scenarios"
    / "candidate_v1_reference_runner.py"
)

RUNTIME_DIR = (
    ROOT
    / "qpx_bot"
    / "scenario_runtime"
)


def safe_name(value: str) -> str:
    result = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        value.strip(),
    ).strip("_")

    return result or "scenario"


def replace_one(
    source: str,
    old: str,
    new: str,
    label: str,
) -> str:
    count = source.count(old)

    if count < 1:
        raise RuntimeError(
            f"Scenario adapter could not locate {label}."
        )

    return source.replace(old, new, 1)


def replace_regex_one(
    source: str,
    pattern: str,
    replacement: str,
    label: str,
) -> str:
    result, count = re.subn(
        pattern,
        replacement,
        source,
        count=1,
        flags=re.MULTILINE,
    )

    if count != 1:
        raise RuntimeError(
            f"Scenario adapter could not locate {label}."
        )

    return result


def scenario_symbol_file(
    scenario_name: str,
    symbols: dict,
) -> Path:
    RUNTIME_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    path = (
        RUNTIME_DIR
        / f"{safe_name(scenario_name)}_symbols.json"
    )

    payload = {
        "candidate_symbols": symbols[
            "candidate_symbols"
        ],
        "tradable_symbols": symbols[
            "tradable_symbols"
        ],
        "income_symbol": symbols[
            "income_symbol"
        ],
        "volatility_symbol": symbols[
            "volatility_symbol"
        ],
    }

    path.write_text(
        json.dumps(
            payload,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return path


def candidate_entry_block(
    source: str,
    *,
    low: float,
    high: float,
) -> str:
    start = source.find(
        "def candidate_entry("
    )

    if start < 0:
        raise RuntimeError(
            "Candidate VIX filter function was not found."
        )

    end = source.find(
        "# ============================================================",
        start + 1,
    )

    if end < 0:
        raise RuntimeError(
            "Candidate VIX filter boundary was not found."
        )

    block = source[start:end]

    # The reference strategy used 20 < VIX < 25.
    # Restrict replacements to this one function.
    block = block.replace(
        "20.0",
        repr(float(low)),
    )
    block = block.replace(
        "25.0",
        repr(float(high)),
    )

    return (
        source[:start]
        + block
        + source[end:]
    )


def build_source(
    scenario,
    *,
    start: date,
    end: date,
) -> str:
    p = scenario.payload

    symbols = p["symbols"]
    capital = p["capital"]
    allocation = p["allocation"]
    entry = p["entry"]
    risk = p["risk"]
    exit_cfg = p["exit"]
    execution = p["execution"]
    tax = p["tax"]

    source = REFERENCE_RUNNER.read_text(
        encoding="utf-8"
    )

    symbol_file = scenario_symbol_file(
        scenario.name,
        symbols,
    )

    source = replace_one(
        source,
        "_SYMBOL_CONFIG = load_symbol_config()",
        (
            "_SYMBOL_CONFIG = load_symbol_config("
            + repr(str(symbol_file))
            + ")"
        ),
        "symbol configuration load",
    )

    # Ensure every engine-level symbol global follows
    # the scenario instead of the repository default.
    marker = (
        "qpx.SWING_SYMBOLS = "
        "_SYMBOL_CONFIG.candidate_symbols"
    )

    injection = marker + '''
qpx.TRADABLE_SYMBOLS = _SYMBOL_CONFIG.tradable_symbols
qpx.INCOME_SYMBOL = _SYMBOL_CONFIG.income_symbol
qpx.VOLATILITY_SYMBOL = _SYMBOL_CONFIG.volatility_symbol
'''

    source = replace_one(
        source,
        marker,
        injection,
        "engine symbol globals",
    )

    # --------------------------------------------------------
    # Capital + allocation
    # --------------------------------------------------------

    source = replace_regex_one(
        source,
        r'monthly_contribution\s*=\s*0\.0,',
        (
            "monthly_contribution="
            f"{float(capital['monthly_contribution'])!r},"
        ),
        "monthly contribution",
    )

    source = replace_regex_one(
        source,
        (
            r'allocation_rebalance_frequency'
            r'\s*=\s*"weekly",'
        ),
        (
            "allocation_rebalance_frequency="
            + repr(
                str(
                    allocation[
                        "rebalance_frequency"
                    ]
                ).lower()
            )
            + ","
        ),
        "rebalance frequency",
    )

    values = {
        "dividend_allocation_years_1_2":
            allocation[
                "income_weight_years_1_2"
            ],
        "swing_allocation_years_1_2":
            allocation[
                "swing_weight_years_1_2"
            ],
        "dividend_allocation_later":
            allocation[
                "income_weight_later"
            ],
        "swing_allocation_later":
            allocation[
                "swing_weight_later"
            ],
    }

    for key, value in values.items():
        source = replace_regex_one(
            source,
            rf'{key}\s*=\s*[0-9.]+,',
            f"{key}={float(value)!r},",
            key,
        )

    # Add all ordinary BotConfig knobs to CandidateBotConfig.
    marker = "    kwargs.update(\n"

    additional_config = f'''        maximum_swing_positions={int(risk["maximum_positions"])},
        minimum_average_daily_volume={int(entry["minimum_average_15m_volume"])},
        breakout_volume_multiplier={float(entry["breakout_volume_multiplier"])!r},
        breakout_lookback={int(entry["breakout_lookback"])},
        maximum_vix_for_entries={float(entry["maximum_vix"])!r},
        rsi_overbought={float(entry["rsi_overbought"])!r},
        risk_per_trade={float(risk["risk_per_trade"])!r},
        maximum_active_portfolio_risk={float(risk["maximum_active_portfolio_risk"])!r},
        stop_atr_multiple={float(exit_cfg["stop_atr_multiple"])!r},
        target_atr_multiple={float(exit_cfg["target_atr_multiple"])!r},
        trailing_activation_atr={float(exit_cfg["trailing_activation_atr"])!r},
        slippage_rate={float(execution["slippage_rate"])!r},
        annual_tax_reserve_rate={float(tax["annual_tax_reserve_rate"])!r},
        allocation_rebalance_tolerance={float(allocation["rebalance_tolerance"])!r},
        minimum_rebalance_trade={float(allocation["minimum_rebalance_trade"])!r},
'''

    source = replace_one(
        source,
        marker,
        marker + additional_config,
        "CandidateBotConfig kwargs",
    )

    # --------------------------------------------------------
    # Relaxed-entry constants
    # --------------------------------------------------------

    marker = "qpx.BotConfig = CandidateBotConfig"

    constants = marker + f'''

qpx.RELAXED_MINIMUM_AVERAGE_15M_VOLUME = {int(entry["minimum_average_15m_volume"])}
qpx.RELAXED_BREAKOUT_VOLUME_MULTIPLIER = {float(entry["breakout_volume_multiplier"])!r}
qpx.RELAXED_BREAKOUT_LOOKBACK = {int(entry["breakout_lookback"])}
qpx.RELAXED_MAXIMUM_VIX = {float(entry["maximum_vix"])!r}
qpx.RELAXED_RSI_OVERBOUGHT = {float(entry["rsi_overbought"])!r}
qpx.RELAXED_MOMENTUM_PERSISTENCE_LEVEL = {float(entry["momentum_persistence_level"])!r}
qpx.RELAXED_MAXIMUM_GAP_ATR_MULTIPLE = {float(entry["maximum_gap_atr_multiple"])!r}
'''

    source = replace_one(
        source,
        marker,
        constants,
        "relaxed-entry configuration",
    )

    # The reference runner rewrites the historical
    # risk profile from 1%/6% to Candidate V1's 3%/10%.
    # Parameterize those replacement targets.
    source = source.replace(
        "risk_per_trade=0.03",
        (
            "risk_per_trade="
            f"{float(risk['risk_per_trade'])!r}"
        ),
    )

    source = source.replace(
        "maximum_active_portfolio_risk=0.10",
        (
            "maximum_active_portfolio_risk="
            f"{float(risk['maximum_active_portfolio_risk'])!r}"
        ),
    )

    # --------------------------------------------------------
    # Notional cap
    # --------------------------------------------------------

    source = replace_regex_one(
        source,
        (
            r'qpx\.RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION'
            r'\s*=\s*\(\s*0\.90\s*\)'
        ),
        (
            "qpx.RESEARCH_MAXIMUM_POSITION_NOTIONAL_FRACTION = ("
            f"\n    {float(risk['maximum_position_notional'])!r}"
            "\n)"
        ),
        "position-notional cap",
    )

    # --------------------------------------------------------
    # VIX exclusion band
    # --------------------------------------------------------

    source = candidate_entry_block(
        source,
        low=float(
            entry["vix_exclusion_low"]
        ),
        high=float(
            entry["vix_exclusion_high"]
        ),
    )

    # --------------------------------------------------------
    # Maximum concurrent positions in policy
    # --------------------------------------------------------

    policy_marker = (
        "qpx.load_policy = _xle_only_policy"
    )

    if policy_marker in source:
        policy_injection = policy_marker + f'''

_original_scenario_policy = qpx.load_policy

def _scenario_policy(*args, **kwargs):
    policy = _original_scenario_policy(
        *args,
        **kwargs,
    )
    return dataclass_replace(
        policy,
        maximum_concurrent_positions={int(risk["maximum_positions"])},
    )

qpx.load_policy = _scenario_policy
'''
        source = source.replace(
            policy_marker,
            policy_injection,
            1,
        )

    # --------------------------------------------------------
    # Test window
    # --------------------------------------------------------

    source = replace_regex_one(
        source,
        (
            r'^START\s*=\s*date'
            r'\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)'
        ),
        (
            f"START = date("
            f"{start.year}, {start.month}, {start.day})"
        ),
        "test start date",
    )

    source = replace_regex_one(
        source,
        (
            r'^REQUESTED_END\s*=\s*date'
            r'\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)'
        ),
        (
            f"REQUESTED_END = date("
            f"{end.year}, {end.month}, {end.day})"
        ),
        "test end date",
    )

    # --------------------------------------------------------
    # Scenario-specific report folder
    # --------------------------------------------------------

    source = source.replace(
        "qpx_candidate_v1_weekly_no_external_cash",
        (
            "qpx_scenario_"
            + safe_name(scenario.name)
        ),
    )

    # Replace misleading XLE-only banner text.
    candidate_text = ", ".join(
        symbols["candidate_symbols"]
    )
    tradable_text = ", ".join(
        symbols["tradable_symbols"]
    )

    source = source.replace(
        'print("Swing universe        : XLE ONLY")',
        (
            'print("Swing universe        : '
            + candidate_text
            + '")'
        ),
    )

    source = source.replace(
        'print("Market-data universe  : XLE + QDTE + official CBOE VIX")',
        (
            'print("Market-data universe  : '
            + candidate_text
            + " + "
            + str(symbols["income_symbol"])
            + ' + official volatility data")'
        ),
    )

    # Keep this first generalized runner LOCAL ONLY.
    # Missing symbols must fail instead of silently falling
    # back to stale/spliced/synthetic data.
    source = source.replace(
        "local_only=True",
        "local_only=True",
    )

    return source


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run the validated QPX strategy engine "
            "from a scenario configuration."
        )
    )

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

    scenario = load_scenario(
        args.scenario
    )

    start = parse_day(args.start)
    end = parse_day(args.end)

    if end < start:
        raise ValueError(
            "Scenario end date cannot precede start date."
        )

    print("=" * 92)
    print("QPX CONFIGURATION-DRIVEN SCENARIO RUNNER")
    print("=" * 92)
    print(f"Scenario              : {scenario.name}")
    print(
        "Candidates            : "
        + ", ".join(
            scenario.symbols[
                "candidate_symbols"
            ]
        )
    )
    print(
        "Tradable              : "
        + ", ".join(
            scenario.symbols[
                "tradable_symbols"
            ]
        )
    )
    print(
        "Monthly contribution  : "
        f"${scenario.capital['monthly_contribution']:,.2f}"
    )
    print(
        "Rebalance             : "
        + str(
            scenario.allocation[
                "rebalance_frequency"
            ]
        ).upper()
    )
    print(
        "Risk / active risk    : "
        f"{scenario.risk['risk_per_trade']:.2%} / "
        f"{scenario.risk['maximum_active_portfolio_risk']:.2%}"
    )
    print(
        "Position notional cap : "
        f"{scenario.risk['maximum_position_notional']:.2%}"
    )
    print(f"Test range            : {start} -> {end}")
    print("Data mode             : VALIDATED LOCAL CACHE")
    print("Synthetic data        : DISABLED")
    print("Placeholder data      : DISABLED")
    print("Live brokerage        : DISABLED")
    print("=" * 92)

    source = build_source(
        scenario,
        start=start,
        end=end,
    )

    namespace = {
        "__name__": "__main__",
        "__file__": str(
            REFERENCE_RUNNER
        ),
    }

    exec(
        compile(
            source,
            str(REFERENCE_RUNNER),
            "exec",
        ),
        namespace,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
