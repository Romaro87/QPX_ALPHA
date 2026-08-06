QPX THREE-POSITION EXACT-ANNIVERSARY FIX
========================================

Problem corrected
-----------------

The unranked three-position research engine previously performed
allocation rebalancing only when the calendar month changed.

For a test beginning on August 6, 2024:

- August 3, 2026 was the first processed session of the month.
- The exact second anniversary was August 6, 2026.
- Since the month had already changed, the strategy did not perform the
  required 65/35 to 40/60 allocation-phase rebalance on August 6.

That caused the test to end near 65% QDTE even though the report claimed
the exact-date transition had occurred.

Correct behavior
----------------

The engine now tracks two independent events:

1. calendar-month change;
2. completed-year allocation-phase change.

A monthly contribution is added only on a month change.

A QDTE/swing rebalance is performed when either event occurs.

When the anniversary occurs after the first session of a month, the
engine performs an ALLOCATION_PHASE_REBALANCE with a zero external
contribution.

When the anniversary and month change occur on the same session, one
combined monthly contribution and allocation rebalance is performed.

Preserved strategy
------------------

- rankings remain removed;
- all eight ETFs are scanned daily;
- maximum three concurrent swing positions;
- exact same entry filters;
- exact same ATR exits and trailing stop;
- exact same slippage and opening-gap rejection;
- exact same quarter-Kelly and 6% global active-risk cap;
- actual QDTE distributions and actual VIX;
- no synthetic data or forced entries;
- live brokerage disabled.

The installer runs all tests, commits and pushes the correction, then
downloads fresh actual data and reruns the same two-year backtest.
