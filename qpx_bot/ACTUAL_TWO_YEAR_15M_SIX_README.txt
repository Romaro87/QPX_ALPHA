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


V12 swing-only fixed-window control
-----------------------------------

The swing-only control uses the same fixed 2024-08-06 through 2026-07-28
window, the same 200-common-bar initialization, the same eight swing
symbols, the same common timestamp intersection, the same previous-session
official Cboe VIX observation policy, the same entry/exit rules, the same
six-slot policy, the same risk sizing, and the same $2,800 initial total
capital plus $2,000 monthly contributions.

Control-specific changes:
- QDTE receives no capital.
- QDTE distributions are disabled.
- All initial capital and monthly contributions enter swing cash.
- QDTE 15-minute bars remain in the common-timestamp intersection solely
  so the control uses the same timestamp sample as the hybrid study.
- Allocation rebalancing is disabled.
- Tax-reserve behavior on profitable swing exits remains active.
- No market data is downloaded and no provider key is requested.


V13 relaxed swing-frequency research control
--------------------------------------------

This is a research-only swing-only profile. It does not change the
live/paper default strategy.

The prior swing-only control showed only one opening-gap rejection and
one risk-sizing rejection. Therefore increasing risk-per-trade or the
6% portfolio-risk ceiling would primarily increase position size, not
trade count.

The relaxed-frequency profile changes only entry-frequency gates:
- 15-minute average-volume floor: 75,000 shares. The original 2,000,000
  field is defined as daily volume but was being compared directly to
  15-minute candle volume. 2,000,000 / 26 is approximately 76,923.
- breakout-volume multiplier: 1.20x -> 1.05x.
- breakout lookback: 20 -> 10 completed 15-minute bars.
- maximum VIX: 28 -> 32.
- RSI overbought ceiling: 70 -> 75.
- momentum: exact EMA/RSI/RMI crosses still count, plus an established
  bullish EMA state with RSI or RMI >= 52.
- opening-gap rejection: 1.5 ATR -> 2.0 ATR.

Unchanged:
- 1% base risk per trade.
- 6% maximum active portfolio risk.
- 2.5 ATR stop.
- 5 ATR target.
- 3 ATR trailing activation.
- 0.075% slippage.
- six concurrent slots.
- no rankings.
- no synthetic, interpolated, placeholder, or forced entries.
- live brokerage remains disabled.


V14 relaxed-frequency no-Kelly research control
-----------------------------------------------

V13 successfully increased qualifying signal bars from the sparse
baseline to a much larger opportunity set, but the fixed-window run
stopped at 20 filled trades while recording 1,565 risk-sizing
rejections.

The risk engine enables Kelly sizing after 20 completed trades. A
non-positive Kelly result becomes a zero risk fraction and blocks the
trade.

V14 keeps the V13 relaxed-frequency entry profile but disables adaptive
Kelly only in this fixed local swing-only research control.

Unchanged protections:
- 1% base risk per trade.
- 6% aggregate active-risk cap.
- 2.5 ATR stop.
- 5 ATR target.
- 3 ATR trailing activation.
- 0.075% slippage.
- six-position maximum.
- no rankings.
- no synthetic, interpolated, placeholder, or forced entries.
- live brokerage disabled.

V14 also records risk-rejection reasons explicitly so subsequent runs
show whether any remaining rejections come from cash, active-risk
capacity, or another sizing rule.


V15 net-realized tax-reserve research control
---------------------------------------------

V14 produced 486 swing trades with the relaxed-frequency entry profile,
fixed 1% risk per trade, 6% aggregate active-risk cap, and Kelly
disabled. It also accumulated a large tax-reserve balance because the
shared portfolio logic reserves 37% of every profitable exit
independently.

V15 is a research-only cash-management control. It keeps the V14
strategy, entries, exits, position risk, aggregate risk, slippage,
symbols, dates, and real-data inputs unchanged.

The only cash-reserve change is:
- after each closed swing trade, research tax reserve is reconciled to
  37% of positive cumulative net realized swing P&L;
- if later realized losses reduce that cumulative net gain, the excess
  reserve is released back to investable swing cash;
- if cumulative net realized P&L is zero or negative, the research
  reserve is zero.

This is not complete tax accounting and is not tax advice. It is an
explicit research control for measuring whether the prior per-winning-
trade reserve was unnecessarily constraining investable cash.

V15 also decomposes the risk engine's combined "risk budget or cash is
too small for one share" rejection into:
- CASH_BELOW_ONE_SHARE;
- BASE_RISK_BUDGET_BELOW_ONE_SHARE;
- ACTIVE_RISK_CAP_BELOW_ONE_SHARE;
- combined cash/risk causes when both apply.

Live/paper defaults, qpx_bot/config.py, qpx_bot/risk.py, and
qpx_bot/portfolio.py are not modified by this workflow.


V16 16% position-notional research control
------------------------------------------

V15 showed that every remaining one-share sizing rejection was caused by
insufficient investable cash, not the 1% per-trade risk budget or the
6% aggregate active-risk ceiling.

V16 keeps the V15 entry, exit, risk, tax-reserve, slippage, symbol,
date, and actual-data behavior unchanged. It adds a research-only
per-position notional target of 16% of account equity after normal
risk sizing.

Whole-share practicality:
- if 16% of account equity is less than the price of one share, V16
  permits one share rather than automatically excluding a high-priced
  ETF;
- this exception is counted separately in the report as a one-share
  floor use;
- therefore the 16% value is a target cap with a one-share minimum,
  not an absolute leverage guarantee for a small whole-share account.

The objective is to prevent one low-ATR signal from consuming most
available cash while preserving the original 1% trade-risk and 6%
aggregate active-risk limits.

Live/paper defaults, qpx_bot/config.py, qpx_bot/risk.py, and
qpx_bot/portfolio.py are not modified by this workflow.


V17 V16 exit / expectancy diagnostic study
-------------------------------------------

V17 is diagnostic-only. It does not rerun the strategy and does not
change entry, exit, sizing, tax-reserve, notional-cap, allocation, or
market-data rules.

It locates the latest completed V16 16%-notional run and reconstructs
each closed trade from the same validated local 15-minute caches. It
verifies the reconstructed common-bar and session counts against the
saved V16 result before producing diagnostics.

Per-trade diagnostics include:
- exit reason;
- conservative maximum favorable excursion (MFE) in initial-R units;
- conservative maximum adverse excursion (MAE) in initial-R units;
- whether +1R, +2R, or +3R was reached before exit;
- whether a losing trade had been sell-side-slippage-adjusted profitable
  on a completed bar before its exit bar;
- holding bars and holding sessions;
- entry VIX regime;
- reconstructed relaxed-entry trigger(s).

The exit-bar excursion method is intentionally conservative: full OHLC
is used only for completed bars before the exit bar. On stop/target exit
bars, the known trigger/open is used instead of the full exit-bar high
or low, avoiding post-exit lookahead.

Summaries are produced overall and by exit reason, symbol, VIX regime,
individual entry trigger, and trigger combination. Trigger counts can
overlap when one entry has multiple triggers.

V17 writes text, JSON, and per-trade CSV diagnostic artifacts into the
source V16 report directory. It makes no provider request and needs no
API key.

These are in-sample diagnostics of an already-examined historical
window. They are intended to formulate a small number of explicit exit
hypotheses for later frozen validation, not to claim independent
performance validation.


V18 fixed-window exit-hypothesis research matrix
------------------------------------------------

V18 freezes the V16 non-exit rules and tests only five explicit exit
profiles on the same fixed local 15-minute window:

1. BASELINE — the unchanged V16 exit behavior.
2. BE_1R — after a completed bar reaches +1.00 initial R, raise the
   next-bar protective stop to sell-slippage-adjusted breakeven.
3. BE_0P75R — same behavior after +0.75 initial R.
4. NO_OVERNIGHT — run normal intrabar stop/target logic first, then
   flatten any remaining position at the final common regular-session
   15-minute bar close; signals from that close are not staged overnight.
5. BE_1R_NO_OVERNIGHT — combine profiles 2 and 4.

Frozen across all five profiles:
- relaxed-frequency V16 entries;
- 16% account-equity position-notional target with one-share floor;
- 1% trade-risk ceiling;
- 6% aggregate active-risk ceiling;
- Kelly disabled;
- net-realized tax-reserve research model;
- 2.5 ATR initial stop;
- 5 ATR target;
- existing trailing-stop calculation;
- 0.075% slippage;
- six concurrent slots;
- no rankings;
- same eight-ETF universe;
- same validated local real 15-minute caches;
- same previous-session official Cboe VIX daily-close series;
- no forced, placeholder, synthetic, or interpolated entries/data.

The break-even stop is never applied retroactively inside the bar that
first reaches its activation level. The new stop becomes eligible only
on the next bar. Its market stop level is adjusted so that, after the
configured sell-side slippage, the modeled fill is approximately the
original entry fill.

The no-overnight profiles preserve ordinary stop/target priority during
the final bar. Only positions still open afterward are closed at that
bar's close, with normal sell-side slippage.

Before testing any alternative exit, V18 reruns BASELINE and compares
it to the latest completed V16 result. The matrix aborts if the baseline
does not reproduce V16 on key trade counts and performance metrics.

V18 writes a text, JSON, and CSV matrix summary plus the full artifacts
for every profile. It does not automatically promote any profile to
paper or live defaults. This remains in-sample research on an already
examined window; any apparently improved profile must be frozen and
validated separately.
