QPX ACTUAL TWO-YEAR EIGHT-SYMBOL PORTFOLIO BACKTEST
====================================================

Command
-------

python QPX_RUN_ACTUAL_TWO_YEAR_PORTFOLIO.py

Actual swing universe
---------------------

DIA
IWM
QQQ
SPY
XLE
XLF
XLK
XLV

QDTE is separate and remains the income sleeve. ^VIX supplies the
entry-volatility gate.

Point-in-time selection
-----------------------

The existing qpx_bot.symbol_selector.rank_candidates engine ranks all
eight candidates at the beginning of each month. Every decision uses
only rows dated strictly before that decision date.

The rank weights are loaded from qpx_bot/swing_universe.json:

- 63-day adjusted return: 25%
- 126-day adjusted return: 30%
- 200-day trend distance: 15%
- median dollar liquidity: 10%
- volatility penalty: 10%
- drawdown penalty: 10%

There are no symbol-specific bonuses or preferred fallback symbols.

Position lock
-------------

The monthly winner becomes the active swing ticker only while the swing
account is flat and no entry is pending. An open position or staged
next-session entry locks its ticker. Once flat, the active ticker moves
to the current month's winner.

Strategy and execution
----------------------

The runner calls the existing QPX components:

- qpx_bot.strategy.evaluate_entry
- qpx_bot.strategy.evaluate_exit
- qpx_bot.risk.calculate_position_size
- qpx_bot.portfolio.Portfolio
- qpx_bot.allocation.rebalance_income_allocation

Signals are generated at the daily close and staged for the next common
market session. The next open is rejected when its absolute gap exceeds
the configured 1.5 ATR limit. Slippage, the 2.5 ATR stop, 5.0 ATR target,
3.0 ATR trailing activation, quarter-Kelly sizing, VIX 28 gate, 6%
active-risk cap, and 37% realized-gain reserve remain active.

Capital and allocation
----------------------

Initial QDTE seed       : $1,300
Initial swing liquidity : $1,500
Initial total capital   : $2,800
Monthly contribution    : $2,000

The portfolio rebalances monthly toward 65% QDTE / 35% swing during
years 1 and 2 and 40% QDTE / 60% swing from year 3 onward. Open swing
positions are not sold merely to rebalance.

Actual-data controls
--------------------

The run downloads true daily data for the eight ETFs, QDTE, and ^VIX
from the Yahoo Finance chart endpoint. Four years are requested to
provide the 252-bar ranking warmup. The reported performance window is
the latest two completed years of common sessions.

The run rejects stale or downsampled data, requires at least 480 common
daily sessions, hashes every input file, logs every monthly ranking and
allocation event, and never uses forced entries or fabricated data.

Outputs
-------

reports/qpx_actual_two_year_eight_symbol/<RUN_ID>/
    actual_two_year_report.txt
    actual_two_year_result.json
    actual_two_year_equity.csv
    actual_two_year_trades.csv
    monthly_selection_log.csv
    allocation_rebalance_log.csv
    actual_two_year_provenance.json

research_data/qpx_actual_two_year_eight_symbol/<RUN_ID>/
    Actual downloaded symbol files and DOWNLOAD_MANIFEST.json

Research simulation only. No brokerage connection or live order path.
