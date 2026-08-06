"""Hybrid dividend-income and swing-trading backtest engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.dividends import DividendEvent, dividend_amounts_by_date
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import (
    ClosedTrade,
    Portfolio,
    contribution_allocation,
)
from qpx_bot.risk import buy_fill, calculate_position_size
from qpx_bot.strategy import evaluate_entry, evaluate_exit


@dataclass(slots=True)
class IncomeHolding:
    """Fractional-share holding used by the income sleeve."""

    symbol: str
    shares: float = 0.0
    invested_cost: float = 0.0
    dividends_received: float = 0.0

    def buy(
        self,
        *,
        cash_amount: float,
        market_price: float,
        slippage_rate: float,
    ) -> float:
        """Invest an exact cash amount and return acquired shares."""
        if cash_amount < 0:
            raise ValueError("Income investment cannot be negative.")

        if cash_amount == 0:
            return 0.0

        fill = buy_fill(market_price, slippage_rate)
        acquired = cash_amount / fill
        self.shares += acquired
        self.invested_cost += cash_amount
        return acquired

    def receive_dividend(self, amount_per_share: float) -> float:
        """Record and return dividend cash produced by current shares."""
        if amount_per_share < 0:
            raise ValueError("Dividend per share cannot be negative.")

        cash = self.shares * amount_per_share
        self.dividends_received += cash
        return cash

    def market_value(self, market_price: float) -> float:
        if market_price <= 0:
            raise ValueError("Income market price must be positive.")
        return self.shares * market_price


@dataclass(frozen=True, slots=True)
class AllocationEvent:
    """One external contribution and its two-sleeve split."""

    date: date
    amount: float
    income_weight: float
    swing_weight: float
    income_amount: float
    swing_amount: float


@dataclass(frozen=True, slots=True)
class HybridEquityPoint:
    """One end-of-day combined portfolio valuation."""

    date: date
    total_equity: float
    income_value: float
    swing_equity: float
    swing_cash: float
    swing_market_value: float
    tax_reserve: float
    income_shares: float
    cumulative_dividends: float
    total_contributions: float


@dataclass(frozen=True, slots=True)
class HybridBacktestResult:
    """Complete result for the income-plus-swing simulation."""

    swing_symbol: str
    income_symbol: str
    start_date: date
    end_date: date
    starting_cash: float
    total_contributions: float
    ending_equity: float
    ending_income_value: float
    ending_income_shares: float
    ending_swing_equity: float
    ending_swing_cash: float
    tax_reserve: float
    total_dividends: float
    dividend_event_count: int
    contribution_count: int
    signal_count: int
    rejected_entries: int
    trades: tuple[ClosedTrade, ...]
    allocation_events: tuple[AllocationEvent, ...]
    equity_curve: tuple[HybridEquityPoint, ...]

    @property
    def net_profit(self) -> float:
        return self.ending_equity - self.total_contributions

    @property
    def return_on_contributed_capital(self) -> float:
        if self.total_contributions <= 0:
            return 0.0
        return self.net_profit / self.total_contributions

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        winners = sum(1 for trade in self.trades if trade.pnl > 0)
        return winners / len(self.trades)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(
            trade.pnl for trade in self.trades if trade.pnl > 0
        )
        gross_loss = -sum(
            trade.pnl for trade in self.trades if trade.pnl < 0
        )

        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 0.0

        return gross_profit / gross_loss

    @property
    def maximum_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0

        peak = self.equity_curve[0].total_equity
        maximum = 0.0

        for point in self.equity_curve:
            peak = max(peak, point.total_equity)
            if peak > 0:
                drawdown = (
                    peak - point.total_equity
                ) / peak
                maximum = max(maximum, drawdown)

        return maximum


def _validate_candles(
    candles: Sequence[Candle],
    label: str,
) -> None:
    if not candles:
        raise ValueError(f"{label} candles cannot be empty.")

    dates = [candle.date for candle in candles]

    if dates != sorted(dates):
        raise ValueError(f"{label} candles must be sorted by date.")

    if len(dates) != len(set(dates)):
        raise ValueError(f"{label} candles contain duplicate dates.")


def _swing_prices(
    portfolio: Portfolio,
    symbol: str,
    price: float,
) -> dict[str, float]:
    if symbol in portfolio.positions:
        return {symbol: price}
    return {}


def _elapsed_years(start: date, current: date) -> int:
    months = (
        (current.year - start.year) * 12
        + current.month
        - start.month
    )
    return max(0, months // 12)


def run_hybrid_backtest(
    *,
    swing_candles: Sequence[Candle],
    income_candles: Sequence[Candle],
    dividends: Sequence[DividendEvent],
    swing_symbol: str,
    config: BotConfig,
    vix: float | Sequence[float] = 20.0,
    forced_entry_indices: set[int] | None = None,
) -> HybridBacktestResult:
    """
    Run the configured Hybrid Dividend + Swing strategy.

    The initial capital and every monthly deposit are split between
    the income and swing sleeves. Years 1–2 use 65/35 and year 3
    onward uses 40/60. Income distributions are routed into swing
    cash and are not counted as external contributions.

    Swing signals are evaluated at the close and filled at the next
    bar's open. The income sleeve remains invested at the end.
    """
    config.validate()
    _validate_candles(swing_candles, "Swing")
    _validate_candles(income_candles, "Income")

    if len(swing_candles) < 2:
        raise ValueError("At least two swing candles are required.")

    normalized_swing = swing_symbol.strip().upper()
    normalized_income = config.dividend_symbol.strip().upper()

    if not normalized_swing:
        raise ValueError("Swing symbol cannot be empty.")

    if not normalized_income:
        raise ValueError("Income symbol cannot be empty.")

    income_by_date = {
        candle.date: candle
        for candle in income_candles
    }
    income_dates = [candle.date for candle in income_candles]
    first_swing_date = swing_candles[0].date

    if income_dates[0] > first_swing_date:
        raise ValueError(
            "Income history must begin on or before swing history."
        )

    dividend_map = dividend_amounts_by_date(dividends)
    indicators = calculate_indicators(swing_candles, config)

    initial_income_weight, initial_swing_weight = (
        contribution_allocation(0, config)
    )
    initial_income_cash = (
        config.starting_cash * initial_income_weight
    )
    initial_swing_cash = (
        config.starting_cash * initial_swing_weight
    )

    income_holding = IncomeHolding(normalized_income)
    swing_portfolio = Portfolio(initial_swing_cash)

    income_pointer = 0
    latest_income = income_candles[0]

    while (
        income_pointer + 1 < len(income_candles)
        and income_candles[income_pointer + 1].date
        <= first_swing_date
    ):
        income_pointer += 1
        latest_income = income_candles[income_pointer]

    income_holding.buy(
        cash_amount=initial_income_cash,
        market_price=latest_income.open,
        slippage_rate=config.slippage_rate,
    )

    total_external_contributions = config.starting_cash
    contribution_count = 0
    dividend_event_count = 0
    signal_count = 0
    rejected_entries = 0
    pending_signal_index: int | None = None
    allocation_events: list[AllocationEvent] = []
    equity_curve: list[HybridEquityPoint] = []

    previous_month = (
        first_swing_date.year,
        first_swing_date.month,
    )

    for index, swing_candle in enumerate(swing_candles):
        while (
            income_pointer + 1 < len(income_candles)
            and income_candles[income_pointer + 1].date
            <= swing_candle.date
        ):
            income_pointer += 1
            latest_income = income_candles[income_pointer]

        current_month = (
            swing_candle.date.year,
            swing_candle.date.month,
        )

        dividend_per_share = dividend_map.get(
            swing_candle.date,
            0.0,
        )

        if dividend_per_share > 0:
            dividend_cash = income_holding.receive_dividend(
                dividend_per_share
            )
            swing_portfolio.cash += dividend_cash
            dividend_event_count += 1

        if current_month != previous_month:
            if config.monthly_contribution > 0:
                elapsed_years = _elapsed_years(
                    first_swing_date,
                    swing_candle.date,
                )
                income_weight, swing_weight = (
                    contribution_allocation(
                        elapsed_years,
                        config,
                    )
                )
                income_amount = (
                    config.monthly_contribution
                    * income_weight
                )
                swing_amount = (
                    config.monthly_contribution
                    * swing_weight
                )

                income_holding.buy(
                    cash_amount=income_amount,
                    market_price=latest_income.open,
                    slippage_rate=config.slippage_rate,
                )
                swing_portfolio.deposit(swing_amount)
                total_external_contributions += (
                    config.monthly_contribution
                )
                contribution_count += 1
                allocation_events.append(
                    AllocationEvent(
                        date=swing_candle.date,
                        amount=config.monthly_contribution,
                        income_weight=income_weight,
                        swing_weight=swing_weight,
                        income_amount=income_amount,
                        swing_amount=swing_amount,
                    )
                )

            previous_month = current_month

        if (
            pending_signal_index is not None
            and normalized_swing
            not in swing_portfolio.positions
        ):
            signal_atr = indicators.atr[
                pending_signal_index
            ]

            if signal_atr is None or signal_atr <= 0:
                rejected_entries += 1
            else:
                swing_prices = _swing_prices(
                    swing_portfolio,
                    normalized_swing,
                    swing_candle.open,
                )
                combined_equity_at_open = (
                    swing_portfolio.equity(swing_prices)
                    + income_holding.market_value(
                        latest_income.open
                    )
                )
                trade_results = [
                    trade.result_r
                    for trade in swing_portfolio.closed_trades
                ]
                sizing = calculate_position_size(
                    account_equity=combined_equity_at_open,
                    available_cash=swing_portfolio.cash,
                    entry_price=swing_candle.open,
                    atr=signal_atr,
                    active_risk=swing_portfolio.active_risk(),
                    config=config,
                    trade_results_r=trade_results,
                )

                if sizing.is_tradeable:
                    swing_portfolio.open_position(
                        symbol=normalized_swing,
                        sizing=sizing,
                        entry_date=swing_candle.date,
                        entry_atr=signal_atr,
                    )
                else:
                    rejected_entries += 1

            pending_signal_index = None

        position = swing_portfolio.positions.get(
            normalized_swing
        )
        current_atr = indicators.atr[index]

        if position is not None and current_atr is not None:
            exit_evaluation = evaluate_exit(
                position=position,
                candle=swing_candle,
                current_atr=current_atr,
                config=config,
            )

            if exit_evaluation.should_exit:
                assert exit_evaluation.exit_price is not None
                swing_portfolio.close_position(
                    symbol=normalized_swing,
                    exit_price=exit_evaluation.exit_price,
                    exit_date=swing_candle.date,
                    reason=exit_evaluation.reason or "EXIT",
                    config=config,
                )
            else:
                position.stop_price = (
                    exit_evaluation.next_stop_price
                )
                position.highest_price = (
                    exit_evaluation.highest_price
                )

        if (
            index < len(swing_candles) - 1
            and normalized_swing
            not in swing_portfolio.positions
            and pending_signal_index is None
        ):
            if forced_entry_indices is None:
                entry_evaluation = evaluate_entry(
                    candles=swing_candles,
                    indicators=indicators,
                    index=index,
                    vix=vix,
                    config=config,
                )
                should_enter = entry_evaluation.should_enter
            else:
                should_enter = (
                    index in forced_entry_indices
                )

            if should_enter:
                signal_count += 1
                pending_signal_index = index

        swing_prices = _swing_prices(
            swing_portfolio,
            normalized_swing,
            swing_candle.close,
        )
        swing_market_value = (
            swing_portfolio.market_value(swing_prices)
        )
        swing_equity = swing_portfolio.equity(
            swing_prices
        )
        income_value = income_holding.market_value(
            latest_income.close
        )

        equity_curve.append(
            HybridEquityPoint(
                date=swing_candle.date,
                total_equity=(
                    swing_equity + income_value
                ),
                income_value=income_value,
                swing_equity=swing_equity,
                swing_cash=swing_portfolio.cash,
                swing_market_value=swing_market_value,
                tax_reserve=(
                    swing_portfolio.tax_reserve_cash
                ),
                income_shares=income_holding.shares,
                cumulative_dividends=(
                    income_holding.dividends_received
                ),
                total_contributions=(
                    total_external_contributions
                ),
            )
        )

    final_swing = swing_candles[-1]

    if normalized_swing in swing_portfolio.positions:
        swing_portfolio.close_position(
            symbol=normalized_swing,
            exit_price=final_swing.close,
            exit_date=final_swing.date,
            reason="END_OF_TEST",
            config=config,
        )

    final_income_value = income_holding.market_value(
        latest_income.close
    )
    final_swing_equity = swing_portfolio.equity({})
    ending_equity = (
        final_swing_equity + final_income_value
    )

    equity_curve[-1] = HybridEquityPoint(
        date=final_swing.date,
        total_equity=ending_equity,
        income_value=final_income_value,
        swing_equity=final_swing_equity,
        swing_cash=swing_portfolio.cash,
        swing_market_value=0.0,
        tax_reserve=swing_portfolio.tax_reserve_cash,
        income_shares=income_holding.shares,
        cumulative_dividends=(
            income_holding.dividends_received
        ),
        total_contributions=total_external_contributions,
    )

    return HybridBacktestResult(
        swing_symbol=normalized_swing,
        income_symbol=normalized_income,
        start_date=swing_candles[0].date,
        end_date=swing_candles[-1].date,
        starting_cash=config.starting_cash,
        total_contributions=total_external_contributions,
        ending_equity=ending_equity,
        ending_income_value=final_income_value,
        ending_income_shares=income_holding.shares,
        ending_swing_equity=final_swing_equity,
        ending_swing_cash=swing_portfolio.cash,
        tax_reserve=swing_portfolio.tax_reserve_cash,
        total_dividends=income_holding.dividends_received,
        dividend_event_count=dividend_event_count,
        contribution_count=contribution_count,
        signal_count=signal_count,
        rejected_entries=rejected_entries,
        trades=tuple(swing_portfolio.closed_trades),
        allocation_events=tuple(allocation_events),
        equity_curve=tuple(equity_curve),
    )
