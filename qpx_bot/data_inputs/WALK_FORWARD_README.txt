QPX WALK-FORWARD VALIDATION
===========================

Run from the QPX_ALPHA project root:

python QPX_RUN_WALK_FORWARD.py --symbol SPY

Default validation design:

- 252 daily bars for parameter selection
- 63 unseen daily bars for out-of-sample testing
- 63-bar step size, producing non-overlapping test windows
- A declared three-choice VIX-entry grid
- Adjusted-close SPY total-return buy-and-hold benchmark
- Identical starting cash and monthly contribution schedule
- Contribution-adjusted time-weighted returns
- CAGR, volatility, Sharpe, Sortino, drawdown, and exposure
- Per-window and aggregate out-of-sample reports

Outputs:

reports/qpx_walk_forward/walk_forward_report.txt
reports/qpx_walk_forward/walk_forward_windows.csv
reports/qpx_walk_forward/walk_forward_result.json
reports/qpx_walk_forward/walk_forward_manifest.json

Raw downloaded data and generated reports are excluded from Git.

Walk-forward results are historical research only. They are not live
performance, a guarantee, or financial advice.
