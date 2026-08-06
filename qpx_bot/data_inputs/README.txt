QPX BOT REAL-DATA INPUT FOLDER
================================

AUTOMATIC WORKFLOW

From the QPX_ALPHA project root, run:

python QPX_FETCH_AND_RUN_REAL_DATA.py --symbol SPY

The command requests an explicit five-year daily window so the
provider cannot silently substitute weekly or monthly bars.

The command downloads:

SWING.csv
    Daily history for the selected swing symbol.

QDTE.csv
    Daily QDTE OHLCV history.

QDTE_DIVIDENDS.csv
    QDTE cash-distribution events.

VIX.csv
    Daily CBOE Volatility Index closing values.

DOWNLOAD_MANIFEST.json
    Provider, symbols, row counts, date range, and SHA-256 hashes.

It then validates the overlapping history and runs the real hybrid
dividend-plus-swing backtest. Reports are written to:

reports/qpx_real_backtest/

MANUAL FALLBACK

The runner also accepts manually exported daily CSV files. Required
names and columns are:

SWING.csv
QDTE.csv
    Date/time, Open, High, Low, Close, Volume

QDTE_DIVIDENDS.csv
    Date, Dividend

VIX.csv
    Date,VIX
    or daily OHLCV with a Close column

Important:
- Use daily bars, not intraday bars.
- Provider data is third-party research data and can be revised.
- Raw downloads and generated reports are intentionally not committed.
- Preserve each DOWNLOAD_MANIFEST.json with its research results.
- This is research simulation software, not live trading or advice.
