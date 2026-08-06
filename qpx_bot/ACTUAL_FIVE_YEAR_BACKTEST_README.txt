QPX ACTUAL FIVE-YEAR BACKTEST
=============================

This runner uses the existing QPX backtest engine. It does not replace
or reimplement strategy execution.

Command
-------

python QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py

The current data-driven selection is used. To research another ticker
explicitly:

python QPX_RUN_ACTUAL_FIVE_YEAR_BACKTEST.py --symbol XLK

No default or fallback ticker is substituted.

Actual-data rules
-----------------

- Data is downloaded from the Yahoo Finance chart endpoint.
- Daily OHLCV and adjusted closes are retained.
- Actual VIX closes are aligned to the swing bars.
- Actual QDTE distributions are downloaded.
- Six years are requested as a boundary buffer.
- The existing swing engine receives exactly five completed market
  years, ending at the latest completed session.
- At least 1,200 actual daily bars are required.
- Stale data is rejected.
- forced_entry_indices is always None.
- The current BotConfig is used without a backtest-only optimization.
- The live paper data folder is not modified.
- Input hashes and the provider manifest are preserved.

Two honest results are produced
-------------------------------

1. ACTUAL FIVE-YEAR SWING STRATEGY

The existing qpx_bot.backtest.run_backtest engine executes the current
swing rules for five completed years using the selected ticker and real
VIX values. A matched adjusted-close buy-and-hold benchmark receives
the same starting cash and monthly contributions.

2. ACTUAL HYBRID AVAILABLE HISTORY

The existing hybrid engine uses real QDTE prices and distributions.
QDTE began trading in 2024, so a genuine five-year hybrid history does
not exist. The hybrid report is limited to actual overlapping history.
No QDTE prices, distributions, or options returns are synthesized
before inception.

Outputs
-------

reports/qpx_actual_five_year/<SYMBOL>/
    actual_five_year_report.txt
    actual_five_year_result.json
    actual_five_year_trades.csv
    actual_five_year_equity.csv
    actual_five_year_benchmark.csv
    actual_five_year_provenance.json
    hybrid_actual_available_history/

Actual source files are stored separately from live paper inputs:

research_data/qpx_actual_five_year/<SYMBOL>/inputs/

This is historical research, not a guarantee of future results. No
brokerage connection or live order path is enabled.
