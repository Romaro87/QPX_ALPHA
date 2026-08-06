from datetime import date

from qpx_bot.actual_two_year_portfolio import (
    REQUIRED_UNIVERSE,
    rank_as_of,
    subtract_years,
)
from qpx_bot.symbol_selector import (
    SelectionConfig,
)
from qpx_bot.yahoo_data import MarketRow


assert REQUIRED_UNIVERSE == (
    "DIA",
    "IWM",
    "QQQ",
    "SPY",
    "XLE",
    "XLF",
    "XLK",
    "XLV",
)
assert len(REQUIRED_UNIVERSE) == 8
assert subtract_years(
    date(2024, 2, 29),
    2,
) == date(2022, 2, 28)

selection_config = SelectionConfig(
    schema_version=1,
    decision_frequency="monthly",
    history_range="4y",
    candidates=REQUIRED_UNIVERSE,
    minimum_history_bars=252,
    minimum_eligible_candidates=3,
    minimum_median_dollar_volume=50_000_000,
    maximum_stale_days=4,
    short_return_lookback=63,
    long_return_lookback=126,
    trend_lookback=200,
    volatility_lookback=63,
    drawdown_lookback=126,
    liquidity_lookback=20,
    weights={
        "short_return": 0.25,
        "long_return": 0.30,
        "trend": 0.15,
        "liquidity": 0.10,
        "volatility_penalty": 0.10,
        "drawdown_penalty": 0.10,
    },
    symbol_bonus_policy="none",
)

histories = {}

for symbol_index, symbol in enumerate(
    REQUIRED_UNIVERSE
):
    rows = []

    for index in range(300):
        day = date.fromordinal(
            date(2023, 1, 2).toordinal()
            + index
        )
        close = (
            100.0
            + index * (
                0.05
                + symbol_index * 0.005
            )
        )
        rows.append(
            MarketRow(
                date=day,
                open=close - 0.1,
                high=close + 0.5,
                low=close - 0.5,
                close=close,
                adjusted_close=close,
                volume=5_000_000,
            )
        )

    histories[symbol] = rows

decision_date = date.fromordinal(
    date(2023, 1, 2).toordinal()
    + 299
)
selection = rank_as_of(
    decision_date=decision_date,
    histories=histories,
    selection_config=selection_config,
)

assert selection.latest_market_date < decision_date
assert (
    selection.selected_symbol
    in REQUIRED_UNIVERSE
)
assert selection.symbol_bonus_policy == "none"

from pathlib import Path

source = (
    Path(__file__).resolve().parents[1]
    / "qpx_bot"
    / "actual_two_year_portfolio.py"
).read_text(encoding="utf-8")

for required in (
    "fetch_chart(",
    "rank_candidates(",
    "evaluate_entry(",
    "evaluate_exit(",
    "calculate_position_size(",
    "rebalance_income_allocation(",
    "row.date < decision_date",
    "forced_entry_indices=None",
    "No synthetic OHLCV",
):
    assert required in source

assert "forced_entry_indices={" not in source
assert "synthetic_candles" not in source
assert "CURRENT_SELECTION_DECISION" not in source

print(
    "QPX Bot Actual Two-Year Eight-Symbol "
    "Portfolio Backtest PASS"
)
