#!/usr/bin/env python3
"""Install, test, push, back up, and migrate QPX capital allocation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap


def find_root() -> Path:
    for start in (
        Path(__file__).resolve().parent,
        Path.cwd().resolve(),
    ):
        for candidate in (
            start,
            *start.parents,
        ):
            if (
                (candidate / ".git").exists()
                and (candidate / "qpx_bot").exists()
                and (candidate / "tests").exists()
            ):
                return candidate

    raise RuntimeError(
        "QPX_ALPHA was not found. Save this installer inside "
        "/storage/emulated/0/QPX_ALPHA and run it again."
    )


ROOT = find_root()
STAMP = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)
BACKUP = (
    ROOT
    / "backups"
    / "qpx_initial_capital_rebalance_v3"
    / STAMP
)

FILES = {
    "qpx_bot/__init__.py": '"""\nQPX Bot\n\nResearch and paper-trading bot for the Hybrid Dividend + Swing strategy.\n"""\n\n__version__ = "1.17.0"\n',
    "qpx_bot/config.py": '"""QPX Bot strategy and execution configuration."""\n\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True, slots=True)\nclass BotConfig:\n    """Default Hybrid Dividend + Swing strategy settings."""\n\n    # Initial capital\n    # $1,300 is seeded into QDTE and $1,500 starts as swing liquidity.\n    starting_cash: float = 1_300.0\n    starting_swing_cash: float = 1_500.0\n    monthly_contribution: float = 2_000.0\n\n    # Years 1–2 target allocation\n    dividend_allocation_years_1_2: float = 0.65\n    swing_allocation_years_1_2: float = 0.35\n\n    # Year 3 onward target allocation\n    dividend_allocation_later: float = 0.40\n    swing_allocation_later: float = 0.60\n\n    # Rebalance on the first processed market session of each month.\n    allocation_rebalance_frequency: str = "monthly"\n    allocation_rebalance_tolerance: float = 0.0025\n    minimum_rebalance_trade: float = 1.0\n\n    dividend_symbol: str = "QDTE"\n\n    # Trend and momentum\n    ema_fast_period: int = 9\n    ema_slow_period: int = 21\n    rsi_period: int = 14\n    rsi_overbought: float = 70.0\n    rsi_strength_level: float = 50.0\n    rmi_period: int = 14\n    rmi_momentum: int = 5\n    sma_trend_period: int = 200\n    sma_slope_lookback: int = 5\n\n    # Volatility and exits\n    atr_period: int = 14\n    stop_atr_multiple: float = 2.5\n    target_atr_multiple: float = 5.0\n    trailing_activation_atr: float = 3.0\n\n    # Liquidity and confirmation\n    minimum_average_daily_volume: int = 2_000_000\n    average_volume_period: int = 20\n    breakout_volume_multiplier: float = 1.20\n    breakout_lookback: int = 20\n    maximum_vix_for_entries: float = 28.0\n\n    # Risk\n    risk_per_trade: float = 0.01\n    maximum_active_portfolio_risk: float = 0.06\n    kelly_fraction: float = 0.25\n    minimum_kelly_trades: int = 20\n\n    # Execution\n    slippage_rate: float = 0.00075\n\n    # Tax reserve\n    annual_tax_reserve_rate: float = 0.37\n\n    @property\n    def total_starting_capital(self) -> float:\n        """Return the complete initial external contribution."""\n        return self.starting_cash + self.starting_swing_cash\n\n    def validate(self) -> None:\n        """Reject internally inconsistent configuration."""\n        allocation_pairs = (\n            (\n                self.dividend_allocation_years_1_2,\n                self.swing_allocation_years_1_2,\n            ),\n            (\n                self.dividend_allocation_later,\n                self.swing_allocation_later,\n            ),\n        )\n\n        for dividend_weight, swing_weight in allocation_pairs:\n            if abs((dividend_weight + swing_weight) - 1.0) > 1e-9:\n                raise ValueError(\n                    "Dividend and swing allocations must total 100%."\n                )\n\n            if not 0.0 <= dividend_weight <= 1.0:\n                raise ValueError(\n                    "Dividend allocation must be between zero and one."\n                )\n\n            if not 0.0 <= swing_weight <= 1.0:\n                raise ValueError(\n                    "Swing allocation must be between zero and one."\n                )\n\n        if self.starting_cash <= 0:\n            raise ValueError(\n                "Initial QDTE capital must be positive."\n            )\n\n        if self.starting_swing_cash < 0:\n            raise ValueError(\n                "Initial swing liquidity cannot be negative."\n            )\n\n        if self.total_starting_capital <= 0:\n            raise ValueError(\n                "Total starting capital must be positive."\n            )\n\n        if self.monthly_contribution < 0:\n            raise ValueError(\n                "Monthly contribution cannot be negative."\n            )\n\n        if self.allocation_rebalance_frequency != "monthly":\n            raise ValueError(\n                "Only monthly allocation rebalancing is supported."\n            )\n\n        if not 0.0 <= self.allocation_rebalance_tolerance < 0.10:\n            raise ValueError(\n                "Rebalance tolerance must be between zero and 10%."\n            )\n\n        if self.minimum_rebalance_trade < 0:\n            raise ValueError(\n                "Minimum rebalance trade cannot be negative."\n            )\n\n        period_values = {\n            "EMA fast": self.ema_fast_period,\n            "EMA slow": self.ema_slow_period,\n            "RSI": self.rsi_period,\n            "RMI": self.rmi_period,\n            "SMA": self.sma_trend_period,\n            "ATR": self.atr_period,\n            "average volume": self.average_volume_period,\n            "breakout": self.breakout_lookback,\n        }\n\n        for name, value in period_values.items():\n            if value < 2:\n                raise ValueError(\n                    f"{name} period must be at least 2."\n                )\n\n        if self.ema_fast_period >= self.ema_slow_period:\n            raise ValueError(\n                "Fast EMA period must be below slow EMA period."\n            )\n\n        if self.rmi_momentum < 1:\n            raise ValueError(\n                "RMI momentum must be at least 1."\n            )\n\n        if not 0 < self.risk_per_trade <= 1:\n            raise ValueError(\n                "Risk per trade must be between 0 and 1."\n            )\n\n        if not 0 < self.maximum_active_portfolio_risk <= 1:\n            raise ValueError(\n                "Maximum active portfolio risk must be "\n                "between 0 and 1."\n            )\n\n        if self.stop_atr_multiple <= 0:\n            raise ValueError(\n                "ATR stop multiple must be positive."\n            )\n\n        if self.target_atr_multiple <= self.stop_atr_multiple:\n            raise ValueError(\n                "ATR target must be greater than the ATR stop."\n            )\n',
    "qpx_bot/allocation.py": '"""QDTE/swing allocation rebalancing with slippage and tax reserves."""\n\nfrom __future__ import annotations\n\nfrom dataclasses import dataclass\n\n\n@dataclass(frozen=True, slots=True)\nclass AllocationRebalance:\n    target_income_weight: float\n    before_income_weight: float\n    after_income_weight: float\n    before_income_value: float\n    after_income_value: float\n    before_investable_value: float\n    after_investable_value: float\n    action: str\n    shares_before: float\n    shares_after: float\n    income_cost_before: float\n    income_cost_after: float\n    swing_cash_before: float\n    swing_cash_after: float\n    trade_cash: float\n    market_value_traded: float\n    realized_pnl: float\n    tax_reserved: float\n    target_fully_reached: bool\n\n    @property\n    def shares_delta(self) -> float:\n        return self.shares_after - self.shares_before\n\n\ndef _weight(\n    income_value: float,\n    investable_value: float,\n) -> float:\n    return (\n        income_value / investable_value\n        if investable_value > 0\n        else 0.0\n    )\n\n\ndef rebalance_income_allocation(\n    *,\n    income_shares: float,\n    income_cost: float,\n    swing_cash: float,\n    swing_market_value: float,\n    income_price: float,\n    target_income_weight: float,\n    slippage_rate: float,\n    tax_reserve_rate: float,\n    tolerance: float,\n    minimum_trade: float,\n) -> AllocationRebalance:\n    """\n    Rebalance QDTE toward its target without liquidating swing positions.\n\n    QDTE may be bought with available swing cash or sold to create swing\n    liquidity. Open swing positions are marked at market but are never\n    sold by this allocator. Positive realized QDTE-sale gains reserve\n    the configured tax percentage in cash.\n    """\n    numeric = {\n        "income shares": income_shares,\n        "income cost": income_cost,\n        "swing cash": swing_cash,\n        "swing market value": swing_market_value,\n        "income price": income_price,\n        "target income weight": target_income_weight,\n        "slippage": slippage_rate,\n        "tax reserve rate": tax_reserve_rate,\n        "tolerance": tolerance,\n        "minimum trade": minimum_trade,\n    }\n\n    for name, value in numeric.items():\n        if value < 0:\n            raise ValueError(\n                f"{name.capitalize()} cannot be negative."\n            )\n\n    if income_price <= 0:\n        raise ValueError(\n            "Income price must be positive."\n        )\n\n    if not 0.0 <= target_income_weight <= 1.0:\n        raise ValueError(\n            "Target income weight must be between zero and one."\n        )\n\n    if not 0.0 <= tax_reserve_rate <= 1.0:\n        raise ValueError(\n            "Tax reserve rate must be between zero and one."\n        )\n\n    if tolerance >= 1.0:\n        raise ValueError(\n            "Allocation tolerance must be below one."\n        )\n\n    shares_before = float(income_shares)\n    cost_before = float(income_cost)\n    cash_before = float(swing_cash)\n    income_before = shares_before * income_price\n    investable_before = (\n        income_before\n        + cash_before\n        + swing_market_value\n    )\n    before_weight = _weight(\n        income_before,\n        investable_before,\n    )\n\n    def result(\n        *,\n        action: str,\n        shares_after: float = shares_before,\n        cost_after: float = cost_before,\n        cash_after: float = cash_before,\n        trade_cash: float = 0.0,\n        market_value_traded: float = 0.0,\n        realized_pnl: float = 0.0,\n        tax_reserved: float = 0.0,\n    ) -> AllocationRebalance:\n        income_after = shares_after * income_price\n        investable_after = (\n            income_after\n            + cash_after\n            + swing_market_value\n        )\n        after_weight = _weight(\n            income_after,\n            investable_after,\n        )\n        return AllocationRebalance(\n            target_income_weight=target_income_weight,\n            before_income_weight=before_weight,\n            after_income_weight=after_weight,\n            before_income_value=income_before,\n            after_income_value=income_after,\n            before_investable_value=investable_before,\n            after_investable_value=investable_after,\n            action=action,\n            shares_before=shares_before,\n            shares_after=shares_after,\n            income_cost_before=cost_before,\n            income_cost_after=max(0.0, cost_after),\n            swing_cash_before=cash_before,\n            swing_cash_after=max(0.0, cash_after),\n            trade_cash=trade_cash,\n            market_value_traded=market_value_traded,\n            realized_pnl=realized_pnl,\n            tax_reserved=tax_reserved,\n            target_fully_reached=(\n                abs(after_weight - target_income_weight)\n                <= tolerance + 1e-9\n            ),\n        )\n\n    if investable_before <= 0:\n        return result(action="NO_CAPITAL")\n\n    if abs(before_weight - target_income_weight) <= tolerance:\n        return result(action="WITHIN_TOLERANCE")\n\n    if before_weight < target_income_weight:\n        target_gap = (\n            target_income_weight * investable_before\n            - income_before\n        )\n        denominator = (\n            1.0\n            + target_income_weight * slippage_rate\n        )\n        required_cash = (\n            (1.0 + slippage_rate)\n            * target_gap\n            / denominator\n        )\n        cash_to_spend = min(\n            max(0.0, required_cash),\n            cash_before,\n        )\n\n        if cash_to_spend < minimum_trade:\n            return result(action="DEFERRED_BUY")\n\n        fill = income_price * (\n            1.0 + slippage_rate\n        )\n        acquired = cash_to_spend / fill\n        partial = cash_to_spend + 1e-9 < required_cash\n        return result(\n            action=(\n                "PARTIAL_BUY"\n                if partial\n                else "BUY"\n            ),\n            shares_after=shares_before + acquired,\n            cost_after=cost_before + cash_to_spend,\n            cash_after=cash_before - cash_to_spend,\n            trade_cash=cash_to_spend,\n            market_value_traded=(\n                acquired * income_price\n            ),\n        )\n\n    if shares_before <= 0:\n        return result(action="NO_SHARES_TO_SELL")\n\n    average_cost = (\n        cost_before / shares_before\n        if shares_before > 0\n        else 0.0\n    )\n    gain_per_market_dollar = max(\n        0.0,\n        (\n            1.0 - slippage_rate\n            - (average_cost / income_price)\n        ),\n    )\n    denominator = (\n        1.0\n        - target_income_weight\n        * (\n            slippage_rate\n            + gain_per_market_dollar\n            * tax_reserve_rate\n        )\n    )\n\n    if denominator <= 0:\n        raise RuntimeError(\n            "Rebalance sale denominator is not positive."\n        )\n\n    market_value_to_sell = min(\n        income_before,\n        (\n            income_before\n            - target_income_weight\n            * investable_before\n        )\n        / denominator,\n    )\n\n    if market_value_to_sell < minimum_trade:\n        return result(action="DEFERRED_SELL")\n\n    shares_to_sell = min(\n        shares_before,\n        market_value_to_sell / income_price,\n    )\n    sell_fill = income_price * (\n        1.0 - slippage_rate\n    )\n    gross_proceeds = shares_to_sell * sell_fill\n    basis_reduction = min(\n        cost_before,\n        average_cost * shares_to_sell,\n    )\n    realized_pnl = (\n        gross_proceeds - basis_reduction\n    )\n    tax_reserved = (\n        max(0.0, realized_pnl)\n        * tax_reserve_rate\n    )\n    net_proceeds = (\n        gross_proceeds - tax_reserved\n    )\n\n    return result(\n        action="SELL",\n        shares_after=max(\n            0.0,\n            shares_before - shares_to_sell,\n        ),\n        cost_after=max(\n            0.0,\n            cost_before - basis_reduction,\n        ),\n        cash_after=cash_before + net_proceeds,\n        trade_cash=-net_proceeds,\n        market_value_traded=(\n            shares_to_sell * income_price\n        ),\n        realized_pnl=realized_pnl,\n        tax_reserved=tax_reserved,\n    )\n',
    "qpx_bot/capital_migration.py": '"""One-time paper-state migration for initial capital and rebalancing."""\n\nfrom __future__ import annotations\n\nimport hashlib\nfrom datetime import date\nfrom pathlib import Path\n\nfrom qpx_bot.allocation import (\n    rebalance_income_allocation,\n)\nfrom qpx_bot.config import BotConfig\nfrom qpx_bot.paper_state import (\n    AuditEvent,\n    StateStore,\n)\nfrom qpx_bot.portfolio import contribution_allocation\nfrom qpx_bot.real_data import load_market_csv\n\n\nPACKAGE_DIR = Path(__file__).resolve().parent\nDEFAULT_RUNTIME = PACKAGE_DIR / "paper_runtime"\nDEFAULT_INPUTS = PACKAGE_DIR / "data_inputs"\nMIGRATION_NAME = "INITIAL_CAPITAL_AND_REBALANCE_V1"\n\n\ndef _elapsed_years(\n    start: date,\n    current: date,\n) -> int:\n    months = (\n        (current.year - start.year) * 12\n        + current.month\n        - start.month\n    )\n    return max(0, months // 12)\n\n\ndef _latest_on_or_before(\n    candles,\n    day: date,\n):\n    selected = None\n\n    for candle in candles:\n        if candle.date > day:\n            break\n        selected = candle\n\n    if selected is None:\n        raise RuntimeError(\n            "Market history does not cover the migration date."\n        )\n\n    return selected\n\n\ndef migrate_paper_capital_and_allocation(\n    *,\n    runtime_directory: str | Path = DEFAULT_RUNTIME,\n    input_directory: str | Path = DEFAULT_INPUTS,\n    config: BotConfig | None = None,\n) -> str:\n    config = config or BotConfig()\n    config.validate()\n    store = StateStore(runtime_directory)\n\n    if not store.exists():\n        return (\n            "No persistent paper account exists. "\n            "New accounts will use the updated capital model."\n        )\n\n    event_id = hashlib.sha256(\n        MIGRATION_NAME.encode("utf-8")\n    ).hexdigest()[:24]\n\n    with store.locked():\n        store.verify_journal()\n        existing_ids = store.journal_event_ids()\n\n        if event_id in existing_ids:\n            return (\n                "Capital and allocation migration was "\n                "already applied."\n            )\n\n        state = store.load()\n        inputs = Path(\n            input_directory\n        ).expanduser().resolve()\n        swing = load_market_csv(\n            inputs / "SWING.csv"\n        )\n        income = load_market_csv(\n            inputs / "QDTE.csv"\n        )\n        migration_date = (\n            state.last_processed_date\n            or min(\n                swing[-1].date,\n                income[-1].date,\n            )\n        )\n        swing_candle = _latest_on_or_before(\n            swing,\n            migration_date,\n        )\n        income_candle = _latest_on_or_before(\n            income,\n            migration_date,\n        )\n        additional_swing_capital = max(\n            0.0,\n            config.total_starting_capital\n            - state.starting_cash,\n        )\n\n        if additional_swing_capital > 0:\n            state.starting_cash += (\n                additional_swing_capital\n            )\n            state.total_contributions += (\n                additional_swing_capital\n            )\n            state.swing_cash += (\n                additional_swing_capital\n            )\n\n        elapsed = _elapsed_years(\n            state.start_date,\n            migration_date,\n        )\n        target_income_weight, _ = (\n            contribution_allocation(\n                elapsed,\n                config,\n            )\n        )\n        swing_market_value = (\n            state.position.shares\n            * swing_candle.close\n            if state.position is not None\n            else 0.0\n        )\n        rebalance = rebalance_income_allocation(\n            income_shares=state.income_shares,\n            income_cost=state.income_cost,\n            swing_cash=state.swing_cash,\n            swing_market_value=swing_market_value,\n            income_price=income_candle.close,\n            target_income_weight=target_income_weight,\n            slippage_rate=config.slippage_rate,\n            tax_reserve_rate=(\n                config.annual_tax_reserve_rate\n            ),\n            tolerance=(\n                config.allocation_rebalance_tolerance\n            ),\n            minimum_trade=(\n                config.minimum_rebalance_trade\n            ),\n        )\n        state.income_shares = (\n            rebalance.shares_after\n        )\n        state.income_cost = (\n            rebalance.income_cost_after\n        )\n        state.swing_cash = (\n            rebalance.swing_cash_after\n        )\n        state.tax_reserve_cash += (\n            rebalance.tax_reserved\n        )\n        state.realized_pnl += (\n            rebalance.realized_pnl\n        )\n        state.revision += 1\n        state.validate()\n        store.save(state)\n        store.append_events(\n            [\n                AuditEvent(\n                    event_id=event_id,\n                    event_type=(\n                        "CAPITAL_ALLOCATION_MIGRATION"\n                    ),\n                    event_date=migration_date,\n                    details={\n                        "migration": MIGRATION_NAME,\n                        "additional_swing_capital": (\n                            additional_swing_capital\n                        ),\n                        "total_starting_capital": (\n                            config.total_starting_capital\n                        ),\n                        "target_income_weight": (\n                            target_income_weight\n                        ),\n                        "before_income_weight": (\n                            rebalance.before_income_weight\n                        ),\n                        "after_income_weight": (\n                            rebalance.after_income_weight\n                        ),\n                        "rebalance_action": (\n                            rebalance.action\n                        ),\n                        "rebalance_tax_reserved": (\n                            rebalance.tax_reserved\n                        ),\n                        "open_swing_position_preserved": (\n                            state.position is not None\n                        ),\n                    },\n                )\n            ]\n        )\n\n    return (\n        "Added the missing initial swing capital and "\n        "rebalanced QDTE toward the active target. "\n        f"Action={rebalance.action}; "\n        f"QDTE weight={rebalance.after_income_weight:.2%}; "\n        f"target={target_income_weight:.2%}."\n    )\n',
    "QPX_MIGRATE_CAPITAL_ALLOCATION.py": '#!/usr/bin/env python3\n"""Migrate the live paper account to the updated capital model."""\n\nfrom qpx_bot.capital_migration import (\n    migrate_paper_capital_and_allocation,\n)\n\n\nif __name__ == "__main__":\n    print(\n        migrate_paper_capital_and_allocation()\n    )\n',
    "tests/test_qpx_bot_initial_capital_rebalance.py": 'from qpx_bot.allocation import (\n    rebalance_income_allocation,\n)\nfrom qpx_bot.config import BotConfig\n\n\nconfig = BotConfig()\nconfig.validate()\n\nassert config.starting_cash == 1_300.0\nassert config.starting_swing_cash == 1_500.0\nassert config.total_starting_capital == 2_800.0\n\nbuy = rebalance_income_allocation(\n    income_shares=32.5,\n    income_cost=1_300.0,\n    swing_cash=1_500.0,\n    swing_market_value=0.0,\n    income_price=40.0,\n    target_income_weight=0.65,\n    slippage_rate=config.slippage_rate,\n    tax_reserve_rate=config.annual_tax_reserve_rate,\n    tolerance=config.allocation_rebalance_tolerance,\n    minimum_trade=config.minimum_rebalance_trade,\n)\n\nassert buy.action == "BUY"\nassert buy.shares_after > buy.shares_before\nassert buy.swing_cash_after < buy.swing_cash_before\nassert abs(buy.after_income_weight - 0.65) < 1e-8\nassert buy.tax_reserved == 0.0\n\nsell = rebalance_income_allocation(\n    income_shares=100.0,\n    income_cost=2_000.0,\n    swing_cash=500.0,\n    swing_market_value=500.0,\n    income_price=50.0,\n    target_income_weight=0.40,\n    slippage_rate=config.slippage_rate,\n    tax_reserve_rate=config.annual_tax_reserve_rate,\n    tolerance=config.allocation_rebalance_tolerance,\n    minimum_trade=config.minimum_rebalance_trade,\n)\n\nassert sell.action == "SELL"\nassert sell.shares_after < sell.shares_before\nassert sell.swing_cash_after > sell.swing_cash_before\nassert sell.realized_pnl > 0\nassert sell.tax_reserved > 0\nassert abs(sell.after_income_weight - 0.40) < 1e-8\n\npartial = rebalance_income_allocation(\n    income_shares=1.0,\n    income_cost=40.0,\n    swing_cash=10.0,\n    swing_market_value=1_000.0,\n    income_price=40.0,\n    target_income_weight=0.65,\n    slippage_rate=config.slippage_rate,\n    tax_reserve_rate=config.annual_tax_reserve_rate,\n    tolerance=config.allocation_rebalance_tolerance,\n    minimum_trade=config.minimum_rebalance_trade,\n)\n\nassert partial.action == "PARTIAL_BUY"\nassert partial.swing_cash_after == 0.0\nassert not partial.target_fully_reached\n\nfrom pathlib import Path\n\nreport_source = (\n    Path(__file__).resolve().parents[1]\n    / "qpx_bot"\n    / "report.py"\n).read_text(encoding="utf-8")\nbacktest_section, hybrid_section = report_source.split(\n    "def format_hybrid_report",\n    1,\n)\n\nassert "result.starting_income_cash" not in backtest_section\nassert "result.starting_swing_cash" not in backtest_section\nassert "result.starting_income_cash" in hybrid_section\nassert "result.starting_swing_cash" in hybrid_section\nassert "Initial total capital" in hybrid_section\nassert "Monthly rebalances" in hybrid_section\n\nprint("QPX Bot Initial Capital and Rebalance PASS")\n',
    "qpx_bot/INITIAL_CAPITAL_REBALANCE_README.txt": 'QPX INITIAL CAPITAL AND ALLOCATION REBALANCE\n============================================\n\nInitial external capital\n------------------------\n\nQDTE seed          : $1,300\nSwing liquidity    : $1,500\nTotal initial cash : $2,800\n\nThe initial account is immediately rebalanced toward the active target\nafter the two explicit seed amounts are deposited.\n\nTarget allocations\n------------------\n\nYears 1–2\n    65% QDTE / 35% swing\n\nYear 3 onward\n    40% QDTE / 60% swing\n\nMonthly processing\n------------------\n\nOn the first processed market session of each new month:\n\n1. The complete $2,000 external contribution enters swing cash.\n2. The portfolio is marked using the current QDTE and swing prices.\n3. QDTE is bought or sold to move toward the active target.\n4. Open swing positions are never liquidated by the allocator.\n5. When QDTE is underweight but swing cash is committed to an open\n   trade, the QDTE purchase is partial and the remaining drift is\n   reported.\n6. Positive realized gains from QDTE rebalance sales reserve 37% in\n   tax cash.\n7. Slippage is applied to every QDTE rebalance trade.\n8. The rebalance is recorded in the paper audit journal.\n\nThe tolerance is 0.25 percentage points. Trades below $1 are deferred.\n\nExisting paper account\n----------------------\n\nThe installer creates a verified backup before migration. It then:\n\n- adds the missing $1,500 initial swing contribution exactly once;\n- changes initial contributed capital from $1,300 to $2,800;\n- rebalances QDTE toward the currently active target;\n- preserves any open swing position;\n- writes a hash-chained CAPITAL_ALLOCATION_MIGRATION event.\n\nManual idempotent migration command:\n\npython QPX_MIGRATE_CAPITAL_ALLOCATION.py\n\nSimulation only. No brokerage connection or live orders.\n',
}

SIMPLE_PATCHES = {
    "qpx_bot/hybrid.py": [
        ('from qpx_bot.config import BotConfig\n', 'from qpx_bot.allocation import (\n    rebalance_income_allocation,\n)\nfrom qpx_bot.config import BotConfig\n'),
        ('@dataclass(frozen=True, slots=True)\nclass AllocationEvent:\n    """One external contribution and its two-sleeve split."""\n\n    date: date\n    amount: float\n    income_weight: float\n    swing_weight: float\n    income_amount: float\n    swing_amount: float\n', '@dataclass(frozen=True, slots=True)\nclass AllocationEvent:\n    """One external contribution and allocation rebalance."""\n\n    date: date\n    amount: float\n    income_weight: float\n    swing_weight: float\n    income_amount: float\n    swing_amount: float\n    rebalance_action: str = "NONE"\n    income_weight_before: float = 0.0\n    income_weight_after: float = 0.0\n    rebalance_tax_reserved: float = 0.0\n    target_fully_reached: bool = True\n'),
        ('    start_date: date\n    end_date: date\n    starting_cash: float\n    total_contributions: float\n', '    start_date: date\n    end_date: date\n    starting_cash: float\n    starting_income_cash: float\n    starting_swing_cash: float\n    total_contributions: float\n'),
        ('    initial_income_weight, initial_swing_weight = (\n        contribution_allocation(0, config)\n    )\n    initial_income_cash = (\n        config.starting_cash * initial_income_weight\n    )\n    initial_swing_cash = (\n        config.starting_cash * initial_swing_weight\n    )\n\n    income_holding = IncomeHolding(normalized_income)\n    swing_portfolio = Portfolio(initial_swing_cash)\n\n    income_pointer = 0\n    latest_income = income_candles[0]\n\n    while (\n        income_pointer + 1 < len(income_candles)\n        and income_candles[income_pointer + 1].date\n        <= first_swing_date\n    ):\n        income_pointer += 1\n        latest_income = income_candles[income_pointer]\n\n    income_holding.buy(\n        cash_amount=initial_income_cash,\n        market_price=latest_income.open,\n        slippage_rate=config.slippage_rate,\n    )\n\n    total_external_contributions = config.starting_cash\n', '    initial_income_cash = config.starting_cash\n    initial_swing_cash = config.starting_swing_cash\n\n    income_holding = IncomeHolding(normalized_income)\n    swing_portfolio = Portfolio(initial_swing_cash)\n\n    income_pointer = 0\n    latest_income = income_candles[0]\n\n    while (\n        income_pointer + 1 < len(income_candles)\n        and income_candles[income_pointer + 1].date\n        <= first_swing_date\n    ):\n        income_pointer += 1\n        latest_income = income_candles[income_pointer]\n\n    income_holding.buy(\n        cash_amount=initial_income_cash,\n        market_price=latest_income.open,\n        slippage_rate=config.slippage_rate,\n    )\n    initial_income_weight, _ = contribution_allocation(\n        0,\n        config,\n    )\n    initial_rebalance = rebalance_income_allocation(\n        income_shares=income_holding.shares,\n        income_cost=income_holding.invested_cost,\n        swing_cash=swing_portfolio.cash,\n        swing_market_value=0.0,\n        income_price=latest_income.open,\n        target_income_weight=initial_income_weight,\n        slippage_rate=config.slippage_rate,\n        tax_reserve_rate=config.annual_tax_reserve_rate,\n        tolerance=config.allocation_rebalance_tolerance,\n        minimum_trade=config.minimum_rebalance_trade,\n    )\n    income_holding.shares = initial_rebalance.shares_after\n    income_holding.invested_cost = (\n        initial_rebalance.income_cost_after\n    )\n    swing_portfolio.cash = (\n        initial_rebalance.swing_cash_after\n    )\n    swing_portfolio.tax_reserve_cash += (\n        initial_rebalance.tax_reserved\n    )\n\n    total_external_contributions = (\n        config.total_starting_capital\n    )\n'),
        ('        starting_cash=config.starting_cash,\n        total_contributions=total_external_contributions,\n', '        starting_cash=config.total_starting_capital,\n        starting_income_cash=config.starting_cash,\n        starting_swing_cash=config.starting_swing_cash,\n        total_contributions=total_external_contributions,\n'),
    ],
    "qpx_bot/paper_engine.py": [
        ('from qpx_bot.config import BotConfig\n', 'from qpx_bot.allocation import (\n    rebalance_income_allocation,\n)\nfrom qpx_bot.config import BotConfig\n'),
        ('            "starting_cash": config.starting_cash,\n            "income_weight": income_weight,\n            "swing_weight": swing_weight,\n            "income_fill": fill,\n            "income_shares": income_shares,\n            "swing_cash": swing_cash,\n            "mode": "SIMULATED_ONLY",\n', '            "starting_income_cash": (\n                config.starting_cash\n            ),\n            "starting_swing_cash": (\n                config.starting_swing_cash\n            ),\n            "total_starting_capital": (\n                config.total_starting_capital\n            ),\n            "income_weight": income_weight,\n            "swing_weight": swing_weight,\n            "income_fill": fill,\n            "income_shares": (\n                initial_rebalance.shares_after\n            ),\n            "swing_cash": (\n                initial_rebalance.swing_cash_after\n            ),\n            "rebalance_action": (\n                initial_rebalance.action\n            ),\n            "income_weight_before": (\n                initial_rebalance.before_income_weight\n            ),\n            "income_weight_after": (\n                initial_rebalance.after_income_weight\n            ),\n            "mode": "SIMULATED_ONLY",\n'),
    ],
    "qpx_bot/report.py": [
        ('def format_hybrid_report(\n    result: HybridBacktestResult,\n) -> str:\n    """Return the combined dividend-plus-swing report."""\n    lines = [\n        "=" * 76,\n        "QPX BOT v1.5 — HYBRID DIVIDEND + SWING BACKTEST",\n        "=" * 76,\n        (\n            f"Sleeves                   : "\n            f"{result.income_symbol} income + "\n            f"{result.swing_symbol} swing"\n        ),\n        (\n            f"Period                    : "\n            f"{result.start_date} to {result.end_date}"\n        ),\n        f"Starting cash             : {_money(result.starting_cash)}",\n        f"Monthly deposits made     : {result.contribution_count}",\n', 'def format_hybrid_report(\n    result: HybridBacktestResult,\n) -> str:\n    """Return the combined dividend-plus-swing report."""\n    lines = [\n        "=" * 76,\n        "QPX BOT v1.5 — HYBRID DIVIDEND + SWING BACKTEST",\n        "=" * 76,\n        (\n            f"Sleeves                   : "\n            f"{result.income_symbol} income + "\n            f"{result.swing_symbol} swing"\n        ),\n        (\n            f"Period                    : "\n            f"{result.start_date} to {result.end_date}"\n        ),\n        (\n            "Initial total capital     : "\n            f"{_money(result.starting_cash)}"\n        ),\n        (\n            "Initial QDTE seed         : "\n            f"{_money(result.starting_income_cash)}"\n        ),\n        (\n            "Initial swing liquidity   : "\n            f"{_money(result.starting_swing_cash)}"\n        ),\n        f"Monthly deposits made     : {result.contribution_count}",\n        (\n            "Monthly rebalances        : "\n            f"{len(result.allocation_events)}"\n        ),\n'),
    ],
    "tests/test_qpx_bot_hybrid.py": [
        ('    starting_cash=10_000.0,\n    monthly_contribution=1_000.0,\n', '    starting_cash=10_000.0,\n    starting_swing_cash=5_000.0,\n    monthly_contribution=1_000.0,\n'),
        ('    config.starting_cash\n    + (\n', '    config.total_starting_capital\n    + (\n'),
    ],
    "tests/test_qpx_bot_paper_trading.py": [
        ('    starting_cash=10_000.0,\n    monthly_contribution=500.0,\n', '    starting_cash=10_000.0,\n    starting_swing_cash=5_000.0,\n    monthly_contribution=500.0,\n'),
        ('assert state.total_contributions == 10_500.0\n', 'assert state.total_contributions == (\n    config.total_starting_capital\n    + config.monthly_contribution\n)\n'),
    ],
}

REGION_PATCHES = {
    "qpx_bot/hybrid.py": [
        (
            '        if current_month != previous_month:\n',
            '            previous_month = current_month\n\n        if (\n            pending_signal_index is not None\n',
            '        if current_month != previous_month:\n            income_weight, swing_weight = (\n                contribution_allocation(\n                    _elapsed_years(\n                        first_swing_date,\n                        swing_candle.date,\n                    ),\n                    config,\n                )\n            )\n            cash_before_contribution = (\n                swing_portfolio.cash\n            )\n\n            if config.monthly_contribution > 0:\n                swing_portfolio.deposit(\n                    config.monthly_contribution\n                )\n                total_external_contributions += (\n                    config.monthly_contribution\n                )\n                contribution_count += 1\n\n            open_position = (\n                swing_portfolio.positions.get(\n                    normalized_swing\n                )\n            )\n            swing_market_value_at_open = (\n                open_position.shares\n                * swing_candle.open\n                if open_position is not None\n                else 0.0\n            )\n            rebalance = rebalance_income_allocation(\n                income_shares=income_holding.shares,\n                income_cost=income_holding.invested_cost,\n                swing_cash=swing_portfolio.cash,\n                swing_market_value=(\n                    swing_market_value_at_open\n                ),\n                income_price=latest_income.open,\n                target_income_weight=income_weight,\n                slippage_rate=config.slippage_rate,\n                tax_reserve_rate=(\n                    config.annual_tax_reserve_rate\n                ),\n                tolerance=(\n                    config.allocation_rebalance_tolerance\n                ),\n                minimum_trade=(\n                    config.minimum_rebalance_trade\n                ),\n            )\n            income_holding.shares = (\n                rebalance.shares_after\n            )\n            income_holding.invested_cost = (\n                rebalance.income_cost_after\n            )\n            swing_portfolio.cash = (\n                rebalance.swing_cash_after\n            )\n            swing_portfolio.tax_reserve_cash += (\n                rebalance.tax_reserved\n            )\n            swing_portfolio.realized_pnl += (\n                rebalance.realized_pnl\n            )\n            allocation_events.append(\n                AllocationEvent(\n                    date=swing_candle.date,\n                    amount=config.monthly_contribution,\n                    income_weight=income_weight,\n                    swing_weight=swing_weight,\n                    income_amount=rebalance.trade_cash,\n                    swing_amount=(\n                        swing_portfolio.cash\n                        - cash_before_contribution\n                    ),\n                    rebalance_action=rebalance.action,\n                    income_weight_before=(\n                        rebalance.before_income_weight\n                    ),\n                    income_weight_after=(\n                        rebalance.after_income_weight\n                    ),\n                    rebalance_tax_reserved=(\n                        rebalance.tax_reserved\n                    ),\n                    target_fully_reached=(\n                        rebalance.target_fully_reached\n                    ),\n                )\n            )\n            previous_month = current_month\n\n        if (\n            pending_signal_index is not None\n',
        ),
    ],
    "qpx_bot/paper_engine.py": [
        (
            '    income_weight, swing_weight = contribution_allocation(\n',
            '    state.validate()\n\n    event = _event(\n',
            '    income_weight, swing_weight = contribution_allocation(\n        0,\n        config,\n    )\n    income_cash = config.starting_cash\n    swing_cash = config.starting_swing_cash\n    fill = buy_fill(\n        income_price,\n        config.slippage_rate,\n    )\n    income_shares = income_cash / fill\n    initial_rebalance = rebalance_income_allocation(\n        income_shares=income_shares,\n        income_cost=income_cash,\n        swing_cash=swing_cash,\n        swing_market_value=0.0,\n        income_price=income_price,\n        target_income_weight=income_weight,\n        slippage_rate=config.slippage_rate,\n        tax_reserve_rate=config.annual_tax_reserve_rate,\n        tolerance=config.allocation_rebalance_tolerance,\n        minimum_trade=config.minimum_rebalance_trade,\n    )\n    state_id = _identifier(\n        normalized_swing,\n        normalized_income,\n        start_date.isoformat(),\n        f"{config.starting_cash:.8f}",\n        f"{config.starting_swing_cash:.8f}",\n    )\n\n    state = PaperState(\n        state_id=state_id,\n        swing_symbol=normalized_swing,\n        income_symbol=normalized_income,\n        start_date=start_date,\n        starting_cash=config.total_starting_capital,\n        swing_cash=initial_rebalance.swing_cash_after,\n        tax_reserve_cash=(\n            initial_rebalance.tax_reserved\n        ),\n        total_contributions=(\n            config.total_starting_capital\n        ),\n        realized_pnl=(\n            initial_rebalance.realized_pnl\n        ),\n        income_shares=(\n            initial_rebalance.shares_after\n        ),\n        income_cost=(\n            initial_rebalance.income_cost_after\n        ),\n        dividends_received=0.0,\n        last_processed_date=None,\n        last_contribution_month=_month_key(start_date),\n    )\n    state.validate()\n\n    event = _event(\n',
        ),
        (
            '    if current_month != state.last_contribution_month:\n',
            '    previous_date = state.last_processed_date\n',
            '    if current_month != state.last_contribution_month:\n        income_weight, swing_weight = contribution_allocation(\n            _elapsed_years(\n                state.start_date,\n                current_date,\n            ),\n            config,\n        )\n        swing_cash_before = state.swing_cash\n        state.swing_cash += config.monthly_contribution\n        state.total_contributions += (\n            config.monthly_contribution\n        )\n        swing_market_value = (\n            state.position.shares * candle.open\n            if state.position is not None\n            else 0.0\n        )\n        rebalance = rebalance_income_allocation(\n            income_shares=state.income_shares,\n            income_cost=state.income_cost,\n            swing_cash=state.swing_cash,\n            swing_market_value=swing_market_value,\n            income_price=income_candle.open,\n            target_income_weight=income_weight,\n            slippage_rate=config.slippage_rate,\n            tax_reserve_rate=(\n                config.annual_tax_reserve_rate\n            ),\n            tolerance=(\n                config.allocation_rebalance_tolerance\n            ),\n            minimum_trade=(\n                config.minimum_rebalance_trade\n            ),\n        )\n        state.income_shares = (\n            rebalance.shares_after\n        )\n        state.income_cost = (\n            rebalance.income_cost_after\n        )\n        state.swing_cash = (\n            rebalance.swing_cash_after\n        )\n        state.tax_reserve_cash += (\n            rebalance.tax_reserved\n        )\n        state.realized_pnl += (\n            rebalance.realized_pnl\n        )\n        state.last_contribution_month = current_month\n\n        events.append(\n            _event(\n                state=state,\n                event_type="MONTHLY_CONTRIBUTION",\n                event_date=current_date,\n                unique=current_month,\n                details={\n                    "amount": (\n                        config.monthly_contribution\n                    ),\n                    "target_income_weight": (\n                        income_weight\n                    ),\n                    "target_swing_weight": (\n                        swing_weight\n                    ),\n                    "rebalance_action": (\n                        rebalance.action\n                    ),\n                    "income_weight_before": (\n                        rebalance.before_income_weight\n                    ),\n                    "income_weight_after": (\n                        rebalance.after_income_weight\n                    ),\n                    "income_trade_cash": (\n                        rebalance.trade_cash\n                    ),\n                    "swing_cash_change": (\n                        state.swing_cash\n                        - swing_cash_before\n                    ),\n                    "rebalance_realized_pnl": (\n                        rebalance.realized_pnl\n                    ),\n                    "rebalance_tax_reserved": (\n                        rebalance.tax_reserved\n                    ),\n                    "target_fully_reached": (\n                        rebalance.target_fully_reached\n                    ),\n                    "open_swing_position_preserved": (\n                        state.position is not None\n                    ),\n                },\n            )\n        )\n\n    previous_date = state.last_processed_date\n',
        ),
    ],
}

GITIGNORE_APPEND = '# QPX capital migration scratch output\nbackups/qpx_initial_capital_rebalance/\n'
TARGETS = [
    *FILES,
    *SIMPLE_PATCHES,
    *REGION_PATCHES,
    ".gitignore",
]
originals: dict[str, bytes | None] = {}


def run(
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess:
    print("$ " + " ".join(command))
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
    )


def is_tracked(relative: str) -> bool:
    return subprocess.run(
        [
            "git",
            "ls-files",
            "--error-unmatch",
            relative,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


def ensure_targets_are_safe() -> None:
    changed: list[str] = []

    for relative in TARGETS:
        path = ROOT / relative
        worktree = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )
        staged = subprocess.run(
            [
                "git",
                "diff",
                "--cached",
                "--quiet",
                "--",
                relative,
            ],
            cwd=ROOT,
        )

        if (
            worktree.returncode != 0
            or staged.returncode != 0
        ):
            changed.append(relative)
            continue

        if (
            relative in FILES
            and path.exists()
            and not is_tracked(relative)
        ):
            changed.append(relative)

    if changed:
        raise RuntimeError(
            "These target files contain local changes and "
            "were not overwritten:\n"
            + "\n".join(changed)
        )


def apply_transformations(
    relative: str,
    content: str,
) -> str:
    for old, new in SIMPLE_PATCHES.get(
        relative,
        [],
    ):
        if old in content:
            content = content.replace(
                old,
                new,
                1,
            )
        elif new in content:
            continue
        else:
            raise RuntimeError(
                f"Expected marker not found in "
                f"{relative}:\n{old}"
            )

    for start_marker, end_marker, replacement in (
        REGION_PATCHES.get(relative, [])
    ):
        if replacement in content:
            continue

        start = content.find(start_marker)

        if start < 0:
            raise RuntimeError(
                f"Region start marker not found in "
                f"{relative}:\n{start_marker}"
            )

        end = content.find(
            end_marker,
            start + len(start_marker),
        )

        if end < 0:
            raise RuntimeError(
                f"Region end marker not found in "
                f"{relative}:\n{end_marker}"
            )

        content = (
            content[:start]
            + replacement
            + content[
                end + len(end_marker):
            ]
        )

    return content


def validate_patch_markers() -> None:
    failures: list[str] = []

    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        path = ROOT / relative

        if not path.exists():
            failures.append(
                f"{relative}: file not found"
            )
            continue

        try:
            transformed = apply_transformations(
                relative,
                path.read_text(
                    encoding="utf-8"
                ),
            )

            if path.suffix == ".py":
                compile(
                    transformed,
                    relative,
                    "exec",
                )
        except Exception as exc:
            failures.append(
                f"{relative}: {type(exc).__name__}: {exc}"
            )

    if failures:
        raise RuntimeError(
            "Patch preflight failed before any file changed:\n\n"
            + "\n\n".join(failures)
        )


def preserve(relative: str) -> None:
    if relative in originals:
        return

    path = ROOT / relative
    originals[relative] = (
        path.read_bytes()
        if path.exists()
        else None
    )

    if path.exists():
        backup_path = BACKUP / relative
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        shutil.copy2(
            path,
            backup_path,
        )


def install_files() -> None:
    for relative, content in FILES.items():
        preserve(relative)
        path = ROOT / relative
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            textwrap.dedent(
                content
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        if path.name.startswith("QPX_"):
            path.chmod(0o700)

        print(f"Installed: {relative}")


def patch_files() -> None:
    for relative in {
        *SIMPLE_PATCHES,
        *REGION_PATCHES,
    }:
        preserve(relative)
        path = ROOT / relative
        transformed = apply_transformations(
            relative,
            path.read_text(
                encoding="utf-8"
            ),
        )
        path.write_text(
            transformed,
            encoding="utf-8",
        )
        print(f"Updated: {relative}")


def patch_gitignore() -> None:
    relative = ".gitignore"
    preserve(relative)
    path = ROOT / relative
    content = path.read_text(
        encoding="utf-8"
    )
    addition = textwrap.dedent(
        GITIGNORE_APPEND
    ).strip()

    if addition not in content:
        path.write_text(
            content.rstrip()
            + "\n\n"
            + addition
            + "\n",
            encoding="utf-8",
        )
        print("Updated: .gitignore")


def restore() -> None:
    print(
        "Restoring previous target files..."
    )

    for relative, original in originals.items():
        path = ROOT / relative

        if original is None:
            if path.exists():
                path.unlink()
        else:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            path.write_bytes(original)


def commit_and_push() -> None:
    paths = list(TARGETS)

    try:
        paths.append(
            str(
                Path(__file__)
                .resolve()
                .relative_to(ROOT)
            )
        )
    except ValueError:
        pass

    run([
        "git",
        "add",
        "--",
        *paths,
    ])

    staged = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ],
        cwd=ROOT,
    )

    if staged.returncode == 0:
        print(
            "Capital and rebalance changes are "
            "already committed."
        )
        return

    run([
        "git",
        "commit",
        "-m",
        (
            "Implement QPX initial swing capital "
            "and allocation rebalancing"
        ),
    ])

    branch = subprocess.check_output(
        [
            "git",
            "branch",
            "--show-current",
        ],
        cwd=ROOT,
        text=True,
    ).strip()

    if not branch:
        raise RuntimeError(
            "Cannot push from detached Git state."
        )

    run([
        "git",
        "push",
        "origin",
        branch,
    ])


def main() -> int:
    print("=" * 78)
    print(
        "QPX BOT — INITIAL CAPITAL AND "
        "ALLOCATION REBALANCE INSTALLER"
    )
    print("=" * 78)
    print(f"Project: {ROOT}")

    ensure_targets_are_safe()
    validate_patch_markers()
    install_files()
    patch_files()
    patch_gitignore()

    try:
        run([
            sys.executable,
            "-m",
            (
                "tests."
                "test_qpx_bot_initial_capital_rebalance"
            ),
        ])
        run([
            sys.executable,
            "tests/run_all_tests.py",
        ])
    except Exception:
        restore()
        raise

    commit_and_push()

    print()
    print(
        "Creating a verified backup before "
        "paper-state migration..."
    )
    print()

    backup_result = run(
        [
            sys.executable,
            "QPX_BACKUP_RUNTIME.py",
            "--create",
            "--force",
            "--drill-latest",
        ],
        check=False,
    )

    if backup_result.returncode != 0:
        print()
        print("=" * 78)
        print(
            "QPX CAPITAL CODE: INSTALLED AND PUSHED"
        )
        print(
            "PAPER MIGRATION: NOT STARTED"
        )
        print("=" * 78)
        print(
            "The verified safety backup failed. "
            "Do not migrate until it passes."
        )
        return backup_result.returncode

    migration_result = run(
        [
            sys.executable,
            "QPX_MIGRATE_CAPITAL_ALLOCATION.py",
        ],
        check=False,
    )

    if migration_result.returncode != 0:
        print()
        print("=" * 78)
        print(
            "QPX CAPITAL CODE: INSTALLED AND PUSHED"
        )
        print(
            "PAPER MIGRATION: NEEDS RETRY"
        )
        print("=" * 78)
        print(
            "Re-run:\n"
            "python QPX_MIGRATE_CAPITAL_ALLOCATION.py"
        )
        return migration_result.returncode

    run(
        [
            sys.executable,
            "QPX_RUN_QUALIFICATION.py",
            "--status",
        ],
        check=False,
    )

    print()
    print("=" * 78)
    print(
        "QPX INITIAL CAPITAL AND REBALANCE: COMPLETE"
    )
    print("=" * 78)
    print(
        "$1,300 QDTE seed + $1,500 swing liquidity, "
        "monthly target rebalancing, tax reserves, "
        "and audit logging are active."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
