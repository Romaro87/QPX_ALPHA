QPX EXACT ANNIVERSARY AND ENTRY-FILTER DIAGNOSTICS
===================================================

This milestone corrects the allocation phase transition and reruns the
same actual two-year, eight-symbol portfolio research without changing
strategy parameters.

Exact anniversary allocation rule
---------------------------------

The 65% QDTE / 35% swing phase remains active until the exact second
calendar anniversary of the test or paper account.

On the exact anniversary, or the first processed market session after
it, the target changes to 40% QDTE / 60% swing and an allocation-phase
rebalance is performed even when the anniversary occurs mid-month.

Leap-day starts use February 28 as the anniversary in non-leap years.

The rule is shared by:

- qpx_bot.hybrid
- qpx_bot.paper_engine
- qpx_bot.capital_migration
- qpx_bot.actual_two_year_portfolio

Entry-filter diagnostics
------------------------

The two-year replay evaluates the existing entry engine for every one
of these eight ETFs on every common daily session:

DIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV

For each symbol-day observation, the CSV records:

- monthly winner and active symbol;
- whether the portfolio was locked;
- whether that symbol was executable under the monthly-winner policy;
- whether the complete entry rule passed;
- bullish EMA, RSI, or RMI triggers;
- every failed filter:
  data readiness, price above SMA, positive SMA slope, average volume,
  breakout volume, price breakout, VIX, RSI overbought, and momentum
  trigger.

The report counts failures across all eight symbols and separately for
the executable active winner. Counts may overlap because one bar can
fail more than one condition.

No parameter optimization
-------------------------

This milestone changes no strategy thresholds, rank weights, slippage,
risk limits, stops, targets, contribution amounts, or allocation
percentages. It corrects timing, adds observability, and reruns the
identical latest two-completed-year window using freshly downloaded
actual data.

Run
---

python QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py

New artifact
------------

entry_filter_diagnostics.csv

The normal result, trades, monthly ranking, allocation, equity,
provenance, and input-hash files remain available in the same run
directory.

Historical research only. Live brokerage remains disabled.
