# QPX_ALPHA RECOVERY & DECISION LEDGER

**Status:** Active authoritative recovery ledger  
**Repository:** Romaro87/QPX_ALPHA  
**Primary local workspace:** `/storage/emulated/0/QPX_ALPHA`  
**Created from:** recovered QPX conversations, user confirmations, surviving Git history, and surviving artifacts  
**Critical rule:** **DO NOT REINTERPRET. DO NOT INVENT MISSING HISTORY.**

---

## 0. SOURCE / STATUS RULES

Every recovered item should be treated as one of these:

- **USER_CONFIRMED** — user explicitly reconfirmed the item in the current recovery work.
- **USER_APPROVED** — historical recovery shows the user accepted it.
- **USER_REQUIREMENT** — user directly stated it as a desired capability/constraint.
- **VERIFIED_REPO** — survives in Git history/code/specifications.
- **VERIFIED_ARTIFACT** — survives in a generated file/artifact.
- **ASSISTANT_PROPOSED** — proposal exists, but user approval has not been proven.
- **DISCUSSED** — conversation existed, but final approval is not proven.
- **FUTURE_DECISION** — intentionally deferred.
- **UNKNOWN / UNRECOVERED** — insufficient evidence. Never fill by inference.

If two sources conflict, preserve both with dates and resolve only with explicit user confirmation.

---

# 1. CORE QPX IDENTITY

**STATUS: USER_APPROVED + VERIFIED_REPO**

QPX_ALPHA is not merely one trading bot. It is intended to become a modular quantitative investment platform / investment operating system that can host multiple strategies, portfolios, brokers, data providers, research workflows, risk profiles, and interfaces.

Core principles recovered or committed include:

- platform before individual strategy
- architecture before implementation
- modularity
- explainability
- reproducibility/determinism
- configuration over hardcoding
- risk separation
- portfolio/accounting separation
- replaceable broker/data/AI interfaces
- testing and progressive validation
- auditability
- no orphan modules
- public product must remain strategy-neutral
- private QPX must remain private and isolated

---

# 2. RESEARCH BASELINE / CURRENT FINALIST STATE

**STATUS: VERIFIED_REPO / RECOVERED_CONTEXT**

Frozen research baseline used for the current finalist comparison:

- starting capital: **$1,300**
- starting QDTE: **$1,300**
- swing cash: **$0**
- external contributions: **$0**
- Thursday-only weekly rebalance
- frozen identical-clock comparison
- 600 sessions
- 14,527 common 15-minute bars
- historical window: 2024-03-07 through 2026-08-07
- no forward filling
- no synthetic timestamps
- no timestamp substitution

Frozen finalists:

- TSLL
- TSLT
- TPET
- SLS
- MU
- ASTS
- JMIA
- GME
- SOFI
- SEDG

Controls:

- QDTE
- XLE
- AMD
- TSLA

Important: a raw full-period winner is **not** automatically a production Champion. Persistence, Benchmark Gate, Shadow, and later qualification remain required.

---

# 3. PERSONALIZED UNIVERSE DISCOVERY

**STATUS: USER_APPROVED**

There should not be one universal Top 100 for every end user.

Intended pipeline:

**user strategy/profile/mandate → eligibility filtering → historical simulation → personalized ranking → Top 100 → identical-data validation → frozen personal research universe**

User-facing performance requirement:

- configuration reranking should feel near-instant where cached data allows
- normal strategy comparisons should complete quickly
- Top-100 accelerator tests should generally be fast enough for interactive research
- a full personalized discovery should ultimately target **well under one minute**, not many minutes or days, once the production data/cache architecture exists

This speed requirement is a product capability, not merely a developer convenience.

---

# 4. ACCELERATOR ARCHITECTURE

## 4.1 Research / Compute Accelerators

**STATUS: VERIFIED_REPO**

Implemented or surviving research acceleration work includes:

- Alpaca universe eligibility prefilter
- safe intraday-density prefilter/sweep acceleration
- resumable/checkpointed universe processing
- frozen Top-100 dataset builder
- common-clock finalist testing
- persistence validation framework
- reusable validated research data

These accelerators must not improve apparent results by changing economics, inventing bars, or substituting timestamps.

## 4.2 Strategy / Performance Accelerators

**STATUS: USER_APPROVED**

Recovered accelerator family includes:

- dynamic sizing
- Top-N rotation
- pyramiding
- regime-dependent allocation
- profit recycling
- Dividend Opportunity Engine
- options
- shorts
- leverage
- leveraged ETFs

Recovered priority combination:

**Top 3 approved swing tickers + dynamic sizing + pyramiding + QDTE sleeve**

Accelerators are to be tested individually and in controlled combinations before promotion.

Important configuration rule:

- accelerator/strategy values should be configuration-driven and hot-swappable where safe
- avoid hard-coded operational values
- configuration revisions must be validated
- open positions retain the rules/configuration that governed their entry unless an explicitly approved migration mechanism says otherwise

---

# 5. CHAMPION / CHALLENGER / SHADOW ARCHITECTURE

## 5.1 Champion

**STATUS: USER_APPROVED**

Champion is the currently approved production strategy/configuration.

Champion should be stable, auditable, and protected from silent adaptive mutation.

No research result replaces Champion merely because of one favorable backtest or short performance streak.

## 5.2 Approved Challengers

**STATUS: USER_APPROVED**

Approved Challengers test alternatives that have already passed enough research controls to deserve formal comparison.

They use comparable decision-time information and cannot self-promote into production.

## 5.3 Permanent Shadow

**STATUS: USER_APPROVED**

A permanent Shadow environment operates beside Champion/production.

Required concepts:

- same relevant market data and timestamps available at decision time
- simulated decisions alongside Champion/live
- divergence logging
- compare what Champion did versus what Shadow would have done
- explain what was the same
- explain what was different
- explain **why** each system made its decision
- compare P&L
- compare drawdown
- compare avoided losses
- compare missed gains
- compare allocation and symbol differences
- compare risk-adjusted attractiveness
- preserve what was knowable at decision time separately from hindsight

Shadow evidence feeds research. Shadow cannot silently alter Champion.

---

# 6. TWO BOUNDARY SHADOWS

**STATUS: USER_CONFIRMED — 2026-08-11**

The earlier single Boundary/Exploratory Shadow concept should be split into **two paper-only research layers**.

Names below are **working identifiers only** and may be changed later.

## 6.1 BOUNDARY_PARAMETER_SHADOW
### Working description: Looser-Envelope Boundary Shadow

Purpose:

Explore the **same overall strategy family** while deliberately operating outside the normal approved parameter/risk envelope.

It may explore dimensions such as:

- substantially looser risk controls
- risk per trade outside normal approved range
- different Top-N breadth
- QDTE allocation potentially far outside normal production range
- higher leverage
- additional pyramids
- wider/different stops
- alternative targets/trailing behavior
- aggressive position sizing
- options overlays
- short overlays
- other broader-but-sensible parameter combinations

This is **paper/simulation only**.

The examples above are exploration dimensions, **not fixed permanent maximum/minimum limits**.

## 6.2 BOUNDARY_STRATEGY_SHADOW
### Working description: Strategy-Changing Boundary Shadow

Purpose:

Explore ideas that can **change the strategy itself**, rather than only loosening parameters inside the existing strategy.

This may include materially different:

- entry logic
- exit logic
- market selection logic
- portfolio construction
- allocation method
- signal combinations
- strategy structure
- instrument/module usage
- other genuinely different research hypotheses

This is **paper/simulation only**.

Current autonomy boundary:

- strategy-changing research is allowed in the research/paper layer
- it has **no authority over live capital**
- it cannot silently rewrite Champion
- it cannot self-promote
- automation/AI authority can be revisited later if evidence proves it is worth having

## 6.3 Reporting Requirements for BOTH Boundary Shadows

**STATUS: USER_CONFIRMED**

Both Boundary Shadows require strong reporting.

Every meaningful comparison should report:

- what Champion / baseline did
- what Boundary Shadow did
- what was the same
- what was different
- why Champion acted
- why Boundary Shadow acted
- what information each had at decision time
- return difference
- drawdown difference
- risk/exposure difference
- trade frequency difference
- symbol/allocation difference
- avoided losses
- missed gains
- resulting equity-path differences
- whether the improvement persisted or depended on a narrow regime/window

Boundary research freedom **does not permit dishonest research**.

It must not use:

- future information
- fabricated prices
- synthetic favorable bars
- timestamp substitution that changes opportunity
- hidden accounting changes
- different capital/contribution assumptions without explicitly reporting them

## 6.4 Promotion

A Boundary Shadow discovery does not become live because it performed well.

Expected path remains governed:

**research → historical validation → Benchmark Gate → walk-forward/out-of-sample → Shadow/Challenger validation → promotion review → approved paper → later limited live candidate → production Champion**

Exact gate ordering may continue to be refined, but **no direct Boundary-to-live promotion is allowed**.

---

# 7. SHADOW ADAPTIVE DECISION QUALITY

**STATUS: USER_APPROVED**

Shadow should not simply choose the lowest-drawdown alternative.

It should evaluate **return-versus-drawdown attractiveness** and enough supporting evidence to prevent noisy switching.

Relevant evidence discussed includes:

- expectancy
- drawdown
- drawdown recovery
- volatility/regime/VIX context
- signal quality
- correlation
- persistence
- streak significance
- profit factor
- other robustness measures

Hysteresis / minimum-evidence rules are desirable so the system does not constantly switch strategies or symbols on noise.

**Exact scoring formula:** deliberately open for now and may be tightened later.

---

# 8. BENCHMARK GATE

**STATUS: USER_APPROVED / PERMANENT**

Complexity must prove that it adds value.

Mandatory comparison targets include, where appropriate:

- SPY
- QQQ
- an appropriate balanced benchmark
- QDTE-only
- simpler QPX variants
- Champion / current approved baseline

Comparisons should use comparable:

- starting capital
- contribution schedule
- dates
- available information
- accounting assumptions

Metrics considered appropriate include:

- ending value
- return / CAGR
- maximum drawdown
- return-to-drawdown efficiency
- volatility
- profit factor / expectancy
- taxes / turnover where applicable
- capital utilization
- drawdown recovery
- persistence/robustness

**Exact weights and pass/fail thresholds are intentionally not fixed yet.**
They may be tightened later.

---

# 9. DIVIDEND OPPORTUNITY ENGINE

**STATUS: USER_APPROVED ACCELERATOR**

Research area includes:

- dividend capture
- post-ex-dividend recovery
- pre-ex-dividend momentum
- quality/income rotation
- related dividend opportunities

It must measure incremental benefit versus simpler alternatives such as normal reinvestment.

---

# 10. MANDATE-DRIVEN QPX

**STATUS: USER_CONFIRMED**

QPX should ultimately ask what the portfolio is trying to accomplish **before forcing one strategy choice**.

Official preset mandates:

## 10.1 Risk It for the Biscuit

Goal:

- maximize short-term growth
- substantial risk may be acceptable

## 10.2 Guard the Nest

Goal:

- maximize growth while minimizing drawdown potential

## 10.3 Retire Before You Expire

Goal:

- determine the required sustainable living-income target
- pursue that income target efficiently
- qualified-dividend/tax-efficiency considerations may matter where appropriate
- once the required sustainable income floor is reached, protect/lock that floor according to the mandate

## 10.4 Presets + Customization

**STATUS: USER_CONFIRMED — 2026-08-11**

Mandate values should be:

- usable immediately through sensible preset defaults
- ultimately changeable/configurable by the user

The presets should make QPX usable without requiring the operator to design every parameter from scratch.

---

# 11. ONE-BUTTON COMPARATIVE BACKTEST

**STATUS: USER_CONFIRMED — 2026-08-11**

Desired user-facing capability:

A user should be able to provide starting capital, press a button, and have QPX run several appropriate preset strategies/mandates against that capital.

The result should provide:

- comparative backtest performance
- ending capital
- drawdown
- risk-adjusted comparisons
- income where relevant
- major trade/allocation differences
- what each strategy did
- **why** it did it
- meaningful differences among the strategies
- explanatory recommendation/context without hiding assumptions

The exact list of strategies run by default can be refined later.

This feature should support easy experimentation without forcing the user to manually construct every research configuration.

---

# 12. CONTRIBUTION / CAPITAL SCENARIOS

**STATUS: USER_APPROVED / HISTORICAL CONTEXT**

Research scenarios have included:

- no-contribution frozen baseline
- $1,000/month contribution scenario
- $400/week contribution discussion

Accounting must separate:

- external user deposits
- strategy/trading profit
- distributions/dividends
- realized/unrealized results
- ending equity

Deposits must not be misreported as strategy profit.

---

# 13. MONTH-UNATTENDED GATE

**STATUS: USER_CONFIRMED / APPROVED**

High-level requirement:

QPX should eventually be trustworthy enough that the user can start it, leave it unattended, and **not check it for at least one month**.

Qualification package is approved.

Required capabilities/tests include:

- 30+ consecutive days of persistent paper operation
- forced restart/reboot testing
- internet-loss handling
- stale-feed detection/handling
- broker rejection handling
- duplicate-order prevention
- corrupted-state detection and recovery
- Champion + Shadow operation during unattended period
- broker/account/state reconciliation
- no unexplained positions or orders
- hard exposure/risk/drawdown controls
- watchdog/heartbeat monitoring
- automatic restart where safe
- fail closed when safety cannot be established
- durable audit logs
- emergency kill switch
- quiet normal operation
- alerts for meaningful faults such as halts, state mismatches, risk locks, or reconciliation failures

Post-period reporting should explain:

- what Champion did
- why it did it
- what Shadow alternatives did
- why they differed
- how those alternatives performed
- decision-time information versus hindsight

This Gate tests trustworthy autonomy, not merely process uptime.

---

# 14. AUTOPILOT / AI AUTHORITY

**STATUS: USER_CONFIRMED CURRENT BOUNDARY**

Current intended separation:

### Autopilot
Automates operation of **approved** strategies and workflows, including appropriate:

- scheduling
- signal generation
- paper operation
- reports
- alerts
- approved operational automation

### Adaptive Intelligence / Research AI
May:

- analyze
- explain
- diagnose loss patterns
- analyze parameter sensitivity
- attribute regime/context
- suggest alternatives
- create research configurations
- help produce Challengers
- support Boundary research

### Governance
Promotes changes after evidence.

Current rule:

**AI does not silently rewrite live strategy logic and does not self-promote into live production.**

Future possibility:

An explicit **automate switch / expanded AI autonomy** may be discussed later **if QPX proves the capability is worth having**.

That future switch is **not currently approved for live autonomous strategy rewriting**.

---

# 15. GUI / CONTROL CENTER

**STATUS: USER_APPROVED + VERIFIED_ARTIFACT**

GUI is a desired permanent platform capability, though implementation has at times been deferred to prioritize core correctness/research.

Surviving Weekend GUI work includes:

- local QPX Control Center
- paper-bot status
- total equity
- open/pending positions
- start/stop GUI-managed paper bot
- run one cycle
- self-test
- controlled symbol editing
- paper account information
- tax reserve
- realized P&L
- distributions
- logs
- Git status
- live brokerage deliberately disabled in that artifact

Longer-term GUI concepts include areas such as:

- Dashboard
- Markets
- Scanner
- Signals
- Open Trades
- Portfolio
- Dividend Engine
- Backtesting
- Paper Trading
- Live Trading
- Performance
- AI Assistant
- Settings

Names/layout remain changeable as needed for clarity.

---

# 16. HOT CONFIGURATION

**STATUS: USER_APPROVED / PARTLY IMPLEMENTED**

Important operational/strategy settings should ultimately be editable without source-code rewrites.

Recovered areas include configuration for:

- allocation
- risk
- VIX/regime controls
- breakout conditions
- exit behavior
- position behavior
- contributions
- symbols/universes
- accelerator values
- related strategy parameters

Invalid or unsafe configuration should fail safely.

Open positions should preserve entry-time policy unless a controlled migration rule exists.

---

# 17. PLATFORM DEVELOPMENT / SELF-BUILDING CAPABILITIES

**STATUS: VERIFIED_REPO**

QPX already contains or historically committed infrastructure for:

- Event Bus
- service/module registries
- dashboard
- Doctor
- Scaffold
- Builder Engine
- Generator Engine
- Template Engine
- Command Router
- Bootstrap Engine
- testing/health/configuration infrastructure

These components support QPX as a governed extensible platform rather than a collection of unrelated scripts.

---

# 18. HOME-LAB / DISTRIBUTED COMPUTE

## 18.1 Known Hardware

**STATUS: USER_CONFIRMED / RECOVERED**

Known machines discussed include:

- Ryzen 9 5900XT, 32 GB DDR4-4000, RTX 5080 main gaming rig
- Ryzen 5 5600X, 32 GB DDR4-3200 daughter main rig
- Ryzen 7 7840U, 32 GB DDR5-5600
- Ethereal: daughter portable rig, Ryzen 7 5800X3D, 16 GB DDR4-3200; may contribute compute when present; no authoritative persistent QPX state should live on it
- rebuildable older AM4 machine, B350/B450-class board
- older DDR3 Intel ITX gaming system
- GTX 1650 Super-class spare hardware
- older Dell Windows-7-era Intel system
- additional loose/unknown older hardware

Hardware inventory can change frequently because systems/parts are upgraded or traded.

## 18.2 Scheduler Direction

**STATUS: USER_CONFIRMED DIRECTION / FUTURE DESIGN**

QPX should eventually automatically manage heterogeneous workers based on the capabilities/resources each node deliberately advertises.

Exact implementation is intentionally deferred until the user is back home with the hardware physically available for inspection.

Not yet fixed:

- coordinator topology
- automatic discovery details
- exact CPU/GPU/RAM quotas
- gaming-aware thresholds
- exact priority scheduler
- migration/rejoin mechanics

These are **future hardware-informed design decisions**.

## 18.3 Worker Privacy

**STATUS: USER_APPROVED**

QPX must not inspect household computer contents merely because a machine contributes compute.

Workers should expose only deliberately offered capability/health/state information such as:

- CPU/RAM/GPU availability
- scratch capacity
- load class
- temperatures/power limits where appropriate
- coarse state such as IDLE / LIGHT USE / GAMING / QPX BUSY / OFFLINE

Use least privilege and bounded workspaces.

## 18.4 Drain Node

**STATUS: USER_APPROVED**

Dedicated hardware can change frequently.

Planned upgrade flow should support:

**drain requested → stop new assignments → finish/checkpoint/move work → return results → NODE DRAINED — SAFE TO POWER OFF → upgrade/replace → node returns and advertises capabilities**

Planned maintenance should reduce capacity, not break QPX.

## 18.5 Power Failure / Recovery

**STATUS: USER_APPROVED**

QPX must tolerate power outages without corrupting authoritative state.

Relevant goals:

- restart services/processes after power restoration
- reconcile state before resuming risky actions
- keep transient workers non-authoritative
- preserve audit/state integrity

## 18.6 Storage Architecture

**STATUS: FUTURE_DECISION**

NAS/RAID/snapshot/replication/off-site backup and authoritative home-lab storage ownership are **not yet decided**.

Reason: they depend on hardware questions that remain unanswered until the available hardware can be inspected.

Do not invent a storage topology.

---

# 19. SERVER ROOM / NETWORK

**STATUS: USER_APPROVED / RECOVERED**

Server room:

- unused spare bedroom
- upstairs
- lockable
- central HVAC
- noise/heat acceptable within reason
- attic-accessing closet
- exterior venting / dedicated heat-extraction possibilities exist

Network:

- household/gaming nodes may remain on Wi-Fi
- server-room equipment may use wired LAN
- transient nodes may appear/disappear
- QPX should tolerate heterogeneous connectivity

---

# 20. MOBILE / REMOTE CONTROL

**STATUS: FUTURE CAPABILITY + FUTURE SECURITY DESIGN**

Mobile applications / Mobile Companion are desired future capabilities.

Current confirmed position:

- mobile monitoring/interaction is desirable
- exact secure remote-administration architecture is **not yet decided**
- do not assume unrestricted inbound remote administration

Security decisions take priority over convenience.

---

# 21. PUBLIC QPX VS PRIVATE QPX

**STATUS: USER_APPROVED / HARD REQUIREMENT**

Strict separation:

## Private / Home Side

May:

- download data
- run private research
- use private compute
- contain private Champion/history
- contain private strategy parameters/symbol choices
- build controlled release artifacts
- push approved artifacts outward

## Public Side

Must:

- run independently
- have no inbound control path to home lab
- not use home CPU/GPU/storage/bandwidth
- not use private credentials
- not use private services/files
- not trigger jobs inside the home lab

Explicitly disallowed public-to-home mechanisms include concepts such as:

- callbacks
- webhooks
- tunnels
- remote shells
- public-triggered private jobs

Private strategy must not silently influence public:

- defaults
- tuning
- benchmarks
- release criteria
- hidden strategy behavior
- private training/optimization contamination

Public QPX should remain strategy-neutral and independently verifiable.

A public release gate should verify isolation.

---

# 22. PUBLIC PRODUCT MECHANICS

**STATUS: FUTURE_DECISION**

Not yet decided:

- tenant model
- hosting provider/architecture
- pricing
- licensing
- community-strategy publication mechanics
- plugin permission model
- commercialization details

User direction:

These are future decisions to make **after a working full-fledged QPX has been live-tested for a few months**.

Do not prematurely lock these decisions.

---

# 23. WORKING PRODUCT / MODULE NAMES

**STATUS: USER_CONFIRMED — NAMES REMAIN CHANGEABLE**

Concepts such as:

- QPX Lab
- QPX Portfolio
- QPX Automate
- QPX Intelligence
- QPX Shadow
- QPX Guard

may be used as working organizational names.

The underlying capabilities are more important than the names.

Names must remain changeable if they become confusing, overlapping, or difficult to track.

---

# 24. LONG-TERM PLATFORM VISION

**STATUS: USER_APPROVED FUTURE VISION + VERIFIED_REPO**

Future capabilities discussed/approved include:

- multiple brokers
- interchangeable AI models
- multiple data providers
- options
- crypto
- futures
- international markets
- cloud deployment
- mobile applications
- multiple portfolios/accounts
- portfolio optimization
- asset allocation
- AI-assisted research
- automated strategy discovery
- intelligent portfolio management
- advanced risk analysis
- plugin marketplace
- community strategies

These are future capabilities, not claims of current implementation.

---

# 25. STRATEGY DISCOVERY AUTHORITY

**STATUS: PARTIALLY RESOLVED / FUTURE DECISION**

Current confirmed position:

- Parameter Boundary Shadow may explore far outside normal parameter/risk limits.
- Strategy Boundary Shadow may change strategy logic for **paper/research purposes**.
- Neither has live authority.
- Neither can self-promote.
- Strong explainability/reporting is required.
- Live AI autonomy may be revisited later.

Still intentionally unresolved:

- exact autonomous-AI authority for inventing strategies
- whether/when an explicit AI automation switch should be allowed beyond research
- safeguards and proof requirements for that future authority

Do not equate “Strategy Boundary Shadow can test changed strategies” with “AI may autonomously rewrite production.”

---

# 26. OPERATIONS / RELIABILITY CAPABILITIES

**STATUS: USER_APPROVED + VERIFIED_REPO IN PART**

QPX reliability architecture includes or targets:

- persistent state
- atomic writes where applicable
- checksums / corruption detection
- audit journals
- kill switches
- verified backup/restore
- retry handling
- circuit-breaker behavior
- market-calendar awareness
- regular-session controls
- health checks
- automatic daily operations
- reconciliation
- restart safety
- duplicate-order prevention
- paper-execution qualification
- controlled live-candidate progression

Month-Unattended Gate is the higher-level production-readiness requirement.

---

# 27. EXPLAINABILITY AS A PLATFORM CAPABILITY

**STATUS: USER_APPROVED / VERIFIED_REPO IN PART**

QPX should explain:

- why a trade was entered
- why it was rejected
- why an exit occurred
- which rule failed/passed
- why Champion and Shadow differed
- why one mandate/strategy behaved differently from another
- why a candidate was promoted/rejected
- what changed between configurations
- what was knowable at decision time

The system should not hide important investment decisions behind unexplained AI output.

---

# 28. EMOTION-FREE OPERATION

**STATUS: USER_APPROVED**

QPX is intended to consistently execute an established evidence-based decision framework rather than react emotionally to short-term market events.

This does not mean “never adapt.” Adaptation belongs in governed research/Shadow/Challenger pathways.

---

# 29. DEFERRED HARDWARE / INFRASTRUCTURE DECISIONS

**STATUS: USER_CONFIRMED**

Some infrastructure decisions were deliberately postponed while current research/Top-100/accelerator work continued.

Detailed distributed scheduler and storage architecture should be discussed when the user is physically back home with the hardware available for inspection.

This is intentional deferral, not missing requirements.

---

# 30. CURRENT EXPLICIT UNRESOLVED ITEMS

These are known open questions and must not be silently filled in:

1. Final exact Shadow scoring formula.
2. Final Benchmark Gate weighting/pass threshold.
3. Exact numeric preset values for each mandate/profile.
4. Final default set for one-button comparative backtesting.
5. Exact distributed scheduler topology and resource policies.
6. Exact authoritative home-lab storage/backup topology.
7. Exact secure mobile/remote-control architecture.
8. Public hosting/tenant/pricing/licensing/plugin/community mechanics.
9. Final names for product modules.
10. Exact future AI automation switch and authority.
11. Exact autonomous strategy-discovery mechanism and safeguards.
12. Final live Champion strategy — still subject to qualification.
13. Remaining persistence/data-provider issues in current research must be resolved without faking coverage.

---

# 31. GOVERNANCE RULE FOR FUTURE CHANGES

Every future major QPX decision should be recorded in this ledger (or a successor formal decision file) with:

- date
- status
- source
- decision
- rationale
- what changed
- whether it supersedes an earlier decision
- implementation status
- **DO NOT REINTERPRET** where appropriate

Major strategy changes should become explicit versions/configurations rather than silently changing historical meaning.

---

# 32. RECOVERY PRINCIPLE

The recovery process itself has established a permanent rule:

**If historical evidence is incomplete, mark it UNKNOWN / UNRECOVERED rather than inventing a plausible answer.**

A remembered assistant proposal is not a user decision unless approval can be demonstrated or the user reconfirms it.

The goal of this ledger is to prevent future QPX work from repeatedly rehashing decisions that were already made.

---

# 33. LATEST USER CONFIRMATIONS — 2026-08-11

The following were explicitly reconfirmed:

1. Two Boundary Shadows should exist:
   - one stays inside the overall strategy with much looser parameters/risk
   - one may change the strategy itself
   - both are paper/research only
   - both require strong same/different/why reporting

2. Boundary exploration dimensions are examples, not fixed permanent hard limits.

3. Shadow scoring formula remains open for now and may be tightened later.

4. Benchmark Gate formula/threshold remains open for now and may be tightened later.

5. Mandates should have useful presets but ultimately be user-configurable.

6. One-button comparative backtesting should use starting capital and return explained strategy comparisons.

7. Distributed scheduler direction is correct, with detailed design deferred until hardware is physically available.

8. Home-lab storage architecture is not decided because hardware questions remain.

9. Mobile monitoring/interaction is desired, while exact secure remote control is undecided.

10. Public product mechanics remain future decisions after full QPX has been live-tested for a few months.

11. Working module names may be used but remain renameable.

12. Autopilot currently automates approved operation; adaptive AI researches; Shadow tests; governance promotes.

13. A future explicit AI automation switch may be discussed if evidence shows it is worthwhile.

<!-- QPX_TOP100_PORTFOLIO_CHECKPOINT_20260811 -->
# TOP-100 PORTFOLIO VIABILITY CHECKPOINT — 2026-08-11
**STATUS: VERIFIED_ARTIFACT + USER-RUN RESULT**
Candidate V1 Top-100 portfolio: $1,300 start; 2024-03-07 through 2026-08-07; 12,049 common 15m bars; 596 sessions; 1,710 trades; 49.06% win rate; PF 1.313.
Swing P&L $14,924.20; net profit $15,185.76; ending equity $16,485.76; reported CAGR 192.71%; maximum drawdown 30.47%.
All 100 symbols traded; 61 profitable and 39 losing; 5,008 risk rejects; 2,405 capacity deferred.
Original ranks 1-10 lost money as a group; ranks 41-50 were strongest; 8 of 10 deciles were profitable.
Discovery ranking and portfolio selection are different problems. Do not hard-code in-sample winners.
**TOP-100 PORTFOLIO VIABILITY: PRELIMINARY PASS**
**STRICT CAUSAL REPLAY: NOT YET FORMALLY QUALIFIED**
Do not treat the reported CAGR as a production expectation.
Next milestone: **FORMAL STRICT-CAUSAL REPLAY AUDIT / GATE**.

<!-- QPX_STRICT_CAUSAL_FOUNDATION_20260811 -->
# STRICT-CAUSAL REPLAY FOUNDATION — 2026-08-11
**STATUS: VERIFIED_ARTIFACT / LOCAL TEST PASS**
Added qpx_bot/causal_replay.py and tests/test_causal_replay.py. Five tests pass: future bar blocked; OPEN exposes only open; completed OHLCV available only at CLOSE; missing-symbol bars do not stop the market clock; causal-prefix indicators match full-history indicators at the same cutoff.
The existing Top-100 result remains preliminary and unqualified until Candidate V1 is rerun through this strict causal interface.

<!-- QPX_STRICT_CAUSAL_FOUNDATION_20260811 -->
# STRICT-CAUSAL REPLAY FOUNDATION — 2026-08-11
**STATUS: VERIFIED_ARTIFACT / LOCAL TEST PASS**
Added qpx_bot/causal_replay.py and tests/test_causal_replay.py. Five tests pass: future bar blocked; OPEN exposes only open; completed OHLCV available only at CLOSE; missing-symbol bars do not stop the market clock; causal-prefix indicators match full-history indicators at the same cutoff.
The existing Top-100 result remains preliminary and unqualified until Candidate V1 is rerun through this strict causal interface.

<!-- QPX_STRICT_TOP100_RESULT_20260811 -->
# STRICT TOP-100 REPLAY RESULT — 2026-08-11
**STATUS: VERIFIED_ARTIFACT / USER-RUN RESULT**
Strict replay ending equity $14,510.45; net profit $13,210.45; CAGR 172.25%; maximum drawdown 41.97%; 1,954 closed trades; win rate 49.39%; profit factor 1.270; 5,861 risk rejections; 2,550 capacity deferred.
Preserved non-strict control ending equity $16,485.76; CAGR 192.71%; maximum drawdown 30.47%.
Strict architecture materially changed results but Candidate V1 remained profitable. Full qualification remains pending corporate-action cash timing.
Live Alpaca QDTE corporate-action records verified fields: ex_date, record_date, payable_date, process_date, rate.

<!-- QPX_PRE_CODEX_GRANULAR_CHECKPOINT_20260811 -->
# PRE-CODEX MAXIMUM-GRANULARITY CONTEXT CHECKPOINT — 2026-08-11

**STATUS: USER_CONFIRMED + RECOVERED_CONTEXT**

Permanent rule added:

- every context/recovery uses maximum available granularity
- preserve as much actual conversation as available
- append conversation deltas to daily journal
- active-work checkpoint target approximately every 5 minutes
- ten minutes is the upper target ceiling
- major decisions/tests/errors/code/workflow changes trigger immediate
  checkpoint
- user must not have to re-explain current QPX state

Daily journal:

`QPX_CONVERSATION_JOURNAL_2026-08-11.md`

Pre-Codex checkpoint:

`QPX_SESSION_CHECKPOINT_2026-08-11_PRE_CODEX.md`

Current workflow transition:

normal ChatGPT GitHub integration reads the repository successfully but
direct write attempts returned HTTP 403.

Next workflow step:

configure Codex with `Romaro87/QPX_ALPHA` after this checkpoint is pushed.

Current technical next milestone after workflow setup:

freeze authentic QDTE dividend payment/cash-availability timing and rerun
strict-causal Candidate V1.


<!-- QPX_DURABLE_RECOVERY_POINT_20260813_PROFIT_RECYCLING_MATRIX -->
# DURABLE RECOVERY POINT — PROFIT RECYCLING FRACTION MATRIX — 2026-08-13

**STATUS:** VERIFIED_REPO + VERIFIED_ARTIFACT + USER_CONFIRMED preservation snapshot
**Purpose:** preserve the complete QPX trajectory before reducing Codex usage.

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

Load this section before interpreting project history, proposing architecture, or generating future instructions.

- Do not merge or modify `main` without explicit authorization.
- Do not modify protected Candidate V1 behavior/files, frozen Top100 membership/order, frozen datasets, provenance protections, permanent control, or the malformed `qpx_bot/QPX_ALPHA` gitlink unless explicitly authorized.
- Research results are evidence only; no Shadow/Challenger/ML component self-promotes.
- Preserve causal accounting, deterministic replay, checkpoint integrity, and fail-closed behavior.
- **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.**

## PARAMETER UNCERTAINTY RULE

If an exact threshold, percentage, cap, delay, cooldown, allocation, weight, multiplier, mode, limit, timing value, or other strategy/operational parameter is not explicitly recovered, **DO NOT assume it was forgotten and DO NOT invent or hard-code a value.**

QPX architecture assumes exact operational/strategy parameters are generally **USER-CONFIGURABLE, VERSIONED, FINGERPRINTED, AND HOT-SWAPPABLE** where safe. The engine implements capability and validation; runtime/versioned configuration supplies values. Historical fixed values normally represent frozen experiment configurations, not universal permanent defaults. Hard safety, accounting, and provenance invariants remain code invariants and are not tuneable. This applies across every QPX engine, accelerator, ML component, allocation rule, risk mechanism, hardware scheduler, and future subsystem unless explicitly overridden by a documented architectural invariant.

## A. EVERYTHING COMPLETED

### Repository and workflow

- Branch: `qpx-shadow-matrix-v1-review-2026-08-12`.
- Current verified HEAD: `1ce96941e8fb1cbe8c9e7c5dabf3327842603814`, `Correct Profit Recycling matrix causal aggregate`.
- Remote review branch matches local; ahead/behind is `0/0`.
- Main and origin/main remain `2cab84accdfe79faa8097b7fdb976da46d8dbde5`; main was not modified.
- No local unpushed commits or intentional untracked source files exist at this checkpoint.
- Ignored generated reports/caches/raw data are disposable under repository policy and are not staged. Credentials/environment files are ignored and not committed.

### Completed accelerator progression

Verified by Git history/artifacts: Candidate V1 strict causal foundation and qualification work; Dynamic Sizing V1; Pyramiding V1; Capacity Arbitration V1; parallel research runner; Regime Allocation V1 foundation, no-op validation, fixed proposals, and matrix; Profit Recycling V1 foundation, no-op/equivalence validation, hot-swappable configuration, redeployment governor, checkpoint continuity repair, and fraction matrix.

Key commits in order include: `837b51f` foundation; `971c823` hot-swappable Profit Recycling; `9cef0ee` governor integration; `f9c14d1` checkpoint continuity repair; `9acd7fe` fraction matrix results; `1ce9694` causal aggregation repair. Earlier Dynamic/Pyramiding/Capacity/Regime commits are preserved in Git history.

### Profit Recycling fraction matrix

Artifact: `docs/research_results/PROFIT_RECYCLING_V1_FRACTION_MATRIX_2026-08-12.json`. Manifest fingerprint: `4213719f443f7ed8285511e4268a8a1b181b32d082cde03a12e75538b1129133`. Dataset fingerprint: `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`. Frozen Top100 fingerprint: `8549b0cf69631a974cacb8b429c52da4e36c40665dce9d1d7c3f1800641cd914`.

Five frozen research-only configs: PR_FRACTION_100 `148f702f9ba50ec788b0554ade08c9bebedb7219ddbe796d62feda884739f691`; PR_FRACTION_75 `90ecbd0541e902745e69ccf6d0ba8a615dedb858de5109f9112bba8f62d84359`; PR_FRACTION_50 `c8d634fcd6a5c1c9503f5dbe38de807b5ee607e21afbb6ea06d1903ba0b5c049`; PR_FRACTION_25 `49178a9864f1f0273a966f5a667693efcc5b6a2343b47eaf61f018b79191c190`; PR_FRACTION_0 `f01f285c44ba189eaeeed8cd4a2ef2f3bb7d0c86478e41c86a585f979743a9f0`.

20/20 jobs completed, 0 failed, 4 workers. All causal gates now aggregate true. The prior false flag was an aggregation/reporting bug: every descriptive gate was required to literally equal `PASS`; valid statuses include `BLOCKED`, `STRICT_RECORDED_UNION`, `NONE`, and others. Commit `1ce9694` fixed this by using `OVERALL_PORTFOLIO_QUALIFICATION == FULL_CAUSAL_ACCOUNTING_PASS`. No historical jobs were rerun and economic values did not change.

Full period: 100% control ending equity `$27,880.67`; 50% `$28,276.83` (+$396) but with worse drawdowns; 75% `$27,228.80` (-$652); 25% `$24,249.85` (-$3,631); 0% `$22,771.37` (-$5,109). Calendar partitions were mixed: 75% improved growth and EOD drawdown in 2025 only; no robust multi-period superiority. Do not tune, promote, or automatically start another matrix.

### Validation and protections

At `1ce9694`: focused Profit Recycling tests 29 passed; full offline core suite 179 passed; GitHub CI run `31657125971` succeeded. Candidate V1 protected provenance passed; frozen Top100, permanent control, Dynamic/Pyramiding/Capacity/Regime behavior, and main were unchanged.

## B. EVERYTHING CURRENTLY IN PROGRESS

- Current feature stage: Profit Recycling fraction-matrix audit/preservation is complete.
- Current verified state: clean synchronized review branch at `1ce9694`; no active implementation or historical run.
- Current blocker: no approved next Profit Recycling configuration family exists. Fixed withholding has mixed evidence and must not be treated as a Champion.
- Immediate next action: on explicit user direction, retrieve/inspect this recovery package and decide whether to define a new research hypothesis. Do not infer one.

## C. EVERYTHING STILL TO DO

1. Preserve and verify recovery point (this task): acceptance = clean branch, pushed recovery docs, local/remote equality, main unchanged.
2. Only after explicit direction, choose a research question and predeclare exact config values/fingerprints.
3. If approved, run a bounded isolated matrix through the process-isolated parallel runner; require resumability, causal gates, and no tuning.
4. Review evidence for mechanism and robustness; governance decides whether any Challenger/Shadow deserves further testing.
5. Separately continue Dividend Opportunity Engine architecture; do not absorb dividend logic into Profit Recycling.
6. Later, test approved accelerator combinations (Dynamic, Pyramiding, Capacity, Regime, Profit Recycling) in controlled isolated stages.
7. Eventually establish Champion/Challenger qualification, paper-trading readiness, and production hardening.

Explicitly not to do now: no broad parameter sweep, no Top100 rebuild, no Candidate baseline edits, no automatic promotion, no main merge, no ML/live adaptive mutation, no hardware procurement assumption.

## D. DETAILED ROADMAP

- **Profit Recycling:** foundation, hot swap, governor, continuity repair, control equivalence, and fraction matrix complete; next direction unknown pending user governance.
- **Dividend Opportunity Engine:** separate future accelerator; exact opportunities, thresholds, ex-dividend rules, and policy values remain unrecovered/configurable unless explicitly approved.
- **Combinations:** test only predeclared combinations after isolated evidence justifies them; preserve accelerator responsibility boundaries.
- **Champion/Challenger:** no experiment self-promotes; establish formal qualification, Shadow evidence, risk and robustness review before any Champion change.
- **Paper trading:** requires strict causal/provenance/accounting gates, checkpoint/recovery, broker reconciliation, secrets isolation, and operational readiness.
- **Laptop/remote workflow:** prior recommendation discussion is recovered context, not a purchase. Phone-to-core remote path is Tailscale to trusted core; local workers remain LAN-managed.
- **Home lab:** AM4 is initial trusted-core host role, not QPX identity. Reuse hardware first; workers are replaceable and opportunistic.
- **ML/Adaptive Intelligence:** approved long-term direction, intentionally deferred until deterministic evidence constraints exist. QPX trains/controls data; ML recommends, Shadows test, governance decides; no self-promotion or silent mutation.
- **Options/short/leverage:** future research only; no exact rules or parameters recovered.
- **Production hardening:** replicated authoritative state, checksummed journals, fencing/lease, failover, broker reconciliation, unattended safe recovery, low-noise alerts, and fail-closed corruption handling remain future work.

## E. UNCERTAINTY LEDGER

### Unknown / unrecovered

- Exact next Profit Recycling mechanism beyond fraction withholding.
- Any approved delay, threshold, loss-recovery, cooldown, conditional trigger, or destination policy.
- Exact Dividend Opportunity Engine policy and parameters.
- Champion identity and live promotion decision.
- Final paper-trading deployment date and broker operational choices.
- Exact ML model family, features, targets, cadence, thresholds, and training schedule.
- Exact home-lab failover hardware, lease protocol, and power/thermal thresholds.
- Exact options/short/leverage research configurations.

### Intentionally configurable

Profit fractions, thresholds, delays, loss recovery, allocation weights, risk limits where architecture allows, worker quotas, wake/sleep policy, telemetry thresholds, model configuration, and operational schedules.

### Frozen research values (not universal defaults)

The five PR fraction configs, fixed-25/hash-control context, existing Regime schedules, Capacity policies, Pyramiding 1.0.0, and Dynamic tiers are reproducibility artifacts only unless separately approved.

### Hypotheses / proposals

Conditional/intelligent profit recycling may be more meaningful than permanent fixed withholding; this is an assistant/user research direction, not an approved policy. ML adaptive intelligence is an approved long-term direction, not an implementation decision.

### Architecture questions requiring verification

How future conditional recycling should interact with entry sizing, sleeve rebalance, capacity, and risk; how distributed trusted-core failover should fence authority; how paper trading will reconcile broker state; and how QPX-native ML evidence will be versioned and promoted.

## RECOVERY RESTORE CONTRACT

On restore: verify branch/HEAD/status and read `QPX_CONTEXT_CONTINUITY_RULE.md`, this section, `QPX_RECOVERY_PROMPT.md`, and the latest journal snapshot before interpreting history. Verify artifact fingerprints and Git provenance. Do not rerun or alter the fraction matrix merely because the aggregate was corrected.


<!-- QPX_AUGUST14_ARCHITECTURE_RECOVERY_20260814 -->
# AUGUST 14 ARCHITECTURE RECOVERY POINT — 2026-08-14

**Status:** USER_CONFIRMED + RECOVERED_CONTEXT; repository facts separately marked VERIFIED_REPO.
**Recovery boundary:** approximately 2026-08-14 13:12 CDT, immediately after approval of the AI Wildcard concept. Anything after that point is UNKNOWN / UNRECOVERED unless independently verified.

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

Load governing rules before interpreting project history, proposing architecture, or generating future instructions. **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.** Do not merge or modify main; preserve protected Candidate V1, frozen Top100/data, provenance, permanent controls, and economic accounting. Research, ML, Shadows, and Wildcard actors never self-promote or gain real-money authority.

### PARAMETER UNCERTAINTY RULE

If an exact threshold, percentage, cap, delay, cooldown, allocation, weight, multiplier, mode, limit, timing value, or other strategy/operational parameter is not explicitly recovered, do not assume it was forgotten and do not invent or hard-code it. QPX should keep these values USER-CONFIGURABLE, VERSIONED, FINGERPRINTED, and HOT-SWAPPABLE where safe. Engine code provides capability and validation; versioned runtime configuration supplies values. Historical fixed values are normally frozen research configurations, not universal defaults. Safety, accounting, and provenance invariants are code invariants, not tuneable parameters.

## RECOVERED AUGUST 14 TRAJECTORY

### 1. QPX Core and Indiana migration

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** The initial permanent trusted QPX Core should use Ubuntu 24.04 LTS and run as dedicated Linux services, not an interactive desktop session. Desired capabilities: pinned/runtime-controlled Python, persistent state and journals, watchdog/health monitoring, checkpoints/backups, SSH, and secure phone access. During the approximately one-week Indiana visit, family time remains the priority. Minimum successful outcome: one dedicated Linux QPX machine reachable from the phone, unattended, state-persistent, and able to survive/reconcile after reboot. Tailscale is the preferred first remote-access path; native WireGuard and broader networking can be evaluated later. Do not finalize the entire home-lab architecture during the trip.

### 2. Development usability

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Prioritize development speed using automation, clear commands, and PASS / FAIL / NEXT STEP workflows where useful. The user eventually wants to understand and independently change QPX, but learning must not block current progress. QPX should remain understandable and usable as a personal tool even if never public; it must not become an opaque black box.

### 3. Hypothetical public/local ownership philosophy

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT; commercialization future governance.** A roughly $20 one-time purchase was discussed hypothetically; it is not a frozen commercial decision. Approved philosophy: affordability, local-first ownership, user control of the copy, user-supplied broker/data/API credentials, no mandatory subscription merely to keep a purchased local copy operating, no mandatory remote license heartbeat, private trading state/strategies/history/credentials local where practical, and strict isolation between public QPX infrastructure and private/home QPX. Final price, license, and commercialization remain undecided until QPX is mature and live-tested.

### 4. Eventual one-minute architecture

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** QPX should eventually support 1-minute granularity before real-money deployment, but current work must not be derailed into an immediate wholesale conversion. Prerequisites: establish QPX Core, bring the 5900XT online as a worker, and prove Core↔worker operation. Existing qualified 15-minute research remains protected control. Future sequence: obtain authentic 1-minute data; validate/freeze it; aggregate it back to 15-minute; prove parity with the protected 15-minute reference; only then research whether finer decision/execution resolution adds value. Decision resolution and execution resolution remain separate concepts.

### 5. Isolated timeframe Shadows

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** After canonical authentic 1-minute data exists, fixed decision resolutions may be tested as isolated Shadows. Each sees only completed candles at its assigned resolution, with no future or cross-resolution leakage. Results are evidence/recommendations only and cannot silently alter Champion.

### 6. Strategy lineage

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Permanent lineage is **Boundary → Challenger → Champion**. Boundary research earns Challenger consideration; Challengers compete for Champion; displaced Champions should remain live-paper forward references where practical. Replacement requires governed evidence, not merely recent profit.

### 7. Governed Challenger capacity

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Maintain approximately 10 active governed Challenger slots as a practical target, not a limit on broad Boundary/Shadow exploration. Scarce Challenger capacity is reserved for candidates earning forward evaluation. Concurrent instances may share canonical validated market data while isolating positions, cash/accounting, indicators/state, pending orders, configuration/version, checkpoints/history, and audit identity.

### 8. Candidate Qualification Layer

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Introduce a governed layer between broad Boundary/Shadow research and scarce Challenger slots. It aggregates evidence, compares quality, rejects candidates, requests missing tests, and nominates sufficiently supported candidates. Evidence can include causal validity, historical/OOS and forward behavior, risk/return, drawdown, stability, slippage/execution, capacity, correlation/novelty, regime dependence, robustness, and evidence gaps. It has no trading-capital authority. Boundary/Shadow/Research ML asks what is worth investigating; Qualification asks which investigated candidates deserve scarce Challenger capacity. Exact scores/thresholds remain configurable or UNKNOWN.

### 9. Three separated ML roles

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Research ML generates hypotheses, assists Boundary/Shadow research, prioritizes experiments, and discovers patterns; it has no promotion or real-money authority. Qualification ML independently evaluates robustness, overfitting, regime dependence, correlation/similarity, degradation, and evidence gaps; the researcher must not grade its own work. Operations ML observes live-paper/eventual operational behavior such as slippage, fills, broker/feed degradation, liquidity, paper/live divergence, and anomalies; bounded advice requires explicit deterministic permission. ML failure must mean loss of intelligence, not loss of safety or deterministic trading correctness.

### 10. Jetson Orin Nano Super

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Jetson Orin Nano Super is the intended dedicated AI/ML hardware direction. One physical device may host the three logical ML roles only with process/data/authority separation; co-location does not collapse governance boundaries.

### 11. Permanent AI Wildcard #11

**Classification: USER_CONFIRMED / RECOVERED_CONTEXT.** Create a permanent conceptual AI Wildcard outside approximately 10 governed Challenger slots. It continuously explores what an autonomous creative research actor would do and serves as an unconventional benchmark. It is LIVE PAPER ONLY, structurally incapable of real-money access, has no broker credentials or live-order authority, cannot self-promote or bypass deterministic safety/governance, uses only causal data, and is fully logged/auditable. “Secret 11th slot” is only a nickname; it must not be secret from provenance/audit. Exceptional discovery follows: freeze/reproduce → normal research/Shadow evidence → Candidate Qualification → Challenger consideration → normal governance.

The Wildcard does not repeal existing AI governance: no silent Champion rewrite, no self-promotion, no safety/accounting/provenance bypass, and no real-money authority.

## CURRENT STATE AT THIS RECOVERY POINT

**Classification: VERIFIED_REPO.** Review branch remains `qpx-shadow-matrix-v1-review-2026-08-12`, current expected HEAD before this preservation commit is `458f26c420b62b1b9999adf9da3c0c4168c34d12`, upstream synchronized, worktree clean, and main/origin-main remain `2cab84accdfe79faa8097b7fdb976da46d8dbde5`. Profit Recycling fraction matrix and its reporting correction are complete; no new development or research is in progress.

## STILL TO DO / ORDERED ROADMAP

1. Indiana minimum: deploy one dedicated Ubuntu Core, secure Tailscale phone reachability, unattended service operation, persistence, reboot reconciliation, and verified checkpoint/backup. Acceptance: phone can observe/control safely and Core resumes from verified state after reboot.
2. Bring up 5900XT as a replaceable worker and prove Core↔worker dispatch/recovery. Acceptance: worker loss cannot lose authoritative state.
3. Keep protected 15-minute Candidate V1 as control; only after authentic 1-minute data is validated/frozen and parity is proven, add isolated timeframe Shadows.
4. Implement Candidate Qualification as governance/evidence only, with approximately 10 Challenger slots and no capital authority. Exact scores remain configurable/UNKNOWN.
5. Evaluate Jetson logical ML separation after deterministic QPX evidence and hardware needs are clearer.
6. Keep Research/Qualification/Operations ML separate, causal, versioned, provenance-bound, and non-self-promoting.
7. Define and test Wildcard #11 paper-only containment, audit, causal replay, and promotion handoff only after architecture review.
8. Later harden replicated authoritative state, checksummed journals, automatic failover, leases/fencing, broker reconciliation, unattended recovery, low-noise alerts, and production readiness.

Explicitly not to do now: no new historical matrix, no fraction tuning, no Top100 rebuild/rerank, no Candidate baseline edits, no automatic Champion promotion, no main merge, no public commercialization finalization, no one-minute conversion before prerequisites, and no real-money Wildcard.

## UNCERTAINTY LEDGER

**UNKNOWN / UNRECOVERED:** Anything after approximately 13:12 CDT on August 14; exact Candidate Qualification scoring/thresholds; exact Challenger slot enforcement mechanics; exact ML models/features/training cadence; exact Wildcard algorithm and resource limits; final Ubuntu hardware; Tailscale/WireGuard final topology; broker/reconciliation implementation; one-minute dataset/vendor and parity acceptance details; final price/license/commercialization; production date; options/short/leverage rules.

**INTENTIONALLY CONFIGURABLE:** Core service quotas, worker availability, wake/sleep thresholds, ML configuration, qualification scores, Challenger capacity policy, Shadow resolutions, data retention, network controls, and operational schedules.

**FROZEN / PROTECTED:** Existing Candidate V1, strict causal accounting, frozen Top100/data/fingerprints, permanent controls, completed accelerator definitions/results, and prior Profit Recycling artifacts.

**ASSISTANT_PROPOSED / FUTURE HYPOTHESIS:** Conditional/intelligent Profit Recycling may be more meaningful than fixed withholding; this is not approved. Hardware/network implementation details remain proposals until explicitly selected.

## RESTORE CONTRACT

On restore, read `QPX_CONTEXT_CONTINUITY_RULE.md`, this appended ledger section, `QPX_RECOVERY_PROMPT.md`, and `QPX_CONVERSATION_JOURNAL_2026-08-14.md`; verify branch, HEAD, upstream, status, main refs, fingerprints, and protected provenance. Treat post-boundary events as UNKNOWN. Retrieve/verify before acting.


<!-- QPX_POST_AUG14_CONTINUITY_ADDENDUM_20260825 -->
# POST-AUGUST-14 CONTINUITY ADDENDUM — 2026-08-25

**Status:** USER_CONFIRMED + RECOVERED_CONTEXT durable principles. This addendum extends the recovered August 14 boundary with preserved August 15–17 context. It does not rewrite older history or resolve anything explicitly marked **UNKNOWN / UNRECOVERED**.

## 1. ML, WILDCARD, AND CHRONOLOGICAL EVIDENCE

- **Autonomy may increase; accountability never decreases.** Increased autonomy never removes causal, provenance, audit, safety, governance, or no-self-promotion requirements.
- Wildcard is clean-room discovery. Teach it how to discover, not trading doctrine.
- Its information flow is one-way: **raw causal market → Wildcard → sterile factual experience → downstream QPX**. Champion, Shadow, Qualification, Research, and Operations conclusions do not feed back into Wildcard.
- Wildcard experiences market history once in chronological order, without rewind: **“Wildcard does not backtest. Wildcard experiences market history once.”** It may remember the past; it may never relive it.
- Traditional QPX should eventually have a separate chronological continuity evidence lane. That lane supplements and does not replace frozen Candidate V1 qualification evidence.
- Income sleeve is a portfolio role. QDTE is one qualified implementation, not the permanent identity of the role. If no qualified income implementation or opportunity exists, leaving that sleeve allocation in cash is legitimate. This principle does not alter protected Candidate V1 economics.

## 2. CORE, WORKERS, AND HOUSEHOLD HARDWARE

- **Core owns authority; workers own horsepower.** Core remains correct and operable when workers or network storage disappear.
- **Hardware can be weird; authority and state semantics cannot be weird.**
- Household usefulness and family use outrank QPX convenience.
- Heterogeneous workers advertise their real, deliberately offered capability. They do not gain authority merely by contributing compute or storage.
- Native Linux is preferred for persistent Core service when practical. Old hardware remains a valid candidate until reliability is measured; unproven is not dead.

## 3. GORILLA LABS AND DEFENSIBLE WEIRDNESS

- Gorilla Labs documents real QPX infrastructure work; projects are not manufactured merely to supply content.
- “Usefully weird computing” is the durable orientation.
- Engineering Clown Shoes permits a ridiculous-looking implementation only when it remains technically defensible. Measurement, electrical awareness, safety, reliability, bounded risk, known failure modes, and failure planning remain mandatory.
- Magic Smoke is shorthand for electrical survival under unconventional but defensible hardware use; it is not permission for recklessness.

## 4. ROAD-SIGN RECOVERY METHOD AND CORRECTIONS

- Recover tangents through purpose and adjacency rather than as a bag of nouns.
- Use positive road signs to preserve known landmarks and their relationships; use negative road signs to prevent contaminated reconstructions from returning.
- The pelican-case reference was assistant contamination and must not return unless independently introduced by the user later.
- There is no third-party keyboard story.
- Do not invent a warning color.
- Multiple “brainstorm while Codex replenishes” remarks must not be collapsed into one unique event.
- Mel Brooks is a genuine comedic influence, not a one-off reference.
- The sea-level/mountain-ahead metaphor refers to QPX as a whole, not context recovery.

## 5. UNKNOWN / UNRECOVERED BOUNDARY

The following remain **UNKNOWN / UNRECOVERED** or explicitly configurable: exact Qualification scoring/thresholds; exact Challenger-slot enforcement; ML models/features/training cadence; Wildcard algorithm, reward weights, bankruptcy threshold, report cadence, providers, causal-field rules, resource quotas, and sibling count; final Core/network/storage topology; one-minute provider/data/parity criteria; scheduler quotas/worker policy; unrecovered Blu-ray jukebox mechanics; and whether the HAL speaker became mandatory.

## 6. PROTECTED BOUNDARY

Candidate V1 lineage/economics, strict-causal accounting/provenance, frozen Top-100 data/fingerprints, completed accelerator evidence, permanent controls, and main remain protected. No research, Shadow, Challenger, Qualification, ML, or Wildcard component may self-promote. This addendum authorizes preservation only; the next development milestone requires explicit user direction.

<!-- QPX_INCOME_ROLE_SELECTOR_FOUNDATION_20260826 -->
# INCOME-ROLE SELECTOR FOUNDATION — 2026-08-26

**Status: VERIFIED_REPO.** The isolated, non-integrated income-role selector foundation is complete. Candidate V1 remains untouched and continues to use its qualified QDTE behavior. The foundation represents the income sleeve as a portfolio role and QDTE as one qualified implementation of that role; it also provides an explicit CASH/no-deployment result.

Qualification-registry enforcement fails closed. Canonical deterministic fingerprints and decision IDs exist, causal/nonfuture input is enforced, and decisions retain immutable selector, configuration, qualification, and context lineage. A legacy Candidate V1 QDTE adapter exists only as a compatibility representation and is not wired into Candidate V1.

No paper/live execution, Shadow Matrix, Regime Allocation, or Dividend Opportunity Engine integration occurred. Focused foundation tests passed 14/14, and bounded existing offline/core regressions passed 39/39. No research or backtest matrix was run. Integration and governance questions remain deferred and require separate direction.

<!-- QPX_GOVERNED_INCOME_QUALIFICATION_REGISTRY_FOUNDATION_20260826 -->
# GOVERNED INCOME QUALIFICATION REGISTRY FOUNDATION — 2026-08-26

**Status: VERIFIED_REPO.** The governed income qualification registry foundation is complete, isolated, and non-integrated. It provides deterministic immutable governed qualification records and causal, order-independent registry snapshots, with explicit revocation and deterministic expiry behavior. Governance and evidence validation fail closed.

The Candidate V1 QDTE compatibility record points only to the existing qualified Candidate V1 provenance; it performs no new qualification and is not wired into Candidate V1. The isolated selector consumes registry snapshots, while neither selector nor registry performs research, scoring, economic-merit assessment, or promotion. No paper/live, Shadow Matrix, Regime Allocation, Dividend Opportunity Engine, ML, portfolio-construction, or qualified-replay integration occurred.

Focused governed-registry tests passed 19/19, existing income-role tests passed 14/14, and bounded existing offline/core regressions passed 39/39. No research or backtest matrix was run. Operational governance authentication/rotation, durable artifact storage/loading, registry issuance/archival, and all integration questions remain deferred. Candidate V1 lineage/economics and main remain protected.


<!-- QPX_DIVIDEND_OPPORTUNITY_ENGINE_FOUNDATION_V1_20260827 -->
# DIVIDEND OPPORTUNITY ENGINE FOUNDATION V1 — 2026-08-27

**Status: VERIFIED_REPO research-only foundation; no economic or promotion claim.** The isolated Dividend Opportunity Engine Foundation V1 represents immutable, deterministic opportunity evidence for dividend capture, post-ex-dividend recovery, pre-ex-dividend momentum, quality/income rotation, and related dividend opportunities. It preserves corporate-action effective time separately from information-availability and evaluation times, rejects incomplete or future information, and emits only explicit `NO_OPPORTUNITY` / `NO_ACTION` decisions because no scoring or actionable policy is approved.

The foundation has no capital-allocation, execution, qualification, promotion, income-role-selection, paper, or live authority. It is not Candidate V1, the income sleeve, QDTE, or a replacement for any qualified income implementation, and it is not integrated with those systems. Candidate V1, qualified QDTE behavior, frozen Top-100 artifacts, and existing qualification evidence remain unchanged.

Scoring weights, thresholds, ranking formulas, holding/capture/recovery windows, capital sizes, comparison controls, and qualification criteria remain unresolved governance/configuration questions. No economic replay, incremental-benefit result, qualification, or promotion occurred in this milestone.


<!-- QPX_DIVIDEND_OPPORTUNITY_ENGINE_POST_EX_RECOVERY_V1_20260827 -->
# DIVIDEND OPPORTUNITY ENGINE — POST-EX RECOVERY V1 MECHANISM — 2026-08-27

**Status: VERIFIED_REPO research-only mechanism; no economic or promotion claim.** Post-Ex Recovery V1 consumes only a causally supplied ex-dividend reference price and chronologically ordered post-ex observations whose information-availability timestamps are no later than evaluation. It preserves event-effective, information-available, observed, and evaluation times separately and fails closed on future or incomplete inputs.

Recovery threshold and evaluation/lookback windows are explicit research configuration, not production-qualified policy. The mechanism emits deterministic opportunity evidence or explicit `NO_OPPORTUNITY` / `NO_ACTION`; it has no capital, execution, qualification, promotion, income-role, paper, or live authority. Candidate V1, qualified QDTE behavior, frozen Top-100 artifacts, and existing qualification evidence remain unchanged.
