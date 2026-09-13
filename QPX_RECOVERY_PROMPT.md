# QPX_ALPHA RECOVERY PROMPT

**Checkpoint date:** 2026-08-11T12:34:41-05:00

Use this file to resume QPX_ALPHA after a lost or frozen ChatGPT conversation.

## RECOVERY RULES

Do not invent QPX history.

Before changing architecture, read:

1. `QPX_RECOVERY_DECISION_LEDGER.md`
2. `QPX_CONTEXT_CONTINUITY_RULE.md`
3. current `git status`
4. current Git HEAD
5. source files relevant to the next milestone

Keep evidence states distinct:
VERIFIED_REPO, VERIFIED_ARTIFACT, USER_CONFIRMED, USER_APPROVED,
USER_REQUIREMENT, RECOVERED_CONTEXT, ASSISTANT_PROPOSED, DISCUSSED,
FUTURE_DECISION, UNKNOWN / UNRECOVERED.

Never convert plausible reconstruction into historical fact.

## WORKSPACE

Repository: `Romaro87/QPX_ALPHA`

Android workspace:
`/storage/emulated/0/QPX_ALPHA`

Environment:
- Pydroid 3
- Termux

The user does not write or assemble code manually.
Provide complete runnable code and exact phone-friendly commands.

Never use `git add .`.
Never silently stage unrelated files.

Normal QPX development must not depend on browser downloads or browser refreshes.
Prefer terminal-created files and Git-backed checkpoints.

## PER-PUSH RULE

Every QPX push must include a freshly updated:

`QPX_RECOVERY_PROMPT.md`

For substantive milestones also update:

`QPX_RECOVERY_DECISION_LEDGER.md`

After every push, verify local HEAD equals the configured upstream tracking ref for the current branch. When `main` is protected and work occurs on a review/research branch, separately verify `main` and `origin/main` remain at the expected protected SHA. Do not imply that a review-branch HEAD should equal `origin/main`.

Continue warning the user roughly five exchanges before usable chat context is likely to run out.

## CURRENT CANDIDATE V1 BASELINE

- starting capital: $1,300
- initially all QDTE
- starting swing cash: $0
- external contributions: $0
- Thursday-only weekly rebalance
- six-position Candidate V1 lineage
- risk lineage: 3% per trade / 10% active risk
- strategy universe remains configuration-driven

## TOP-100 PORTFOLIO CHECKPOINT

Frozen selection fingerprint:

`5e271e4a9e0d4a20b6f4d0cecc08e8bf9efe1d2123a64832d09ba1c1eb9ffd23`

Frozen dataset fingerprint:

`1a0d8d772b02079ee340109811d38678c73053f9a55e2fb3d3b5b96e484c5007`

Local experimental runner:

`QPX_RUN_FROZEN_TOP100_PORTFOLIO.py`

Runner SHA-256:

`0fb5e1937ab94ac5d7f0e10dc902219986a9f1c73bb5a8c5727bf8ce1b1faa1a`

Do not assume that runner is committed unless Git verifies it.

## LATEST TOP-100 RESULT

Range: 2024-03-07 through 2026-08-07

- common 15m bars: 12,049
- sessions: 596
- trades: 1,710
- win rate: 49.06%
- profit factor: 1.313
- swing P&L: $14,924.20
- net portfolio profit: $15,185.76
- ending equity: $16,485.76
- reported CAGR: 192.71%
- maximum drawdown: 30.47%
- risk rejections: 5,008
- capacity deferred: 2,405
- all 100 symbols traded
- 61 profitable overall
- 39 losing overall

Summary fingerprint:

`f185f69744ca1e4663de0bbb0263759c331b06f049440edd2afbbb90f4417672`

Status:

**TOP-100 VIABILITY: PRELIMINARY PASS**

**STRICT CAUSAL REPLAY: NOT YET FORMALLY QUALIFIED**

Do not treat the reported CAGR as a production expectation.

## KEY FINDINGS

The original discovery rank is not a reliable portfolio priority order.

- ranks 1-10 lost money as a group
- ranks 41-50 were the strongest decile
- 8 of 10 rank deciles were profitable
- discovery ranking and portfolio selection are different problems

Winner rotation was substantial:

- profitable both halves: 26
- profitable early only: 28
- profitable late only: 30

Do not hard-code in-sample winners into a production universe.

The $1,300 account was materially capital constrained:

- 4,853 risk rejects because one share could not fit available risk/cash
- 155 rejects because no capital was available
- six-position limit was reached
- 2,405 opportunities were capacity deferred

Do not assume rejected or deferred trades would have been profitable.

## STRICT CAUSAL REPLAY REQUIREMENT

At every simulated historical moment, future information must be technically inaccessible.

Required properties:

- no future-bar access
- no future OHLCV access
- no future-derived indicators
- completed-bar signals execute only at the next legitimate execution point
- no synthetic favorable data
- no forward-filled opportunity
- no timestamp substitution
- support and corporate data obey actual availability time
- missing one symbol's bar must not fabricate data
- one missing symbol should not erase valid opportunities for unrelated symbols

## NEXT EXACT MILESTONE

Stop further in-sample winner mining.

Next:

**FORMAL STRICT-CAUSAL REPLAY AUDIT / GATE**

Target report:

- LOOKAHEAD PROTECTION: PASS
- SIMULATION CLOCK: STRICT
- FUTURE BAR ACCESS: BLOCKED
- SYNTHETIC FUTURE DATA: NONE
- DECISION DATA CUTOFF: VERIFIED
- EXECUTION TIMING: VERIFIED

Resume from this audit unless the user explicitly redirects.

<!-- QPX_PRE_CODEX_RESUME_POINT_20260811 -->
# PRE-CODEX RESUME POINT — 2026-08-11

Before asking the user any QPX-history question, read:

1. `QPX_SESSION_CHECKPOINT_2026-08-11_PRE_CODEX.md`
2. `QPX_CONVERSATION_JOURNAL_2026-08-11.md`
3. `QPX_RECOVERY_DECISION_LEDGER.md`
4. `QPX_CONTEXT_CONTINUITY_RULE.md`

Maximum granularity is mandatory.

Preserve as much actual conversation as available.

During active work checkpoint approximately every five minutes and no later
than the ten-minute target ceiling, or immediately after a major event.

Current workflow action:

**configure Codex GitHub access after this checkpoint is safely pushed**

Current next technical QPX milestone after Codex setup:

**authentic QDTE dividend cash timing → strict-causal Candidate V1 rerun**


<!-- QPX_DURABLE_RECOVERY_PROMPT_20260813 -->
# DURABLE RECOVERY PROMPT — 2026-08-13

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

Load governing rules before project history. **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.**

### PARAMETER UNCERTAINTY RULE

If an exact threshold, percentage, cap, delay, cooldown, allocation, weight, multiplier, mode, limit, timing value, or other strategy/operational parameter is not explicitly recovered, do not assume it was forgotten and do not invent or hard-code it. QPX values are generally user-configurable, versioned, fingerprinted, and hot-swappable where safe. Engine code supplies capability and validation; runtime configuration supplies values. Frozen experiment values are not universal defaults. Safety, accounting, and provenance invariants remain code invariants.

## RESTORE NOW

Repository `/mnt/sdcard/QPX_ALPHA`; branch `qpx-shadow-matrix-v1-review-2026-08-12`; local/remote HEAD `1ce96941e8fb1cbe8c9e7c5dabf3327842603814`; main/origin-main `2cab84accdfe79faa8097b7fdb976da46d8dbde5`; ahead/behind `0/0`; worktree clean before this context update.

Read in order: `QPX_CONTEXT_CONTINUITY_RULE.md`, latest appended section in `QPX_RECOVERY_DECISION_LEDGER.md`, this prompt, and latest `QPX_CONVERSATION_JOURNAL_2026-08-13.md` if present. Then inspect `git status`, current HEAD, and artifact fingerprints.

## COMPLETED TRAJECTORY

The repository preserves strict Candidate V1 causal/provenance work; fixed-25 qualification; Dynamic Sizing V1; Pyramiding V1; Capacity Arbitration V1; process-isolated parallel research; Regime Allocation V1 foundation/no-op/policies/results; and Profit Recycling foundation, hot swap, governor, checkpoint continuity, equivalence, and fraction matrix. See the detailed ledger section for commits and evidence.

Profit Recycling fraction matrix: 20/20 jobs, 0 failures, fixed-25/hash-control, fractions 100/75/50/25/0, periods full/2024/2025/2026, dataset `8a9b1786680fe09af35807a2e33417b16a2c7b1fdcb79ba999d1cba959d986f8`, manifest `4213719f443f7ed8285511e4268a8a1b181b32d082cde03a12e75538b1129133`. The former false causal flag was a reporting bug fixed by `1ce9694`; corrected flag is true, no economics changed.

## CURRENT STATE / NEXT ACTION

No active run, no unpushed commit, and no approved next Profit Recycling matrix. Do not tune or promote any fraction. Next action requires explicit user direction and predeclaration of exact values.

## ROADMAP / LONG-TERM DIRECTION

Preserve Top100 exactly; keep Dividend Opportunity Engine separate; test accelerator combinations only after evidence; use Champion/Challenger/Shadow governance; eventually harden trusted-core failover, broker reconciliation, unattended safe recovery, LAN workers, Tailscale phone access, energy-aware scheduling, and QPX-native constrained ML. AM4 is a replaceable role host, not QPX identity.

## SECURITY / PRESERVATION

Do not stage ignored reports, caches, raw data, `.env`, credentials, private broker data, or the malformed `qpx_bot/QPX_ALPHA` gitlink. Never use `git add .`. Main remains untouched.


<!-- QPX_AUGUST14_RECOVERY_PROMPT_20260814 -->
# AUGUST 14 RECOVERY PROMPT — APPLY BEFORE RESUMING

## QPX GOVERNING RULES — APPLY IMMEDIATELY ON RESTORE

**MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.** Do not modify main, protected Candidate V1, frozen Top100/data, provenance, permanent controls, or economic behavior. Do not self-promote research/ML/Wildcard outputs.

### PARAMETER UNCERTAINTY RULE

Unrecovered exact thresholds, percentages, caps, delays, allocations, weights, modes, limits, schedules, resource quotas, and ML values must not be invented or hard-coded. Treat them as versioned, fingerprinted, user-configurable/hot-swappable where safe; engine code validates capability and invariants.

## RESTORE STATE

Repository: `/mnt/sdcard/QPX_ALPHA`
Branch: `qpx-shadow-matrix-v1-review-2026-08-12`
Recovery HEAD before this snapshot: `458f26c420b62b1b9999adf9da3c0c4168c34d12`
Main/origin-main: `2cab84accdfe79faa8097b7fdb976da46d8dbde5`
Boundary: approximately 2026-08-14 13:12 CDT; later context is UNKNOWN / UNRECOVERED.

Read the continuity rule, latest ledger section, this prompt, and `QPX_CONVERSATION_JOURNAL_2026-08-14.md`; then verify Git state before action.

## RECOVERED DECISIONS

- Ubuntu 24.04 LTS dedicated Linux services are the initial trusted QPX Core direction; Tailscale is the preferred fast phone path. Indiana success means one reachable, unattended, persistent, reboot-reconciling Core; family time remains priority.
- Development speed and understandable PASS/FAIL/NEXT workflows matter; learning should not block progress and QPX must not become opaque.
- Local-first ownership, user-supplied credentials, no mandatory subscription/heartbeat, and private-state locality are approved philosophy only; price/licensing remain future decisions.
- One-minute support is eventual: Core + 5900XT worker first, authentic/frozen 1-minute data, 1-minute→15-minute parity against protected 15-minute control, then isolated resolution Shadows.
- Strategy lineage is Boundary → Challenger → Champion; approximately 10 governed Challenger slots; Qualification Layer has no capital authority.
- Research, Qualification, and Operations ML are logically separated. Jetson Orin Nano Super is intended ML hardware direction.
- AI Wildcard #11 is permanent conceptual, paper-only, causal, logged, no credentials/live order/real-money authority/self-promotion, and must pass normal freeze/reproduce → evidence → qualification → governance if exceptional.

## NEXT ACTION

This is preservation-only. Verify the pushed recovery commit, then stop and await explicit direction. Do not begin Indiana deployment, one-minute work, Qualification implementation, ML work, Wildcard implementation, or research until separately requested and exact parameters/acceptance criteria are recovered or declared.


<!-- QPX_POST_AUG14_CONTINUITY_RESTORE_20260825 -->
# POST-AUGUST-14 CONTINUITY RESTORE — 2026-08-25

**Status:** USER_CONFIRMED continuity extension. **MISSING CONTEXT MEANS RETRIEVE/VERIFY — NEVER REINTERPRET OR INVENT.**

The former August 14 recovery boundary is now extended by recovered August 15–17 material. This extension does not turn anything marked **UNKNOWN / UNRECOVERED** into known history; all such items remain **UNKNOWN / UNRECOVERED** until retrieved, verified, or explicitly decided.

On restoration, read in this order:

1. `QPX_CONTEXT_CONTINUITY_RULE.md`
2. the latest section of `QPX_RECOVERY_DECISION_LEDGER.md`
3. `QPX_RECOVERY_PROMPT.md`
4. `QPX_POST_AUG14_CONTINUITY_CHECKPOINT_2026-08-17.md`
5. `QPX_CONVERSATION_JOURNAL_2026-08-17.md`
6. then verify branch, HEAD, upstream, worktree status, and main/origin-main refs before action

Recovery completion is not authorization to begin development. Do not touch main. Do not modify Candidate V1, frozen data/fingerprints, strict-causal provenance, permanent controls, or completed accelerator evidence without separate explicit authorization. Research, Shadow, Challenger, ML, Qualification, and Wildcard actors retain no self-promotion authority.

The next development milestone still requires explicit user direction. Until then, remain preservation-only.


<!-- QPX_SEPTEMBER10_CAPACITY_GOVERNED_FINALIZATION_RESTORE -->
# SEPTEMBER 10 CAPACITY-GOVERNED FINALIZATION RESTORE

Repository: `/home/ron/QPX_ALPHA`

Branch: `qpx-shadow-matrix-v1-review-2026-08-12`

Predecessor restore HEAD: `0d43008045a1d61c53c1db8c6d8c930ec123ea62`

Restore the commit named `Restore capacity-governed historical finalization`,
then verify its exact SHA, upstream state, and worktree before acting. Main remains
protected and must not be touched.

The governed coexistence rule is: Clean-V2 has priority, not exclusivity.
Historical downloads and local partition finalization may proceed in
`LIVE_COEXISTENCE` whenever the existing capacity authority permits them.
Market-open status alone is not a blocker, and `OFF_MARKET` is not required for
finalization. Existing protected-window, Clean-V2 health/degradation,
host-pressure, attribution, safety-latch, and provider-capacity controls remain
binding. Provider-request throttling applies to requests, not local finalization.

At the read-only restore observation, the V3 smoke partition
`year=2026/batch=00187` was already finalized: 6,888/7,370 complete,
358,407,648 rows, 482 pending, zero pending finalizations, latest manifest
integrity true, and training eligibility remained
`ACQUISITION_PARTIAL_NOT_TRAINING_ELIGIBLE`. Historical acquisition was
inactive/dead with PID 0. These are recovery observations, not authorization to
restart it or begin training.

Focused lifecycle/V3/calendar-repair tests passed 38/38. Continue to apply
`QPX_TEST_SCOPE_RULE_V1`: do not turn stale unrelated legacy fixtures or optional
hardening into a new blocker. Preserve downloaded evidence and use the existing
capacity/coexistence arbitration when separately authorized to resume historical
work.

<!-- QPX_SEPTEMBER11_CORPORATE_ACTION_IDENTITY_RESTORE -->
# SEPTEMBER 11 CORPORATE-ACTION IDENTITY RESTORE

**VERIFIED_REPO:** Work continues on
`qpx-shadow-matrix-v1-review-2026-08-12`. The prior remote review HEAD was
`e0371a70b06328df5edcbd1b423048ca9b57de6b`; the corporate-action/rule
implementation commit is `b184d18423fcb842800faeae758a6a46ac591c3f`.
Main remains protected.

**VERIFIED_ARTIFACT:** Historical bars are complete and preserved at
7,370/7,370 partitions and 383,082,447 rows. The former corporate-action run
failed at the obsolete normalizer precondition with
`ValueError: Corporate action requires authoritative id and symbol.` The exact
offending raw provider record remains **UNKNOWN / UNRECOVERED**.

**VERIFIED_REPO:** Provider event ID remains mandatory, but primary `symbol` is
optional. `symbol`, `old_symbol`, and `new_symbol` normalize independently and
flow to the existing no-guess stable-identity resolver. Corporate-action
evidence is schema 3 / `ALPACA_CORPORATE_ACTIONS_HISTORICAL_V3`; requests bind
`region=us`, `data_quality=complete`, and include
`capital_gains_distribution`. Qualification V2 accepts an unresolved event as
bounded only when both excluded provider IDs and bounded dates exist.

**VERIFIED_ARTIFACT:** The directly affected acquisition and qualification
modules passed 116/116 focused tests; changed production modules compiled and
`git diff --check` passed. Existing QPX rules and governed contracts are now
explicit completion criteria in `AGENTS.md` and the continuity rule.

**VERIFIED_ARTIFACT:** The existing acquisition service resumed with PID 451384,
skipped all completed bars, and successfully paginated real corporate actions
under `LIVE_COEXISTENCE`. At 2026-09-11 11:17 CDT it was alive and cooperatively
yielding for `CLEAN_V2_DECISION_WINDOW`; corporate-action status remained
`PENDING`, so final event and identity-resolution counts were not yet
authoritative. Training remains unauthorized.

**NEXT EXACT STEP:** Observe completion of the already-running corporate-action
stage; validate committed CA artifact/manifest and resolved, unresolved-bounded,
and unresolved-unbounded counts. Then proceed through the already-governed
calendar repair and independent historical qualification path. Do not start
training from acquisition completion.

## September 11 coexistence correction

**USER_CONFIRMED / VERIFIED_REPO:** The Clean-V2 decision-window clock is
telemetry, not an unconditional historical stop. Safe historical work continues
at the governed low live rate whenever actual provider capacity, Clean-V2
health/latency, and host resources permit it. Existing provider reservation,
resource pressure, attributable degradation, 429/session latch, and finalization
rules remain intact. The directly affected acquisition module passed 104/104
tests after this correction.

**NEXT EXACT STEP:** The existing service must be restarted through systemd after
the correction commit so it loads the new capacity decision, while preserving
7,370 completed bar partitions and 383,082,447 rows. Then let corporate-action
pagination finish; do not start training.

**VERIFIED_ARTIFACT RUNTIME UPDATE:** Commit
`a864b1048ee826c8ee127f457b72aac3012dbcbf` was pushed and loaded by the existing
service. It reported `LIVE_COEXISTENCE`, not a clock-only decision-window stop,
with all 7,370 partitions and 383,082,447 rows preserved. Alpaca then repeatedly
returned HTTP 504 `backend request timeout`; bounded retries exhausted and the
existing systemd `Restart=on-failure` recovery remained active. Corporate
actions are still `PENDING`; training is unauthorized.

**NEXT EXACT STEP:** Allow the existing service retry path to resume corporate
actions when Alpaca responds, then validate the atomic CA evidence and identity
counts before calendar repair and independent qualification.

## September 11 durable corporate-action page recovery

**VERIFIED_REPO:** Commit `8ec5ed3` restores the standing rule that every
successfully validated provider page is durable before the next request.
Corporate-action pages, provenance, token continuity, and a checksummed
request-bound checkpoint are persisted atomically; restart reconstructs the
working set from that evidence and resumes at the first unfinished page.
Corrupt, stale, contradictory, or duplicate-ID evidence fails closed. Terminal
artifacts remain committed only after complete validated pagination.

**VERIFIED_ARTIFACT:** The directly affected acquisition and qualification
modules passed 123/123 focused tests. The acquisition module compiled and
`git diff --check` passed. All 7,370 bar partitions and 383,082,447 rows remain
unchanged; training remains unauthorized.

**VERIFIED_ARTIFACT / PROVIDER BLOCKED:** The existing service loaded commit
`8ec5ed3` through its normal systemd restart path. Alpaca continued returning
HTTP 504 `backend request timeout` before the first corporate-action page, so no
real staged page exists yet and runtime acquisition success is not claimed.
The service remains in its governed retry/restart path with corporate actions
`PENDING`.

**NEXT EXACT STEP:** Let the existing service continue until Alpaca returns the
first page; verify the new staged page/checkpoint and, if another transient error
occurs, verify restart requests the saved next-page token rather than page 1.
Then validate terminal CA evidence before calendar repair and independent
qualification. Do not start training.

## Mandatory Codex compliance prompt — 2026-09-11

**USER_REQUIREMENT / VERIFIED_REPO:** `QPX_CODEX_COMPLIANCE_PROMPT.md` is now a
binding pre-task process for QPX Codex work. `AGENTS.md` points to it as the
mandatory first step before interpreting, planning, or acting on any repository
task. It requires governed sequencing, proportional testing, exact runtime
evidence, per-push continuity, honest incomplete/blocked reporting, and a
mandatory completion audit.

**NEXT EXACT STEP:** Every future QPX task must begin by loading the compliance
prompt through the `AGENTS.md` pointer and applying it as acceptance criteria.

## Adamantine compliance hardening — 2026-09-11

**USER_REQUIREMENT / VERIFIED_REPO:** The mandatory compliance prompt is now
explicitly fail-closed. It defines authority precedence and non-waiver, requires
an ordered pre-action checklist, prevents dependent actions when a prerequisite
is absent, maps positive claims to minimum direct evidence, and requires the
completion audit immediately before gated Git/completion actions. Later success
or a follow-up continuity commit cannot retroactively cure a violation.

**NEXT EXACT STEP:** Apply the hardened prompt before every task and do not
advance past any unmet prerequisite.

## Complete compliance-prompt load requirement — 2026-09-11

**USER_REQUIREMENT / VERIFIED_REPO:** Every QPX task must load the entire current
`QPX_CODEX_COMPLIANCE_PROMPT.md` from its first byte through EOF before acting.
Summaries, excerpts, searches, cached memory, prior-turn reads, and truncated or
partially paginated output do not qualify. Reads must continue until EOF is
positively reached, and the first work update must say the complete load occurred.

**NEXT EXACT STEP:** On every task, load the full current prompt through EOF
before any action beyond the minimum needed to locate and read governance.

## Every individual prompt requires a fresh complete load — 2026-09-11

**USER_REQUIREMENT / VERIFIED_REPO:** From this point forward, every individual
QPX user prompt/message independently requires a fresh full load of
`QPX_CODEX_COMPLIANCE_PROMPT.md` from first byte through EOF before any response
or action. This includes continuations, corrections, clarifications,
interruptions, status requests, objections, approvals, and one-line follow-ups.
A load for the immediately preceding prompt never carries forward.

**NEXT EXACT STEP:** Reload the complete current prompt after every user message
before responding or acting on that message.

## 2026-09-11T13:03:59-05:00 — Corporate-action durability correction accepted

Corporate-action acquisition now persists each successful provider page as a self-contained atomic durable bundle before requesting another page. Restart position is reconstructed from durable page evidence rather than depending on separately timed page/manifest/checkpoint writes. Acquired provider pages remain retained after terminal aggregation.

**REAL RUNTIME PROOF:** real CA page 1 survived restart and acquisition resumed forward to real page 2.

Page-1 SHA256: `a5ee1dad88a8ec810080adeb6a9073069d79a0b76a9b7d799f8200f6e7b6acd4`.

Historical reservoir remains 7370 partitions and 383082447 rows. Training remains unauthorized.

## 2026-09-11T13:09:31-05:00 — Actual corporate-action restart/resume proof

Correction: the earlier page-1/page-2 runtime statement was not sufficient proof because 349 validated legacy pages had already been migrated before that restart observation.

**VERIFIED RUNTIME:** after an explicit process stop/restart, terminal durable pages 1-364 remained byte-identical and QPX recovered to corporate-action COMPLETE without creating another provider page.

Frozen pre-restart durable chain: 364 pages.
Chain SHA256: `d3c6b985aa263c6f8d5ce96baf846c041e154336a26182163684bb9ef97920d0`.

Historical reservoir remains 7370 partitions and 383082447 rows.
Training remains unauthorized.

## 2026-09-11 — Provider-reported name-change lineage qualification checkpoint

**USER_REQUIREMENT / VERIFIED_REPO:** Corporate-action identity qualification
may traverse only explicit provider `name_change` old/new-symbol evidence as a
same-security lineage. Merger, spin-off, reorganization, distribution, and
other action types do not create same-security edges merely because aliases are
present. Unique anchored components resolve; multi-ID components retain every
candidate; unanchored components remain unbounded.

**VERIFIED_ARTIFACT:** The immutable 363,148-event archive was not reacquired.
The corrected resolution artifact fingerprint is
`3e97e6aeafb3815e0fe6380df2b78c428abe1ff28ef5ced42be114e1bb32591a`;
its manifest fingerprint is
`857a39e00bf690e89933be731e4fa18e0e2b7bd55ddeb6a768ab6d66db4b4e39`.
Of the original 69,063 unbounded events, 10,358 became uniquely resolved, 621
became bounded ambiguous, and 58,084 remain unbounded: 5,413 have no usable
symbol evidence and 52,671 have no authoritative provider-population anchor
through the complete acquired name-change lineage.

**VERIFIED_ARTIFACT:** Bars remain 7,370/7,370 and 383,082,447 rows. Focused
resolver/qualification tests passed 8/8, compilation and diff checks passed,
and training remains unauthorized.

**NEXT EXACT STEP:** Obtain authoritative provider identity evidence for the
remaining 58,084 dated events, or an explicit governance decision for their
treatment. Calendar repair and independent qualification remain gated and were
not run.

## September 12 targeted identity enrichment completion

**VERIFIED_ARTIFACT:** Targeted CUSIP/ISIN enrichment completed without
reacquiring the 363,148-event corporate-action archive. The validated,
state-bound enrichment fingerprint is
`110c9231e677b2fbf2e618fd33944f7ccdac10fd20475f86a93bf7b737694c24`.
It binds 58,084 target events, 59 durable event batches, and 14,286 durable
CUSIP lookups. The rebuilt corporate-action identity-resolution fingerprint is
`bf36d339de8ceab65a4175d31c742a204b8af2b9efc7819757895e6f9af52f1b`.

**VERIFIED_ARTIFACT:** Final resolution counts are 300,628 resolved, 32,623
explicitly outside the frozen provider population, 7,399 bounded ambiguous,
and 22,498 unresolved/unbounded. Residuals are 16,626 events with no CUSIP/ISIN,
5,625 with no provider asset lookup result, and 247 with mixed
matched/unresolved identity evidence. Bars remain 7,370/7,370 and 383,082,447
rows. Focused enrichment/resolver/qualification verification passed 13/13.

**USER_APPROVED:** Experimental ML training is now authorized against an
explicitly fingerprinted snapshot of the currently available reservoir despite
strict qualification remaining `NOT_TRAINING_ELIGIBLE`. This does not resolve
the 22,498 identities, complete calendar repair, authorize promotion/capital,
or weaken strict qualification.

**VERIFIED_REPO / BLOCKER:** No executable ML trainer or governed complete
training configuration currently exists. ADR-0011 deliberately leaves model
family, training algorithm, optimizer/capsule mechanics, bankroll, permissions,
and implementation resource limits unresolved. Do not invent them.

**NEXT EXACT STEP:** Govern the missing trainer/model/training configuration,
then implement the explicit `EXPERIMENTAL_UNQUALIFIED_TRAINING` launch boundary
with snapshot-limit provenance and zero promotion/live/capital authority.

## September 12 experimental causal baseline V1

**USER_APPROVED:** `QPX_ML_EXPERIMENTAL_CAUSAL_BASELINE_V1` is the first
executable engineering/research trainer. It is explicitly
`EXPERIMENTAL_UNQUALIFIED_TRAINING`, not ADR-0011 Historical Apprenticeship, and
has no promotion, live, broker, or capital authority.

**VERIFIED_REPO:** The standard-library CPU trainer streams the immutable 15m
partition inventory, creates seven causal current/past-bar features, predicts
only the next consecutive same-session bar direction, performs one unshuffled
online logistic-regression SGD training pass at learning rate 0.01, and keeps
validation/test read-only. Partition checksums and row counts are verified
during streaming. Atomic checksummed checkpoints commit only completed
partitions and bind content-addressed per-batch feature state.

**VERIFIED_ARTIFACT:** Input snapshot fingerprint is
`bcace64bb55c68de66c256c5b9ed443e6384f80904cff7debaefeb862792d595`;
partition-inventory fingerprint is
`1fa355435551705b6b1aadb70af40aca65039fdc46b0ada0b98f4eb2917ad3cc`;
configuration fingerprint is
`cb1a68a29280a9c4faafa5e04a37667b6436f4134db6486a68d54c694d8beaf4`.
The snapshot explicitly retains strict status
`ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`, 22,498 unresolved/unbounded
corporate actions, and calendar repair `NOT_RUN`.

**NEXT EXACT STEP:** After the trainer commit is pushed and remote-verified,
launch one detached `nice -n 10` CPU process, verify its PID and run manifest
once, then return without polling. Do not start any promoted or capital-bearing
training path.

## September 12 Wildcard V1 causal-world foundation

**VERIFIED_ARTIFACT:** Experimental Causal Baseline V1 run
`e0ad4ca03fcbbca8fe7253ca756d66b4eaae127ef3624745ffeb6888c9311d0c`
completed all 7,370 partitions. Its checksummed exit status is `COMPLETE`, final
report fingerprint is
`f7d9184a4e3f6d1fa44e5558a4b40b23c5e50bc29729b3d41fc1e8bd77bdf357`,
and strict dataset status remains
`ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`. The absent `broker_authority`
manifest field is not part of the committed Baseline V1 schema and does not
invalidate the run. The run was not restarted or modified.

**USER_APPROVED / VERIFIED_REPO:** ADR-0012 Wildcard V1 execution physics now
specify Decimal scale 8 with `ROUND_HALF_EVEN`, cent cash settlement, 0.001-share
quantity precision, evidence-gated fractional execution, causal FIFO order
sequence, replace-as-acknowledged-cancel-plus-new-order, and no statutory fee
without an authoritative effective-dated rule. Commission remains zero,
slippage 5 bps, and observed-volume participation 1%.

**VERIFIED_REPO:** The sterile Wildcard world foundation accepts one immutable
causal event at a time from an external driver, exposes no archive read path,
owns a fresh $100,000 cash-only long account and DAY market-order lifecycle,
executes no earlier than the next eligible event, and provides atomic
checksummed restart state plus immutable write-only audit lineage. It has no ML
learner and no promotion, live, broker, or capital authority.

**VERIFIED_ARTIFACT:** Focused Wildcard world and reward-policy tests passed
47/47; Python compilation and `git diff --check` passed.

**NEXT EXACT STEP:** Extend the external DEVELOPMENT_ONLY scripted driver and
sterile reporting around this world before selecting or introducing a Wildcard
learner. Do not confuse the completed experimental baseline with Wildcard
apprenticeship or strict training eligibility.

## September 12 completed-boundary clock/reward cadence

**USER_APPROVED:** Wildcard V1 scheduled market time and reward reconciliation
occur exactly once per completed world boundary. Individual security bars,
corporate actions, identity events, and lifecycle events may change factual
world state but never advance the global scheduled clock or emit dense reward.
Universe size and missing observations cannot multiply or freeze elapsed market
time.

**VERIFIED_REPO:** The external `DEVELOPMENT_ONLY` driver owns archive grouping,
orders each boundary's events by declared causal sequence, delivers them one at
a time, and emits one deterministic completion carrying authoritative scheduled
exchange minutes. Open/completed boundary identity and event IDs are included in
the atomic world checkpoint, so recovery before completion finishes once and
recovery after completion cannot duplicate time or reward.

**VERIFIED_REPO:** The one-way sterile reporter emits factual evidence at the
8,190 scheduled-regular-session-minute cadence, or on terminal/integrity state,
without exposing a feedback/read path to Wildcard. Historical-to-forward source
handoff requires a completed boundary.

**VERIFIED_ARTIFACT:** Focused world, driver/report, and reward-policy tests
passed 58/58. Changed Python files compiled and `git diff --check` passed.

**NEXT EXACT STEP:** Select the governed Wildcard learner/model family and its
apprenticeship authorization boundary. Do not introduce a learner or claim
training authority from the DEVELOPMENT_ONLY world evidence alone.

## September 12 Wildcard V1 causal learner and capsule selection

**USER_REQUIREMENT / VERIFIED_REPO:** The separate ADR-0011 high-risk model
review selected a small GRU softmax policy as Wildcard V1's causal learner
family. A small feed-forward network is the runner-up; linear/logistic lacks
learned sequential state, LSTM adds unnecessary V1 surface, and large
attention/replay models enlarge the causal archive boundary without current
need.

**VERIFIED_REPO:** ADR-0013 freezes a fixed fingerprinted neutral state vector
plus separately fingerprinted reward/preference vector, deterministic seeded
action sampling, one-boundary online reward-modulated plain SGD, episode-local
hidden/pending/RNG state, and immutable episode-terminal additive capsules.
Plain SGD has no persistent adaptive state, so capsules explicitly record
optimizer destruction. The unique parent chain composes in ascending sequence
and rejects corrupt, ambiguous, same-boundary, future, or cross-experiment
learning.

**VERIFIED_ARTIFACT:** The `DEVELOPMENT_ONLY` standard-library skeleton passed
14/14 focused learner/capsule tests, including deterministic initialization,
strict action/reward ordering, episode-memory destruction, durable capsule
integrity, eligibility, composition, checkpoint equivalence, preference
plumbing, archive absence, and zero authority. Python compilation and
`git diff --check` passed.

**AUTHORITY:** The current reservoir remains
`ACQUISITION_COMPLETE_NOT_TRAINING_ELIGIBLE`. No real Wildcard apprenticeship,
historical training, research conclusion, promotion, broker/live use, or capital
authority was created.

**NEXT EXACT STEP:** Independently complete strict historical qualification.
Only after `TRAINING_ELIGIBLE` and a separate user-authorized transition may an
experiment configure the real neutral state/action dimensions and begin
`HISTORICAL_APPRENTICESHIP`.
