"""QPX Bot strategy and execution configuration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BotConfig:
    """Default Hybrid Dividend + Swing strategy settings."""

    # Initial capital
    # $1,300 is seeded into QDTE and $1,500 starts as swing liquidity.
    starting_cash: float = 1_300.0
    starting_swing_cash: float = 1_500.0
    monthly_contribution: float = 2_000.0

    # Years 1–2 target allocation
    dividend_allocation_years_1_2: float = 0.65
    swing_allocation_years_1_2: float = 0.35

    # Year 3 onward target allocation
    dividend_allocation_later: float = 0.40
    swing_allocation_later: float = 0.60

    # Rebalance on the first processed market session of each month.
    allocation_rebalance_frequency: str = "monthly"
    allocation_rebalance_tolerance: float = 0.0025
    minimum_rebalance_trade: float = 1.0

    dividend_symbol: str = "QDTE"

    # Swing opportunity set
    maximum_swing_positions: int = 6

    # Trend and momentum
    ema_fast_period: int = 9
    ema_slow_period: int = 21
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_strength_level: float = 50.0
    rmi_period: int = 14
    rmi_momentum: int = 5
    sma_trend_period: int = 200
    sma_slope_lookback: int = 5

    # Volatility and exits
    atr_period: int = 14
    stop_atr_multiple: float = 2.5
    target_atr_multiple: float = 5.0
    trailing_activation_atr: float = 3.0

    # Liquidity and confirmation
    minimum_average_daily_volume: int = 2_000_000
    average_volume_period: int = 20
    breakout_volume_multiplier: float = 1.20
    breakout_lookback: int = 20
    maximum_vix_for_entries: float = 28.0

    # Risk
    risk_per_trade: float = 0.01
    maximum_active_portfolio_risk: float = 0.06
    kelly_fraction: float = 0.25
    minimum_kelly_trades: int = 20

    # Execution
    slippage_rate: float = 0.00075

    # Tax reserve
    annual_tax_reserve_rate: float = 0.37

    @property
    def total_starting_capital(self) -> float:
        """Return the complete initial external contribution."""
        return self.starting_cash + self.starting_swing_cash

    def validate(self) -> None:
        """Reject internally inconsistent configuration."""
        allocation_pairs = (
            (
                self.dividend_allocation_years_1_2,
                self.swing_allocation_years_1_2,
            ),
            (
                self.dividend_allocation_later,
                self.swing_allocation_later,
            ),
        )

        for dividend_weight, swing_weight in allocation_pairs:
            if abs((dividend_weight + swing_weight) - 1.0) > 1e-9:
                raise ValueError(
                    "Dividend and swing allocations must total 100%."
                )

            if not 0.0 <= dividend_weight <= 1.0:
                raise ValueError(
                    "Dividend allocation must be between zero and one."
                )

            if not 0.0 <= swing_weight <= 1.0:
                raise ValueError(
                    "Swing allocation must be between zero and one."
                )

        if self.starting_cash <= 0:
            raise ValueError(
                "Initial QDTE capital must be positive."
            )

        if self.starting_swing_cash < 0:
            raise ValueError(
                "Initial swing liquidity cannot be negative."
            )

        if self.total_starting_capital <= 0:
            raise ValueError(
                "Total starting capital must be positive."
            )

        if self.monthly_contribution < 0:
            raise ValueError(
                "Monthly contribution cannot be negative."
            )

        if self.allocation_rebalance_frequency != "monthly":
            raise ValueError(
                "Only monthly allocation rebalancing is supported."
            )

        if not 0.0 <= self.allocation_rebalance_tolerance < 0.10:
            raise ValueError(
                "Rebalance tolerance must be between zero and 10%."
            )

        if self.minimum_rebalance_trade < 0:
            raise ValueError(
                "Minimum rebalance trade cannot be negative."
            )

        if self.maximum_swing_positions != 6:
            raise ValueError(
                "This strategy requires exactly six swing slots."
            )

        period_values = {
            "EMA fast": self.ema_fast_period,
            "EMA slow": self.ema_slow_period,
            "RSI": self.rsi_period,
            "RMI": self.rmi_period,
            "SMA": self.sma_trend_period,
            "ATR": self.atr_period,
            "average volume": self.average_volume_period,
            "breakout": self.breakout_lookback,
        }

        for name, value in period_values.items():
            if value < 2:
                raise ValueError(
                    f"{name} period must be at least 2."
                )

        if self.ema_fast_period >= self.ema_slow_period:
            raise ValueError(
                "Fast EMA period must be below slow EMA period."
            )

        if self.rmi_momentum < 1:
            raise ValueError(
                "RMI momentum must be at least 1."
            )

        if not 0 < self.risk_per_trade <= 1:
            raise ValueError(
                "Risk per trade must be between 0 and 1."
            )

        if not 0 < self.maximum_active_portfolio_risk <= 1:
            raise ValueError(
                "Maximum active portfolio risk must be "
                "between 0 and 1."
            )

        if self.stop_atr_multiple <= 0:
            raise ValueError(
                "ATR stop multiple must be positive."
            )

        if self.target_atr_multiple <= self.stop_atr_multiple:
            raise ValueError(
                "ATR target must be greater than the ATR stop."
            )
