#!/usr/bin/env python3
"""Run the actual two-year QPX eight-symbol portfolio backtest."""

from qpx_bot.actual_two_year_portfolio import (
    format_console_summary,
    run_actual_two_year_eight_symbol_backtest,
)


if __name__ == "__main__":
    result, artifacts = (
        run_actual_two_year_eight_symbol_backtest()
    )
    print(
        format_console_summary(
            result,
            artifacts,
        )
    )
