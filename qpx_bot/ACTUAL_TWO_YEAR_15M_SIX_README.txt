QPX ACTUAL TWO-YEAR 15-MINUTE SIX-POSITION BACKTEST — CBOE VIX
================================================================

The Massive/Polygon key downloaded the ETF histories but returned HTTP
403 for I:VIX because the account is not entitled to that index ticker.

This revision does not fabricate VIX values and does not use an ETF
proxy. It downloads Cboe's official daily VIX closing history.

For each 15-minute session bar, the VIX gate uses the official close
from the previous completed market session. Monday therefore uses
Friday's official close. Tuesday uses Monday's official close.

This prevents look-ahead. It is real VIX data, but it is deliberately
lagged daily data rather than unavailable intraday VIX data. The report,
manifest, and provenance files disclose that distinction.

DIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV, and QDTE continue to use actual
15-minute Massive/Polygon bars. The runner reuses validated files from
the incomplete download, avoiding repeated rate-limited requests. A
symbol is downloaded again only if its cache is missing or incomplete.

Actual QDTE dividend records still come from the authenticated provider.

The runner aborts instead of using synthetic or interpolated ETF bars,
daily ETF bars in place of intraday bars, a volatility ETF proxy,
fabricated VIX values, fake distributions, or forced trades.

Rankings remain removed. The six-position cap, risk controls, next-bar
execution, ATR exits, contributions, allocation rules, slippage, and tax
reserves remain unchanged. Live brokerage remains disabled.

Research simulation only. Historical results do not guarantee future
performance.


V4 unit-test correction
-----------------------

Production still requires 12,000 covered VIX timestamps. The small
three-bar deterministic unit fixture passes an explicit three-bar test
threshold so it can validate previous-session timing without weakening
the real backtest coverage requirement.
