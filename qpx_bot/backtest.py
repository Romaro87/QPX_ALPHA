"""Historical backtesting engine for QPX Bot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from qpx_bot.config import BotConfig
from qpx_bot.data_loader import Candle
from qpx_bot.indicators import calculate_indicators
from qpx_bot.portfolio import ClosedTrade, Portfolio
from qpx_bot.risk import calculate_position_size
from qpx_bot.strategy import evaluate_entry, evaluate_exit


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """One end-of-day portfolio valuation."""

    date: date
    equity: float
    cash: float
    market_value: float
    tax_reserve: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Complete immutable result of one historical simulation."""

    symbol: str
    start_date: date
    end_date: date
    starting_cash: float
    total_contributions: float
    ending_equity: float
    ending_cash: float
    tax_reserve: float
    signal_count: int
    rejected_entries: int
    contribution_count: int
    trades: tuple[ClosedTrade, ...]
    equity_curve: tuple[EquityPoint, ...]

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

        peak = self.equity_curve[0].equity
        maximum = 0.0

        for point in self.equity_curve:
            peak = max(peak, point.equity)
            if peak > 0:
                drawdown = (peak - point.equity) / peak
                maximum = max(maximum, drawdown)

        return maximum


def _portfolio_prices(
    portfolio: Portfolio,
    symbol: str,
    price: float,
) -> dict[str, float]:
    if symbol in portfolio.positions:
        return {symbol: price}
    return {}


def run_backtest(
    *,
    candles: Sequence[Candle],
    symbol: str,
    config: BotConfig,
    vix: float | Sequence[float] = 20.0,
    forced_entry_indices: set[int] | None = None,
) -> BacktestResult:
    """
    Run a long-only, one-symbol historical simulation.

    Strategy signals are evaluated at the close and executed at the
    next bar's open. Existing stops are checked before targets when a
    daily bar touches both. Monthly contributions are deposited on the
    first available trading bar of each new calendar month.

    ``forced_entry_indices`` is an explicit signal adapter used by
    deterministic tests and external strategy integrations. Production
    runs should leave it as ``None`` so QPX strategy rules are used.
    """
    config.validate()

    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol:
        raise ValueError("Backtest symbol cannot be empty.")

    if len(candles) < 2:
        raise ValueError("At least two candles are required.")

    dates = [candle.date for candle in candles]
    if dates != sorted(dates):
        raise ValueError("Candles must be sorted by date.")

    if len(dates) != len(set(dates)):
        raise ValueError("Candles contain duplicate dates.")

    indicators = calculate_indicators(candles, config)
    portfolio = Portfolio(config.starting_cash)

    pending_signal_index: int | None = None
    signal_count = 0
    rejected_entries = 0
    contribution_count = 0
    equity_curve: list[EquityPoint] = []
    previous_month = (
        candles[0].date.year,
        candles[0].date.month,
    )

    for index, candle in enumerate(candles):
        current_month = (candle.date.year, candle.date.month)

        if current_month != previous_month:
            if config.monthly_contribution > 0:
                portfolio.deposit(config.monthly_contribution)
                contribution_count += 1
            previous_month = current_month

        if (
            pending_signal_index is not None
            and normalized_symbol not in portfolio.positions
        ):
            signal_atr = indicators.atr[pending_signal_index]

            if signal_atr is None or signal_atr <= 0:
                rejected_entries += 1
            else:
                equity_at_open = portfolio.equity(
                    _portfolio_prices(
                        portfolio,
                        normalized_symbol,
                        candle.open,
                    )
                )
                trade_results = [
                    trade.result_r
                    for trade in portfolio.closed_trades
                ]
                sizing = calculate_position_size(
                    account_equity=equity_at_open,
                    available_cash=portfolio.cash,
                    entry_price=candle.open,
                    atr=signal_atr,
                    active_risk=portfolio.active_risk(),
                    config=config,
                    trade_results_r=trade_results,
                )

                if sizing.is_tradeable:
                    portfolio.open_position(
                        symbol=normalized_symbol,
                        sizing=sizing,
                        entry_date=candle.date,
                        entry_atr=signal_atr,
                    )
                else:
                    rejected_entries += 1

            pending_signal_index = None

        position = portfolio.positions.get(normalized_symbol)
        current_atr = indicators.atr[index]

        if position is not None and current_atr is not None:
            exit_evaluation = evaluate_exit(
                position=position,
                candle=candle,
                current_atr=current_atr,
                config=config,
            )

            if exit_evaluation.should_exit:
                assert exit_evaluation.exit_price is not None
                portfolio.close_position(
                    symbol=normalized_symbol,
                    exit_price=exit_evaluation.exit_price,
                    exit_date=candle.date,
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
            index < len(candles) - 1
            and normalized_symbol not in portfolio.positions
            and pending_signal_index is None
        ):
            if forced_entry_indices is None:
                entry_evaluation = evaluate_entry(
                    candles=candles,
                    indicators=indicators,
                    index=index,
                    vix=vix,
                    config=config,
                )
                should_enter = entry_evaluation.should_enter
            else:
                should_enter = index in forced_entry_indices

            if should_enter:
                signal_count += 1
                pending_signal_index = index

        prices = _portfolio_prices(
            portfolio,
            normalized_symbol,
            candle.close,
        )
        market_value = portfolio.market_value(prices)
        equity_curve.append(
            EquityPoint(
                date=candle.date,
                equity=portfolio.equity(prices),
                cash=portfolio.cash,
                market_value=market_value,
                tax_reserve=portfolio.tax_reserve_cash,
            )
        )

    final_candle = candles[-1]

    if normalized_symbol in portfolio.positions:
        portfolio.close_position(
            symbol=normalized_symbol,
            exit_price=final_candle.close,
            exit_date=final_candle.date,
            reason="END_OF_TEST",
            config=config,
        )
        equity_curve[-1] = EquityPoint(
            date=final_candle.date,
            equity=portfolio.equity({}),
            cash=portfolio.cash,
            market_value=0.0,
            tax_reserve=portfolio.tax_reserve_cash,
        )

    ending_equity = portfolio.equity({})

    return BacktestResult(
        symbol=normalized_symbol,
        start_date=candles[0].date,
        end_date=candles[-1].date,
        starting_cash=config.starting_cash,
        total_contributions=portfolio.total_contributions,
        ending_equity=ending_equity,
        ending_cash=portfolio.cash,
        tax_reserve=portfolio.tax_reserve_cash,
        signal_count=signal_count,
        rejected_entries=rejected_entries,
        contribution_count=contribution_count,
        trades=tuple(portfolio.closed_trades),
        equity_curve=tuple(equity_curve),
    )
