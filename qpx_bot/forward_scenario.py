from __future__ import annotations

from dataclasses import dataclass, replace

from qpx_bot.config import BotConfig
from qpx_bot.scenario_config import Scenario


@dataclass(frozen=True, slots=True)
class ForwardSymbols:
    candidate_symbols: tuple[str, ...]
    tradable_symbols: tuple[str, ...]
    income_symbol: str
    volatility_symbol: str


def validate_forward_scenario(
    scenario: Scenario,
) -> None:
    entry_profile = str(
        scenario.entry["profile"]
    )

    if entry_profile != "RELAXED_FREQUENCY_RESEARCH_V1":
        raise ValueError(
            "Forward Candidate engine currently requires "
            "entry.profile="
            "'RELAXED_FREQUENCY_RESEARCH_V1'."
        )

    if str(
        scenario.exit["profile"]
    ) != "BASELINE_EXIT":
        raise ValueError(
            "Forward Candidate engine currently requires "
            "exit.profile='BASELINE_EXIT'."
        )

    if str(
        scenario.payload["tax"]["profile"]
    ) != "NET_REALIZED_PNL_RESEARCH":
        raise ValueError(
            "Forward Candidate engine currently requires "
            "tax.profile='NET_REALIZED_PNL_RESEARCH'."
        )

    if (
        scenario.payload["safety"][
            "live_broker_enabled"
        ]
        is not False
    ):
        raise ValueError(
            "Forward paper mode requires "
            "live_broker_enabled=false."
        )

    if (
        scenario.payload["safety"][
            "extended_hours_enabled"
        ]
        is not False
    ):
        raise ValueError(
            "Forward paper mode requires "
            "extended_hours_enabled=false."
        )


def forward_symbols(
    scenario: Scenario,
) -> ForwardSymbols:
    validate_forward_scenario(
        scenario
    )

    return ForwardSymbols(
        candidate_symbols=tuple(
            str(value).strip().upper()
            for value
            in scenario.symbols[
                "candidate_symbols"
            ]
        ),
        tradable_symbols=tuple(
            str(value).strip().upper()
            for value
            in scenario.symbols[
                "tradable_symbols"
            ]
        ),
        income_symbol=str(
            scenario.symbols[
                "income_symbol"
            ]
        ).strip().upper(),
        volatility_symbol=str(
            scenario.symbols[
                "volatility_symbol"
            ]
        ).strip().upper(),
    )


def forward_bot_config(
    scenario: Scenario,
    base: BotConfig | None = None,
) -> BotConfig:
    validate_forward_scenario(
        scenario
    )

    config = (
        base
        if base is not None
        else BotConfig()
    )

    symbols = forward_symbols(
        scenario
    )

    config = replace(
        config,

        monthly_contribution=float(
            scenario.capital[
                "monthly_contribution"
            ]
        ),

        dividend_allocation_years_1_2=float(
            scenario.allocation[
                "income_weight_years_1_2"
            ]
        ),
        swing_allocation_years_1_2=float(
            scenario.allocation[
                "swing_weight_years_1_2"
            ]
        ),
        dividend_allocation_later=float(
            scenario.allocation[
                "income_weight_later"
            ]
        ),
        swing_allocation_later=float(
            scenario.allocation[
                "swing_weight_later"
            ]
        ),

        allocation_rebalance_frequency=str(
            scenario.allocation[
                "rebalance_frequency"
            ]
        ).lower(),
        allocation_rebalance_tolerance=float(
            scenario.allocation[
                "rebalance_tolerance"
            ]
        ),
        minimum_rebalance_trade=float(
            scenario.allocation[
                "minimum_rebalance_trade"
            ]
        ),

        dividend_symbol=(
            symbols.income_symbol
        ),

        maximum_swing_positions=int(
            scenario.risk[
                "maximum_positions"
            ]
        ),

        minimum_average_daily_volume=int(
            scenario.entry[
                "minimum_average_15m_volume"
            ]
        ),
        breakout_volume_multiplier=float(
            scenario.entry[
                "breakout_volume_multiplier"
            ]
        ),
        breakout_lookback=int(
            scenario.entry[
                "breakout_lookback"
            ]
        ),
        maximum_vix_for_entries=float(
            scenario.entry[
                "maximum_vix"
            ]
        ),
        rsi_overbought=float(
            scenario.entry[
                "rsi_overbought"
            ]
        ),

        risk_per_trade=float(
            scenario.risk[
                "risk_per_trade"
            ]
        ),
        maximum_active_portfolio_risk=float(
            scenario.risk[
                "maximum_active_portfolio_risk"
            ]
        ),

        stop_atr_multiple=float(
            scenario.exit[
                "stop_atr_multiple"
            ]
        ),
        target_atr_multiple=float(
            scenario.exit[
                "target_atr_multiple"
            ]
        ),
        trailing_activation_atr=float(
            scenario.exit[
                "trailing_activation_atr"
            ]
        ),

        slippage_rate=float(
            scenario.payload[
                "execution"
            ][
                "slippage_rate"
            ]
        ),

        annual_tax_reserve_rate=float(
            scenario.payload[
                "tax"
            ][
                "annual_tax_reserve_rate"
            ]
        ),
    )

    config.validate()

    return config


def forward_policy(
    base_policy,
    scenario: Scenario,
):
    validate_forward_scenario(
        scenario
    )

    symbols = forward_symbols(
        scenario
    )

    policy = replace(
        base_policy,

        maximum_concurrent_positions=int(
            scenario.risk[
                "maximum_positions"
            ]
        ),

        maximum_gap_atr_multiple=float(
            scenario.entry[
                "maximum_gap_atr_multiple"
            ]
        ),

        candidates=(
            symbols.candidate_symbols
        ),
        tradable_symbols=(
            symbols.tradable_symbols
        ),
        income_symbol=(
            symbols.income_symbol
        ),
        volatility_symbol=(
            symbols.volatility_symbol
        ),

        extended_hours_enabled=False,
        live_broker_enabled=False,
    )

    policy.validate()

    return policy
