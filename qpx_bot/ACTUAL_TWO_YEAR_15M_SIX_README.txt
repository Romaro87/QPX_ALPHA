QPX ACTUAL TWO-YEAR 15-MINUTE SIX-POSITION BACKTEST
====================================================

Purpose
-------

This research runner replays the active QPX 15-minute strategy over two
completed years using actual provider bars.

It does not alter the active paper account or its scheduled runtime.

Why a second provider is required
---------------------------------

The active Yahoo paper feed requests only 60 days of 15-minute history.
That is sufficient for live paper scanning but cannot support a genuine
two-year 15-minute replay.

The backtest therefore uses the Massive/Polygon aggregate API:

- nine stock/ETF histories:
  DIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV, QDTE;
- the actual VIX index history using I:VIX;
- actual QDTE dividend records.

A Massive or Polygon API key with access to the requested stock and
index history is required. The installer asks for the key using hidden
terminal input. It does not save, print, commit, or push the key.

No fallback policy
------------------

The runner aborts instead of substituting:

- daily bars;
- synthetic bars;
- interpolated bars;
- placeholder VIX values;
- placeholder QDTE distributions;
- forced entries.

Strategy reproduced
-------------------

- all eight swing ETFs checked on every common completed 15-minute bar;
- rankings removed;
- up to six concurrent positions;
- next-common-bar opening execution;
- 1.5 ATR opening-gap rejection;
- quarter-Kelly sizing;
- 1% base risk per position;
- 6% aggregate active-risk cap;
- 2.5 ATR stop;
- 5 ATR target;
- trailing activation after 3 ATR;
- VIX entry ceiling of 28;
- existing trend, momentum, breakout, and volume filters;
- $1,300 QDTE seed;
- $1,500 swing liquidity;
- $2,000 monthly contributions;
- 65/35 allocation through the first two complete years;
- exact-date transition to 40/60;
- slippage and realized-gain tax reserves.

Coverage controls
-----------------

The downloader requests 75 calendar days of pre-test warmup and the
latest two completed years. It filters to regular-session bars and uses
only timestamps present in every required history.

The run requires:

- at least 12,000 common 15-minute test bars;
- at least 480 market sessions;
- at least 200 pre-test bars for every required series;
- a current end date;
- actual QDTE dividend events.

Outputs
-------

reports/qpx_actual_two_year_15m_six/<RUN_ID>/
    actual_two_year_15m_report.txt
    actual_two_year_15m_result.json
    actual_two_year_15m_equity.csv
    actual_two_year_15m_trades.csv
    actual_two_year_15m_signals.csv
    actual_two_year_15m_allocations.csv
    actual_two_year_15m_diagnostics.json
    actual_two_year_15m_provenance.json

research_data/qpx_actual_two_year_15m_six/<RUN_ID>/
    actual provider CSV files
    QDTE_DIVIDENDS.csv
    DOWNLOAD_MANIFEST.json

Research simulation only. Live brokerage remains disabled.
