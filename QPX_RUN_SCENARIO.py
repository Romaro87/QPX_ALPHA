from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import date
from pathlib import Path

from qpx_bot.scenario_config import (
    DEFAULT_SCENARIO,
    load_scenario,
)

from qpx_bot.alpaca_provider import (
    sync as sync_alpaca,
)

from qpx_bot.alpaca_dividends import (
    sync_dividends as sync_alpaca_dividends,
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

    # Replace misleading XLE-only summary label.
    source = source.replace(
        'f"Closed XLE trades     : "',
        'f"Closed swing trades   : "',
        1,
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



def prepare_scenario_data(
    scenario,
    *,
    start: date,
    end: date,
) -> tuple[Path, str]:
    provider = str(
        scenario.data["provider"]
    ).strip().lower()

    massive_root = (
        ROOT
        / "research_data"
        / "qpx_actual_two_year_15m_six"
    ).resolve()

    if provider == "massive_cache":
        return (
            massive_root,
            "MASSIVE VALIDATED CACHE",
        )

    if provider != "alpaca_sip":
        raise ValueError(
            f"Unsupported data provider: {provider}"
        )

    volatility_symbol = str(
        scenario.symbols[
            "volatility_symbol"
        ]
    ).strip().upper()

    if volatility_symbol != "^VIX":
        raise ValueError(
            "Current historical VIX adapter "
            "requires volatility_symbol='^VIX'."
        )

    symbols = []

    for raw in (
        *scenario.symbols[
            "candidate_symbols"
        ],
        scenario.symbols[
            "income_symbol"
        ],
    ):
        symbol = str(
            raw
        ).strip().upper()

        if (
            symbol
            and symbol not in symbols
        ):
            symbols.append(symbol)

    print()
    print("=" * 92)
    print("QPX DATA PREFLIGHT — ALPACA SIP")
    print("=" * 92)
    print(
        "Symbols               : "
        + ", ".join(symbols)
    )

    sync_alpaca(
        symbols=symbols,
        start=start,
        end=end,
    )

    income_symbol = str(
        scenario.symbols[
            "income_symbol"
        ]
    ).strip().upper()

    sync_alpaca_dividends(
        symbol=income_symbol,
        start=start,
        end=end,
    )

    alpaca_root = (
        ROOT
        / "research_data"
        / "qpx_alpaca_sip"
    ).resolve()

    shared = (
        alpaca_root
        / "shared"
    )

    shared.mkdir(
        parents=True,
        exist_ok=True,
    )

    vix_source = (
        massive_root
        / "shared"
        / "CBOE_VIX_DAILY.csv"
    )

    vix_target = (
        shared
        / "CBOE_VIX_DAILY.csv"
    )

    if not vix_source.exists():
        raise RuntimeError(
            "Validated official CBOE VIX "
            f"cache is missing: {vix_source}"
        )

    if not vix_target.exists():
        shutil.copy2(
            vix_source,
            vix_target,
        )

        print(
            "CBOE VIX              : "
            "COPIED VALIDATED CACHE"
        )
    else:
        print(
            "CBOE VIX              : CACHE HIT"
        )

    print("=" * 92)
    print()

    return (
        alpaca_root,
        "ALPACA SIP HISTORICAL",
    )


def adapt_source_for_provider(
    source: str,
    *,
    scenario,
    provider_root: Path,
) -> str:
    provider = str(
        scenario.data["provider"]
    ).strip().lower()

    old_root = (
        'FRESH_ROOT = Path('
        '"research_data/qpx_actual_two_year_15m_six"'
        ')'
    )

    new_root = (
        "FRESH_ROOT = Path("
        + repr(str(provider_root))
        + ")"
    )

    if old_root not in source:
        raise RuntimeError(
            "Could not locate historical "
            "provider root in reference runner."
        )

    source = source.replace(
        old_root,
        new_root,
        1,
    )

    if provider == "massive_cache":
        return source

    source = source.replace(
        'print("REUSING EXISTING VALIDATED PROVIDER DATA")',
        'print("REUSING ALPACA SIP HISTORICAL DATA")',
        1,
    )

    source = source.replace(
        'print("Market data           : FRESH MASSIVE/POLYGON ONLY")',
        'print("Market data           : ALPACA SIP HISTORICAL")',
        1,
    )

    source = source.replace(
        "Validated local Massive/Polygon actual 15-minute ETF/QDTE caches + official Cboe VIX daily closes",
        "Alpaca SIP historical 15-minute stock/ETF bars + Alpaca corporate actions + official Cboe VIX daily closes",
    )

    inspect_marker = (
        "source = inspect.getsource(\n"
        "    qpx.run_backtest\n"
        ")\n"
    )

    provider_patch = (
        inspect_marker
        + "\n"
        + "source = source.replace(\n"
        + '    "LOCAL_VALIDATED_MASSIVE_POLYGON_CACHE",\n'
        + '    "ALPACA_SIP_HISTORICAL_CACHE",\n'
        + ")\n"
        + "\n"
        + "source = source.replace(\n"
        + '    "LOCAL_VALIDATED_MASSIVE_POLYGON_DIVIDEND_CACHE",\n'
        + '    "ALPACA_CORPORATE_ACTIONS_CACHE",\n'
        + ")\n"
        + "\n"
        + "source = source.replace(\n"
        + '    "Validated local Massive/Polygon actual 15-minute ETF/QDTE caches + official Cboe VIX daily closes",\n'
        + '    "Alpaca SIP historical 15-minute stock/ETF bars + Alpaca corporate actions + official Cboe VIX daily closes",\n'
        + ")\n"
    )

    if inspect_marker not in source:
        raise RuntimeError(
            "Could not locate dynamic "
            "run_backtest source block."
        )

    source = source.replace(
        inspect_marker,
        provider_patch,
        1,
    )

    runner_assignment = (
        'qpx.run_backtest = (\n'
        '    namespace["run_backtest"]\n'
        ')\n'
    )

    alpaca_wrapper = (
        runner_assignment
        + "\n"
        + "_qpx_alpaca_inner_run_backtest = qpx.run_backtest\n"
        + "\n"
        + "def _qpx_alpaca_run_backtest(*args, **kwargs):\n"
        + "    result, artifacts = _qpx_alpaca_inner_run_backtest(\n"
        + "        *args,\n"
        + "        **kwargs,\n"
        + "    )\n"
        + "\n"
        + "    result = dataclass_replace(\n"
        + "        result,\n"
        + "        provider=(\n"
        + '            "Alpaca SIP historical 15-minute stock/ETF bars "\n'
        + '            "+ Alpaca corporate actions "\n'
        + '            "+ official CboE VIX daily closes"\n'
        + "        ),\n"
        + "    )\n"
        + "\n"
        + "    artifacts.report.write_text(\n"
        + "        qpx._format_report(result) + \"\\n\",\n"
        + '        encoding="utf-8",\n'
        + "    )\n"
        + "\n"
        + "    result_payload = qpx.asdict(result)\n"
        + "\n"
        + "    for field in (\n"
        + '        "requested_start",\n'
        + '        "actual_start",\n'
        + '        "actual_end",\n'
        + '        "warmup_start",\n'
        + "    ):\n"
        + "        result_payload[field] = getattr(\n"
        + "            result,\n"
        + "            field,\n"
        + "        ).isoformat()\n"
        + "\n"
        + "    qpx._atomic_json(\n"
        + "        artifacts.result,\n"
        + "        result_payload,\n"
        + "    )\n"
        + "\n"
        + "    return result, artifacts\n"
        + "\n"
        + "qpx.run_backtest = _qpx_alpaca_run_backtest\n"
    )

    if runner_assignment not in source:
        raise RuntimeError(
            "Could not locate generated run_backtest assignment."
        )

    source = source.replace(
        runner_assignment,
        alpaca_wrapper,
        1,
    )


    old_summary = (
        'print(\n'
        '    "This result is the authoritative Candidate V1 "\n'
        '    "historical test for the currently available "\n'
        '    "provider data window."\n'
        ')\n'
    )

    new_summary = (
        'print(\n'
        '    "This is an Alpaca SIP research run. "\n'
        '    "It does not replace the authoritative "\n'
        '    "Candidate V1 Massive benchmark."\n'
        ')\n'
    )

    if old_summary in source:
        source = source.replace(
            old_summary,
            new_summary,
            1,
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

    provider_root, provider_label = (
        prepare_scenario_data(
            scenario,
            start=start,
            end=end,
        )
    )

    print("=" * 92)
    print("QPX CONFIGURATION-DRIVEN SCENARIO RUNNER")
    print("=" * 92)
    print(f"Scenario              : {scenario.name}")
    print(f"Revision              : {scenario.revision}")
    print(
        "Fingerprint           : "
        f"{scenario.fingerprint[:16]}"
    )
    print(
        "Data provider         : "
        f"{scenario.data['provider']}"
    )
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
    print(f"Data mode             : {provider_label}")
    print("Synthetic data        : DISABLED")
    print("Placeholder data      : DISABLED")
    print("Live brokerage        : DISABLED")
    print("=" * 92)

    source = build_source(
        scenario,
        start=start,
        end=end,
    )

    source = adapt_source_for_provider(
        source,
        scenario=scenario,
        provider_root=provider_root,
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
