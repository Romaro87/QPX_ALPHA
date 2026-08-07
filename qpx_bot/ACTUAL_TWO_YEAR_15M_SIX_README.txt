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


V5 split execution workflow
---------------------------

Installation and Git push are now independent from all slow market-data
requests.

The installer performs only these network-independent code actions:

1. install the revised source;
2. run the focused and complete test suites;
3. commit and push the source;
4. run the small official Cboe VIX-only preflight;
5. stop.

The VIX preflight runs before any Massive/Polygon aggregate request and
writes a stable local cache:

research_data/qpx_actual_two_year_15m_six/shared/CBOE_VIX_DAILY.csv

The long backtest is launched later with:

python QPX_RUN_ACTUAL_TWO_YEAR_15M_SIX.py

That run validates or reuses the VIX cache first. Only after VIX passes
does it request or reuse ETF and QDTE data.

Market-data CSV files remain local and are excluded from Git. Reports
record their paths, provenance, and SHA-256 hashes.


V6 resumable aggregate checkpoints
----------------------------------

The long provider download now persists each completed 90-day symbol
chunk immediately in:

research_data/qpx_actual_two_year_15m_six/shared/aggregate_15m/

Every stable symbol CSV has a companion manifest listing completed
chunks. If Termux is interrupted or a later input fails, the next run
skips those completed chunks.

Before any new provider request, QPX recursively scans all earlier
timestamped research directories. A complete valid symbol history is
imported into the stable cache and marked complete.

The installer runs a no-network cache audit and then the separate Cboe
VIX preflight. It does not launch the long Massive/Polygon backtest.


V7 focused-test correction
--------------------------

The V6 focused test searched for one display sentence that Python builds
from two adjacent source strings. The runtime message was valid, but the
combined sentence was not a contiguous source substring.

V7 removes that brittle presentation-text check and verifies the actual
checkpoint structures instead:

- _mark_all_chunks_complete
- LOCAL_VALIDATED_MASSIVE_POLYGON_CACHE
- completed chunk manifests
- stable aggregate cache import/resume paths

No strategy, provider, VIX, coverage, risk, or execution rule changed.
