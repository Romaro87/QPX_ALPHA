QPX UNRANKED THREE-POSITION SWING STRATEGY
==========================================

Swing universe
--------------

DIA
IWM
QQQ
SPY
XLE
XLF
XLK
XLV

QDTE remains the income sleeve. ^VIX remains the volatility gate.

Rankings removed
----------------

There is no monthly winner, ranking score, momentum rank, liquidity
rank, preferred symbol, or fallback ticker.

Every completed daily bar evaluates the existing QPX entry rules for
all eight ETFs independently.

Three concurrent positions
--------------------------

The swing sleeve may hold up to three different ETF positions at once.

Signals are generated at the close and staged for the next common
market-session open. A symbol cannot be staged when it is already open
or already pending.

When more ETFs qualify on one close than there are open slots, the
collision is resolved by SHA-256(signal date | symbol). This tie-break
uses no price, return, volume, volatility, momentum, future information,
or symbol bonus. It is deterministic and changes with the signal date.

Risk and execution preserved
----------------------------

- quarter-Kelly sizing;
- 1% base risk per position;
- 6% total active portfolio-risk cap;
- 2.5 ATR stop;
- 5.0 ATR target;
- trailing stop after a 3.0 ATR advance;
- VIX entry gate at 28;
- 1.2x breakout-volume requirement;
- 2,000,000 average daily volume;
- positive 200-day SMA slope;
- 0.075% adverse slippage;
- 1.5 ATR next-open gap rejection;
- 37% reserve on profitable realized gains.

Capital and allocation preserved
--------------------------------

Initial QDTE seed       : $1,300
Initial swing liquidity : $1,500
Initial total capital   : $2,800
Monthly contribution    : $2,000

The exact-anniversary allocation remains 65% QDTE / 35% swing through
the first two complete years, then 40% QDTE / 60% swing.

Actual-data replay
------------------

The installer downloads fresh true-daily data for all eight ETFs, QDTE,
and ^VIX. Four years are requested for indicator warmup; performance is
reported for the latest two completed years.

No synthetic data, placeholder distributions, rankings, forced entries,
brokerage connection, or live orders are used.

Outputs
-------

reports/qpx_actual_two_year_three_position/<RUN_ID>/
    actual_two_year_three_position_report.txt
    actual_two_year_three_position_result.json
    actual_two_year_three_position_equity.csv
    actual_two_year_three_position_trades.csv
    entry_filter_diagnostics.csv
    signal_decisions.csv
    allocation_rebalance_log.csv
    actual_two_year_three_position_provenance.json

research_data/qpx_actual_two_year_three_position/<RUN_ID>/
    downloaded source files and DOWNLOAD_MANIFEST.json

Research simulation only. Historical results do not guarantee future
performance.
