"""QDTE/swing allocation rebalancing with slippage and tax reserves."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AllocationRebalance:
    target_income_weight: float
    before_income_weight: float
    after_income_weight: float
    before_income_value: float
    after_income_value: float
    before_investable_value: float
    after_investable_value: float
    action: str
    shares_before: float
    shares_after: float
    income_cost_before: float
    income_cost_after: float
    swing_cash_before: float
    swing_cash_after: float
    trade_cash: float
    market_value_traded: float
    realized_pnl: float
    tax_reserved: float
    target_fully_reached: bool

    @property
    def shares_delta(self) -> float:
        return self.shares_after - self.shares_before


def _weight(
    income_value: float,
    investable_value: float,
) -> float:
    return (
        income_value / investable_value
        if investable_value > 0
        else 0.0
    )


def rebalance_income_allocation(
    *,
    income_shares: float,
    income_cost: float,
    swing_cash: float,
    swing_market_value: float,
    income_price: float,
    target_income_weight: float,
    slippage_rate: float,
    tax_reserve_rate: float,
    tolerance: float,
    minimum_trade: float,
) -> AllocationRebalance:
    """
    Rebalance QDTE toward its target without liquidating swing positions.

    QDTE may be bought with available swing cash or sold to create swing
    liquidity. Open swing positions are marked at market but are never
    sold by this allocator. Positive realized QDTE-sale gains reserve
    the configured tax percentage in cash.
    """
    numeric = {
        "income shares": income_shares,
        "income cost": income_cost,
        "swing cash": swing_cash,
        "swing market value": swing_market_value,
        "income price": income_price,
        "target income weight": target_income_weight,
        "slippage": slippage_rate,
        "tax reserve rate": tax_reserve_rate,
        "tolerance": tolerance,
        "minimum trade": minimum_trade,
    }

    for name, value in numeric.items():
        if value < 0:
            raise ValueError(
                f"{name.capitalize()} cannot be negative."
            )

    if income_price <= 0:
        raise ValueError(
            "Income price must be positive."
        )

    if not 0.0 <= target_income_weight <= 1.0:
        raise ValueError(
            "Target income weight must be between zero and one."
        )

    if not 0.0 <= tax_reserve_rate <= 1.0:
        raise ValueError(
            "Tax reserve rate must be between zero and one."
        )

    if tolerance >= 1.0:
        raise ValueError(
            "Allocation tolerance must be below one."
        )

    shares_before = float(income_shares)
    cost_before = float(income_cost)
    cash_before = float(swing_cash)
    income_before = shares_before * income_price
    investable_before = (
        income_before
        + cash_before
        + swing_market_value
    )
    before_weight = _weight(
        income_before,
        investable_before,
    )

    def result(
        *,
        action: str,
        shares_after: float = shares_before,
        cost_after: float = cost_before,
        cash_after: float = cash_before,
        trade_cash: float = 0.0,
        market_value_traded: float = 0.0,
        realized_pnl: float = 0.0,
        tax_reserved: float = 0.0,
    ) -> AllocationRebalance:
        income_after = shares_after * income_price
        investable_after = (
            income_after
            + cash_after
            + swing_market_value
        )
        after_weight = _weight(
            income_after,
            investable_after,
        )
        return AllocationRebalance(
            target_income_weight=target_income_weight,
            before_income_weight=before_weight,
            after_income_weight=after_weight,
            before_income_value=income_before,
            after_income_value=income_after,
            before_investable_value=investable_before,
            after_investable_value=investable_after,
            action=action,
            shares_before=shares_before,
            shares_after=shares_after,
            income_cost_before=cost_before,
            income_cost_after=max(0.0, cost_after),
            swing_cash_before=cash_before,
            swing_cash_after=max(0.0, cash_after),
            trade_cash=trade_cash,
            market_value_traded=market_value_traded,
            realized_pnl=realized_pnl,
            tax_reserved=tax_reserved,
            target_fully_reached=(
                abs(after_weight - target_income_weight)
                <= tolerance + 1e-9
            ),
        )

    if investable_before <= 0:
        return result(action="NO_CAPITAL")

    if abs(before_weight - target_income_weight) <= tolerance:
        return result(action="WITHIN_TOLERANCE")

    if before_weight < target_income_weight:
        target_gap = (
            target_income_weight * investable_before
            - income_before
        )
        denominator = (
            1.0
            + target_income_weight * slippage_rate
        )
        required_cash = (
            (1.0 + slippage_rate)
            * target_gap
            / denominator
        )
        cash_to_spend = min(
            max(0.0, required_cash),
            cash_before,
        )

        if cash_to_spend < minimum_trade:
            return result(action="DEFERRED_BUY")

        fill = income_price * (
            1.0 + slippage_rate
        )
        acquired = cash_to_spend / fill
        partial = cash_to_spend + 1e-9 < required_cash
        return result(
            action=(
                "PARTIAL_BUY"
                if partial
                else "BUY"
            ),
            shares_after=shares_before + acquired,
            cost_after=cost_before + cash_to_spend,
            cash_after=cash_before - cash_to_spend,
            trade_cash=cash_to_spend,
            market_value_traded=(
                acquired * income_price
            ),
        )

    if shares_before <= 0:
        return result(action="NO_SHARES_TO_SELL")

    average_cost = (
        cost_before / shares_before
        if shares_before > 0
        else 0.0
    )
    gain_per_market_dollar = max(
        0.0,
        (
            1.0 - slippage_rate
            - (average_cost / income_price)
        ),
    )
    denominator = (
        1.0
        - target_income_weight
        * (
            slippage_rate
            + gain_per_market_dollar
            * tax_reserve_rate
        )
    )

    if denominator <= 0:
        raise RuntimeError(
            "Rebalance sale denominator is not positive."
        )

    market_value_to_sell = min(
        income_before,
        (
            income_before
            - target_income_weight
            * investable_before
        )
        / denominator,
    )

    if market_value_to_sell < minimum_trade:
        return result(action="DEFERRED_SELL")

    shares_to_sell = min(
        shares_before,
        market_value_to_sell / income_price,
    )
    sell_fill = income_price * (
        1.0 - slippage_rate
    )
    gross_proceeds = shares_to_sell * sell_fill
    basis_reduction = min(
        cost_before,
        average_cost * shares_to_sell,
    )
    realized_pnl = (
        gross_proceeds - basis_reduction
    )
    tax_reserved = (
        max(0.0, realized_pnl)
        * tax_reserve_rate
    )
    net_proceeds = (
        gross_proceeds - tax_reserved
    )

    return result(
        action="SELL",
        shares_after=max(
            0.0,
            shares_before - shares_to_sell,
        ),
        cost_after=max(
            0.0,
            cost_before - basis_reduction,
        ),
        cash_after=cash_before + net_proceeds,
        trade_cash=-net_proceeds,
        market_value_traded=(
            shares_to_sell * income_price
        ),
        realized_pnl=realized_pnl,
        tax_reserved=tax_reserved,
    )
