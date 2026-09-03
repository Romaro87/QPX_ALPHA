from __future__ import annotations

import math
import unittest
from dataclasses import fields, replace

import qpx_bot.actual_two_year_15m_six as qpx

from qpx_bot.candidate_v1_causal import (
    CandidateV1CausalInputs,
    evaluate_candidate_v1_causal,
)
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators


def config() -> BotConfig:
    return replace(
        BotConfig(),
        starting_cash=1300.0,
        starting_swing_cash=0.0,
        monthly_contribution=0.0,
        dividend_allocation_years_1_2=0.125,
        swing_allocation_years_1_2=0.875,
        dividend_allocation_later=0.125,
        swing_allocation_later=0.875,
        allocation_rebalance_frequency="weekly",
        maximum_swing_positions=6,
        minimum_average_daily_volume=75_000,
        breakout_volume_multiplier=1.05,
        breakout_lookback=10,
        maximum_vix_for_entries=32.0,
        rsi_overbought=75.0,
        risk_per_trade=0.03,
        maximum_active_portfolio_risk=0.10,
        stop_atr_multiple=2.5,
        target_atr_multiple=5.0,
        trailing_activation_atr=3.0,
        slippage_rate=0.00075,
        annual_tax_reserve_rate=0.37,
    )


def candles() -> list[Candle]:
    result = []
    price = 20.0
    for index in range(320):
        drift = (
            0.06
            + 0.22 * math.sin(index / 9.0)
            - 0.15 * math.cos(index / 17.0)
        )
        open_price = max(
            1.0,
            price + 0.03 * math.sin(index / 3.0),
        )
        close = max(
            1.0,
            open_price + drift,
        )
        high = max(open_price, close) + 0.35
        low = max(
            0.01,
            min(open_price, close) - 0.30,
        )
        result.append(
            Candle(
                date=__import__("datetime").date(
                    2025,
                    1,
                    1,
                )
                + __import__("datetime").timedelta(
                    days=index,
                ),
                open=open_price,
                high=high,
                low=low,
                close=close,
                volume=(
                    100_000
                    + (index % 11) * 12_000
                ),
            )
        )
        price = close
    return result


def strict_inputs(
    *,
    source: list[Candle],
    indicator_set,
    index: int,
    vix: float,
    cfg: BotConfig,
) -> CandidateV1CausalInputs:
    previous = index - 1
    slope = index - cfg.sma_slope_lookback
    breakout_start = (
        index - cfg.breakout_lookback
    )
    current = source[index]
    return CandidateV1CausalInputs(
        index=index,
        current_close=current.close,
        current_volume=current.volume,
        current_fast=float(
            indicator_set.ema_fast[index]
        ),
        previous_fast=float(
            indicator_set.ema_fast[previous]
        ),
        current_slow=float(
            indicator_set.ema_slow[index]
        ),
        previous_slow=float(
            indicator_set.ema_slow[previous]
        ),
        current_rsi=float(
            indicator_set.rsi[index]
        ),
        previous_rsi=float(
            indicator_set.rsi[previous]
        ),
        current_rmi=float(
            indicator_set.rmi[index]
        ),
        previous_rmi=float(
            indicator_set.rmi[previous]
        ),
        current_sma=float(
            indicator_set.sma_trend[index]
        ),
        slope_sma=float(
            indicator_set.sma_trend[slope]
        ),
        baseline_volume=float(
            indicator_set.average_volume[
                previous
            ]
        ),
        current_atr=float(
            indicator_set.atr[index]
        ),
        prior_high=max(
            item.high
            for item in source[
                breakout_start:index
            ]
        ),
        vix=vix,
    )


def legacy(
    *,
    source,
    indicator_set,
    index,
    vix,
    cfg,
):
    evaluation = (
        qpx.evaluate_entry(
            candles=source,
            indicators=indicator_set,
            index=index,
            vix=vix,
            config=cfg,
        )
    )
    return evaluation


class CandidateV1CausalTests(unittest.TestCase):
    def test_strategy_surface_contains_only_scalars(self):
        forbidden = {
            "candles",
            "history",
            "histories",
            "indicators",
            "portal",
            "bars",
            "future",
        }
        names = {
            item.name.lower()
            for item in fields(
                CandidateV1CausalInputs
            )
        }
        self.assertTrue(
            names.isdisjoint(forbidden)
        )

    def test_strict_logic_matches_preserved_candidate(self):
        cfg = config()
        source = candles()
        indicators = calculate_indicators(
            source,
            cfg,
        )

        comparisons = 0
        for index in (
            205,
            220,
            240,
            260,
            280,
            300,
            319,
        ):
            for vix in (
                18.0,
                22.0,
                25.0,
                30.0,
                33.0,
            ):
                inputs = strict_inputs(
                    source=source,
                    indicator_set=indicators,
                    index=index,
                    vix=vix,
                    cfg=cfg,
                )
                strict = (
                    evaluate_candidate_v1_causal(
                        inputs=inputs,
                        config=cfg,
                    )
                )
                old = legacy(
                    source=source,
                    indicator_set=indicators,
                    index=index,
                    vix=vix,
                    cfg=cfg,
                )

                self.assertEqual(
                    strict.should_enter,
                    old.should_enter,
                )
                self.assertEqual(
                    dict(strict.checks),
                    dict(old.checks),
                )
                self.assertEqual(
                    strict.triggers,
                    old.triggers,
                )
                self.assertEqual(
                    strict.failed_checks,
                    old.failed_checks,
                )
                comparisons += 1

        self.assertEqual(
            comparisons,
            35,
        )

    def test_historical_vix_range_is_not_an_extra_gate(self):
        cfg = config()
        source = candles()
        indicators = calculate_indicators(
            source,
            cfg,
        )
        for vix in (20.0001, 24.9999):
            evaluation = (
                evaluate_candidate_v1_causal(
                    inputs=strict_inputs(
                        source=source,
                        indicator_set=indicators,
                        index=250,
                        vix=vix,
                        cfg=cfg,
                    ),
                    config=cfg,
                )
            )
            self.assertNotIn("candidate_vix_20_25_exclusion", evaluation.checks)

    def test_persistent_momentum_is_not_an_entry_trigger(self):
        cfg = config()
        source = candles()
        indicators = calculate_indicators(source, cfg)
        inputs = strict_inputs(
            source=source, indicator_set=indicators, index=250, vix=18.0, cfg=cfg
        )
        inputs = replace(
            inputs,
            previous_fast=inputs.current_fast + 1.0,
            previous_slow=inputs.current_slow,
            current_fast=inputs.current_slow + 1.0,
            current_slow=inputs.current_slow,
            previous_rsi=inputs.current_rsi,
            current_rsi=max(52.0, inputs.current_rsi),
            previous_rmi=inputs.current_rmi,
            current_rmi=max(52.0, inputs.current_rmi),
        )
        evaluation = evaluate_candidate_v1_causal(inputs=inputs, config=cfg)
        self.assertNotIn("MOMENTUM_PERSISTENCE", evaluation.triggers)
        self.assertNotIn("candidate_vix_20_25_exclusion", evaluation.checks)


if __name__ == "__main__":
    unittest.main(verbosity=2)
