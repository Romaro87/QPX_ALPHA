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


V8 stale-tail checkpoint repair
-------------------------------

A completed-chunk manifest must now be supported by actual bars that
reach the end of that requested chunk within the unchanged freshness
tolerance.

Older manifests could mark the final 90-day request complete even when
the provider returned a stale tail. That caused every later run to skip
the exact request needed to refresh the test endpoint.

V8 validates declared chunks against the local CSV, removes stale or
incomplete declarations, and saves a chunk as complete only after its
actual bar coverage reaches the chunk endpoint.

QPX_REPAIR_15M_CHECKPOINTS.py performs this manifest repair and prints
per-symbol endpoint diagnostics without making a network request. The
next backtest downloads only missing or invalidated chunks.


V9 focused-test correction
--------------------------

V8 used two exact English sentence fragments in its static source test.
The implementation builds those messages from adjacent source strings,
so the runtime output was valid while the contiguous source assertions
were not.

V9 verifies the stable checkpoint structures instead:

- invalidated_chunks
- last_attempted_chunk_complete
- chunk_complete
- _validated_completed_chunks

The stale-tail repair behavior and every strategy, coverage, risk,
provider, and no-placeholder rule remain unchanged.


V10 fixed local near-two-year backtest
--------------------------------------

This revision adds a separate, local-only historical validation window:

- fixed start: 2024-08-06;
- fixed end: 2026-07-28;
- calendar span: 721 days;
- real 15-minute DIA, IWM, QQQ, SPY, XLE, XLF, XLK, XLV, and QDTE
  cache files already present on the device;
- official Cboe daily VIX closes using the previous completed session;
- actual cached QDTE distribution events;
- first 200 common 15-minute bars reserved for indicator
  initialization, with swing entries disabled;
- minimum 11,500 common bars and 480 sessions;
- no network requests;
- no API key;
- no synthetic, interpolated, placeholder, or forced data.

This is deliberately labeled a fixed near-two-year study, not an exact
two-year study. It ends nine calendar days before 2026-08-06. Therefore,
the exact second-anniversary 40/60 allocation phase is not reached
inside this window; the 65/35 phase remains active through the end.

The original rolling provider-backed runner remains available. The
fixed local runner is:

python QPX_RUN_FIXED_2024_08_06_TO_2026_07_28.py


V11 fixed-window observed-session threshold
-------------------------------------------

The fixed 2024-08-06 through 2026-07-28 local study keeps the existing
11,500 common 15-minute bar requirement and now uses a fixed-window-only
minimum of 450 common market sessions. The rolling exact two-year study
still requires 480 sessions.

The fixed study also reports the expected exchange sessions calculated
from the QPX market calendar and the observed common-session coverage
percentage. Missing bars are not filled, interpolated, synthesized, or
replaced.
