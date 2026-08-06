"""One-time paper-state migration for initial capital and rebalancing."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from qpx_bot.allocation import (
    rebalance_income_allocation,
)
from qpx_bot.config import BotConfig
from qpx_bot.paper_state import (
    AuditEvent,
    StateStore,
)
from qpx_bot.portfolio import contribution_allocation
from qpx_bot.real_data import load_market_csv
from qpx_bot.time_rules import elapsed_complete_years


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RUNTIME = PACKAGE_DIR / "paper_runtime"
DEFAULT_INPUTS = PACKAGE_DIR / "data_inputs"
MIGRATION_NAME = "INITIAL_CAPITAL_AND_REBALANCE_V1"


def _elapsed_years(
    start: date,
    current: date,
) -> int:
    return elapsed_complete_years(start, current)


def _latest_on_or_before(
    candles,
    day: date,
):
    selected = None

    for candle in candles:
        if candle.date > day:
            break
        selected = candle

    if selected is None:
        raise RuntimeError(
            "Market history does not cover the migration date."
        )

    return selected


def migrate_paper_capital_and_allocation(
    *,
    runtime_directory: str | Path = DEFAULT_RUNTIME,
    input_directory: str | Path = DEFAULT_INPUTS,
    config: BotConfig | None = None,
) -> str:
    config = config or BotConfig()
    config.validate()
    store = StateStore(runtime_directory)

    if not store.exists():
        return (
            "No persistent paper account exists. "
            "New accounts will use the updated capital model."
        )

    event_id = hashlib.sha256(
        MIGRATION_NAME.encode("utf-8")
    ).hexdigest()[:24]

    with store.locked():
        store.verify_journal()
        existing_ids = store.journal_event_ids()

        if event_id in existing_ids:
            return (
                "Capital and allocation migration was "
                "already applied."
            )

        state = store.load()
        inputs = Path(
            input_directory
        ).expanduser().resolve()
        swing = load_market_csv(
            inputs / "SWING.csv"
        )
        income = load_market_csv(
            inputs / "QDTE.csv"
        )
        migration_date = (
            state.last_processed_date
            or min(
                swing[-1].date,
                income[-1].date,
            )
        )
        swing_candle = _latest_on_or_before(
            swing,
            migration_date,
        )
        income_candle = _latest_on_or_before(
            income,
            migration_date,
        )
        additional_swing_capital = max(
            0.0,
            config.total_starting_capital
            - state.starting_cash,
        )

        if additional_swing_capital > 0:
            state.starting_cash += (
                additional_swing_capital
            )
            state.total_contributions += (
                additional_swing_capital
            )
            state.swing_cash += (
                additional_swing_capital
            )

        elapsed = _elapsed_years(
            state.start_date,
            migration_date,
        )
        target_income_weight, _ = (
            contribution_allocation(
                elapsed,
                config,
            )
        )
        swing_market_value = (
            state.position.shares
            * swing_candle.close
            if state.position is not None
            else 0.0
        )
        rebalance = rebalance_income_allocation(
            income_shares=state.income_shares,
            income_cost=state.income_cost,
            swing_cash=state.swing_cash,
            swing_market_value=swing_market_value,
            income_price=income_candle.close,
            target_income_weight=target_income_weight,
            slippage_rate=config.slippage_rate,
            tax_reserve_rate=(
                config.annual_tax_reserve_rate
            ),
            tolerance=(
                config.allocation_rebalance_tolerance
            ),
            minimum_trade=(
                config.minimum_rebalance_trade
            ),
        )
        state.income_shares = (
            rebalance.shares_after
        )
        state.income_cost = (
            rebalance.income_cost_after
        )
        state.swing_cash = (
            rebalance.swing_cash_after
        )
        state.tax_reserve_cash += (
            rebalance.tax_reserved
        )
        state.realized_pnl += (
            rebalance.realized_pnl
        )
        state.revision += 1
        state.validate()
        store.save(state)
        store.append_events(
            [
                AuditEvent(
                    event_id=event_id,
                    event_type=(
                        "CAPITAL_ALLOCATION_MIGRATION"
                    ),
                    event_date=migration_date,
                    details={
                        "migration": MIGRATION_NAME,
                        "additional_swing_capital": (
                            additional_swing_capital
                        ),
                        "total_starting_capital": (
                            config.total_starting_capital
                        ),
                        "target_income_weight": (
                            target_income_weight
                        ),
                        "before_income_weight": (
                            rebalance.before_income_weight
                        ),
                        "after_income_weight": (
                            rebalance.after_income_weight
                        ),
                        "rebalance_action": (
                            rebalance.action
                        ),
                        "rebalance_tax_reserved": (
                            rebalance.tax_reserved
                        ),
                        "open_swing_position_preserved": (
                            state.position is not None
                        ),
                    },
                )
            ]
        )

    return (
        "Added the missing initial swing capital and "
        "rebalanced QDTE toward the active target. "
        f"Action={rebalance.action}; "
        f"QDTE weight={rebalance.after_income_weight:.2%}; "
        f"target={target_income_weight:.2%}."
    )
