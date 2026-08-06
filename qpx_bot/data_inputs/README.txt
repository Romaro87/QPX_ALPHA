QPX BOT REAL-DATA DROP FOLDER
================================

Place these four daily CSV files in this folder:

1. SWING.csv
   The swing-trading symbol exported from TradingView.
   Required columns, case-insensitive:
   Date/time, Open, High, Low, Close, Volume

2. QDTE.csv
   Daily QDTE OHLCV history.
   Required columns:
   Date/time, Open, High, Low, Close, Volume

3. QDTE_DIVIDENDS.csv
   Actual QDTE cash distributions.
   Required columns:
   Date, Dividend

4. VIX.csv
   Daily VIX history.
   Accepted formats:
   Date,VIX
   or a TradingView OHLCV export, using its Close column.

Run from the QPX_ALPHA project root:

python QPX_RUN_REAL_BACKTEST.py --check-only

After all four files show FOUND:

python QPX_RUN_REAL_BACKTEST.py --symbol SPY

Reports are written to:

reports/qpx_real_backtest/

Important:
- Use daily bars, not intraday bars.
- Do not invent dividends or extend QDTE before its actual history.
- The runner trims all sources to their real overlapping date range.
- Input file SHA-256 hashes are recorded for reproducibility.
