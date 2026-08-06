"""Restart-safe simulated execution for the QPX hybrid strategy."""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Sequence

from qpx_bot.allocation import (
    rebalance_income_allocation,
)
from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent
from qpx_bot.indicators import IndicatorSet
from qpx_bot.paper_state import (
    AuditEvent,
    PaperState,
    PendingEntry,
    PersistentPosition,
)
from qpx_bot.portfolio import Position, contribution_allocation
from qpx_bot.risk import (
    buy_fill,
    calculate_position_size,
    sell_fill,
)
from qpx_bot.strategy import evaluate_entry, evaluate_exit
from qpx_bot.time_rules import elapsed_complete_years


def _identifier(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _event(
    *,
    state: PaperState,
    event_type: str,
    event_date: date,
    unique: str,
    details: dict[str, object],
) -> AuditEvent:
    return AuditEvent(
        event_id=_identifier(
            state.state_id,
            event_type,
            event_date.isoformat(),
            unique,
        ),
        event_type=event_type,
        event_date=event_date,
        details=details,
    )


def _month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _elapsed_years(start: date, current: date) -> int:
    return elapsed_complete_years(start, current)


def _latest_income_candle(
    income_candles: Sequence[Candle],
    current_date: date,
) -> Candle:
    selected: Candle | None = None

    for candle in income_candles:
        if candle.date > current_date:
            break
        selected = candle

    if selected is None:
        raise ValueError(
            "Income history does not cover the paper date."
        )

    return selected


def create_initial_state(
    *,
    swing_symbol: str,
    income_symbol: str,
    start_date: date,
    income_price: float,
    config: BotConfig,
) -> tuple[PaperState, AuditEvent]:
    config.validate()

    normalized_swing = swing_symbol.strip().upper()
    normalized_income = income_symbol.strip().upper()

    if not normalized_swing or not normalized_income:
        raise ValueError("Paper symbols cannot be empty.")

    income_weight, swing_weight = contribution_allocation(
        0,
        config,
    )
    income_cash = config.starting_cash
    swing_cash = config.starting_swing_cash
    fill = buy_fill(
        income_price,
        config.slippage_rate,
    )
    income_shares = income_cash / fill
    initial_rebalance = rebalance_income_allocation(
        income_shares=income_shares,
        income_cost=income_cash,
        swing_cash=swing_cash,
        swing_market_value=0.0,
        income_price=income_price,
        target_income_weight=income_weight,
        slippage_rate=config.slippage_rate,
        tax_reserve_rate=config.annual_tax_reserve_rate,
        tolerance=config.allocation_rebalance_tolerance,
        minimum_trade=config.minimum_rebalance_trade,
    )
    state_id = _identifier(
        normalized_swing,
        normalized_income,
        start_date.isoformat(),
        f"{config.starting_cash:.8f}",
        f"{config.starting_swing_cash:.8f}",
    )

    state = PaperState(
        state_id=state_id,
        swing_symbol=normalized_swing,
        income_symbol=normalized_income,
        start_date=start_date,
        starting_cash=config.total_starting_capital,
        swing_cash=initial_rebalance.swing_cash_after,
        tax_reserve_cash=(
            initial_rebalance.tax_reserved
        ),
        total_contributions=(
            config.total_starting_capital
        ),
        realized_pnl=(
            initial_rebalance.realized_pnl
        ),
        income_shares=(
            initial_rebalance.shares_after
        ),
        income_cost=(
            initial_rebalance.income_cost_after
        ),
        dividends_received=0.0,
        last_processed_date=None,
        last_contribution_month=_month_key(start_date),
    )
    state.validate()

    event = _event(
        state=state,
        event_type="ACCOUNT_INITIALIZED",
        event_date=start_date,
        unique="initial",
        details={
            "swing_symbol": normalized_swing,
            "income_symbol": normalized_income,
            "starting_income_cash": (
                config.starting_cash
            ),
            "starting_swing_cash": (
                config.starting_swing_cash
            ),
            "total_starting_capital": (
                config.total_starting_capital
            ),
            "income_weight": income_weight,
            "swing_weight": swing_weight,
            "income_fill": fill,
            "income_shares": (
                initial_rebalance.shares_after
            ),
            "swing_cash": (
                initial_rebalance.swing_cash_after
            ),
            "rebalance_action": (
                initial_rebalance.action
            ),
            "income_weight_before": (
                initial_rebalance.before_income_weight
            ),
            "income_weight_after": (
                initial_rebalance.after_income_weight
            ),
            "mode": "SIMULATED_ONLY",
        },
    )
    return state, event


def _as_position(
    position: PersistentPosition,
) -> Position:
    return Position(
        symbol=position.symbol,
        shares=position.shares,
        entry_date=position.entry_date,
        entry_price=position.entry_price,
        entry_atr=position.entry_atr,
        stop_price=position.stop_price,
        target_price=position.target_price,
        highest_price=position.highest_price,
    )


def _mark_equity(
    state: PaperState,
    *,
    swing_price: float,
    income_price: float,
) -> float:
    return state.equity(
        swing_price=swing_price,
        income_price=income_price,
    )


def reconcile_state(
    state: PaperState,
    *,
    swing_price: float,
    income_price: float,
) -> dict[str, float | int | str | None]:
    """Validate and return a deterministic account reconciliation."""
    state.validate()
    swing_value = (
        state.position.shares * swing_price
        if state.position
        else 0.0
    )
    income_value = state.income_shares * income_price
    equity = (
        state.swing_cash
        + state.tax_reserve_cash
        + swing_value
        + income_value
    )

    if abs(
        equity
        - state.equity(
            swing_price=swing_price,
            income_price=income_price,
        )
    ) > 1e-7:
        raise RuntimeError("Paper equity reconciliation failed.")

    return {
        "state_id": state.state_id,
        "revision": state.revision,
        "last_processed_date": (
            state.last_processed_date.isoformat()
            if state.last_processed_date
            else None
        ),
        "swing_cash": state.swing_cash,
        "tax_reserve_cash": state.tax_reserve_cash,
        "swing_market_value": swing_value,
        "income_market_value": income_value,
        "total_equity": equity,
        "total_contributions": state.total_contributions,
        "realized_pnl": state.realized_pnl,
        "dividends_received": state.dividends_received,
        "open_shares": (
            state.position.shares
            if state.position
            else 0
        ),
        "pending_entry": (
            state.pending_entry.order_id
            if state.pending_entry
            else None
        ),
    }


def process_paper_day(
    *,
    state: PaperState,
    swing_candles: Sequence[Candle],
    income_candles: Sequence[Candle],
    dividends: Sequence[DividendEvent],
    indicators: IndicatorSet,
    vix_values: Sequence[float],
    index: int,
    config: BotConfig,
    forced_entry: bool | None = None,
) -> list[AuditEvent]:
    """
    Process exactly one new daily bar.

    Pending entries are never filled by after-close analysis. The
    regular-session runner consumes them during the next opening
    window. Stops and targets use completed regular-session OHLC for
    post-session reconciliation. New signals are created after close.
    """
    config.validate()
    state.validate()

    if index < 0 or index >= len(swing_candles):
        raise IndexError("Paper index is outside swing history.")

    if len(vix_values) != len(swing_candles):
        raise ValueError(
            "Paper VIX series must align with swing candles."
        )

    candle = swing_candles[index]
    current_date = candle.date

    if (
        state.last_processed_date is not None
        and current_date <= state.last_processed_date
    ):
        return []

    income_candle = _latest_income_candle(
        income_candles,
        current_date,
    )
    current_atr = indicators.atr[index]
    events: list[AuditEvent] = []

    current_month = _month_key(current_date)

    previous_allocation_date = (
        state.last_processed_date
        or state.start_date
    )
    current_allocation_years = _elapsed_years(
        state.start_date,
        current_date,
    )
    previous_allocation_years = _elapsed_years(
        state.start_date,
        previous_allocation_date,
    )
    month_changed = (
        current_month
        != state.last_contribution_month
    )
    phase_changed = (
        current_allocation_years
        != previous_allocation_years
    )

    if month_changed or phase_changed:
        income_weight, swing_weight = contribution_allocation(
            current_allocation_years,
            config,
        )
        contribution_amount = (
            config.monthly_contribution
            if month_changed
            else 0.0
        )
        swing_cash_before = state.swing_cash

        if contribution_amount > 0:
            state.swing_cash += contribution_amount
            state.total_contributions += (
                contribution_amount
            )

        swing_market_value = (
            state.position.shares * candle.open
            if state.position is not None
            else 0.0
        )
        rebalance = rebalance_income_allocation(
            income_shares=state.income_shares,
            income_cost=state.income_cost,
            swing_cash=state.swing_cash,
            swing_market_value=swing_market_value,
            income_price=income_candle.open,
            target_income_weight=income_weight,
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

        if month_changed:
            state.last_contribution_month = (
                current_month
            )

        event_type = (
            "MONTHLY_CONTRIBUTION"
            if month_changed
            else "ALLOCATION_PHASE_REBALANCE"
        )
        unique = (
            current_month
            if month_changed
            else current_date.isoformat()
        )
        events.append(
            _event(
                state=state,
                event_type=event_type,
                event_date=current_date,
                unique=unique,
                details={
                    "amount": contribution_amount,
                    "target_income_weight": (
                        income_weight
                    ),
                    "target_swing_weight": (
                        swing_weight
                    ),
                    "allocation_years": (
                        current_allocation_years
                    ),
                    "exact_anniversary_rule": True,
                    "rebalance_action": (
                        rebalance.action
                    ),
                    "income_weight_before": (
                        rebalance.before_income_weight
                    ),
                    "income_weight_after": (
                        rebalance.after_income_weight
                    ),
                    "income_trade_cash": (
                        rebalance.trade_cash
                    ),
                    "swing_cash_change": (
                        state.swing_cash
                        - swing_cash_before
                    ),
                    "rebalance_realized_pnl": (
                        rebalance.realized_pnl
                    ),
                    "rebalance_tax_reserved": (
                        rebalance.tax_reserved
                    ),
                    "target_fully_reached": (
                        rebalance.target_fully_reached
                    ),
                    "open_swing_position_preserved": (
                        state.position is not None
                    ),
                },
            )
        )

    previous_date = state.last_processed_date

    for dividend in dividends:
        if dividend.date > current_date:
            break

        if previous_date is not None and dividend.date <= previous_date:
            continue

        if previous_date is None and dividend.date != current_date:
            continue

        key = (
            f"{dividend.date.isoformat()}:"
            f"{dividend.amount_per_share:.10f}"
        )

        if key in state.processed_dividend_keys:
            continue

        gross_cash = (
            state.income_shares
            * dividend.amount_per_share
        )
        state.swing_cash += gross_cash
        state.dividends_received += gross_cash
        state.processed_dividend_keys.append(key)

        events.append(
            _event(
                state=state,
                event_type="DIVIDEND_CASH",
                event_date=dividend.date,
                unique=key,
                details={
                    "amount_per_share": (
                        dividend.amount_per_share
                    ),
                    "income_shares": state.income_shares,
                    "gross_cash": gross_cash,
                    "destination": "SWING_CASH",
                },
            )
        )

    # Staged entries are consumed only by qpx_bot.session_execution
    # during the next regular-session opening window. After-close
    # processing must never fill or clear a pending entry.

    if state.position is not None and current_atr is not None:
        live_position = _as_position(state.position)
        exit_evaluation = evaluate_exit(
            position=live_position,
            candle=candle,
            current_atr=current_atr,
            config=config,
        )

        if exit_evaluation.should_exit:
            assert exit_evaluation.exit_price is not None
            fill = sell_fill(
                exit_evaluation.exit_price,
                config.slippage_rate,
            )
            proceeds = fill * state.position.shares
            pnl = (
                (fill - state.position.entry_price)
                * state.position.shares
            )
            tax_reserved = (
                max(0.0, pnl)
                * config.annual_tax_reserve_rate
            )
            initial_risk = (
                state.position.entry_atr
                * config.stop_atr_multiple
                * state.position.shares
            )
            result_r = (
                pnl / initial_risk
                if initial_risk > 0
                else 0.0
            )
            entry_date = state.position.entry_date
            shares = state.position.shares

            state.swing_cash += proceeds - tax_reserved
            state.tax_reserve_cash += tax_reserved
            state.realized_pnl += pnl
            state.trade_results_r.append(result_r)
            state.position = None

            exit_key = _identifier(
                state.swing_symbol,
                entry_date.isoformat(),
                current_date.isoformat(),
                exit_evaluation.reason or "EXIT",
            )
            events.append(
                _event(
                    state=state,
                    event_type="EXIT_FILLED",
                    event_date=current_date,
                    unique=exit_key,
                    details={
                        "shares": shares,
                        "entry_date": entry_date.isoformat(),
                        "fill_price": fill,
                        "pnl": pnl,
                        "tax_reserved": tax_reserved,
                        "result_r": result_r,
                        "reason": (
                            exit_evaluation.reason or "EXIT"
                        ),
                        "execution_session": (
                            "REGULAR_SESSION_RECONCILIATION"
                        ),
                        "extended_hours": False,
                    },
                )
            )
        else:
            state.position.stop_price = (
                exit_evaluation.next_stop_price
            )
            state.position.highest_price = (
                exit_evaluation.highest_price
            )

    if (
        state.position is None
        and state.pending_entry is None
        and index < len(swing_candles)
    ):
        if forced_entry is None:
            evaluation = evaluate_entry(
                candles=swing_candles,
                indicators=indicators,
                index=index,
                vix=vix_values,
                config=config,
            )
            should_enter = evaluation.should_enter
            triggers = evaluation.triggers
            failed_checks = evaluation.failed_checks
        else:
            should_enter = forced_entry
            triggers = (
                ("TEST_FORCED_ENTRY",)
                if forced_entry
                else ()
            )
            failed_checks = (
                ()
                if forced_entry
                else ("TEST_FORCED_HOLD",)
            )

        if should_enter and current_atr is not None:
            order_id = _identifier(
                "ENTRY",
                state.state_id,
                state.swing_symbol,
                current_date.isoformat(),
            )

            if order_id not in state.completed_order_keys:
                state.pending_entry = PendingEntry(
                    order_id=order_id,
                    symbol=state.swing_symbol,
                    signal_date=current_date,
                    signal_atr=current_atr,
                )
                events.append(
                    _event(
                        state=state,
                        event_type="ENTRY_SIGNAL",
                        event_date=current_date,
                        unique=order_id,
                        details={
                            "order_id": order_id,
                            "signal_atr": current_atr,
                            "triggers": list(triggers),
                            "execution": (
                                "NEXT_REGULAR_SESSION_OPENING_WINDOW"
                            ),
                            "extended_hours": False,
                        },
                    )
                )
        else:
            events.append(
                _event(
                    state=state,
                    event_type="DAILY_HOLD",
                    event_date=current_date,
                    unique="no-entry",
                    details={
                        "failed_checks": list(failed_checks),
                        "position_open": (
                            state.position is not None
                        ),
                    },
                )
            )

    state.last_processed_date = current_date
    state.revision += 1
    state.validate()

    reconciliation = reconcile_state(
        state,
        swing_price=candle.close,
        income_price=income_candle.close,
    )
    events.append(
        _event(
            state=state,
            event_type="DAILY_RECONCILIATION",
            event_date=current_date,
            unique=f"revision-{state.revision}",
            details=reconciliation,
        )
    )

    return events
