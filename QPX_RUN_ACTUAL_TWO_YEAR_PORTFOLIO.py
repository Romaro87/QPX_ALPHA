#!/usr/bin/env python3
"""Run the unranked three-position actual-data portfolio backtest."""

from qpx_bot.actual_two_year_three_position import (
    format_console_summary,
    run_actual_two_year_three_position_backtest,
)


if __name__ == "__main__":
    result, artifacts = (
        run_actual_two_year_three_position_backtest()
    )
    print(
        format_console_summary(
            result,
            artifacts,
        )
    )
