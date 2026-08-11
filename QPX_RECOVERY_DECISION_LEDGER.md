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
